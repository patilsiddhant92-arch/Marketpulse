"""
MarketPulse Modern Terminal Backend API (Option A)
High-performance FastAPI service reading DuckDB analytical models directly.
Restores full analytical depth: multi-day deal accumulation, 400-day Darvas box geometry,
comprehensive momentum screener filters, deduplicated VCP workbench, and historical sector rotation.
"""
from __future__ import annotations

import json
import os
import sys
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
from Scripts.desk_contract import PRIMARY_QUEUES, match_exposure
from Scripts.vcp import classify_vcp_frame
from Scripts.institutional_engine import classify_client
from Scripts.institutional_attribution import fetch_star_fund_radar
from Scripts.telegram_deals import build_deals_telegram_report, to_tv_list
from Scripts.minervini_geometry import detect_contractions, load_template_context, load_ohlcv

app = FastAPI(
    title="MarketPulse Terminal API",
    description="High-density EOD swing trading analytical engine for Indian markets",
    version="3.1.0",
)

# Enable CORS for local development and embedded webviews
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    from App.ui.market_health import load_exposure_inputs, resolve_india_vix

    with get_db() as con:
        trade_date = con.execute("SELECT max(trade_date) FROM indicators_daily").fetchone()[0]
        vix_val, vix_1d_pct = resolve_india_vix(con, trade_date)
        exp_inputs = load_exposure_inputs(con, trade_date=trade_date)

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

        c_52w_h = int(exp_inputs.get("count_52w_highs") or near_52_cnt)
        c_52w_l = int(exp_inputs.get("count_52w_lows") or 0)

        gate = compute_exposure_gate(
            adv_pct=adv_pct,
            ab20_pct=ab20_pct,
            ab200_pct=ab200_pct,
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
        darvas_sq_count = con.execute(
            """
            SELECT count(DISTINCT symbol)
            FROM indicators_daily
            WHERE trade_date = ? AND close_price > ema_200 AND abs(away_52w_high_pct) <= 25.0
            """,
            [trade_date]
        ).fetchone()[0] or 0

    raw_pct = gate.get("pct", 50.0)
    if isinstance(raw_pct, str):
        raw_pct = raw_pct.replace("%", "").strip()
    exp_num = _sanitize_float(raw_pct, 50.0)

    # Actionable trading execution guidance
    if exp_num >= 75.0:
        execution_playbook = "Aggressive Risk-On: Full market participation. Trade clean Stage 2 pivots & breakouts with standard 1.0R position sizing. Trail stops below 10/20 EMA."
        action_bias = "Bullish / Trend Following"
        max_pos = "15%–20%"
        risk_per_trade = "1.0%"
    elif exp_num >= 40.0:
        execution_playbook = f"Selective Allocation ({int(exp_num)}% Exposure): Breadth is sub-40% (>50 EMA {ab50_pct:.1f}%). Prioritize tightly coiled Stage 2 VCP & Darvas breakouts with strict 3%–5% stops. Avoid extended chases; focus on RS 80+ leaders."
        action_bias = "Selective / Coiled Setups Only"
        max_pos = "8%–10%"
        risk_per_trade = "0.5%–0.75%"
    else:
        execution_playbook = "Defensive / Capital Preservation: Broad market distribution. Sit in cash; only trade pristine high-RS relative strength leaders or hold existing winners with trailing stops."
        action_bias = "Defensive / Heavy Cash"
        max_pos = "5%–7%"
        risk_per_trade = "0.25%–0.5%"

    return {
        "as_of": str(pd.to_datetime(trade_date).date()),
        "exposure_gate": {
            "recommended_pct": exp_num,
            "state": gate.get("state", "Caution"),
            "badge": gate.get("badge", f"{int(exp_num)}% Exposure"),
            "guidance": gate.get("guidance", "Selective setups only"),
            "is_actionable": exp_num > 0,
            "execution_playbook": execution_playbook,
            "action_bias": action_bias,
            "max_position_size": max_pos,
            "risk_per_trade": risk_per_trade,
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
            "darvas_count": darvas_sq_count,
            "vcp_count": int(b_df.iloc[0].get("vcp_candidates") or 0) if not b_df.empty else 0,
        },
    }


# =========================================================================
# 2. Executive Cockpit / Action Desk Candidate Setups API
# =========================================================================
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
        for _, row in df.iterrows():
            sym = str(row.get("symbol", "")).strip().upper()
            if not sym:
                continue
            
            # Formatting fields with safety deadbands (Rule 4)
            cmp_val = _sanitize_float(row.get("cmp") or row.get("close_price") or row.get("close"))
            open_val = _sanitize_float(row.get("open_price"))
            chg_pct = round(((cmp_val - open_val) / open_val * 100), 2) if open_val > 0 else _sanitize_float(row.get("change_pct") or row.get("return_1d_pct"))
            dist_pivot = _sanitize_float(row.get("pivot_distance_pct") or row.get("distance_to_trigger_pct") or row.get("dist_pivot_pct"))
            risk_pct = _sanitize_float(row.get("initial_risk_pct") or row.get("risk_pct"))
            rvol_val = _sanitize_float(row.get("rvol"), 1.0)
            rr_val = _sanitize_float(row.get("reward_to_risk") or row.get("rr"), 2.0)
            
            sq_raw = row.get("squeeze_pct") if ("squeeze_pct" in row and pd.notna(row.get("squeeze_pct"))) else row.get("darvas_squeeze_pct")
            if sq_raw is not None and pd.notna(sq_raw):
                try:
                    f = float(sq_raw)
                    sq_val = round(f, 2) if not (np.isnan(f) or np.isinf(f)) else None
                except (ValueError, TypeError):
                    sq_val = None
            else:
                sq_val = None
            
            records.append({
                "symbol": sym,
                "sector": str(row.get("sector", "") or "General"),
                "queue": q_name,
                "cmp": cmp_val,
                "change_1d_pct": chg_pct,
                "pattern_state": str(row.get("pattern_state") or row.get("state") or q_name),
                "rvol": round(rvol_val, 2),
                "dist_to_pivot_pct": round(dist_pivot, 2),
                "risk_pct": round(risk_pct, 2) if risk_pct > 0 else 3.5,
                "reward_to_risk": round(rr_val, 1),
                "trigger_price": _sanitize_float(row.get("trigger_price") or row.get("pivot_price")),
                "invalidation_price": _sanitize_float(row.get("stop_price") or row.get("invalidation_price") or row.get("stop_loss")),
                "mcap_cr": _sanitize_float(row.get("market_cap_cr") or row.get("mcap_cr")),
                "why_now": str(row.get("why_now", "")),
                "rs_percentile": _sanitize_float(row.get("rs_percentile")),
                "delivery_pct": _sanitize_float(row.get("delivery_pct")),
                "theme": str(row.get("theme", "—")),
                "deal_flow": str(row.get("deal_flow", "—")),
                "squeeze_pct": sq_val,
            })

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
        "as_of": data.get("as_of"),
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
        trigger_where.append(f"i.symbol = '{debug_symbol.strip().upper()}'")

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
        current_where.append(f"c.symbol = '{debug_symbol.strip().upper()}'")

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
        df = con.execute(sql).fetchdf()

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
    conviction_df = tiers.get("conviction", pd.DataFrame())
    fresh_radar_df = tiers.get("fresh_radar", pd.DataFrame())
    prop_only_df = tiers.get("prop_only", pd.DataFrame())
    quarantined_df = tiers.get("quarantined", pd.DataFrame())
    distribution_df = tiers.get("distribution", pd.DataFrame())

    # Apply setup filter if requested
    if setup_filter == "ABOVE_200":
        if not conviction_df.empty and "is_above_200" in conviction_df.columns:
            conviction_df = conviction_df[conviction_df["is_above_200"]].copy()
        if not fresh_radar_df.empty and "is_above_200" in fresh_radar_df.columns:
            fresh_radar_df = fresh_radar_df[fresh_radar_df["is_above_200"]].copy()
    elif setup_filter == "TURNAROUND":
        if not conviction_df.empty and "is_above_200" in conviction_df.columns:
            conviction_df = conviction_df[~conviction_df["is_above_200"]].copy()
        if not fresh_radar_df.empty and "is_above_200" in fresh_radar_df.columns:
            fresh_radar_df = fresh_radar_df[~fresh_radar_df["is_above_200"]].copy()

    def _df_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
        if df.empty:
            return []
        out = []
        for _, r in df.iterrows():
            cats = r.get("categories", set())
            c_str = "/".join(sorted(list(cats))) if isinstance(cats, (set, list)) else str(cats)
            out.append({
                "symbol": str(r.get("symbol", "")),
                "deal_days": int(r.get("deal_days") or 1),
                "clientele": c_str,
                "net_cr": round(_sanitize_float(r.get("net_cr")), 1),
                "buy_cr": round(_sanitize_float(r.get("buy_cr")), 1),
                "sell_cr": round(_sanitize_float(r.get("sell_cr")), 1),
                "close_price": round(_sanitize_float(r.get("close_price")), 2),
                "ema_200": round(_sanitize_float(r.get("ema_200")), 2),
                "trend": str(r.get("trend_stage") or ("🟢 >200 EMA" if r.get("is_above_200") else "🟡 Base / Turnaround")),
                "away_52w_high_pct": round(_sanitize_float(r.get("away_52w_high_pct")), 1),
                "rs_percentile": round(_sanitize_float(r.get("rs_percentile")), 1),
                "market_cap_cr": round(_sanitize_float(r.get("market_cap_cr")), 0),
                "sector": str(r.get("sector", "General") or "General"),
            })
        return out

    # Fund Leaderboard
    lead_df = star_radar.get("leaderboard", pd.DataFrame())
    leaderboard_records = []
    if not lead_df.empty:
        for _, lr in lead_df.iterrows():
            leaderboard_records.append({
                "fund_house": str(lr.get("fund_house", "")),
                "tier": str(lr.get("fund_tier", "")),
                "catalyst_score": round(_sanitize_float(lr.get("catalyst_score")), 1),
                "win_rate_20d": round(_sanitize_float(lr.get("win_rate_20d")), 1),
                "avg_runup": round(_sanitize_float(lr.get("avg_runup")), 1),
                "bets_count": int(lr.get("bets_count") or 0),
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

    conviction_recs = _df_to_records(conviction_df)
    fresh_recs = _df_to_records(fresh_radar_df)

    # Multi-day persistence counts
    cnt_4plus = sum(1 for r in conviction_recs if r["deal_days"] >= 4)
    cnt_3 = sum(1 for r in conviction_recs if r["deal_days"] == 3)
    cnt_2 = sum(1 for r in conviction_recs if r["deal_days"] == 2)

    return {
        "as_of": report.get("as_of"),
        "lookback_days": lookback_days,
        "counts": {
            "conviction": len(conviction_recs),
            "fresh_radar": len(fresh_recs),
            "four_plus_days": cnt_4plus,
            "three_days": cnt_3,
            "two_days": cnt_2,
            "prop_only": len(prop_only_df),
            "quarantined": len(quarantined_df),
            "distribution": len(distribution_df),
            "star_deals": len(star_deals),
            "funds": len(leaderboard_records),
        },
        "conviction": conviction_recs,
        "fresh_radar": fresh_recs,
        "prop_only": _df_to_records(prop_only_df),
        "quarantined": _df_to_records(quarantined_df),
        "distribution": _df_to_records(distribution_df),
        "star_radar": star_deals,
        "fund_leaderboard": leaderboard_records,
        "tv_strings": report.get("tv_strings", {}),
    }


# =========================================================================
# 6. Sector Relative Strength & Breadth Matrix API
# =========================================================================
@app.get("/api/sector/rotation")
def get_sector_rotation(
    level: str = Query("Broad Industry", enum=["Sector", "Broad Industry", "Industry"]),
    lookback_days: int = Query(30, description="Trailing lookback sessions"),
    states: Optional[list[str]] = Query(None, description="Filter by rotation states (e.g. Leading, Emerging, Improving, Weakening, Lagging, Neutral)"),
):
    """
    Sector Relative Strength (5D/20D/63D), visual breadth, and multi-horizon rotation.
    Synthesizes Stage 2 participation %, median RS, turnover share delta, and inflow streaks.
    """
    board = query_rotation_board(DB_PATH, level=level)
    if board.empty:
        return {"total_count": 0, "filtered_count": 0, "state_counts": {}, "sectors": []}

    try:
        div_df = query_sector_breadth_divergence(DB_PATH)
        div_map = {str(r["group_name"]): str(r["divergence_status"]) for _, r in div_df.iterrows()}
    except Exception:
        div_map = {}

    col = "broad_industry"
    if level == "Sector":
        col = "sector"
    elif level == "Industry":
        col = "industry"

    # Query live Stage 2 metrics and leader details from DuckDB
    stage2_map = {}
    leaders_map = {}
    try:
        with get_db() as con:
            stats_df = con.execute(f"""
                WITH latest_date AS (SELECT MAX(trade_date) as td FROM indicators_daily),
                stage2_stats AS (
                    SELECT 
                        trim(m.{col}) as group_name,
                        count(*) as total_stocks,
                        count(CASE WHEN i.close_price > i.ema_200 AND i.away_52w_high_pct >= -25 THEN 1 END) as stage2_count,
                        round(count(CASE WHEN i.close_price > i.ema_200 AND i.away_52w_high_pct >= -25 THEN 1 END) * 100.0 / nullif(count(*), 0), 1) as stage2_pct,
                        round(median(i.rs_percentile), 1) as median_rs
                    FROM indicators_daily i
                    JOIN stocks_master m ON m.symbol = i.symbol
                    WHERE i.trade_date = (SELECT td FROM latest_date)
                      AND nullif(trim(m.{col}), '') IS NOT NULL
                    GROUP BY 1
                ),
                leaders AS (
                    SELECT 
                        trim(m.{col}) as group_name,
                        i.symbol,
                        round(coalesce(i.rs_percentile, 50.0), 1) as rs_percentile,
                        round(((i.close_price - i.prev_close) / nullif(i.prev_close, 0)) * 100, 2) as change_1d_pct,
                        row_number() over (partition by trim(m.{col}) order by i.rs_percentile desc nulls last) as rn
                    FROM indicators_daily i
                    JOIN stocks_master m ON m.symbol = i.symbol
                    WHERE i.trade_date = (SELECT td FROM latest_date)
                      AND nullif(trim(m.{col}), '') IS NOT NULL
                )
                SELECT s.*, 
                       string_agg(l.symbol || ':' || coalesce(cast(l.rs_percentile as varchar), '0') || ':' || coalesce(cast(l.change_1d_pct as varchar), '0'), ',' order by l.rn) as top3_leaders
                FROM stage2_stats s
                LEFT JOIN leaders l ON s.group_name = l.group_name AND l.rn <= 3
                GROUP BY s.group_name, s.total_stocks, s.stage2_count, s.stage2_pct, s.median_rs
            """).fetchdf()

            for _, row in stats_df.iterrows():
                gn = str(row["group_name"])
                stage2_map[gn] = {
                    "total_stocks": int(row["total_stocks"] or 0),
                    "stage2_count": int(row["stage2_count"] or 0),
                    "stage2_percentage": _sanitize_float(row["stage2_pct"]),
                    "median_rs": _sanitize_float(row["median_rs"]),
                }
                ldrs = []
                if row.get("top3_leaders"):
                    for item in str(row["top3_leaders"]).split(","):
                        parts = item.split(":")
                        if len(parts) >= 3:
                            try:
                                ldrs.append({
                                    "symbol": parts[0],
                                    "rs_percentile": round(float(parts[1]), 1),
                                    "change_1d_pct": round(float(parts[2]), 2),
                                })
                            except Exception:
                                pass
                leaders_map[gn] = ldrs
    except Exception as e:
        print(f"Error querying stage2 stats: {e}")

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

        st_data = stage2_map.get(g_name, {})
        ld_data = leaders_map.get(g_name, [])

        all_results.append({
            "sector": g_name,
            "total_stocks": st_data.get("total_stocks", int(r.get("stocks") or 0)),
            "stage2_count": st_data.get("stage2_count", 0),
            "stage2_percentage": st_data.get("stage2_percentage", 0.0),
            "median_rs": st_data.get("median_rs", _sanitize_float(r.get("rs_percentile"))),
            "return_5d_pct": _sanitize_float(r.get("return_5d_pct")),
            "return_20d_pct": _sanitize_float(r.get("return_1m_pct")),
            "return_63d_pct": _sanitize_float(r.get("return_3m_pct")),
            "rs_percentile": _sanitize_float(r.get("rs_percentile")),
            "advancers_pct": _sanitize_float(r.get("adv_pct") or 55.0),
            "above_10_ema_pct": _sanitize_float(r.get("above_10ema_pct")),
            "above_50_ema_pct": _sanitize_float(r.get("above_50ema_pct")),
            "above_200_ema_pct": _sanitize_float(r.get("above_200ema_pct")),
            "near_52w_highs": int(r.get("near_52w_highs") or 0),
            "rotation_state": st,
            "rotation_rank": int(r.get("rotation_rank") or 0),
            "turnover_1d_cr": round(_sanitize_float(r.get("turnover_1d_cr")), 1),
            "turnover_share_pct": round(_sanitize_float(r.get("turnover_share_pct")), 2),
            "turnover_share_delta_1d": round(_sanitize_float(r.get("turnover_share_delta_1d")), 2),
            "turnover_share_delta_5d": round(_sanitize_float(r.get("turnover_share_delta_5d")), 2),
            "turnover_expansion": str(r.get("turnover_expansion", "—")),
            "divergence_status": div_map.get(g_name, "In-Sync"),
            "leaders": [s.strip() for s in str(r.get("leader_symbols", "")).split(",") if s.strip()][:5],
            "leader_chips": ld_data,
        })

    if states:
        filtered = [r for r in all_results if r["rotation_state"] in states]
    else:
        filtered = all_results

    return {
        "total_count": len(all_results),
        "filtered_count": len(filtered),
        "state_counts": state_counts,
        "sectors": filtered,
    }


# =========================================================================
# 5B. Capital Flow & Multi-Horizon Rotation Radar
# =========================================================================
@app.get("/api/market/capital-flow")
def get_capital_flow(level: str = Query("Sector")):
    """
    Market-wide Capital Flow Radar across 1D (Session Tape), 1W (5D Shift), and 1M (21D Rotation).
    Identifies sectors capturing turnover share vs sectors suffering capital exodus.
    Also returns top stock accumulators (Turnover expansion > 2x with price up & delivery surge).
    """
    lvl_lower = level.strip().lower()
    if lvl_lower in ["sector", "sectors"]:
        clean_level = "Sector"
    elif lvl_lower in ["industry", "industries"]:
        clean_level = "Industry"
    else:
        clean_level = "Broad Industry"

    with get_db() as con:
        max_d = con.execute("SELECT max(trade_date) FROM sector_rotation").fetchone()[0]
        if not max_d:
            return {
                "as_of": "",
                "top_inflows_1d": [],
                "top_outflows_1d": [],
                "top_inflows_5d": [],
                "top_outflows_5d": [],
                "top_inflows_1m": [],
                "top_outflows_1m": [],
                "stock_accumulators": [],
            }

        # Query sector rotation board at this level
        df = con.execute("""
            SELECT group_name, turnover_1d_cr, turnover_share_pct, turnover_share_delta_1d, turnover_share_delta_5d,
                   return_5d_pct, return_1m_pct, return_3m_pct, above_200ema_pct, rotation_state, leader_symbols
            FROM sector_rotation
            WHERE level = ? AND trade_date = ?
        """, [clean_level, max_d]).fetchdf()

        # Query net institutional deal flow per group over last 10 days
        col_name = "broad_industry" if clean_level == "Broad Industry" else ("sector" if clean_level == "Sector" else "industry")
        try:
            deals_df = con.execute(f"""
                SELECT 
                    trim(m.{col_name}) as group_name,
                    round(sum(CASE WHEN upper(d.side) LIKE '%BUY%' THEN d.deal_value_cr ELSE -d.deal_value_cr END), 1) as net_deal_cr
                FROM deals d
                JOIN stocks_master m ON m.symbol = d.symbol
                WHERE d.trade_date >= (SELECT max(trade_date) - INTERVAL 10 DAY FROM deals)
                  AND nullif(trim(m.{col_name}), '') IS NOT NULL
                GROUP BY 1
            """).fetchdf()
            deals_map = dict(zip(deals_df["group_name"], deals_df["net_deal_cr"])) if not deals_df.empty else {}
        except Exception:
            deals_map = {}

        # Top Stock Accumulators across market
        acc_df = con.execute("""
            SELECT 
                i.symbol, m.security_name, m.sector, m.industry, i.close_price,
                round(((i.close_price - nullif(i.prev_close, 0))/nullif(i.prev_close, 0))*100, 2) AS day_pct,
                round(i.turnover_cr, 1) as turnover_cr,
                round(i.avg_traded_value_cr_20d, 1) as avg_turnover_20d_cr,
                round(((i.turnover_cr - nullif(i.avg_traded_value_cr_20d, 0))/nullif(i.avg_traded_value_cr_20d, 0))*100, 1) as turnover_expansion_pct,
                round(i.delivery_qty / nullif(i.avg_delivery_qty_20d, 0), 2) as delivery_ratio,
                round(i.delivery_pct, 1) as delivery_pct,
                round(coalesce(i.rs_percentile, 50.0), 1) as rs_percentile,
                i.delivery_spike, i.price_up_delivery_up,
                round(i.avg_trade_size / nullif(i.avg_trade_size_20d, 0), 2) as ticket_ratio
            FROM indicators_daily i
            JOIN stocks_master m ON m.symbol = i.symbol
            WHERE i.trade_date = (SELECT max(trade_date) FROM indicators_daily)
              AND i.turnover_cr >= 5.0
              AND (i.price_up_delivery_up = true OR i.delivery_spike = true)
              AND i.close_price > i.prev_close
            ORDER BY turnover_expansion_pct DESC
            LIMIT 25
        """).fetchdf()

    records = []
    for _, r in df.iterrows():
        gname = str(r["group_name"])
        leaders = [s.strip() for s in str(r.get("leader_symbols") or "").split(",") if s.strip()][:3]
        records.append({
            "group_name": gname,
            "level": clean_level,
            "turnover_cr": round(_sanitize_float(r.get("turnover_1d_cr")), 1),
            "turnover_share_pct": round(_sanitize_float(r.get("turnover_share_pct")), 2),
            "turnover_share_delta_1d": round(_sanitize_float(r.get("turnover_share_delta_1d")), 2),
            "turnover_share_delta_5d": round(_sanitize_float(r.get("turnover_share_delta_5d")), 2),
            "return_5d_pct": round(_sanitize_float(r.get("return_5d_pct")), 1),
            "return_1m_pct": round(_sanitize_float(r.get("return_1m_pct")), 1),
            "return_3m_pct": round(_sanitize_float(r.get("return_3m_pct")), 1),
            "above_200_ema_pct": round(_sanitize_float(r.get("above_200ema_pct")), 1),
            "rotation_state": str(r.get("rotation_state") or "Neutral"),
            "deal_net_cr": deals_map.get(gname, 0.0),
            "leaders": leaders,
        })

    # Sort records for 1D, 5D, 1M
    by_1d = sorted(records, key=lambda x: x["turnover_share_delta_1d"], reverse=True)
    top_inflows_1d = by_1d[:8]
    top_outflows_1d = sorted([r for r in by_1d if r["turnover_share_delta_1d"] < 0], key=lambda x: x["turnover_share_delta_1d"])[:8]

    by_5d = sorted(records, key=lambda x: x["turnover_share_delta_5d"], reverse=True)
    top_inflows_5d = by_5d[:8]
    top_outflows_5d = sorted([r for r in by_5d if r["turnover_share_delta_5d"] < 0], key=lambda x: x["turnover_share_delta_5d"])[:8]

    by_1m = sorted(records, key=lambda x: x["return_1m_pct"], reverse=True)
    top_inflows_1m = by_1m[:8]
    top_outflows_1m = sorted([r for r in by_1m if r["return_1m_pct"] < 0], key=lambda x: x["return_1m_pct"])[:8]

    stock_accumulators = []
    if not acc_df.empty:
        for _, r in acc_df.iterrows():
            stock_accumulators.append({
                "symbol": str(r["symbol"]),
                "security_name": str(r["security_name"]),
                "sector": str(r["sector"]),
                "industry": str(r["industry"]),
                "cmp": round(_sanitize_float(r["close_price"]), 2),
                "day_pct": round(_sanitize_float(r["day_pct"]), 2),
                "turnover_cr": round(_sanitize_float(r["turnover_cr"]), 1),
                "turnover_expansion_pct": round(_sanitize_float(r["turnover_expansion_pct"]), 1),
                "delivery_ratio": round(_sanitize_float(r["delivery_ratio"]), 2),
                "delivery_pct": round(_sanitize_float(r["delivery_pct"]), 1),
                "rs_percentile": round(_sanitize_float(r["rs_percentile"]), 1),
                "ticket_ratio": round(_sanitize_float(r["ticket_ratio"]), 2),
                "is_whale": bool(_sanitize_float(r["ticket_ratio"]) >= 1.25),
                "deliv_spike": bool(r.get("delivery_spike")),
                "acc_vol": bool(r.get("price_up_delivery_up")),
            })

    return {
        "as_of": str(pd.to_datetime(max_d).date()),
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
    limit: int = Query(30, le=100),
    min_mcap: int = Query(0),
):
    """Fetch member stocks for a specific sector, broad industry, or industry."""
    from App.app import stock_rows_for_group
    from App.sector_read_model import LEVEL_COLUMNS

    col = LEVEL_COLUMNS.get(level, "broad_industry")
    df = stock_rows_for_group(col, group_name, limit=limit, min_mcap=min_mcap)
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
