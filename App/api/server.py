"""
MarketPulse Modern Terminal Backend API (Option A)
High-performance FastAPI service reading DuckDB analytical models directly.
The React UI talks to /api/v2 (App/api/v2). The remaining /api/* routes here are
legacy endpoints still used by the UI (/api/health, /api/market/breadth/historical)
or pinned by tests (regime, cockpit, momentum, vcp).
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
from App.indicators.uc_thrust import uc_flag_label, uc_score_map
from App.sector_read_model import (
    leading_themes_from_board,
    query_rotation_board,
)
from App.deals_read_model import query_deals_advanced
from Scripts.desk_contract import POOL, PRIMARY_QUEUES, match_exposure
from Scripts.vcp import classify_vcp_frame
from Scripts.institutional_engine import classify_client

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

# API v2 (spec §8) — mounted before the SPA static mount so /api/v2/* wins.
from App.api.v2 import router as v2_router  # noqa: E402

app.include_router(v2_router)

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
        "vix": vix_payload(vix_val, vix_1d_pct),
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


def vix_payload(vix_val: Any, vix_1d_pct: Any) -> dict[str, Any]:
    """Missing VIX stays missing: no fabricated 0.00 "Low Risk" reading.

    current/change_1d_pct are None when the source value is missing/NaN/inf/non-numeric.
    tone is None whenever current is None; otherwise the existing Low/Moderate/High bands.
    """
    current = _opt_float(vix_val)
    change_1d_pct = _opt_float(vix_1d_pct)
    if current is None:
        tone = None
    elif current < 15:
        tone = "Low Risk"
    elif current < 20:
        tone = "Moderate"
    else:
        tone = "High Risk"
    return {
        "current": current,
        "change_1d_pct": change_1d_pct,
        "tone": tone,
    }


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
            c.rs_percentile AS rs_percentile,
            ROUND(c.away_10ema_pct, 2) AS away_10ema_pct,
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
            c.delivery_pct AS delivery_pct,
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
            "rs_percentile": _opt_float(r["rs_percentile"], 1),
            "away_10ema_pct": _opt_float(r["away_10ema_pct"]),
            "bucket": str(r["bucket"]),
            "dist_52w_high_pct": round(_sanitize_float(r["dist_52w_high_pct"]), 2),
            "dist_52w_low_pct": round(_sanitize_float(r["dist_52w_low_pct"]), 2),
            "volume": int(r["volume"] or 0),
            "avg_volume_20d": int(r["avg_volume_20d"] or 0),
            "rvol": round(_sanitize_float(r["rvol"], 1.0), 2),
            "delivery_pct": _opt_float(r["delivery_pct"], 1),
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
                "avg_rs": _opt_float(grp["rs_percentile"].mean(), 1),
                "symbols": syms[:10],
                "tv_str": ",".join(f"NSE:{s}" for s in syms),
            })
        sec_list.sort(key=lambda x: (x["stock_count"], x["avg_rs"] if x["avg_rs"] is not None else -1.0), reverse=True)
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
                "avg_rs": _opt_float(grp["rs_percentile"].mean(), 1),
                "symbols": syms[:10],
                "tv_str": ",".join(f"NSE:{s}" for s in syms),
            })
        ind_list.sort(key=lambda x: (x["stock_count"], x["avg_rs"] if x["avg_rs"] is not None else -1.0), reverse=True)
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
def vcp_row(r: Mapping[str, Any]) -> dict[str, Any] | None:
    sym = str(r.get("symbol") or "").strip().upper()
    if not sym:
        return None
    entry = _opt_float(r.get("trigger_price"))
    stop = _opt_float(r.get("stop_loss"))
    vdu = _opt_float(r.get("vdu_ratio"))
    vdu_active = r.get("vdu_active")
    why = _opt_str(r.get("why_now")) or ""
    per_share = (entry - stop) if (entry is not None and stop is not None and entry > stop) else None

    def shares(risk_rupees: float) -> int | None:
        return int(risk_rupees / per_share) if per_share else None

    return {
        "symbol": sym,
        "cmp": _opt_float(r.get("cmp")),
        "wave_sequence": why.split("·")[0].strip() or None,
        "vdu_ratio": vdu,
        "vdu_confirmed": bool(vdu_active) if (vdu_active is not None and not pd.isna(vdu_active)) else bool(vdu is not None and vdu <= 0.80),
        "pivot_entry": entry,
        "stop_loss": stop,
        "risk_pct": _opt_float(r.get("risk_pct")),
        "dist_to_pivot_pct": _opt_float(r.get("pivot_distance_pct"), 1),
        "suggested_shares_for_10k_risk": shares(10_000),
        "suggested_shares_for_25k_risk": shares(25_000),
        "suggested_shares_for_50k_risk": shares(50_000),
        "rs_percentile": _opt_float(r.get("rs_percentile"), 1),
        "sector": _opt_str(r.get("sector")),
    }


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

    vcp_results = [row for row in (vcp_row(rec) for rec in vcp_df.to_dict("records")) if row is not None] if not vcp_df.empty else []
    vcp_results.sort(key=lambda x: (
        abs(x["dist_to_pivot_pct"]) if x["dist_to_pivot_pct"] is not None else 9999.0,
        x["risk_pct"] if x["risk_pct"] is not None else 9999.0,
    ))
    trade_date = data.get("trade_date")
    return {
        "as_of": str(pd.to_datetime(trade_date).date()) if trade_date is not None else None,
        "total_count": len(vcp_results),
        "candidates": vcp_results,
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
# Mount Built Frontend (SPA)
# =========================================================================
frontend_dist = ROOT_DIR / "frontend" / "dist"
if frontend_dist.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("App.api.server:app", host="127.0.0.1", port=8000, reload=True)
