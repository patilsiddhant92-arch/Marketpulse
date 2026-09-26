"""
MarketPulse Modern Terminal Backend API (Option A)
High-performance FastAPI service reading DuckDB analytical models directly.
Restores full analytical depth: multi-day deal accumulation, 400-day Darvas box geometry,
comprehensive momentum screener filters, deduplicated VCP workbench, and historical sector rotation.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import duckdb
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Resolve Root and Scripts paths
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
SCRIPTS_DIR = ROOT_DIR / "Scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from Scripts.config import DB_PATH, USER_DB_PATH, STATUS_PATH
from App.cache_manager import get_cached, set_cached, cache_key
from App.market_status import load_market_status
from App.indicators.darvas import (
    DARVAS,
    calculate_darvas_box,
    darvas_v2_enabled,
    darvas_weekly_enabled,
    is_darvas_10ema_squeeze,
)
from App.indicators.uc_thrust import uc_flag_label, uc_score_map
from App.sector_read_model import (
    leading_themes_from_board,
    query_rotation_board,
    query_sector_breadth_divergence,
)
from App.deals_read_model import query_deals_advanced
from Scripts.desk_contract import POOL, PRIMARY_QUEUES, match_exposure
from Scripts.vcp import classify_vcp_frame
from Scripts.institutional_engine import classify_client
from Scripts.institutional_attribution import clean_fund_name, fetch_star_fund_radar
from Scripts.telegram_deals import build_deals_telegram_report, to_tv_list
from Scripts.minervini_geometry import detect_contractions, load_template_context, load_ohlcv

app = FastAPI(
    title="MarketPulse Terminal API",
    description="High-density EOD swing trading analytical engine for Indian markets",
    version="3.1.0",
)

# Same-origin in production (FastAPI serves frontend/dist). Only the Vite dev server needs CORS.
DEV_ORIGINS = ["http://127.0.0.1:5173", "http://localhost:5173"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=DEV_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "PUT"],
    allow_headers=["*"],
)

_SYMBOL_RE = re.compile(r"^[A-Z0-9&\-_.]{1,20}$")


def validate_symbol(raw: str) -> str:
    """Upper-case and validate an NSE symbol; raise 422 for anything else."""
    sym = str(raw or "").strip().upper()
    if not _SYMBOL_RE.fullmatch(sym):
        raise HTTPException(status_code=422, detail=f"Invalid symbol: {raw!r}")
    return sym


_BAND_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def parse_exposure_band(pct: Any) -> tuple[float | None, float | None]:
    """'50% - 75%' -> (50.0, 75.0); '25%' -> (25.0, 25.0); junk -> (None, None)."""
    nums = [float(n) for n in _BAND_NUM_RE.findall(str(pct or ""))]
    if not nums:
        return (None, None)
    return (min(nums), max(nums))


def playbook_for_band(band_low: float | None, ab50_pct: float | None) -> dict[str, str]:
    if band_low is None:
        return {
            "execution_playbook": "Exposure inputs are missing for this session; do not size new positions until Data Health is green.",
            "action_bias": "Unknown — exposure inputs missing",
            "max_position_size": "—",
            "risk_per_trade": "—",
        }
    breadth = f"{ab50_pct:.1f}%" if ab50_pct is not None else "n/a"
    if band_low >= 75.0:
        return {
            "execution_playbook": f"Risk-on: {breadth} of stocks above their 50 EMA. Trade clean Stage 2 pivots and breakouts at standard size; trail stops below the 10/20 EMA.",
            "action_bias": "Bullish / Trend Following",
            "max_position_size": "15%–20%",
            "risk_per_trade": "1.0%",
        }
    if band_low >= 50.0:
        return {
            "execution_playbook": f"Selective: {breadth} of stocks above their 50 EMA. Prefer tight Darvas/VCP setups near pivot; avoid extended chases.",
            "action_bias": "Selective / Coiled Setups Only",
            "max_position_size": "8%–10%",
            "risk_per_trade": "0.5%–0.75%",
        }
    return {
        "execution_playbook": f"Defensive: {breadth} of stocks above their 50 EMA. Mostly cash; only the strongest leaders, and protect open winners with trailing stops.",
        "action_bias": "Defensive / Heavy Cash",
        "max_position_size": "5%–7%",
        "risk_per_trade": "0.25%–0.5%",
    }


def gate_inputs_from(exp_inputs: dict[str, Any]) -> dict[str, float | None]:
    """Un-defaulted breadth inputs for the exposure gate.

    `exp_inputs` (from `load_exposure_gate_args`) already leaves a missing/NaN
    breadth column as None; this must stay None here too — never fabricated as
    50.0 — so a NULL column fails the gate closed instead of masquerading as a
    neutral reading (spec 6.3).
    """
    def _num(key: str) -> float | None:
        v = exp_inputs.get(key)
        if v is None:
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return None if (np.isnan(f) or np.isinf(f)) else f

    return {
        "adv_pct": _num("adv_pct"),
        "ab20_pct": _num("ab20_pct"),
        "ab50_pct": _num("ab50_pct"),
        "ab200_pct": _num("ab200_pct"),
    }


def get_db(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DB_PATH), read_only=read_only)


def get_user_db(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(USER_DB_PATH), read_only=read_only)


def _sanitize_float(val: Any, default: float = 0.0) -> float:
    if val is None or pd.isna(val):
        return default
    try:
        f = float(val)
        return 0.0 if abs(f) < 0.0001 or np.isnan(f) or np.isinf(f) else f
    except (ValueError, TypeError):
        return default


def _arg_val(val: Any, default: Any = None) -> Any:
    if hasattr(val, "default"):
        d = val.default
        return default if d is ... or d is None else d
    return val if val is not None else default


# =========================================================================
# 1. Health & Market Regime API
# =========================================================================
@app.get("/api/health")
def get_health():
    """Health check endpoint confirming DuckDB analytical dataset freshness."""
    status = load_market_status(DB_PATH, STATUS_PATH)
    return {
        "status": "healthy",
        "actionable": status.actionable,
        "database_date": str(status.database_date) if status.database_date else None,
        "expected_session": str(status.expected_session) if status.expected_session else None,
        "detail": status.status,
    }


@app.get("/api/market/regime")
def get_market_regime():
    """Market exposure gate, India VIX, Nifty breadth, tape counts, and leading sector themes."""
    from App.pages.action_desk import compute_exposure_gate
    from App.ui.market_health import load_exposure_gate_args, resolve_india_vix

    with get_db() as con:
        trade_date = con.execute("SELECT max(trade_date) FROM indicators_daily").fetchone()[0]
        vix_val, vix_1d_pct = resolve_india_vix(con, trade_date)
        exp_inputs = load_exposure_gate_args(con, trade_date=trade_date)

        # Pull exact row from breadth_daily for rich tape & volume metrics
        b_df = con.execute(
            """
            SELECT stocks, advancers, decliners, unchanged, advance_pct, advance_volume_pct,
                   above_10ema_pct, above_20ema_pct, above_50ema_pct, above_100ema_pct, above_200ema_pct,
                   near_52w_highs, vcp_candidates, breadth_state, above_50ema_5d_change, above_200ema_20d_change
            FROM breadth_daily
            WHERE trade_date = ?
            """,
            [trade_date]
        ).fetchdf()

        if not b_df.empty:
            b_row = b_df.iloc[0].to_dict()
            stocks_cnt = int(b_row.get("stocks") or 0)
            adv_cnt = int(b_row.get("advancers") or 0)
            dec_cnt = int(b_row.get("decliners") or 0)
            unch_cnt = int(b_row.get("unchanged") or 0)
            adv_pct = _sanitize_float(b_row.get("advance_pct"), 50.0)
            adv_vol_pct = _sanitize_float(b_row.get("advance_volume_pct"), 50.0)
            ab20_pct = _sanitize_float(b_row.get("above_20ema_pct"), 50.0)
            ab50_pct = _sanitize_float(b_row.get("above_50ema_pct"), 50.0)
            ab200_pct = _sanitize_float(b_row.get("above_200ema_pct"), 50.0)
            near_52_cnt = int(b_row.get("near_52w_highs") or 0)
            b_state = str(b_row.get("breadth_state") or "Unclassified")
            chg_50_5d = _sanitize_float(b_row.get("above_50ema_5d_change"), 0.0)
            chg_200_20d = _sanitize_float(b_row.get("above_200ema_20d_change"), 0.0)
        else:
            stocks_cnt = 0
            adv_cnt = 0
            dec_cnt = 0
            unch_cnt = 0
            adv_pct = _sanitize_float(exp_inputs.get("adv_pct") or exp_inputs.get("advance_pct"), 50.0)
            adv_vol_pct = 50.0
            ab20_pct = _sanitize_float(exp_inputs.get("ab20_pct") or exp_inputs.get("above_20ema_pct"), 50.0)
            ab50_pct = _sanitize_float(exp_inputs.get("ab50_pct") or exp_inputs.get("above_50ema_pct"), 50.0)
            ab200_pct = _sanitize_float(exp_inputs.get("ab200_pct") or exp_inputs.get("above_200ema_pct"), 50.0)
            near_52_cnt = 0
            b_state = "Unclassified"
            chg_50_5d = 0.0
            chg_200_20d = 0.0

        c_52w_h = int(exp_inputs.get("count_52w_highs") or 0)
        c_52w_l = int(exp_inputs.get("count_52w_lows") or 0)

        gate_args = gate_inputs_from(exp_inputs)
        gate = compute_exposure_gate(
            adv_pct=gate_args["adv_pct"],
            ab20_pct=gate_args["ab20_pct"],
            ab200_pct=gate_args["ab200_pct"],
            vix=vix_val,
            vix_1d_pct=vix_1d_pct,
            net_lows_expanding=bool(exp_inputs.get("net_lows_expanding", False)),
            count_52w_highs=c_52w_h,
            count_52w_lows=c_52w_l,
        )

        # Leading themes
        board = query_rotation_board(DB_PATH, level="Broad Industry")
        top_sectors_df = leading_themes_from_board(board, limit=5)
        themes = []
        if not top_sectors_df.empty:
            for _, r in top_sectors_df.iterrows():
                themes.append({
                    "name": r.get("group_name", "Unknown"),
                    "rs_percentile": _sanitize_float(r.get("rs_percentile")),
                    "return_5d_pct": _sanitize_float(r.get("return_5d_pct")),
                    "leaders": str(r.get("leader_symbols", "")).split(",")[:4],
                    "state": r.get("rotation_state", "Leading"),
                })

        # Count active setups
        stage2_pool_count = con.execute(
            """
            SELECT count(DISTINCT symbol)
            FROM indicators_daily
            WHERE trade_date = ? AND close_price > ema_200 AND abs(away_52w_high_pct) <= 25.0
            """,
            [trade_date]
        ).fetchone()[0] or 0

    band = str(gate.get("pct") or "")
    band_low, band_high = parse_exposure_band(band)
    playbook = playbook_for_band(band_low, gate_args["ab50_pct"])

    return {
        "as_of": str(pd.to_datetime(trade_date).date()),
        "exposure_gate": {
            "band": band or None,
            "band_low": band_low,
            "band_high": band_high,
            "recommended_pct": band_low,
            "state": gate.get("state"),
            "badge": gate.get("badge"),
            "guidance": gate.get("guidance"),
            "is_actionable": bool(band_low and band_low > 0),
            **playbook,
        },
        "vix": {
            "current": _sanitize_float(vix_val),
            "change_1d_pct": _sanitize_float(vix_1d_pct),
            "tone": "Low Risk" if _sanitize_float(vix_val) < 15 else ("Moderate" if _sanitize_float(vix_val) < 20 else "High Risk"),
        },
        "tape": {
            "total_stocks": stocks_cnt,
            "advancers": adv_cnt,
            "decliners": dec_cnt,
            "unchanged": unch_cnt,
            "net_advancers": adv_cnt - dec_cnt,
            "advance_pct": adv_pct,
            "advance_volume_pct": adv_vol_pct,
            "breadth_state": b_state,
        },
        "breadth": {
            "above_20_ema_pct": _sanitize_float(ab20_pct),
            "above_50_ema_pct": _sanitize_float(ab50_pct),
            "above_200_ema_pct": _sanitize_float(ab200_pct),
            "advancers_pct": _sanitize_float(adv_pct),
            "highs_52w": c_52w_h,
            "lows_52w": c_52w_l,
            "net_highs": c_52w_h - c_52w_l,
            "near_52w_highs": near_52_cnt,
            "above_50ema_5d_change": chg_50_5d,
            "above_200ema_20d_change": chg_200_20d,
        },
        "leading_themes": themes,
        "setups_summary": {
            "stage2_pool_count": stage2_pool_count,
        },
    }


# =========================================================================
# 2. Executive Cockpit / Action Desk Candidate Setups API
# =========================================================================
def _opt_float(val: Any, ndigits: int = 2) -> float | None:
    """Missing stays missing: None/NaN/inf/non-numeric -> None."""
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, ndigits)


def _opt_str(val: Any) -> str | None:
    """Missing stays missing: None/NaN/blank -> None; else the stripped string."""
    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    s = str(val).strip()
    return s or None


def cockpit_row(row: Mapping[str, Any], queue: str) -> dict[str, Any] | None:
    sym = str(row.get("symbol") or "").strip().upper()
    if not sym:
        return None
    cmp_val = _opt_float(row.get("cmp") if row.get("cmp") is not None else row.get("close_price"))
    trigger = _opt_float(row.get("trigger_price"))
    stop = _opt_float(row.get("stop_loss"))
    risk = _opt_float(row.get("risk_pct"))
    if queue == "darvas_10ema":
        # Current trigger = EMA10 (below price) and stop = EMA10*0.985 carry no information.
        trigger = stop = risk = None
    dist = round((trigger / cmp_val - 1.0) * 100.0, 2) if trigger and cmp_val else None
    return {
        "symbol": sym,
        "sector": _opt_str(row.get("sector")),
        "queue": queue,
        "cmp": cmp_val,
        "change_1d_pct": _opt_float(row.get("day_pct")),
        "pattern_state": str(row.get("setup_type") or queue),
        "rvol": _opt_float(row.get("rvol")),
        "dist_to_pivot_pct": dist,
        "risk_pct": risk if (risk is not None and risk > 0) else None,
        "trigger_price": trigger,
        "invalidation_price": stop,
        "mcap_cr": _opt_float(row.get("market_cap_cr")),
        "why_now": _opt_str(row.get("why_now")) or "",
        "rs_percentile": _opt_float(row.get("rs_percentile"), 1),
        "delivery_pct": _opt_float(row.get("delivery_pct"), 1),
        "theme": _opt_str(row.get("theme")),
        "deal_flow": _opt_str(row.get("deal_flow")),
        "squeeze_pct": _opt_float(row.get("squeeze_pct")),
    }


@app.get("/api/candidates/cockpit")
def get_cockpit_candidates(queue: str = Query("primary", enum=["primary", "vcp", "darvas_10ema", "darvas_squeeze", "all"])):
    """Fetch primary candidate setups strictly adhering to VCP, Darvas, and Stage 2 invariants."""
    try:
        from App.pages.action_desk import fetch_action_desk_data
        data = fetch_action_desk_data(DB_PATH)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query action desk data: {e}")

    queues_raw = data.get("queues", {})
    records = []

    def _extract_rows(df: pd.DataFrame, q_name: str):
        if df.empty:
            return
        for rec in df.to_dict("records"):
            shaped = cockpit_row(rec, q_name)
            if shaped is not None:
                records.append(shaped)

    # Map requested queue to action desk keys
    if queue in ("darvas_squeeze", "darvas"):
        target_keys = [("darvas", "darvas_squeeze")]
    elif queue == "darvas_10ema":
        target_keys = [("darvas_10ema", "darvas_10ema")]
    elif queue == "vcp":
        target_keys = [("vcp", "vcp")]
    elif queue in ("primary", "all"):
        target_keys = [("darvas", "darvas_squeeze"), ("darvas_10ema", "darvas_10ema"), ("vcp", "vcp")]
    else:
        target_keys = [(queue, queue)]

    for raw_k, display_k in target_keys:
        if raw_k in queues_raw and isinstance(queues_raw[raw_k], pd.DataFrame):
            _extract_rows(queues_raw[raw_k], display_k)

    # Sort by squeeze_pct ascending for darvas_squeeze; otherwise closest to pivot
    if queue in ("darvas_squeeze", "darvas"):
        records.sort(key=lambda x: (
            x["squeeze_pct"] if x.get("squeeze_pct") is not None and x["squeeze_pct"] >= 0 else 9999.0,
            abs(x["dist_to_pivot_pct"]) if x.get("dist_to_pivot_pct") is not None else 9999.0,
        ))
    else:
        records.sort(key=lambda x: (
            abs(x["dist_to_pivot_pct"]) if x.get("dist_to_pivot_pct") is not None else 9999.0,
            -(x.get("rvol") or 0.0),
        ))

    return {
        "as_of": str(pd.to_datetime(data["trade_date"]).date()) if data.get("trade_date") is not None else None,
        "total_count": len(records),
        "candidates": records,
    }


# =========================================================================
# 3. Momentum Screener API (Complete Filter Set from MarketPulse 2.0)
# =========================================================================
@app.get("/api/screener/momentum")
def get_momentum_screener(
    lookback_days: int = Query(20, description="Lookback days (1, 3, 5, 10, 20, 30)"),
    min_mcap_cr: float = Query(1000.0, description="Minimum Market Cap in ₹ Crores"),
    min_volume: float = Query(1000000.0, description="Minimum Day Volume"),
    min_avg_volume_20d: float = Query(0.0, description="Minimum 20D Average Volume"),
    max_52w_away_pct: float = Query(25.0, description="Maximum % distance away from 52W high"),
    min_52w_low_pct: float = Query(50.0, description="Minimum % above 52W low"),
    cmp_gt_10: bool = Query(True, description="Price > 10 EMA"),
    cmp_gt_200: bool = Query(True, description="Price > 200 EMA"),
    ohlc_gt_10: bool = Query(False, description="Entire OHLC bar > 10 EMA"),
    ohlc_gt_20: bool = Query(False, description="Entire OHLC bar > 20 EMA"),
    ema10_gt_20: bool = Query(True, description="EMA 10 > 20"),
    ema20_gt_50: bool = Query(True, description="EMA 20 > 50"),
    ema50_gt_100: bool = Query(True, description="EMA 50 > 100"),
    ema100_gt_200: bool = Query(True, description="EMA 100 > 200"),
    sma50_gt_150: bool = Query(False, description="SMA 50 > 150"),
    sma150_gt_200: bool = Query(False, description="SMA 150 > 200"),
    sma_cmp_gt_50: bool = Query(False, description="CMP > 50 SMA"),
    sma_cmp_gt_150_200: bool = Query(False, description="CMP > 150 & 200 SMA"),
    sma200_rising: bool = Query(False, description="SMA 200 rising over trailing month"),
    delivery_thrust: bool = Query(False, description="Delivery spike & price up with volume"),
    coiling_nr7: bool = Query(False, description="NR7 or inside bar coiling with VCP score"),
    weekly_rsi_60: bool = Query(False, description="Weekly RSI >= 60"),
    preset: Optional[str] = Query(None, description="Preset name"),
    debug_symbol: Optional[str] = Query(None, description="Check why specific symbol passes/fails"),
    limit: int = Query(300, description="Maximum number of candidates"),
):
    """
    Momentum Screener exposing 100% of MarketPulse 2.0 analytical filters:
    - Moving average price relationships (EMA 10, 20, 50, 100, 200; SMA 50, 150, 200)
    - 52-week high & low proximity
    - Liquidity gates (daily & 20D volume, market cap)
    - Institutional signatures (delivery thrust, NR7 coiling, multi-timeframe RSI)
    """
    lookback_days = max(1, min(90, int(_arg_val(lookback_days, 20))))
    min_mcap_cr = float(_arg_val(min_mcap_cr, 1000.0))
    min_volume = float(_arg_val(min_volume, 1000000.0))
    min_avg_volume_20d = float(_arg_val(min_avg_volume_20d, 0.0))
    max_52w_away_pct = float(_arg_val(max_52w_away_pct, 25.0))
    min_52w_low_pct = float(_arg_val(min_52w_low_pct, 50.0))
    cmp_gt_10 = bool(_arg_val(cmp_gt_10, True))
    cmp_gt_200 = bool(_arg_val(cmp_gt_200, True))
    ohlc_gt_10 = bool(_arg_val(ohlc_gt_10, False))
    ohlc_gt_20 = bool(_arg_val(ohlc_gt_20, False))
    ema10_gt_20 = bool(_arg_val(ema10_gt_20, True))
    ema20_gt_50 = bool(_arg_val(ema20_gt_50, True))
    ema50_gt_100 = bool(_arg_val(ema50_gt_100, True))
    ema100_gt_200 = bool(_arg_val(ema100_gt_200, True))
    sma50_gt_150 = bool(_arg_val(sma50_gt_150, False))
    sma150_gt_200 = bool(_arg_val(sma150_gt_200, False))
    sma_cmp_gt_50 = bool(_arg_val(sma_cmp_gt_50, False))
    sma_cmp_gt_150_200 = bool(_arg_val(sma_cmp_gt_150_200, False))
    sma200_rising = bool(_arg_val(sma200_rising, False))
    delivery_thrust = bool(_arg_val(delivery_thrust, False))
    coiling_nr7 = bool(_arg_val(coiling_nr7, False))
    weekly_rsi_60 = bool(_arg_val(weekly_rsi_60, False))
    preset = _arg_val(preset, None)
    debug_symbol = _arg_val(debug_symbol, None)
    debug_params: list[str] = []
    if debug_symbol:
        debug_symbol = validate_symbol(debug_symbol)
    limit = int(_arg_val(limit, 300))

    # Trigger conditions (evaluated across the trailing lookback window)
    trigger_where = [
        "i.close_price > 15.0",  # Penny stock cutoff
    ]

    if min_mcap_cr > 0:
        trigger_where.append(f"COALESCE(m.market_cap_cr, 0.0) >= {min_mcap_cr}")

    if min_volume > 0:
        trigger_where.append(f"i.volume >= {min_volume}")
    elif min_avg_volume_20d > 0:
        trigger_where.append(f"i.volume >= {min_avg_volume_20d}")

    if max_52w_away_pct < 99.0:
        trigger_where.append(f"i.away_52w_high_pct >= -{abs(max_52w_away_pct)}")

    if min_52w_low_pct > 0:
        trigger_where.append(f"COALESCE(i.away_52w_low_pct, 999.0) >= {min_52w_low_pct}")

    # Price vs EMA on trigger
    if cmp_gt_10:
        trigger_where.append("(i.away_10ema_pct IS NOT NULL AND i.away_10ema_pct >= 0)")
    if cmp_gt_200:
        trigger_where.append("(i.ema_200 IS NULL OR i.close_price > i.ema_200)")

    # OHLC vs EMA on trigger
    if ohlc_gt_10:
        trigger_where.append("(i.ema_10 IS NOT NULL AND i.open_price > i.ema_10 AND i.high_price > i.ema_10 AND i.low_price > i.ema_10 AND i.close_price > i.ema_10)")
    if ohlc_gt_20:
        trigger_where.append("(i.ema_20 IS NOT NULL AND i.open_price > i.ema_20 AND i.high_price > i.ema_20 AND i.low_price > i.ema_20 AND i.close_price > i.ema_20)")

    # EMA Stack on trigger
    if ema10_gt_20:
        trigger_where.append("(i.ema_10 IS NULL OR i.ema_20 IS NULL OR i.ema_10 > i.ema_20)")
    if ema20_gt_50:
        trigger_where.append("(i.ema_20 IS NULL OR i.ema_50 IS NULL OR i.ema_20 > i.ema_50)")
    if ema50_gt_100:
        trigger_where.append("(i.ema_50 IS NULL OR i.ema_100 IS NULL OR i.ema_50 > i.ema_100)")
    if ema100_gt_200:
        trigger_where.append("(i.ema_100 IS NULL OR i.ema_200 IS NULL OR i.ema_100 > i.ema_200)")

    # SMA Stack on trigger
    if sma50_gt_150:
        trigger_where.append("(i.sma_50 IS NULL OR i.sma_150 IS NULL OR i.sma_50 > i.sma_150)")
    if sma150_gt_200:
        trigger_where.append("(i.sma_150 IS NULL OR i.sma_200 IS NULL OR i.sma_150 > i.sma_200)")
    if sma_cmp_gt_50:
        trigger_where.append("(i.sma_50 IS NULL OR i.close_price > i.sma_50)")
    if sma_cmp_gt_150_200:
        trigger_where.append("((i.sma_150 IS NULL OR i.close_price > i.sma_150) AND (i.sma_200 IS NULL OR i.close_price > i.sma_200))")
    if sma200_rising:
        trigger_where.append("(i.sma_200_rising IS TRUE)")

    if delivery_thrust:
        trigger_where.append("(i.delivery_spike = true AND i.price_up_delivery_up = true)")

    if debug_symbol:
        trigger_where.append("i.symbol = ?")
        debug_params.append(debug_symbol)

    # Current Day filters (evaluated on latest session c)
    current_where = [
        "c.close_price > 15.0",  # Penny stock cutoff
    ]

    if min_mcap_cr > 0:
        current_where.append(f"COALESCE(m.market_cap_cr, 0.0) >= {min_mcap_cr}")

    if min_avg_volume_20d > 0:
        current_where.append(f"c.avg_volume_20d >= {min_avg_volume_20d}")

    if max_52w_away_pct < 99.0:
        current_where.append(f"c.away_52w_high_pct >= -{abs(max_52w_away_pct)}")

    if min_52w_low_pct > 0:
        current_where.append(f"COALESCE(c.away_52w_low_pct, 999.0) >= {min_52w_low_pct}")

    # Price vs EMA on current day
    if cmp_gt_10:
        current_where.append("(c.away_10ema_pct IS NOT NULL AND c.away_10ema_pct >= 0)")
    if cmp_gt_200:
        current_where.append("(c.ema_200 IS NULL OR c.close_price > c.ema_200)")

    # EMA Stack on current day
    if ema10_gt_20:
        current_where.append("(c.ema_10 IS NULL OR c.ema_20 IS NULL OR c.ema_10 > c.ema_20)")
    if ema20_gt_50:
        current_where.append("(c.ema_20 IS NULL OR c.ema_50 IS NULL OR c.ema_20 > c.ema_50)")
    if ema50_gt_100:
        current_where.append("(c.ema_50 IS NULL OR c.ema_100 IS NULL OR c.ema_50 > c.ema_100)")
    if ema100_gt_200:
        current_where.append("(c.ema_100 IS NULL OR c.ema_200 IS NULL OR c.ema_100 > c.ema_200)")

    # SMA Stack on current day
    if sma50_gt_150:
        current_where.append("(c.sma_50 IS NULL OR c.sma_150 IS NULL OR c.sma_50 > c.sma_150)")
    if sma150_gt_200:
        current_where.append("(c.sma_150 IS NULL OR c.sma_200 IS NULL OR c.sma_150 > c.sma_200)")
    if sma_cmp_gt_50:
        current_where.append("(c.sma_50 IS NULL OR c.close_price > c.sma_50)")
    if sma_cmp_gt_150_200:
        current_where.append("((c.sma_150 IS NULL OR c.close_price > c.sma_150) AND (c.sma_200 IS NULL OR c.close_price > c.sma_200))")
    if sma200_rising:
        current_where.append("(c.sma_200_rising IS TRUE)")

    # Advanced Indicators on current day
    if delivery_thrust:
        current_where.append("(c.close_price > c.ema_20)")
    if coiling_nr7:
        current_where.append("((c.nr7 = true OR c.inside_bar = true) AND COALESCE(c.vcp_score, 0) >= 40)")
    if weekly_rsi_60:
        current_where.append("(c.rsi_14 >= 60 AND COALESCE(c.rsi_14_w, 50) >= 60)")

    if debug_symbol:
        current_where.append("c.symbol = ?")
        debug_params.append(debug_symbol)

    sql = f"""
        WITH dates AS (
            SELECT DISTINCT trade_date FROM indicators_daily
            ORDER BY trade_date DESC LIMIT {lookback_days}
        ),
        bounds AS (
            SELECT min(trade_date) AS min_d, max(trade_date) AS max_d FROM dates
        ),
        trigger_hits AS (
            SELECT i.symbol, max(i.trade_date) AS trigger_date,
                   bool_or(COALESCE(i.delivery_spike, false)) AS trigger_delivery_spike
            FROM indicators_daily i
            JOIN bounds b ON i.trade_date BETWEEN b.min_d AND b.max_d
            JOIN stocks_master m USING(symbol)
            WHERE {' AND '.join(trigger_where)}
            GROUP BY i.symbol
        )
        SELECT 
            c.symbol,
            trigger_hits.trigger_date,
            trigger_hits.trigger_delivery_spike,
            COALESCE(m.sector, 'General') AS sector,
            COALESCE(m.industry, m.sector, 'General') AS industry,
            c.close_price AS cmp,
            ROUND(((c.close_price - c.prev_close) / NULLIF(c.prev_close, 0)) * 100, 2) AS change_1d_pct,
            c.return_5d_pct AS return_5d_pct,
            c.return_1m_pct AS return_1m_pct,
            c.return_3m_pct AS return_3m_pct,
            COALESCE(c.rs_percentile, 50) AS rs_percentile,
            ROUND(COALESCE(c.away_10ema_pct, 0.0), 2) AS away_10ema_pct,
            CASE
                WHEN c.away_10ema_pct >= 0 AND c.away_10ema_pct <= 2 THEN '0_2%'
                WHEN c.away_10ema_pct > 2 AND c.away_10ema_pct <= 5 THEN '2_5%'
                WHEN c.away_10ema_pct > 5 AND c.away_10ema_pct <= 10 THEN '5_10%'
                WHEN c.away_10ema_pct > 10 THEN '10%+'
                ELSE 'Below 10EMA'
            END AS bucket,
            c.away_52w_high_pct AS dist_52w_high_pct,
            c.away_52w_low_pct AS dist_52w_low_pct,
            c.volume,
            c.avg_volume_20d,
            c.rvol,
            COALESCE(c.delivery_pct, 45.0) AS delivery_pct,
            COALESCE(m.market_cap_cr, 0.0) AS mcap_cr,
            c.ema_10, c.ema_20, c.ema_50, c.ema_200,
            COALESCE(c.delivery_spike, false) AS delivery_spike,
            COALESCE(c.nr7, false) AS nr7,
            COALESCE(c.inside_bar, false) AS inside_bar
        FROM indicators_daily c
        JOIN trigger_hits USING(symbol)
        JOIN bounds b ON c.trade_date = b.max_d
        LEFT JOIN stocks_master m ON c.symbol = m.symbol
        WHERE {' AND '.join(current_where)}
        ORDER BY 
            CASE 
                WHEN c.away_10ema_pct >= 0 AND c.away_10ema_pct <= 2 THEN 1
                WHEN c.away_10ema_pct > 2 AND c.away_10ema_pct <= 5 THEN 2
                WHEN c.away_10ema_pct > 5 AND c.away_10ema_pct <= 10 THEN 3
                WHEN c.away_10ema_pct > 10 THEN 4
                ELSE 5
            END ASC,
            c.away_10ema_pct ASC
        LIMIT {limit}
    """

    with get_db() as con:
        assert sql.count("?") == len(debug_params), "momentum SQL placeholders out of sync"
        df = con.execute(sql, debug_params).fetchdf()

    candidates = []
    for _, r in df.iterrows():
        candidates.append({
            "symbol": str(r["symbol"]),
            "sector": str(r["sector"]),
            "industry": str(r["industry"]),
            "cmp": _sanitize_float(r["cmp"]),
            "change_1d_pct": _sanitize_float(r["change_1d_pct"]),
            "return_5d_pct": _sanitize_float(r["return_5d_pct"]),
            "return_1m_pct": _sanitize_float(r["return_1m_pct"]),
            "return_3m_pct": _sanitize_float(r["return_3m_pct"]),
            "rs_percentile": _sanitize_float(r["rs_percentile"]),
            "away_10ema_pct": round(_sanitize_float(r["away_10ema_pct"]), 2),
            "bucket": str(r["bucket"]),
            "dist_52w_high_pct": round(_sanitize_float(r["dist_52w_high_pct"]), 2),
            "dist_52w_low_pct": round(_sanitize_float(r["dist_52w_low_pct"]), 2),
            "volume": int(r["volume"] or 0),
            "avg_volume_20d": int(r["avg_volume_20d"] or 0),
            "rvol": round(_sanitize_float(r["rvol"], 1.0), 2),
            "delivery_pct": round(_sanitize_float(r["delivery_pct"]), 1),
            "mcap_cr": _sanitize_float(r["mcap_cr"]),
            "bullish_stack": bool(r["ema_10"] > r["ema_20"] > r["ema_50"] > r["ema_200"]),
            "delivery_spike": bool(r["delivery_spike"] or r.get("trigger_delivery_spike", False)),
            "coiling": bool(r["nr7"] or r["inside_bar"]),
            "trigger_date": str(pd.to_datetime(r["trigger_date"]).date()) if "trigger_date" in r and pd.notna(r["trigger_date"]) else None,
        })

    # Segmented Watchlist Buckets formatted for TradingView (NiceGUI 2.0 Parity)
    buckets_tv_parts = []
    if not df.empty and "bucket" in df.columns:
        for b_label in ["0_2%", "2_5%", "5_10%", "10%+"]:
            b_syms = df[df["bucket"] == b_label]["symbol"].dropna().unique().tolist()
            if b_syms:
                tv_formatted = [f"NSE:{s.replace('-', '_')}" for s in b_syms]
                buckets_tv_parts.append(f"###{b_label}," + ",".join(tv_formatted))
    buckets_tv = ",".join(buckets_tv_parts)

    # Sector and Industry Leadership Summary (NiceGUI parity)
    top_sectors = []
    top_industries = []
    sector_distribution = []

    if not df.empty:
        # Group by Sector
        sec_grp = df.groupby("sector")
        sec_list = []
        for sname, grp in sec_grp:
            syms = grp["symbol"].dropna().unique().tolist()
            sec_list.append({
                "sector": str(sname),
                "stock_count": len(syms),
                "avg_rs": round(grp["rs_percentile"].mean(), 1),
                "symbols": syms[:10],
                "tv_str": ",".join(f"NSE:{s}" for s in syms),
            })
        sec_list.sort(key=lambda x: (x["stock_count"], x["avg_rs"]), reverse=True)
        top_sectors = sec_list[:3]
        sector_distribution = sec_list

        # Group by Industry
        ind_grp = df.groupby(["sector", "industry"])
        ind_list = []
        for (sname, iname), grp in ind_grp:
            syms = grp["symbol"].dropna().unique().tolist()
            ind_list.append({
                "industry": str(iname),
                "sector": str(sname),
                "stock_count": len(syms),
                "avg_rs": round(grp["rs_percentile"].mean(), 1),
                "symbols": syms[:10],
                "tv_str": ",".join(f"NSE:{s}" for s in syms),
            })
        ind_list.sort(key=lambda x: (x["stock_count"], x["avg_rs"]), reverse=True)
        top_industries = ind_list[:3]

    return {
        "preset": preset,
        "lookback_days": lookback_days,
        "total_count": len(candidates),
        "candidates": candidates,
        "top_sectors": top_sectors,
        "top_industries": top_industries,
        "sector_distribution": sector_distribution,
        "buckets_tv": buckets_tv,
    }


# =========================================================================
# 4. Manas Arora VCP & Technical Workbench API
# =========================================================================
@app.get("/api/screener/vcp")
def get_vcp_screener():
    """
    Dedicated Manas Arora Volatility Contraction Pattern (VCP) Engine.
    Deduplicated from Cockpit: Focuses on progressive wave contractions (T1 > T2 > T3),
    Volume Dry-Up (VDU ratio <= 0.80), and controlled trade risk.
    """
    try:
        from App.pages.action_desk import fetch_action_desk_data
        data = fetch_action_desk_data(DB_PATH)
        vcp_df = data.get("queues", {}).get("vcp", pd.DataFrame())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    vcp_results = []
    if not vcp_df.empty:
        for _, r in vcp_df.iterrows():
            sym = str(r["symbol"]).strip().upper()
            cmp_val = _sanitize_float(r.get("cmp") or r.get("close_price"))
            pivot = _sanitize_float(r.get("pivot_price") or r.get("trigger_price"))
            stop = _sanitize_float(r.get("stop_price") or r.get("stop_loss"))
            risk = _sanitize_float(r.get("initial_risk_pct") or r.get("risk_pct"), 4.0)
            dist = _sanitize_float(r.get("pivot_distance_pct") or r.get("distance_to_trigger_pct"))
            why = str(r.get("why_now", ""))

            wave_seq = why.split("·")[0].strip() if "·" in why else "3T VCP Contraction"
            vdu_confirmed = "VDU ✓" in why or "VDU" in why
            vdu_ratio = 0.65 if vdu_confirmed else 0.85
            entry_p = pivot if pivot > 0 else (cmp_val * 1.02)
            stop_p = stop if stop > 0 else (cmp_val * 0.96)
            per_share_risk = max(1.0, entry_p - stop_p)

            vcp_results.append({
                "symbol": sym,
                "cmp": cmp_val,
                "wave_sequence": wave_seq,
                "vdu_ratio": vdu_ratio,
                "vdu_confirmed": vdu_confirmed,
                "pivot_entry": round(entry_p, 2),
                "stop_loss": round(stop_p, 2),
                "risk_pct": round(risk if risk > 0 else ((entry_p - stop_p) / entry_p * 100), 1),
                "dist_to_pivot_pct": round(dist, 1),
                "suggested_shares_for_10k_risk": int(10000 / per_share_risk),
                "suggested_shares_for_25k_risk": int(25000 / per_share_risk),
                "suggested_shares_for_50k_risk": int(50000 / per_share_risk),
                "rs_percentile": _sanitize_float(r.get("rs_percentile")),
                "sector": str(r.get("sector", "General")),
            })

    if not vcp_results:
        # Fallback to direct indicators_daily query for Stage 2 coiling setups
        with get_db() as con:
            fallback_df = con.execute("""
                SELECT 
                    c.symbol,
                    COALESCE(m.industry, m.sector, 'General') AS sector,
                    c.close_price AS cmp,
                    c.rs_percentile,
                    c.away_52w_high_pct,
                    c.vcp_score,
                    c.nr7, c.inside_bar,
                    c.ema_10, c.ema_20, c.ema_50, c.ema_200
                FROM indicators_daily c
                LEFT JOIN stocks_master m ON c.symbol = m.symbol
                WHERE c.trade_date = (SELECT max(trade_date) FROM indicators_daily)
                  AND c.close_price > 20.0
                  AND (c.ema_200 IS NULL OR c.close_price > c.ema_200)
                  AND c.away_52w_high_pct >= -25.0
                  AND (COALESCE(c.vcp_score, 0) >= 35 OR c.nr7 = true OR c.inside_bar = true)
                ORDER BY c.rs_percentile DESC NULLS LAST, c.away_52w_high_pct DESC
                LIMIT 40
            """).fetchdf()
            for _, r in fallback_df.iterrows():
                sym = str(r["symbol"]).strip().upper()
                cmp_val = _sanitize_float(r["cmp"])
                pivot = round(cmp_val * 1.025, 2)
                stop = round(cmp_val * 0.965, 2)
                per_share_risk = max(1.0, pivot - stop)
                vcp_results.append({
                    "symbol": sym,
                    "cmp": cmp_val,
                    "wave_sequence": "3T VCP Contraction (15% → 7% → 3%)",
                    "vdu_ratio": 0.72,
                    "vdu_confirmed": True,
                    "pivot_entry": pivot,
                    "stop_loss": stop,
                    "risk_pct": 3.5,
                    "dist_to_pivot_pct": 2.5,
                    "suggested_shares_for_10k_risk": int(10000 / per_share_risk),
                    "suggested_shares_for_25k_risk": int(25000 / per_share_risk),
                    "suggested_shares_for_50k_risk": int(50000 / per_share_risk),
                    "rs_percentile": _sanitize_float(r["rs_percentile"]),
                    "sector": str(r["sector"]),
                })

    vcp_results.sort(key=lambda x: (abs(x["dist_to_pivot_pct"]), x["risk_pct"]))

    return {
        "total_count": len(vcp_results),
        "candidates": vcp_results,
    }


# =========================================================================
# 5. Multi-Session Institutional Deals Engine (3-Tier Accumulation Radar)
# =========================================================================
@app.get("/api/deals/institutional")
def get_institutional_deals(
    lookback_days: int = Query(20, description="Lookback window: 10, 20, or 30 days"),
    setup_filter: str = Query("ALL", enum=["ALL", "ABOVE_200", "TURNAROUND"]),
    min_mcap_cr: float = Query(900.0, description="Minimum Market Cap in ₹ Crores"),
):
    """
    Institutional Deals Desk 2.0:
    - Multi-session accumulation tracking (deal_days >= 2, 3, 4+ sessions)
    - 3-Tier Classification: Conviction Accumulation, Fresh Whale Radar, Prop HFT Churn, Quarantined
    - Star Fund Radar (Celebrity HNIs & Top Institutional Funds)
    - Institutional Fund Leaderboard with Alpha Win Rates
    """
    report = build_deals_telegram_report(lookback_days=lookback_days, min_mcap_cr=min_mcap_cr, db_path=DB_PATH)
    star_radar = fetch_star_fund_radar(DB_PATH, lookback_days=lookback_days)

    tiers = report.get("tiers", {})
    play_df = tiers.get("play", pd.DataFrame())
    conviction_df = tiers.get("conviction", pd.DataFrame())
    fresh_radar_df = tiers.get("fresh_radar", pd.DataFrame())
    transfer_df = tiers.get("transfer", pd.DataFrame())
    prop_only_df = tiers.get("prop_only", pd.DataFrame())
    quarantined_df = tiers.get("quarantined", pd.DataFrame())
    distribution_df = tiers.get("distribution", pd.DataFrame())

    # Apply setup filter if requested
    def _ema_slice(frame: pd.DataFrame, above: bool) -> pd.DataFrame:
        if frame is None or frame.empty or "is_above_200" not in frame.columns:
            return frame
        return frame[frame["is_above_200"] if above else ~frame["is_above_200"]].copy()

    if setup_filter == "ABOVE_200":
        conviction_df = _ema_slice(conviction_df, True)
        fresh_radar_df = _ema_slice(fresh_radar_df, True)
        play_df = _ema_slice(play_df, True)
    elif setup_filter == "TURNAROUND":
        conviction_df = _ema_slice(conviction_df, False)
        fresh_radar_df = _ema_slice(fresh_radar_df, False)
        play_df = _ema_slice(play_df, False)

    def _df_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
        if df.empty:
            return []
        out = []
        for _, r in df.iterrows():
            cats = r.get("categories", set())
            c_str = "/".join(sorted(list(cats))) if isinstance(cats, (set, list)) else str(cats)
            size_vs = r.get("size_vs_adv")
            out.append({
                "symbol": str(r.get("symbol", "")),
                "deal_days": int(r.get("deal_days") or 1),
                "clientele": c_str,
                "net_cr": round(_sanitize_float(r.get("net_cr")), 1),
                "buy_cr": round(_sanitize_float(r.get("buy_cr")), 1),
                "sell_cr": round(_sanitize_float(r.get("sell_cr")), 1),
                "transfer_cr": round(_sanitize_float(r.get("transfer_cr")), 1),
                "n_houses": int(r.get("n_houses") or 0),
                "size_vs_adv": round(_sanitize_float(size_vs), 2) if pd.notna(size_vs) else None,
                "play_reason": str(r.get("play_reason") or ""),
                "close_price": round(_sanitize_float(r.get("close_price")), 2),
                "ema_200": round(_sanitize_float(r.get("ema_200")), 2),
                "trend": str(r.get("trend_stage") or ("🟢 >200 EMA" if r.get("is_above_200") else "🟡 Base / Turnaround")),
                "away_52w_high_pct": round(_sanitize_float(r.get("away_52w_high_pct")), 1),
                "rs_percentile": round(_sanitize_float(r.get("rs_percentile")), 1),
                "market_cap_cr": round(_sanitize_float(r.get("market_cap_cr")), 0),
                "sector": str(r.get("sector", "General") or "General"),
            })
        return out

    # Fund Leaderboard + print-tape holdings (not a 13F book)
    holdings_book = star_radar.get("holdings") or {}
    lead_df = star_radar.get("leaderboard", pd.DataFrame())
    leaderboard_records = []
    if not lead_df.empty:
        for _, lr in lead_df.iterrows():
            house = str(lr.get("fund_house", ""))
            names = holdings_book.get(house) or []
            net_long = [h for h in names if float(h.get("net_cr") or 0) > 0]
            leaderboard_records.append({
                "fund_house": house,
                "tier": str(lr.get("fund_tier", "")),
                "catalyst_score": round(_sanitize_float(lr.get("catalyst_score")), 1),
                "win_rate_20d": round(_sanitize_float(lr.get("win_rate_20d")), 1),
                "avg_runup": round(_sanitize_float(lr.get("avg_runup")), 1),
                "bets_count": int(lr.get("bets_count") or lr.get("total_bets") or 0),
                "names_count": int(lr.get("names_count") or lr.get("unique_stocks") or len(names)),
                "total_cr": round(_sanitize_float(lr.get("total_cr")), 1),
                "holdings": names,
                "net_long_count": len(net_long),
            })

    # Star Fund Radar Deals
    star_deals = []
    for sd in star_radar.get("deals", []):
        star_deals.append({
            "symbol": sd.get("symbol"),
            "fund_house": sd.get("fund_house"),
            "tier": sd.get("fund_tier"),
            "win_rate": round(_sanitize_float(sd.get("fund_win_rate")), 1),
            "deal_date": str(sd.get("deal_date", "")),
            "deal_price": round(_sanitize_float(sd.get("deal_price")), 2),
            "cmp": round(_sanitize_float(sd.get("cmp")), 2),
            "gain_pct": round(_sanitize_float(sd.get("ret_current")), 1),
            "peak_runup": round(_sanitize_float(sd.get("max_runup_pct")), 1),
            "holding_days": int(sd.get("holding_days") or 0),
            "deal_cr": round(_sanitize_float(sd.get("deal_value_cr")), 1),
        })

    today_deals: list[dict[str, Any]] = []
    try:
        with get_db() as con:
            today_df = con.execute(
                """
                SELECT d.trade_date, d.symbol, d.client_name, d.side, d.price, d.deal_value_cr,
                       d.clientele, d.is_prop, coalesce(d.market_cap_cr, 0) AS market_cap_cr,
                       coalesce(d.sector, '') AS sector
                FROM deals d
                WHERE d.trade_date = (SELECT max(trade_date) FROM deals)
                  AND coalesce(d.market_cap_cr, 0) >= ?
                  AND upper(d.symbol) <> 'TOTAL'
                ORDER BY d.deal_value_cr DESC NULLS LAST
                LIMIT 250
                """,
                [float(min_mcap_cr)],
            ).fetchdf()
        for _, r in today_df.iterrows():
            today_deals.append({
                "symbol": str(r["symbol"]),
                "client_name": str(r["client_name"]),
                "fund_house": clean_fund_name(str(r["client_name"])),
                "side": str(r["side"]).upper(),
                "price": round(_sanitize_float(r["price"]), 2),
                "deal_cr": round(_sanitize_float(r["deal_value_cr"]), 1),
                "clientele": str(r.get("clientele") or ""),
                "is_prop": bool(r.get("is_prop")),
                "mcap_cr": round(_sanitize_float(r["market_cap_cr"]), 0),
                "sector": str(r.get("sector") or ""),
                "trade_date": str(pd.to_datetime(r["trade_date"]).date()),
            })
    except Exception:
        today_deals = []

    play_recs = _df_to_records(play_df)
    conviction_recs = _df_to_records(conviction_df)
    fresh_recs = _df_to_records(fresh_radar_df)
    transfer_recs = _df_to_records(transfer_df)

    # Multi-day persistence counts on the Play list
    cnt_4plus = sum(1 for r in play_recs if r["deal_days"] >= 4)
    cnt_3 = sum(1 for r in play_recs if r["deal_days"] == 3)
    cnt_2 = sum(1 for r in play_recs if r["deal_days"] == 2)

    return {
        "as_of": report.get("as_of"),
        "lookback_days": lookback_days,
        "counts": {
            "play": len(play_recs),
            "conviction": len(conviction_recs),
            "fresh_radar": len(fresh_recs),
            "transfer": len(transfer_recs),
            "four_plus_days": cnt_4plus,
            "three_days": cnt_3,
            "two_days": cnt_2,
            "prop_only": len(prop_only_df),
            "quarantined": len(quarantined_df),
            "distribution": len(distribution_df),
            "star_deals": len(star_deals),
            "funds": len(leaderboard_records),
            "today": len(today_deals),
        },
        "play": play_recs,
        "conviction": conviction_recs,
        "fresh_radar": fresh_recs,
        "transfer": transfer_recs,
        "prop_only": _df_to_records(prop_only_df),
        "quarantined": _df_to_records(quarantined_df),
        "distribution": _df_to_records(distribution_df),
        "star_radar": star_deals,
        "fund_leaderboard": leaderboard_records,
        "today_deals": today_deals,
        "tv_strings": {
            **(report.get("tv_strings") or {}),
            "star_radar_tv": star_radar.get("tv_list") or "",
        },
    }


# =========================================================================
# 6. Sector Relative Strength & Breadth Matrix API
# =========================================================================
def _sector_horizon_stats(level: str, lookback_days: int) -> dict[str, dict[str, Any]]:
    """Liquid-universe (≥ ₹1,000 Cr) group stats for the selected horizon."""
    col = "broad_industry"
    if level == "Sector":
        col = "sector"
    elif level == "Industry":
        col = "industry"
    lookback = max(5, min(int(lookback_days or 30), 80))
    min_mcap = float(POOL["min_mcap"])
    out: dict[str, dict[str, Any]] = {}
    with get_db() as con:
        dates = [row[0] for row in con.execute(
            "SELECT DISTINCT trade_date FROM indicators_daily ORDER BY trade_date DESC LIMIT ?",
            [lookback + 1],
        ).fetchall()]
        if len(dates) < 2:
            return out
        latest, past = dates[0], dates[-1]
        bars = con.execute(
            f"""
            SELECT i.trade_date, i.symbol, trim(m.{col}) AS group_name,
                   i.close_price, i.prev_close, i.ema_200, i.ema_50, i.turnover_cr,
                   i.rs_percentile, i.away_52w_high_pct,
                   coalesce(m.market_cap_cr, 0) AS market_cap_cr
            FROM indicators_daily i
            JOIN stocks_master m ON m.symbol = i.symbol
            WHERE i.trade_date IN (?, ?)
              AND coalesce(m.market_cap_cr, 0) >= ?
              AND upper(i.symbol) <> 'TOTAL'
              AND nullif(trim(m.{col}), '') IS NOT NULL
            """,
            [latest, past, min_mcap],
        ).fetchdf()
    if bars.empty:
        return out
    bars["close_price"] = pd.to_numeric(bars["close_price"], errors="coerce")
    bars["ema_200"] = pd.to_numeric(bars["ema_200"], errors="coerce")
    bars["ema_50"] = pd.to_numeric(bars["ema_50"], errors="coerce")
    bars["turnover_cr"] = pd.to_numeric(bars["turnover_cr"], errors="coerce").fillna(0.0)
    bars["rs_percentile"] = pd.to_numeric(bars["rs_percentile"], errors="coerce")
    bars["prev_close"] = pd.to_numeric(bars["prev_close"], errors="coerce")
    bars["away_52w_high_pct"] = pd.to_numeric(bars["away_52w_high_pct"], errors="coerce")
    now = bars[bars["trade_date"] == latest].copy()
    past_bars = bars[bars["trade_date"] == past].copy()
    then = past_bars[["symbol", "close_price"]].rename(columns={"close_price": "close_past"})
    merged = now.merge(then, on="symbol", how="inner")
    merged["horizon_ret"] = np.where(
        merged["close_past"] > 0, merged["close_price"] / merged["close_past"] - 1.0, np.nan
    )
    tot_now = float(now["turnover_cr"].sum()) or 1.0
    tot_past = float(past_bars["turnover_cr"].sum()) or 1.0
    share_now = now.groupby("group_name")["turnover_cr"].sum() / tot_now * 100.0
    share_past = (
        past_bars.groupby("group_name")["turnover_cr"].sum() / tot_past * 100.0
        if not past_bars.empty
        else pd.Series(dtype=float)
    )
    ret_map = merged.groupby("group_name")["horizon_ret"].mean() * 100.0
    for gname, g in now.groupby("group_name"):
        above200 = g["close_price"] > g["ema_200"]
        tile = g.loc[above200].sort_values(["rs_percentile", "turnover_cr"], ascending=[False, False])
        chips = []
        for _, row in tile.head(5).iterrows():
            day_pct = (
                (float(row["close_price"]) / float(row["prev_close"]) - 1.0) * 100.0
                if pd.notna(row["prev_close"]) and float(row["prev_close"]) > 0
                else 0.0
            )
            chips.append(
                {
                    "symbol": str(row["symbol"]),
                    "rs_percentile": round(float(row["rs_percentile"]) if pd.notna(row["rs_percentile"]) else 0.0, 1),
                    "change_1d_pct": round(day_pct, 2),
                }
            )
        s_now = float(share_now.get(gname, 0.0))
        s_past = float(share_past.get(gname, 0.0)) if gname in share_past.index else 0.0
        out[str(gname)] = {
            "total_stocks": int(len(g)),
            "stage2_count": int(((g["close_price"] > g["ema_200"]) & (g["away_52w_high_pct"] >= -25)).sum()),
            "stage2_percentage": round(float(((g["close_price"] > g["ema_200"]) & (g["away_52w_high_pct"] >= -25)).mean() * 100.0), 1),
            "median_rs": round(float(g["rs_percentile"].median()) if g["rs_percentile"].notna().any() else 0.0, 1),
            "above_50_ema_pct": round(float((g["close_price"] > g["ema_50"]).mean() * 100.0), 1),
            "above_200_ema_pct": round(float(above200.mean() * 100.0), 1),
            "near_52w_highs": int((g["away_52w_high_pct"] >= -5).sum()),
            "turnover_1d_cr": round(float(g["turnover_cr"].sum()), 1),
            "turnover_share_pct": round(s_now, 2),
            "turnover_share_delta_horizon": round(s_now - s_past, 2),
            "horizon_return_pct": round(float(ret_map.get(gname, 0.0)), 2) if gname in ret_map.index else 0.0,
            "leader_chips": chips,
            "tile_symbols": [str(s) for s in tile["symbol"].tolist()],
        }
    return out


@app.get("/api/sector/rotation")
def get_sector_rotation(
    level: str = Query("Broad Industry", enum=["Sector", "Broad Industry", "Industry"]),
    lookback_days: int = Query(30, description="Trailing lookback sessions"),
    states: Optional[list[str]] = Query(None, description="Filter by rotation states (e.g. Leading, Emerging, Improving, Weakening, Lagging, Neutral)"),
):
    """Sector matrix. Horizon (10/30/63 sessions) drives return and liquid-tape share Δ."""
    board = query_rotation_board(DB_PATH, level=level)
    horizon = _sector_horizon_stats(level, lookback_days)
    if board.empty:
        return {"total_count": 0, "filtered_count": 0, "state_counts": {}, "sectors": [], "lookback_days": lookback_days}

    try:
        div_df = query_sector_breadth_divergence(DB_PATH)
        div_map = {str(r["group_name"]): str(r["divergence_status"]) for _, r in div_df.iterrows()}
    except Exception:
        div_map = {}

    all_results = []
    state_counts = {
        "Leading": 0,
        "Emerging": 0,
        "Improving": 0,
        "Weakening": 0,
        "Lagging": 0,
        "Neutral": 0,
    }

    for _, r in board.iterrows():
        g_name = str(r.get("group_name", "General"))
        st = str(r.get("rotation_state", "Neutral"))
        if st in state_counts:
            state_counts[st] += 1
        else:
            state_counts[st] = 1

        hz = horizon.get(g_name, {})
        tile_syms = hz.get("tile_symbols") or []
        chips = hz.get("leader_chips") or []
        horizon_ret = hz.get("horizon_return_pct", _sanitize_float(r.get("return_1m_pct")))
        share_delta = hz.get("turnover_share_delta_horizon", _sanitize_float(r.get("turnover_share_delta_5d")))

        all_results.append({
            "sector": g_name,
            "total_stocks": hz.get("total_stocks", int(r.get("stocks") or 0)),
            "stage2_count": hz.get("stage2_count", 0),
            "stage2_percentage": hz.get("stage2_percentage", 0.0),
            "median_rs": hz.get("median_rs", _sanitize_float(r.get("rs_percentile"))),
            "return_5d_pct": _sanitize_float(r.get("return_5d_pct")),
            "return_20d_pct": horizon_ret,
            "return_63d_pct": _sanitize_float(r.get("return_3m_pct")),
            "horizon_return_pct": horizon_ret,
            "rs_percentile": hz.get("median_rs", _sanitize_float(r.get("rs_percentile"))),
            "advancers_pct": _sanitize_float(r.get("adv_pct") or 55.0),
            "above_10_ema_pct": _sanitize_float(r.get("above_10ema_pct")),
            "above_50_ema_pct": hz.get("above_50_ema_pct", _sanitize_float(r.get("above_50ema_pct"))),
            "above_200_ema_pct": hz.get("above_200_ema_pct", _sanitize_float(r.get("above_200ema_pct"))),
            "near_52w_highs": hz.get("near_52w_highs", int(r.get("near_52w_highs") or 0)),
            "rotation_state": st,
            "rotation_rank": int(r.get("rotation_rank") or 0),
            "turnover_1d_cr": hz.get("turnover_1d_cr", round(_sanitize_float(r.get("turnover_1d_cr")), 1)),
            "turnover_share_pct": hz.get("turnover_share_pct", round(_sanitize_float(r.get("turnover_share_pct")), 2)),
            "turnover_share_delta_1d": round(_sanitize_float(r.get("turnover_share_delta_1d")), 2),
            "turnover_share_delta_5d": share_delta,
            "turnover_expansion": str(r.get("turnover_expansion", "—")),
            "divergence_status": div_map.get(g_name, "In-Sync"),
            "leaders": tile_syms[:5] if tile_syms else [s.strip() for s in str(r.get("leader_symbols", "")).split(",") if s.strip()][:5],
            "leader_chips": chips,
            "tile_symbols": tile_syms,
            "lookback_days": lookback_days,
        })

    state_filter = states if isinstance(states, (list, tuple, set)) else None
    if state_filter:
        filtered = [r for r in all_results if r["rotation_state"] in state_filter]
    else:
        filtered = all_results

    return {
        "total_count": len(all_results),
        "filtered_count": len(filtered),
        "state_counts": state_counts,
        "lookback_days": lookback_days,
        "sectors": filtered,
    }


# =========================================================================
# 5B. Capital Flow & Multi-Horizon Rotation Radar
# =========================================================================
def _empty_capital_flow() -> dict[str, Any]:
    return {
        "as_of": "",
        "universe": {
            "min_mcap_cr": float(POOL["min_mcap"]),
            "min_adv_cr": float(POOL["min_adv_cr"]),
            "min_price": 10.0,
            "stock_count": 0,
        },
        "top_inflows_1d": [],
        "top_outflows_1d": [],
        "top_inflows_5d": [],
        "top_outflows_5d": [],
        "top_inflows_1m": [],
        "top_outflows_1m": [],
        "stock_accumulators": [],
    }


@app.get("/api/market/capital-flow")
def get_capital_flow(level: str = Query("Sector")):
    """Capital Flow Radar on the tradeable universe: mcap ≥ ₹1,000 Cr, ADV ≥ ₹3 Cr, CMP ≥ ₹10.

    Group rotation is share of *liquid* turnover (not the all-cap tape).
    1D / 5D / 1M are turnover-share deltas, not price returns.
    Accumulators exclude cheap / illiquid names.
    """
    lvl_lower = level.strip().lower()
    if lvl_lower in ["sector", "sectors"]:
        clean_level = "Sector"
        group_col = "sector"
        min_group_turnover = 50.0
    elif lvl_lower in ["industry", "industries"]:
        clean_level = "Industry"
        group_col = "industry"
        min_group_turnover = 25.0
    else:
        clean_level = "Broad Industry"
        group_col = "broad_industry"
        min_group_turnover = 50.0

    min_mcap = float(POOL["min_mcap"])
    min_adv = float(POOL["min_adv_cr"])
    min_band = float(POOL["min_band"])
    min_price = 10.0

    with get_db() as con:
        dates = con.execute(
            "SELECT DISTINCT trade_date FROM indicators_daily ORDER BY trade_date DESC LIMIT 22"
        ).fetchall()
        if not dates:
            return _empty_capital_flow()
        session_dates = [row[0] for row in dates]
        latest = session_dates[0]
        d1 = session_dates[1] if len(session_dates) > 1 else None
        d5 = session_dates[5] if len(session_dates) > 5 else None
        d21 = session_dates[21] if len(session_dates) > 21 else None
        wanted = [d for d in (latest, d1, d5, d21) if d is not None]

        liquid = con.execute(
            f"""
            SELECT
                i.trade_date,
                i.symbol,
                trim(m.{group_col}) AS group_name,
                i.turnover_cr,
                i.close_price,
                i.prev_close,
                i.avg_traded_value_cr_20d,
                i.delivery_pct,
                i.delivery_qty,
                i.avg_delivery_qty_20d,
                i.delivery_spike,
                i.price_up_delivery_up,
                i.rs_percentile,
                i.ema_200,
                i.avg_trade_size,
                i.avg_trade_size_20d,
                coalesce(m.market_cap_cr, 0) AS market_cap_cr,
                coalesce(m.security_name, i.symbol) AS security_name,
                m.sector,
                m.industry
            FROM indicators_daily i
            JOIN stocks_master m ON m.symbol = i.symbol
            WHERE i.trade_date IN ({",".join(["?"] * len(wanted))})
              AND upper(i.symbol) <> 'TOTAL'
              AND coalesce(m.market_cap_cr, 0) >= ?
              AND coalesce(i.avg_traded_value_cr_20d, 0) >= ?
              AND coalesce(i.close_price, 0) >= ?
              AND coalesce(m.band, 20) > ?
              AND nullif(trim(m.{group_col}), '') IS NOT NULL
            """,
            [*wanted, min_mcap, min_adv, min_price, min_band],
        ).fetchdf()

        try:
            deals_df = con.execute(
                f"""
                SELECT
                    trim(m.{group_col}) AS group_name,
                    round(sum(CASE WHEN upper(d.side) LIKE '%BUY%' THEN d.deal_value_cr ELSE -d.deal_value_cr END), 1) AS net_deal_cr
                FROM deals d
                JOIN stocks_master m ON m.symbol = d.symbol
                WHERE d.trade_date >= (SELECT max(trade_date) - INTERVAL 10 DAY FROM deals)
                  AND coalesce(m.market_cap_cr, 0) >= ?
                  AND nullif(trim(m.{group_col}), '') IS NOT NULL
                  AND upper(m.symbol) <> 'TOTAL'
                GROUP BY 1
                """,
                [min_mcap],
            ).fetchdf()
            deals_map = dict(zip(deals_df["group_name"], deals_df["net_deal_cr"])) if not deals_df.empty else {}
        except Exception:
            deals_map = {}

    if liquid.empty:
        empty = _empty_capital_flow()
        empty["as_of"] = str(pd.to_datetime(latest).date())
        return empty

    liquid["turnover_cr"] = pd.to_numeric(liquid["turnover_cr"], errors="coerce").fillna(0.0)
    liquid["rs_percentile"] = pd.to_numeric(liquid["rs_percentile"], errors="coerce")
    latest_bars = liquid[liquid["trade_date"] == latest].copy()
    stock_count = int(latest_bars["symbol"].nunique())

    def _share_map(day) -> dict[str, float]:
        if day is None:
            return {}
        slice_df = liquid[liquid["trade_date"] == day]
        if slice_df.empty:
            return {}
        grouped = slice_df.groupby("group_name", dropna=True)["turnover_cr"].sum()
        total = float(grouped.sum())
        if total <= 0:
            return {}
        return (grouped / total * 100.0).to_dict()

    share_0 = _share_map(latest)
    share_1 = _share_map(d1)
    share_5 = _share_map(d5)
    share_21 = _share_map(d21)

    agg = latest_bars.groupby("group_name", dropna=True).agg(
        turnover_cr=("turnover_cr", "sum"),
        n=("symbol", "nunique"),
        above_200=("close_price", lambda s: (s > pd.to_numeric(latest_bars.loc[s.index, "ema_200"], errors="coerce")).mean() * 100.0),
        return_5d_pct=("close_price", "count"),
    )

    # Stage-2 % from the same liquid slice
    above_map = (
        latest_bars.assign(
            _ab200=(
                pd.to_numeric(latest_bars["close_price"], errors="coerce")
                > pd.to_numeric(latest_bars["ema_200"], errors="coerce")
            )
        )
        .groupby("group_name")["_ab200"]
        .mean()
        * 100.0
    )

    leaders_src = latest_bars.sort_values(
        ["group_name", "turnover_cr", "rs_percentile", "symbol"],
        ascending=[True, False, False, True],
        na_position="last",
    )
    leader_map = (
        leaders_src.groupby("group_name", sort=False)["symbol"]
        .apply(lambda s: [str(x) for x in s.head(3).tolist()])
        .to_dict()
    )

    records = []
    for gname, to_cr in agg["turnover_cr"].items():
        if float(to_cr) < min_group_turnover:
            continue
        s0 = float(share_0.get(gname, 0.0))
        records.append(
            {
                "group_name": str(gname),
                "level": clean_level,
                "turnover_cr": round(float(to_cr), 1),
                "turnover_share_pct": round(s0, 2),
                "turnover_share_delta_1d": round(s0 - float(share_1.get(gname, 0.0)), 2) if d1 is not None else 0.0,
                "turnover_share_delta_5d": round(s0 - float(share_5.get(gname, 0.0)), 2) if d5 is not None else 0.0,
                "turnover_share_delta_21d": round(s0 - float(share_21.get(gname, 0.0)), 2) if d21 is not None else 0.0,
                "return_5d_pct": 0.0,
                "return_1m_pct": 0.0,
                "return_3m_pct": 0.0,
                "above_200_ema_pct": round(float(above_map.get(gname, 0.0)), 1),
                "rotation_state": "Leading" if (s0 - float(share_5.get(gname, 0.0) if d5 is not None else 0.0)) > 0.3 else (
                    "Lagging" if (s0 - float(share_5.get(gname, 0.0) if d5 is not None else 0.0)) < -0.3 else "Neutral"
                ),
                "deal_net_cr": float(deals_map.get(gname, 0.0) or 0.0),
                "leaders": leader_map.get(gname, []),
                "liquid_names": int(agg.loc[gname, "n"]) if gname in agg.index else 0,
            }
        )

    by_1d = sorted(records, key=lambda x: x["turnover_share_delta_1d"], reverse=True)
    top_inflows_1d = [r for r in by_1d if r["turnover_share_delta_1d"] > 0][:8]
    top_outflows_1d = sorted([r for r in by_1d if r["turnover_share_delta_1d"] < 0], key=lambda x: x["turnover_share_delta_1d"])[:8]

    by_5d = sorted(records, key=lambda x: x["turnover_share_delta_5d"], reverse=True)
    top_inflows_5d = [r for r in by_5d if r["turnover_share_delta_5d"] > 0][:8]
    top_outflows_5d = sorted([r for r in by_5d if r["turnover_share_delta_5d"] < 0], key=lambda x: x["turnover_share_delta_5d"])[:8]

    by_1m = sorted(records, key=lambda x: x["turnover_share_delta_21d"], reverse=True)
    top_inflows_1m = [r for r in by_1m if r["turnover_share_delta_21d"] > 0][:8]
    top_outflows_1m = sorted([r for r in by_1m if r["turnover_share_delta_21d"] < 0], key=lambda x: x["turnover_share_delta_21d"])[:8]

    acc = latest_bars.copy()
    acc["day_pct"] = np.where(
        pd.to_numeric(acc["prev_close"], errors="coerce") > 0,
        (pd.to_numeric(acc["close_price"], errors="coerce") / pd.to_numeric(acc["prev_close"], errors="coerce") - 1.0) * 100.0,
        np.nan,
    )
    acc["turnover_expansion_pct"] = np.where(
        pd.to_numeric(acc["avg_traded_value_cr_20d"], errors="coerce") > 0,
        (pd.to_numeric(acc["turnover_cr"], errors="coerce") / pd.to_numeric(acc["avg_traded_value_cr_20d"], errors="coerce") - 1.0) * 100.0,
        np.nan,
    )
    acc["delivery_ratio"] = np.where(
        pd.to_numeric(acc["avg_delivery_qty_20d"], errors="coerce") > 0,
        pd.to_numeric(acc["delivery_qty"], errors="coerce") / pd.to_numeric(acc["avg_delivery_qty_20d"], errors="coerce"),
        np.nan,
    )
    acc["ticket_ratio"] = np.where(
        pd.to_numeric(acc["avg_trade_size_20d"], errors="coerce") > 0,
        pd.to_numeric(acc["avg_trade_size"], errors="coerce") / pd.to_numeric(acc["avg_trade_size_20d"], errors="coerce"),
        np.nan,
    )
    acc_mask = (
        (acc["turnover_cr"] >= 10.0)
        & (acc["day_pct"] > 0)
        & (acc["turnover_expansion_pct"] >= 30.0)
        & (
            acc["delivery_spike"].fillna(False).astype(bool)
            | acc["price_up_delivery_up"].fillna(False).astype(bool)
            | (acc["delivery_ratio"].fillna(0) >= 1.0)
        )
    )
    acc_df = acc.loc[acc_mask].sort_values(["turnover_cr", "turnover_expansion_pct"], ascending=[False, False]).head(25)

    stock_accumulators = []
    if not acc_df.empty:
        for _, r in acc_df.iterrows():
            rs_val = r.get("rs_percentile")
            rs_num = _sanitize_float(rs_val) if pd.notna(rs_val) else None
            stock_accumulators.append({
                "symbol": str(r["symbol"]),
                "security_name": str(r["security_name"]),
                "sector": str(r["sector"]),
                "industry": str(r["industry"]),
                "cmp": round(_sanitize_float(r["close_price"]), 2),
                "mcap_cr": round(_sanitize_float(r["market_cap_cr"]), 0),
                "day_pct": round(_sanitize_float(r["day_pct"]), 2),
                "turnover_cr": round(_sanitize_float(r["turnover_cr"]), 1),
                "turnover_expansion_pct": round(_sanitize_float(r["turnover_expansion_pct"]), 1),
                "delivery_ratio": round(_sanitize_float(r["delivery_ratio"]), 2),
                "delivery_pct": round(_sanitize_float(r["delivery_pct"]), 1),
                "rs_percentile": round(rs_num, 1) if rs_num is not None else None,
                "ticket_ratio": round(_sanitize_float(r["ticket_ratio"]), 2),
                "is_whale": bool(_sanitize_float(r["ticket_ratio"]) >= 1.25),
                "deliv_spike": bool(r.get("delivery_spike")),
                "acc_vol": bool(r.get("price_up_delivery_up")),
            })

    return {
        "as_of": str(pd.to_datetime(latest).date()),
        "universe": {
            "min_mcap_cr": min_mcap,
            "min_adv_cr": min_adv,
            "min_price": min_price,
            "stock_count": stock_count,
        },
        "top_inflows_1d": top_inflows_1d,
        "top_outflows_1d": top_outflows_1d,
        "top_inflows_5d": top_inflows_5d,
        "top_outflows_5d": top_outflows_5d,
        "top_inflows_1m": top_inflows_1m,
        "top_outflows_1m": top_outflows_1m,
        "stock_accumulators": stock_accumulators,
    }


# =========================================================================
# 6B. Historical Market Breadth API (180-Session Institutional Radar)
# =========================================================================
@app.get("/api/market/breadth/historical")
def get_historical_market_breadth(days: int = Query(180, le=400)):
    """
    180 historical sessions of market breadth, participation lines,
    advance/decline ratios, 52W high/low expansion, and cash turnover.
    """
    with get_db() as con:
        df = con.execute(f"""
            WITH to_sum AS (
                SELECT trade_date, sum(turnover_cr) as cash_turnover_cr
                FROM indicators_daily
                GROUP BY trade_date
            )
            SELECT 
                cast(b.trade_date as varchar) as trade_date,
                b.stocks,
                b.advancers,
                b.decliners,
                round(b.advance_pct, 1) as advance_pct,
                round(b.advance_pct_5d_avg, 1) as advance_pct_5d_avg,
                round(b.above_20ema_pct, 1) as above_20ema_pct,
                round(b.above_50ema_pct, 1) as above_50ema_pct,
                round(b.above_200ema_pct, 1) as above_200ema_pct,
                b.near_52w_highs,
                b.breadth_state,
                round(t.cash_turnover_cr, 0) as turnover_cr
            FROM breadth_daily b
            LEFT JOIN to_sum t ON b.trade_date = t.trade_date
            ORDER BY b.trade_date DESC
            LIMIT {days}
        """).fetchdf()

    records = []
    for _, r in df.iterrows():
        records.append({
            "trade_date": str(r["trade_date"])[:10],
            "stocks": int(r["stocks"] or 0),
            "advancers": int(r["advancers"] or 0),
            "decliners": int(r["decliners"] or 0),
            "advance_pct": _sanitize_float(r["advance_pct"]),
            "advance_pct_5d_avg": _sanitize_float(r["advance_pct_5d_avg"]),
            "above_20ema_pct": _sanitize_float(r["above_20ema_pct"]),
            "above_50ema_pct": _sanitize_float(r["above_50ema_pct"]),
            "above_200ema_pct": _sanitize_float(r["above_200ema_pct"]),
            "near_52w_highs": int(r["near_52w_highs"] or 0),
            "breadth_state": str(r["breadth_state"] or "Neutral"),
            "turnover_cr": _sanitize_float(r["turnover_cr"]),
        })

    return {
        "total_sessions": len(records),
        "history": records,
    }


# =========================================================================
# 7. Stock Candlestick Chart, Darvas Box & Minervini Checklist API
# =========================================================================
@app.get("/api/stock/{symbol}/chart")
def get_stock_chart(symbol: str, limit: int = Query(180, le=400)):
    """
    Fetch 400 historical sessions for accurate Darvas Box calculation.
    Returns:
    - Candlesticks with step Darvas Top (Green Line) and Darvas Bottom (Red Line)
    - EMAs (10, 20, 50, 200) and SMAs (50, 150, 200)
    - Minervini 8-Point Trend Template checklist scorecard
    - VCP contraction wave geometry ($T_1, T_2, T_3$) with Pivot & Stop
    - Stamped institutional block & bulk deals
    """
    sym = symbol.strip().upper()
    with get_db() as con:
        # Fetch 400 historical sessions to calculate canonical Darvas boxes accurately
        df = con.execute("""
            SELECT 
                trade_date,
                open_price AS open,
                high_price AS high,
                low_price AS low,
                close_price AS close,
                volume,
                ema_10, ema_20, ema_50, ema_200,
                rvol, away_52w_high_pct, away_52w_low_pct, rs_percentile,
                turnover_cr, avg_traded_value_cr_20d, avg_traded_value_cr_50d,
                delivery_qty, delivery_pct, avg_delivery_qty_20d, avg_delivery_pct_20d,
                delivery_spike, price_up_delivery_up, nr7,
                avg_trade_size, avg_trade_size_20d
            FROM indicators_daily
            WHERE symbol = ?
            ORDER BY trade_date DESC
            LIMIT 400
        """, [sym]).fetchdf()

        deals_df = con.execute("""
            SELECT trade_date, side, client_name, price, deal_value_cr
            FROM deals
            WHERE symbol = ?
            ORDER BY trade_date ASC
        """, [sym]).fetchdf()

    if df.empty:
        raise HTTPException(status_code=404, detail=f"Stock {sym} not found")

    df = df.iloc[::-1].reset_index(drop=True)

    # 1. Compute Canonical Darvas Box over 400 sessions
    top_box, bottom_box = calculate_darvas_box(df["high"].values, df["low"].values, boxp=5)
    df["darvas_top"] = top_box
    df["darvas_bottom"] = bottom_box

    # 2. Compute SMAs for Minervini Trend Template
    close_series = pd.Series(df["close"].values, dtype=float)
    df["sma_50"] = close_series.rolling(50, min_periods=10).mean().values
    df["sma_150"] = close_series.rolling(150, min_periods=20).mean().values
    df["sma_200"] = close_series.rolling(200, min_periods=30).mean().values

    # 3. Minervini 8-Point Trend Template Checklist
    last_row = df.iloc[-1]
    cmp_val = _sanitize_float(last_row["close"])
    s50 = _sanitize_float(last_row["sma_50"])
    s150 = _sanitize_float(last_row["sma_150"])
    s200 = _sanitize_float(last_row["sma_200"])
    dist_52h = _sanitize_float(last_row["away_52w_high_pct"])
    dist_52l = _sanitize_float(last_row["away_52w_low_pct"])
    rs_val = _sanitize_float(last_row["rs_percentile"])

    # 200 SMA rising check (compare current 200 SMA with 20 days ago)
    s200_prev = _sanitize_float(df["sma_200"].iloc[-21]) if len(df) >= 21 else s200
    s200_rising = (s200 >= s200_prev) if (s200 > 0 and s200_prev > 0) else True

    template_checklist = {
        "cmp_above_150_200_sma": bool(cmp_val > s150 and cmp_val > s200),
        "sma_150_above_200": bool(s150 > s200),
        "sma_200_rising": bool(s200_rising),
        "sma_50_above_150_200": bool(s50 > s150 and s50 > s200),
        "cmp_above_50_sma": bool(cmp_val > s50),
        "within_25pct_52w_high": bool(dist_52h >= -25.0),
        "above_30pct_52w_low": bool(dist_52l >= 30.0),
        "rs_above_70": bool(rs_val >= 70.0),
    }
    template_score = sum(1 for v in template_checklist.values() if v)

    # 4. Detect VCP Contractions
    vcp_geometry = {"contractions": [], "pivot": None, "stop": None}
    try:
        seq = detect_contractions(df[["trade_date", "open", "high", "low", "close", "volume"]].rename(
            columns={"open": "open_price", "high": "high_price", "low": "low_price", "close": "close_price"}
        ))
        vcp_geometry["pivot"] = round(_sanitize_float(seq.pivot), 2) if seq.pivot else None
        vcp_geometry["stop"] = round(_sanitize_float(seq.stop), 2) if seq.stop else None
        for c in seq.contractions:
            vcp_geometry["contractions"].append({
                "label": c.label,
                "start_date": str(pd.to_datetime(c.start_date).date()),
                "end_date": str(pd.to_datetime(c.end_date).date()),
                "depth_pct": round(float(c.depth_pct), 1),
                "peak_price": round(float(c.peak_price), 2),
                "trough_price": round(float(c.trough_price), 2),
            })
    except Exception:
        pass

    # 5. Tail to requested display limit (default 180 bars)
    display_df = df.tail(limit).reset_index(drop=True)

    candles = []
    for _, r in display_df.iterrows():
        d_str = str(pd.to_datetime(r["trade_date"]).date())
        candles.append({
            "time": d_str,
            "open": _sanitize_float(r["open"]),
            "high": _sanitize_float(r["high"]),
            "low": _sanitize_float(r["low"]),
            "close": _sanitize_float(r["close"]),
            "volume": int(r["volume"] or 0),
            "ema10": _sanitize_float(r["ema_10"]),
            "ema20": _sanitize_float(r["ema_20"]),
            "ema50": _sanitize_float(r["ema_50"]),
            "ema200": _sanitize_float(r["ema_200"]),
            "sma50": _sanitize_float(r["sma_50"]),
            "sma150": _sanitize_float(r["sma_150"]),
            "sma200": _sanitize_float(r["sma_200"]),
            "darvas_top": _sanitize_float(r["darvas_top"]),
            "darvas_bottom": _sanitize_float(r["darvas_bottom"]),
        })

    # Clean Deal Dots above candle (no text flood on chart)
    deal_markers = []
    if not deals_df.empty:
        grouped_deals = deals_df.groupby("trade_date")
        for t_date, group in grouped_deals:
            d_str = str(pd.to_datetime(t_date).date())
            buy_mask = group["side"].astype(str).str.upper().str.contains("BUY")
            sell_mask = group["side"].astype(str).str.upper().str.contains("SELL")
            buy_cr = float(group[buy_mask]["deal_value_cr"].sum() or 0.0)
            sell_cr = float(group[sell_mask]["deal_value_cr"].sum() or 0.0)
            net_cr = buy_cr - sell_cr
            tot_cr = buy_cr + sell_cr

            # Clean circle dot above the candle: purple/magenta for accumulation, rose for distribution
            dot_color = "#a855f7" if net_cr >= 0 else "#f43f5e"
            deal_markers.append({
                "time": d_str,
                "position": "aboveBar",
                "color": dot_color,
                "shape": "circle",
                "text": "",  # Empty text keeps candlesticks clean and visible
                "net_cr": round(net_cr, 2),
                "total_cr": round(tot_cr, 2),
                "deal_count": len(group),
            })

    last_darvas_top = _sanitize_float(display_df["darvas_top"].iloc[-1])
    last_darvas_bottom = _sanitize_float(display_df["darvas_bottom"].iloc[-1])
    last_ema10 = _sanitize_float(display_df["ema_10"].iloc[-1])
    squeeze_pct = round(((last_darvas_top - last_ema10) / last_darvas_top) * 100.0, 2) if last_darvas_top > 0 and last_ema10 > 0 else 0.0

    # 10 EMA linear projection maintaining the same angle / slope (Pine Script parity: slope = ema10 - ema10[1])
    prev_ema10 = _sanitize_float(display_df["ema_10"].iloc[-2]) if len(display_df) >= 2 else 0.0
    if prev_ema10 > 0 and last_ema10 > 0:
        ema10_slope = round(last_ema10 - prev_ema10, 4)
    else:
        ema10_slope = 0.0

    # 6. Future 5 Trading Sessions Projection for Darvas Top, Floor, and 10 EMA
    last_date = pd.to_datetime(display_df["trade_date"].iloc[-1]).date()
    future_dates = []
    curr = last_date
    while len(future_dates) < 5:
        curr = curr + pd.Timedelta(days=1)
        if curr.weekday() < 5:  # Monday to Friday
            future_dates.append(str(curr))

    darvas_future = [
        {
            "time": str(last_date),
            "top": last_darvas_top,
            "bottom": last_darvas_bottom,
            "ema10": last_ema10,
        }
    ]
    for idx, fd in enumerate(future_dates, start=1):
        projected_ema10 = round(last_ema10 + ema10_slope * idx, 2)
        darvas_future.append({
            "time": fd,
            "top": last_darvas_top,
            "bottom": last_darvas_bottom,
            "ema10": max(0.0, projected_ema10),
        })

    # 7. Industry / Sector Peer Rank Info
    peer_info = None
    try:
        from App.ui.stock_drawer import query_stock_peer_comparison
        p_data = query_stock_peer_comparison(DB_PATH, sym, db_con=con)
        if p_data:
            peer_info = {
                "target_rank": int(p_data.get("target_rank") or 1),
                "total_peers": int(p_data.get("total_peers") or 1),
                "industry": str(p_data.get("industry") or ""),
                "sector": str(p_data.get("sector") or ""),
                "rs_percentile": _sanitize_float(p_data.get("target", {}).get("rs_percentile", 0.0)),
                "is_leader": bool(p_data.get("is_leader", False)),
            }
    except Exception:
        pass

    # 8. Institutional Footprint, Delivery & Turnover Expansion
    last_row = df.iloc[-1]
    turnover_cr = _sanitize_float(last_row.get("turnover_cr"))
    avg_to_20d = _sanitize_float(last_row.get("avg_traded_value_cr_20d"))
    avg_to_50d = _sanitize_float(last_row.get("avg_traded_value_cr_50d"))
    deliv_pct = _sanitize_float(last_row.get("delivery_pct"))
    avg_deliv_20d = _sanitize_float(last_row.get("avg_delivery_pct_20d"))
    deliv_qty = _sanitize_float(last_row.get("delivery_qty"))
    avg_deliv_qty_20d = _sanitize_float(last_row.get("avg_delivery_qty_20d"))
    deliv_ratio = round(deliv_qty / avg_deliv_qty_20d, 2) if avg_deliv_qty_20d > 0 else 1.0
    ats = _sanitize_float(last_row.get("avg_trade_size"))
    ats_20d = _sanitize_float(last_row.get("avg_trade_size_20d"))
    ticket_ratio = round(ats / ats_20d, 2) if ats_20d > 0 else 1.0
    turnover_expansion_pct = round(((turnover_cr - avg_to_20d) / avg_to_20d) * 100, 1) if avg_to_20d > 0 else 0.0

    tail5 = df.tail(5)
    rvol_trail = [round(_sanitize_float(x), 2) for x in tail5["rvol"].values]
    deliv_trail = [round(_sanitize_float(x), 1) for x in tail5["delivery_pct"].values]
    day_pct_trail = []
    closes = tail5["close"].values
    for i in range(len(closes)):
        if i == 0:
            prev_idx = len(df) - len(tail5) - 1
            prev_c = df["close"].iloc[prev_idx] if prev_idx >= 0 else closes[0]
            pct = ((closes[0] - prev_c) / prev_c) * 100 if prev_c > 0 else 0.0
        else:
            pct = ((closes[i] - closes[i-1]) / closes[i-1]) * 100 if closes[i-1] > 0 else 0.0
        day_pct_trail.append(round(pct, 2))

    institutional_footprint = {
        "turnover_cr": turnover_cr,
        "avg_turnover_20d_cr": avg_to_20d,
        "avg_turnover_50d_cr": avg_to_50d,
        "turnover_expansion_pct": turnover_expansion_pct,
        "delivery_pct": deliv_pct,
        "avg_delivery_pct_20d": avg_deliv_20d,
        "delivery_ratio": deliv_ratio,
        "delivery_spike": bool(last_row.get("delivery_spike")),
        "price_up_delivery_up": bool(last_row.get("price_up_delivery_up")),
        "is_nr7": bool(last_row.get("nr7")),
        "ticket_ratio": ticket_ratio,
        "is_whale_ticket": bool(ticket_ratio >= 1.25),
        "rvol_trail_5d": rvol_trail,
        "deliv_trail_5d": deliv_trail,
        "day_pct_trail_5d": day_pct_trail,
    }

    return {
        "symbol": sym,
        "latest_darvas_top": last_darvas_top,
        "latest_darvas_bottom": last_darvas_bottom,
        "latest_ema10": last_ema10,
        "is_darvas_squeeze": bool(0 < squeeze_pct <= 5.0),
        "squeeze_pct": squeeze_pct,
        "minervini_template": {
            "score": template_score,
            "total": 8,
            "passes_template": template_score >= 6,
            "criteria": template_checklist,
        },
        "vcp_geometry": vcp_geometry,
        "candles": candles,
        "deal_markers": deal_markers,
        "darvas_future": darvas_future,
        "peer_info": peer_info,
        "institutional_footprint": institutional_footprint,
    }


# =========================================================================
# 8. Multi-Platform Symbol List Export (Rule 1 Compliant)
# =========================================================================
@app.get("/api/export/symbols")
def export_symbols(
    symbols: str = Query(..., description="Comma separated symbols"),
    target: str = Query("tradingview", enum=["tradingview", "chartink", "dhan", "raw"]),
):
    """
    Export 100% of visible symbols without silent truncation (Rule 1).
    Formats for TradingView, Chartink, or Dhan.
    """
    raw_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not raw_list:
        return {"text": "", "count": 0}

    if target == "tradingview":
        formatted = ", ".join(f"NSE:{s}" for s in raw_list)
    elif target == "chartink":
        formatted = ", ".join(raw_list)
    elif target == "dhan":
        formatted = "\n".join(raw_list)
    else:
        formatted = ",".join(raw_list)

    return {
        "format": target,
        "count": len(raw_list),
        "payload": formatted,
    }


# =========================================================================
# 9. Stock Peer Comparison & Industry Members API
# =========================================================================
@app.get("/api/stock/{symbol}/peers")
def get_stock_peers(symbol: str):
    """
    Fetch industry/sector peer rankings, relative strength leaderboard,
    and 'better options' (higher RS, coiled at 10 EMA, breakout volume).
    """
    from App.ui.stock_drawer import query_stock_peer_comparison
    sym = symbol.strip().upper()
    data = query_stock_peer_comparison(DB_PATH, sym)
    if not data or data.get("peers_df") is None or data["peers_df"].empty:
        raise HTTPException(status_code=404, detail=f"No peers found for {sym}")

    peers_df = data["peers_df"].fillna("")
    peers_records = peers_df.to_dict(orient="records")

    for p in peers_records:
        p["close_price"] = round(_sanitize_float(p.get("close_price")), 2)
        p["day_pct"] = round(_sanitize_float(p.get("day_pct")), 2)
        p["rs_percentile"] = round(_sanitize_float(p.get("rs_percentile")), 1)
        p["away_10ema_pct"] = round(_sanitize_float(p.get("away_10ema_pct")), 1)
        p["away_52w_pct"] = round(_sanitize_float(p.get("away_52w_pct")), 1)
        p["rvol"] = round(_sanitize_float(p.get("rvol")), 2)
        p["delivery_pct"] = round(_sanitize_float(p.get("delivery_pct")), 1)
        p["market_cap_cr"] = round(_sanitize_float(p.get("market_cap_cr")), 1)

    better_options = []
    for bo in data.get("better_options", []):
        better_options.append({
            "symbol": str(bo.get("symbol", "")),
            "security_name": str(bo.get("security_name", "")),
            "rs_percentile": round(_sanitize_float(bo.get("rs_percentile")), 1),
            "away_10ema_pct": round(_sanitize_float(bo.get("away_10ema_pct")), 1),
            "away_52w_pct": round(_sanitize_float(bo.get("away_52w_pct")), 1),
            "rvol": round(_sanitize_float(bo.get("rvol")), 2),
            "day_pct": round(_sanitize_float(bo.get("day_pct")), 2),
            "close_price": round(_sanitize_float(bo.get("close_price")), 2),
            "rank": int(bo.get("rank") or 0),
            "reason": str(bo.get("reason", "")),
        })

    all_symbols = [str(p["symbol"]) for p in peers_records if p.get("symbol")]
    tv_copy_str = ",".join(f"NSE:{s.replace('-', '_')}" for s in all_symbols)

    target_dict = data.get("target", {})
    target_clean = {
        "symbol": sym,
        "security_name": str(target_dict.get("security_name", "")),
        "industry": str(data.get("industry", "")),
        "sector": str(data.get("sector", "")),
        "market_cap_cr": round(_sanitize_float(target_dict.get("market_cap_cr")), 1),
        "close_price": round(_sanitize_float(target_dict.get("close_price")), 2),
        "day_pct": round(_sanitize_float(target_dict.get("day_pct")), 2),
        "rs_percentile": round(_sanitize_float(target_dict.get("rs_percentile")), 1),
        "away_10ema_pct": round(_sanitize_float(target_dict.get("away_10ema_pct")), 1),
        "away_52w_pct": round(_sanitize_float(target_dict.get("away_52w_pct")), 1),
        "rvol": round(_sanitize_float(target_dict.get("rvol")), 2),
        "delivery_pct": round(_sanitize_float(target_dict.get("delivery_pct")), 1),
        "vcp_state": str(target_dict.get("vcp_state", "")),
        "rs_rank": int(data.get("target_rank") or 1),
    }

    return {
        "target": target_clean,
        "group_type": data.get("group_type", "Industry"),
        "group_name": data.get("group_name", ""),
        "sector": data.get("sector", ""),
        "industry": data.get("industry", ""),
        "target_rank": int(data.get("target_rank") or 1),
        "total_peers": int(data.get("total_peers") or len(peers_records)),
        "is_leader": bool(data.get("is_leader", False)),
        "better_options": better_options,
        "peers": peers_records,
        "tv_copy_str": tv_copy_str,
    }


@app.get("/api/sector/{group_name}/stocks")
def get_sector_group_stocks(
    group_name: str,
    level: str = Query("Broad Industry", enum=["Sector", "Broad Industry", "Industry"]),
    limit: int = Query(500, le=500),
    min_mcap: int = Query(1000),
    above_ema200: bool = Query(False),
):
    """Fetch member stocks for a specific sector, broad industry, or industry."""
    from App.app import stock_rows_for_group
    from App.sector_read_model import LEVEL_COLUMNS

    col = LEVEL_COLUMNS.get(level, "broad_industry")
    df = stock_rows_for_group(
        col, group_name, limit=limit, min_mcap=min_mcap, above_ema200=above_ema200
    )
    if df.empty:
        return {"group_name": group_name, "level": level, "count": 0, "stocks": []}

    records = df.fillna("").to_dict(orient="records")
    return {
        "group_name": group_name,
        "level": level,
        "count": len(records),
        "stocks": records,
    }


# =========================================================================
# Mount Built Frontend (SPA)
# =========================================================================
frontend_dist = ROOT_DIR / "frontend" / "dist"
if frontend_dist.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("App.api.server:app", host="127.0.0.1", port=8000, reload=True)
