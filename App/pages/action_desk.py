"""
Action Desk: Executive Swing Trading Command Center.
Provides a 3-step actionable workflow:
1. Market Exposure Gate (Recommended Exposure % and Stop Discipline)
2. Leading Sector Themes (Institutional Money Flow)
3. The 8 setup queues (Near 20D Pivot, EMA Pullback, Episodic Pivot, 52W Breakout, Darvas Squeeze, Silent Coil, Stair-Step, Spike-Pause)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import duckdb
import numpy as np
import pandas as pd
from nicegui import ui

from App.cache_manager import get_cached, set_cached, cache_key
try:
    from App.sector_read_model import query_rotation_board
except ModuleNotFoundError:
    from sector_read_model import query_rotation_board  # type: ignore
from App.indicators.darvas import (
    DARVAS,
    WEEKLY_LOOKBACK_SESSIONS,
    apply_display_window,
    calculate_darvas_box,
    darvas_v2_enabled,
    darvas_weekly_enabled,
    is_darvas_10ema_squeeze,
    is_darvas_10ema_squeeze_legacy,
    squeeze_frame,
)
try:
    from App.thematic_engine import get_macro_pulse, get_stock_thematic_tags
except ModuleNotFoundError:
    from thematic_engine import get_macro_pulse, get_stock_thematic_tags  # type: ignore
try:
    from Scripts.telegram_deals import to_tv_list
except ModuleNotFoundError:
    from telegram_deals import to_tv_list  # type: ignore

try:
    from App.ui.stock_drawer import open_stock_360_modal, query_stock_candlestick_data, render_stock_inspector_panel
except ModuleNotFoundError:
    from ui.stock_drawer import open_stock_360_modal, query_stock_candlestick_data, render_stock_inspector_panel  # type: ignore

try:
    from App.ui.vcp_chart import render_vcp_ohlc
except ModuleNotFoundError:
    from ui.vcp_chart import render_vcp_ohlc  # type: ignore

try:
    from App.ui.playbook_guide import open_playbook_modal, render_inline_field_guide_banner
except ModuleNotFoundError:
    from ui.playbook_guide import open_playbook_modal, render_inline_field_guide_banner  # type: ignore

try:
    from Scripts.desk_contract import DARVAS, POOL, QUEUE_DISPLAY_CAPS, QUEUE_META, match_exposure
except ModuleNotFoundError:
    from desk_contract import DARVAS, POOL, QUEUE_DISPLAY_CAPS, QUEUE_META, match_exposure  # type: ignore

try:
    from App.ui.market_health import load_exposure_inputs, render_market_health_strip
except ModuleNotFoundError:
    from ui.market_health import load_exposure_inputs, render_market_health_strip  # type: ignore


def _fmt_exp_pct(val: Any) -> str:
    if val is None:
        return "n/a"
    try:
        return f"{float(val):.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _exp_pct_tone(val: Any, threshold: float) -> str:
    if val is None:
        return "text-amber-400"
    try:
        return "text-emerald-400" if float(val) >= threshold else "text-rose-400"
    except (TypeError, ValueError):
        return "text-amber-400"


def resolve_india_vix(con: duckdb.DuckDBPyConnection, trade_date: Any) -> tuple[float | None, float]:
    """Load India VIX for the session. Missing row is (None, 0.0) — never a silent 11.3."""
    try:
        vix_res = con.execute(
            """
            SELECT close_price,
                   coalesce(
                       return_1d_pct,
                       (close_price / nullif(previous_close, 0) - 1.0) * 100
                   ) AS vix_1d_pct
            FROM index_daily
            WHERE trade_date = ? AND index_name = 'India VIX'
            """,
            [trade_date],
        ).fetchone()
        if vix_res and vix_res[0] is not None:
            return round(float(vix_res[0]), 2), round(float(vix_res[1] or 0.0), 1)
    except Exception:
        pass
    return None, 0.0


def compute_exposure_gate(
    *,
    adv_pct: float,
    ab20_pct: float,
    ab200_pct: float,
    vix: float | None,
    vix_1d_pct: float,
    net_lows_expanding: bool,
    count_52w_highs: int,
    count_52w_lows: int,
) -> dict[str, Any]:
    """Canonical exposure gate via desk_contract. VIX n/a skips every vix-threshold branch."""
    vix_spike = bool(vix is not None and vix_1d_pct >= 10.0)
    gate = match_exposure(
        {
            "adv_pct": adv_pct,
            "ab20_pct": ab20_pct,
            "ab200_pct": ab200_pct,
            "vix": vix,
            "vix_spike": vix_spike,
            "net_lows_expanding": net_lows_expanding,
            "count_52w_lows": count_52w_lows,
            "count_52w_highs": count_52w_highs,
            "vix_1d_pct": vix_1d_pct,
        }
    )
    vix_available = not gate["vix_na"]
    gate["vix"] = vix
    gate["vix_1d_pct"] = vix_1d_pct
    gate["vix_available"] = vix_available
    gate["vix_label"] = "VIX n/a" if not vix_available else f"{vix}"
    gate["vix_spike"] = vix_spike
    return gate


def fetch_action_desk_data(db_path: Path | str) -> dict[str, Any]:
    """
    Query and assemble all datasets required for the Action Desk.
    Results are cached in memory for sub-millisecond response on subsequent tab visits.
    """
    use_v2 = darvas_v2_enabled()
    use_weekly = darvas_weekly_enabled()
    key = cache_key(
        db_path,
        None,
        "action_desk_v10",
        "darvas_v2" if use_v2 else "darvas_v1",
        "weekly" if use_weekly else "daily",
    )
    cached = get_cached(key)
    if cached is not None:
        return cached

    with duckdb.connect(str(db_path), read_only=True) as con:
        # 1. Latest trade date
        max_d_res = con.execute("SELECT max(trade_date) FROM indicators_daily").fetchone()
        if not max_d_res or not max_d_res[0]:
            return {"ready": False, "reason": "No data in indicators_daily"}
        trade_date = max_d_res[0]
        trade_date_str = str(pd.to_datetime(trade_date).date())

        # 2. Market Breadth & Exposure Gate — same breadth_daily row as the health strip.
        exp_inputs = load_exposure_inputs(con, trade_date=trade_date)
        total_stocks = exp_inputs["total_stocks"]
        adv_pct = exp_inputs["adv_pct"]
        ab20_pct = exp_inputs["ab20_pct"]
        ab50_pct = exp_inputs["ab50_pct"]
        ab200_pct = exp_inputs["ab200_pct"]
        breadth_source = exp_inputs["source"]
        breadth_as_of = exp_inputs["as_of"]

        vix_val, vix_1d_pct = resolve_india_vix(con, trade_date)

        # Net 52-Week Highs / Lows Breadth Gate
        high_low_row = con.execute(
            """
            SELECT 
                count(CASE WHEN away_52w_high_pct >= -2.0 THEN 1 END) AS count_52w_highs,
                count(CASE WHEN (close_price / nullif(low_52w, 0) - 1.0) <= 0.02 THEN 1 END) AS count_52w_lows
            FROM indicators_daily
            WHERE trade_date = ?
            """,
            [trade_date],
        ).fetchone()
        count_52w_highs = int(high_low_row[0] or 0) if high_low_row else 0
        count_52w_lows = int(high_low_row[1] or 0) if high_low_row else 0
        net_highs = count_52w_highs - count_52w_lows
        net_lows_expanding = count_52w_lows > count_52w_highs

        gate = compute_exposure_gate(
            adv_pct=adv_pct,
            ab20_pct=ab20_pct,
            ab200_pct=ab200_pct,
            vix=vix_val,
            vix_1d_pct=vix_1d_pct,
            net_lows_expanding=net_lows_expanding,
            count_52w_highs=count_52w_highs,
            count_52w_lows=count_52w_lows,
        )
        exposure_pct = gate["pct"]
        exposure_state = gate["state"]
        exposure_badge = gate["badge"]
        exposure_guidance = gate["guidance"]

        # 3. Top Leading Themes — same named sort as the Broad Industry board
        board = query_rotation_board(Path(db_path), level="Broad Industry")
        top_sectors = board.head(4).copy() if not board.empty else pd.DataFrame()
        if not top_sectors.empty:
            top_sectors["sector"] = top_sectors["group_name"]
            top_sectors["leaders"] = top_sectors["leader_symbols"] if "leader_symbols" in top_sectors.columns else ""
            top_sectors["total_to_cr"] = top_sectors["turnover_1d_cr"] if "turnover_1d_cr" in top_sectors.columns else 0.0
            top_sectors["avg_5d_pct"] = top_sectors["return_5d_pct"] if "return_5d_pct" in top_sectors.columns else 0.0
            top_sectors["avg_rs"] = top_sectors["rs_percentile"] if "rs_percentile" in top_sectors.columns else 0.0
            top_sectors["above_50_pct"] = top_sectors["above_50ema_pct"] if "above_50ema_pct" in top_sectors.columns else 0.0

        # 4. Strict Quality Filtered Pool for Setups (Without RS gate, so Darvas & Pre-Move queues can find unextended gems)
        setup_pool = con.execute(
            """
            WITH dates AS (
                SELECT DISTINCT trade_date 
                FROM indicators_daily 
                ORDER BY trade_date DESC 
                LIMIT 7
            ),
            hist AS (
                SELECT symbol,
                       ARRAY_AGG(round(rvol, 2) ORDER BY trade_date ASC) as rvol_arr,
                       ARRAY_AGG(round(delivery_pct, 1) ORDER BY trade_date ASC) as deliv_arr,
                       ARRAY_AGG(round((close_price / prev_close - 1.0)*100, 2) ORDER BY trade_date ASC) as day_pct_arr
                FROM indicators_daily
                WHERE trade_date IN (SELECT trade_date FROM dates)
                GROUP BY symbol
            ),
            pool AS (
                SELECT 
                    i.trade_date,
                    i.symbol,
                    m.security_name,
                    m.sector,
                    m.industry,
                    m.market_cap_cr,
                    COALESCE(m.band, 20.0) AS band,
                    i.close_price AS cmp,
                    (i.close_price / nullif(i.prev_close, 0) - 1.0) * 100 AS day_pct,
                    i.return_5d_pct,
                    i.return_1m_pct,
                    i.away_52w_high_pct,
                    i.rs_percentile,
                    i.rvol,
                    i.delivery_pct,
                    i.high_20d,
                    i.low_10d,
                    i.low_price,
                    i.high_price,
                    i.open_price,
                    i.ema_10,
                    i.ema_20,
                    i.ema_50,
                    i.ema_200,
                    i.away_10ema_pct,
                    i.away_20ema_pct,
                    i.low_volatility_near_high,
                    COALESCE(i.avg_traded_value_cr_20d, i.turnover_cr) AS to_cr,
                    round(i.avg_trade_size / nullif(i.avg_trade_size_20d, 0), 2) AS ticket_ratio,
                    h.rvol_arr,
                    h.deliv_arr,
                    h.day_pct_arr
                FROM indicators_daily i
                JOIN stocks_master m ON m.symbol = i.symbol
                JOIN hist h ON h.symbol = i.symbol
                WHERE i.trade_date = ?
                  AND m.market_cap_cr >= ?
                  AND COALESCE(m.band, 20.0) > ?
                  AND i.symbol NOT LIKE '%-RE' AND i.symbol NOT LIKE '%_RE'
                  AND COALESCE(i.avg_traded_value_cr_20d, i.turnover_cr) >= ?
                  AND COALESCE(m.band_remarks, '') NOT LIKE '%GSM%'
                  AND COALESCE(m.band_remarks, '') NOT LIKE '%STAGE 2%'
            )
            SELECT * FROM pool
            """,
            [trade_date, POOL["min_mcap"], POOL["min_band"], POOL["min_adv_cr"]],
        ).fetchdf()

        # Build readable RVOL Trail and institutional flow strings
        if not setup_pool.empty:
            setup_pool["rvol_trail"] = setup_pool["rvol_arr"].apply(
                lambda arr: " -> ".join([f"{x:.1f}x" for x in arr]) if arr is not None and len(arr) > 0 else "—"
            )
            setup_pool["ticket_flow"] = setup_pool["ticket_ratio"].apply(
                lambda tr: f"{float(tr):.1f}x 🏛️" if tr is not None and not (pd.isna(tr) or np.isnan(float(tr))) and float(tr) >= 1.20 else (f"{float(tr):.1f}x" if tr is not None and not (pd.isna(tr) or np.isnan(float(tr))) else "—")
            )
            setup_pool["band_fmt"] = setup_pool["band"].apply(
                lambda b: "10% ⚡" if b is not None and not pd.isna(b) and float(b) == 10.0 else (f"{int(b)}%" if b is not None and not pd.isna(b) else "20%")
            )
            setup_pool["away_10ema"] = setup_pool["away_10ema_pct"].apply(
                lambda a: f"{float(a):+.1f}%" if a is not None and not pd.isna(a) else "—"
            )
            setup_pool["away_20ema"] = setup_pool["away_20ema_pct"].apply(
                lambda a: f"{float(a):+.1f}%" if a is not None and not pd.isna(a) else "—"
            )
        else:
            setup_pool["rvol_trail"] = pd.Series(dtype=str)
            setup_pool["ticket_flow"] = pd.Series(dtype=str)
            setup_pool["band_fmt"] = pd.Series(dtype=str)
            setup_pool["away_10ema"] = pd.Series(dtype=str)
            setup_pool["away_20ema"] = pd.Series(dtype=str)

        # Attach macro theme tags to setup pool
        user_db_path = Path(db_path).parent / "marketpulse_user.duckdb"
        stock_tags = get_stock_thematic_tags(str(user_db_path))
        if not setup_pool.empty:
            setup_pool["theme"] = setup_pool["symbol"].map(lambda s: stock_tags.get(s, ["—"])[0])
        else:
            setup_pool["theme"] = pd.Series(dtype=str)

        # Attach institutional deal accumulation tags to setup pool (25-day lookback)
        deals_agg = con.execute(
            """
            SELECT 
                symbol,
                count(*) as deals_cnt,
                round(sum(CASE WHEN side = 'BUY' THEN COALESCE(deal_value_cr, quantity * price / 10000000.0) ELSE 0 END), 1) as buy_cr,
                round(sum(CASE WHEN side = 'SELL' THEN COALESCE(deal_value_cr, quantity * price / 10000000.0) ELSE 0 END), 1) as sell_cr
            FROM deals
            WHERE trade_date >= (SELECT max(trade_date) - INTERVAL 25 DAY FROM deals)
            GROUP BY symbol
            """
        ).fetchdf()
        deal_badge_map = {}
        if not deals_agg.empty:
            for _, r in deals_agg.iterrows():
                b_cr = float(r["buy_cr"] or 0)
                if b_cr >= 10.0:
                    deal_badge_map[r["symbol"]] = f"🏛️ +₹{b_cr:,.0f}Cr"
                elif r["deals_cnt"] > 0:
                    deal_badge_map[r["symbol"]] = f"🏛️ {int(r['deals_cnt'])} Deals"
        if not setup_pool.empty:
            setup_pool["deal_flow"] = setup_pool["symbol"].map(deal_badge_map).fillna("—")
        else:
            setup_pool["deal_flow"] = pd.Series(dtype=str)

        # Trailing bars for Darvas Box calculation across setup pool.
        # Weekly flag may fetch 400 sessions for resampling; daily queue still uses 252 / 45.
        darvas_hist = pd.DataFrame()
        daily_lookback = int(DARVAS["box_lookback_sessions"]) if use_v2 else 45
        fetch_lookback = (
            max(daily_lookback, int(WEEKLY_LOOKBACK_SESSIONS)) if use_weekly else daily_lookback
        )
        if not setup_pool.empty:
            pool_symbols = setup_pool["symbol"].tolist()
            con.register("pool_syms_tbl", pd.DataFrame({"symbol": pool_symbols}))
            darvas_hist = con.execute(
                f"""
                WITH dates AS (
                    SELECT DISTINCT trade_date 
                    FROM indicators_daily 
                    ORDER BY trade_date DESC 
                    LIMIT {int(fetch_lookback)}
                )
                SELECT i.symbol, i.trade_date, i.open_price, i.high_price, i.low_price, i.close_price, i.ema_10, i.ema_20
                FROM indicators_daily i
                JOIN pool_syms_tbl p ON i.symbol = p.symbol
                JOIN dates d ON i.trade_date = d.trade_date
                ORDER BY i.symbol, i.trade_date ASC
                """
            ).fetchdf()

    # Classify the Setup Queues (No stop loss filter in screeners)
    # -------------------------------------------------------------
    # Queue 1: Near 20D Pivot (not a successive-contraction VCP engine)
    # -------------------------------------------------------------
    vcp_df = setup_pool[
        (setup_pool["rs_percentile"] >= 70.0)
        & (setup_pool["away_52w_high_pct"] >= -25.0)
        & (setup_pool["ema_200"].isna() | (setup_pool["cmp"] > setup_pool["ema_200"]))
        & (setup_pool["ema_200"].isna() | (setup_pool["ema_50"] > setup_pool["ema_200"]))
    ].copy() if not setup_pool.empty else pd.DataFrame()
    if not vcp_df.empty:
        vcp_df["trigger_price"] = vcp_df["high_20d"].round(2)
        vcp_df["stop_loss"] = vcp_df[["ema_20", "low_10d"]].max(axis=1).round(2)
        vcp_df["dist_to_trigger_pct"] = ((vcp_df["trigger_price"] / vcp_df["cmp"] - 1.0) * 100).round(2)
        vcp_df["risk_pct"] = ((vcp_df["trigger_price"] / vcp_df["stop_loss"] - 1.0) * 100).round(2)
        vcp_df = vcp_df[
            vcp_df["dist_to_trigger_pct"].between(0.0, 3.5)
        ].sort_values(["rs_percentile", "dist_to_trigger_pct"], ascending=[False, True]).head(
            QUEUE_DISPLAY_CAPS["near_pivot"]
        )
        vcp_df["setup_type"] = "Near 20D Pivot"
        vcp_df["is_vdu"] = vcp_df["rvol"] <= 0.70
        vcp_df["why_now"] = np.where(
            vcp_df["is_vdu"],
            "Coiling <3.5% below pivot with confirmed Volume Dry-Up (VDU)",
            "Coiling <3.5% below 20D pivot with orderly consolidation",
        )

    # -------------------------------------------------------------
    # Queue 2: 10/20 EMA Pullback (Continuation)
    # -------------------------------------------------------------
    pb_df = setup_pool[
        (setup_pool["rs_percentile"] >= 70.0)
        & (setup_pool["away_52w_high_pct"].between(-25.0, -2.5))
        & (setup_pool["ema_200"].isna() | (setup_pool["cmp"] > setup_pool["ema_200"]))
    ].copy() if not setup_pool.empty else pd.DataFrame()
    if not pb_df.empty:
        pb_df["trigger_price"] = (pb_df["cmp"] * 1.01).round(2)
        pb_df["stop_loss"] = (pb_df["ema_20"] * 0.985).round(2)
        pb_df["risk_pct"] = ((pb_df["cmp"] / pb_df["stop_loss"] - 1.0) * 100).round(2)
        pb_df = pb_df[
            ((pb_df["away_10ema_pct"].abs() <= 2.2) | (pb_df["away_20ema_pct"].abs() <= 2.2))
            & (pb_df["away_52w_high_pct"].between(-18.0, -2.5))
        ].sort_values("rs_percentile", ascending=False).head(QUEUE_DISPLAY_CAPS["pullback"])
        pb_df["setup_type"] = "EMA Pullback"
        pb_df["why_now"] = "Orderly rest on 10/20 EMA support in confirmed uptrend"

    # -------------------------------------------------------------
    # Queue 3: High RVOL Episodic Pivot
    # -------------------------------------------------------------
    ep_df = setup_pool.copy()
    if not ep_df.empty:
        ep_df["trigger_price"] = ep_df["high_price"].round(2)
        ep_df["stop_loss"] = ep_df["low_price"].round(2)
        ep_df["risk_pct"] = ((ep_df["cmp"] / ep_df["stop_loss"] - 1.0) * 100).round(2)
        ep_df = ep_df[
            (ep_df["rvol"] >= 2.0)
            & (ep_df["day_pct"] >= 2.5)
        ].sort_values(["rvol", "day_pct"], ascending=[False, False]).head(QUEUE_DISPLAY_CAPS["episodic"])
        ep_df["setup_type"] = "Episodic Pivot"
        ep_df["why_now"] = "Explosive 2x+ RVOL surge out of base"

    # -------------------------------------------------------------
    # Queue 4: 52-Week High Breakout
    # -------------------------------------------------------------
    h52_df = setup_pool[
        (setup_pool["rs_percentile"] >= 70.0)
        & (setup_pool["away_52w_high_pct"] >= -2.0)
    ].copy() if not setup_pool.empty else pd.DataFrame()
    if not h52_df.empty:
        h52_df["trigger_price"] = (h52_df["cmp"] * 1.005).round(2)
        h52_df["stop_loss"] = h52_df[["ema_20", "low_10d"]].max(axis=1).round(2)
        h52_df["risk_pct"] = ((h52_df["cmp"] / h52_df["stop_loss"] - 1.0) * 100).round(2)
        h52_df = h52_df[
            (h52_df["away_52w_high_pct"] >= -2.0)
            & (h52_df["rvol"] >= 1.2)
        ].sort_values(["rs_percentile", "rvol"], ascending=[False, False]).head(QUEUE_DISPLAY_CAPS["high52"])
        h52_df["setup_type"] = "52W High Breakout"
        h52_df["why_now"] = "Printing fresh 52-week high with volume thrust and leadership RS"

    # -------------------------------------------------------------
    # Queue 5: Darvas Box & 10/20 EMA Squeeze (Decoupled from RS)
    # Squeeze into top box and 10 EMA / 20 EMA. No stop-loss filter.
    # Weekly path is behind MP_DARVAS_WEEKLY (completed weeks only).
    # -------------------------------------------------------------
    def _hist_last_sessions(hist: pd.DataFrame, n: int) -> pd.DataFrame:
        if hist is None or hist.empty:
            return hist
        sessions = pd.to_datetime(hist["trade_date"]).drop_duplicates().sort_values()
        keep = set(sessions.tail(int(n)))
        return hist.loc[pd.to_datetime(hist["trade_date"]).isin(keep)].copy()

    darvas_hist_daily = (
        _hist_last_sessions(darvas_hist, daily_lookback) if use_weekly else darvas_hist
    )

    def _assemble_darvas_queue(
        cand_df: pd.DataFrame, *, v2: bool, weekly: bool = False
    ) -> tuple[pd.DataFrame, int]:
        if cand_df is None or cand_df.empty or setup_pool.empty:
            return pd.DataFrame(), 0
        out = setup_pool.merge(cand_df, on="symbol", how="inner")
        if out.empty:
            return pd.DataFrame(), 0
        out["trigger_price"] = out["darvas_top"]
        if weekly and "ema_floor" in out.columns:
            stop_base = pd.to_numeric(out["ema_floor"], errors="coerce")
        else:
            stop_base = out["ema_10"]
        out["stop_loss"] = (stop_base * 0.985).round(2)
        out["risk_pct"] = ((out["trigger_price"] / out["stop_loss"] - 1.0) * 100.0).round(2)
        out["setup_type"] = "Darvas Squeeze"
        if v2:
            out["why_now"] = [
                f"Close inside, wick ≤1.5% under stacked 10/20 floor · Squeezed {sq:.1f}% (Range {cr:.1f}%) into Green Line ₹{top:,.1f}"
                for sq, cr, top in zip(out["squeeze_pct"], out["candle_range_pct"], out["darvas_top"])
            ]
            return apply_display_window(out)
        out["why_now"] = [
            f"OHLC inside box · Squeezed {sq:.1f}% (Range {cr:.1f}%) into Green Line ₹{top:,.1f}"
            for sq, cr, top in zip(out["squeeze_pct"], out["candle_range_pct"], out["darvas_top"])
        ]
        out = out.sort_values(["squeeze_pct", "candle_range_pct"], ascending=[True, True]).head(150)
        return out, int(len(out))

    darvas_cand_df = pd.DataFrame()
    if not darvas_hist_daily.empty:
        if use_v2:
            sq_frame = squeeze_frame(darvas_hist_daily, timeframe="D")
            if not sq_frame.empty:
                darvas_cand_df = sq_frame.loc[sq_frame["qualifies"]].copy()
        else:
            rows = []
            for sym, group in darvas_hist_daily.groupby("symbol"):
                if len(group) < 10:
                    continue
                top_box, bottom_box = calculate_darvas_box(
                    group["high_price"].values, group["low_price"].values, boxp=5
                )
                last_o = float(group["open_price"].iloc[-1])
                last_h = float(group["high_price"].iloc[-1])
                last_l = float(group["low_price"].iloc[-1])
                last_c = float(group["close_price"].iloc[-1])
                last_top = float(top_box[-1])
                last_btm = float(bottom_box[-1])
                last_ema10 = float(group["ema_10"].iloc[-1])
                last_ema20 = (
                    float(group["ema_20"].iloc[-1])
                    if "ema_20" in group.columns and pd.notna(group["ema_20"].iloc[-1])
                    else None
                )
                if is_darvas_10ema_squeeze_legacy(
                    last_c,
                    last_top,
                    last_btm,
                    last_ema10,
                    high=last_h,
                    low=last_l,
                    open_price=last_o,
                    max_squeeze_pct=5.0,
                    max_candle_range_pct=4.0,
                    require_ohlc_inside=True,
                    ema20=last_ema20,
                ):
                    sq_pct = round(((last_top - last_ema10) / last_top) * 100.0, 2)
                    sq_pct = max(0.0, min(sq_pct, 5.0))
                    cr_pct = round(((last_h - last_l) / last_c) * 100.0, 2) if last_c > 0 else 0.0
                    rows.append({
                        "symbol": sym,
                        "darvas_top": round(last_top, 2),
                        "darvas_bottom": round(last_btm, 2),
                        "squeeze_pct": sq_pct,
                        "candle_range_pct": cr_pct,
                    })
            darvas_cand_df = pd.DataFrame(rows)

    darvas_df, darvas_count = _assemble_darvas_queue(darvas_cand_df, v2=use_v2)

    darvas_weekly_df = pd.DataFrame()
    darvas_count_weekly = 0
    if use_weekly and not darvas_hist.empty:
        sq_weekly = squeeze_frame(darvas_hist, timeframe="W", as_of=trade_date)
        cand_w = sq_weekly.loc[sq_weekly["qualifies"]].copy() if not sq_weekly.empty else pd.DataFrame()
        darvas_weekly_df, darvas_count_weekly = _assemble_darvas_queue(cand_w, v2=True, weekly=True)

    def _is_num(v: Any) -> bool:
        if v is None or v is np.ma.masked:
            return False
        try:
            f = float(v)
            return not (np.isnan(f) or np.isinf(f))
        except Exception:
            return False

    # -------------------------------------------------------------
    # Queue 6: Silent Coil (VDU at 10/20 EMA)
    # -------------------------------------------------------------
    sc_candidates = []
    if not setup_pool.empty:
        for _, r in setup_pool.iterrows():
            raw_rvol = r.get("rvol_arr")
            arr = [float(x) for x in raw_rvol if _is_num(x)] if isinstance(raw_rvol, (list, np.ndarray)) else []
            if len(arr) < 3:
                continue
            near_ema = abs(r["away_10ema_pct"]) <= 2.5 or abs(r["away_20ema_pct"]) <= 2.5
            vdu = r["rvol"] <= 0.70
            raw_day = r.get("day_pct_arr")
            d_arr = [float(x) for x in raw_day if _is_num(x)] if isinstance(raw_day, (list, np.ndarray)) else []
            tight_days = sum(1 for d in d_arr if abs(d) < 2.0)
            raw_del = r.get("deliv_arr")
            deliv_valid = [float(x) for x in raw_del if _is_num(x)] if isinstance(raw_del, (list, np.ndarray)) else []
            deliv_good = (r["delivery_pct"] >= 50.0 if _is_num(r.get("delivery_pct")) else False) or (max(deliv_valid) >= 55.0 if deliv_valid else False)
            unextended = abs(r["return_5d_pct"]) <= 3.5 if _is_num(r.get("return_5d_pct")) else True
            if near_ema and vdu and (tight_days >= 3 or unextended) and deliv_good:
                sc_candidates.append(r)
    sc_df = pd.DataFrame(sc_candidates) if sc_candidates else pd.DataFrame()
    if not sc_df.empty:
        sc_df["trigger_price"] = (sc_df["cmp"] * 1.005).round(2)
        sc_df["stop_loss"] = (sc_df["ema_20"] * 0.985).round(2)
        sc_df["risk_pct"] = ((sc_df["cmp"] / sc_df["stop_loss"] - 1.0) * 100).round(2)
        sc_df["setup_type"] = "Silent Coil"
        sc_df["why_now"] = "Severe volume dry-up (RVOL ≤ 0.70x) + tight consolidation at 10/20 EMA with delivery accumulation"
        sort_col = "ticket_ratio" if "ticket_ratio" in sc_df.columns else "delivery_pct"
        sc_df = sc_df.sort_values([sort_col, "delivery_pct"], ascending=[False, False]).head(
            QUEUE_DISPLAY_CAPS["silent_coil"]
        )

    # -------------------------------------------------------------
    # Queue 7: Volume Stair-Step (RVOL Escalation)
    # -------------------------------------------------------------
    vss_candidates = []
    if not setup_pool.empty:
        for _, r in setup_pool.iterrows():
            raw_rvol = r.get("rvol_arr")
            arr = [float(x) for x in raw_rvol if _is_num(x)] if isinstance(raw_rvol, (list, np.ndarray)) else []
            if len(arr) < 3:
                continue
            near_ema = abs(r["away_10ema_pct"]) <= 3.0 or abs(r["away_20ema_pct"]) <= 3.0
            rising_3d = (len(arr) >= 3) and (arr[-1] > arr[-2] > arr[-3])
            prev_slice = arr[-4:-1]
            prev_min = min(prev_slice) if len(prev_slice) > 0 else 99.0
            jump_from_dry = arr[-1] >= 1.3 and prev_min <= 0.65
            unextended = r["day_pct"] <= 4.0 and (not _is_num(r.get("return_5d_pct")) or r["return_5d_pct"] <= 5.0)
            if near_ema and (rising_3d or jump_from_dry) and unextended:
                vss_candidates.append(r)
    vss_df = pd.DataFrame(vss_candidates) if vss_candidates else pd.DataFrame()
    if not vss_df.empty:
        vss_df["trigger_price"] = (vss_df["cmp"] * 1.005).round(2)
        vss_df["stop_loss"] = (vss_df["ema_20"] * 0.985).round(2)
        vss_df["risk_pct"] = ((vss_df["cmp"] / vss_df["stop_loss"] - 1.0) * 100).round(2)
        vss_df["setup_type"] = "Volume Stair-Step"
        vss_df["why_now"] = "RVOL expanding day-over-day at 10/20 EMA support before the breakout"
        sort_col = "ticket_ratio" if "ticket_ratio" in vss_df.columns else "rvol"
        vss_df = vss_df.sort_values([sort_col, "rvol"], ascending=[False, False]).head(
            QUEUE_DISPLAY_CAPS["stair_step"]
        )

    # -------------------------------------------------------------
    # Queue 8: Spike-Pause (Pre-Blast Consolidation)
    # -------------------------------------------------------------
    sp_candidates = []
    if not setup_pool.empty:
        for _, r in setup_pool.iterrows():
            raw_rvol = r.get("rvol_arr")
            arr = [float(x) for x in raw_rvol if _is_num(x)] if isinstance(raw_rvol, (list, np.ndarray)) else []
            if len(arr) < 3:
                continue
            prev_slice = arr[:-1]
            had_spike = max(prev_slice) >= 2.0 if len(prev_slice) > 0 else False
            raw_day = r.get("day_pct_arr")
            d_arr = [float(x) for x in raw_day if _is_num(x)] if isinstance(raw_day, (list, np.ndarray)) else []
            prev_days = d_arr[:-1]
            had_blast = max(prev_days) >= 9.5 if len(prev_days) > 0 else False
            pausing = (abs(r["day_pct"]) <= 3.5) and (r["rvol"] <= 0.85)
            near_ema = abs(r["away_10ema_pct"]) <= 4.0 or abs(r["away_20ema_pct"]) <= 4.0
            if (had_spike or had_blast) and pausing and near_ema:
                sp_candidates.append(r)
    sp_df = pd.DataFrame(sp_candidates) if sp_candidates else pd.DataFrame()
    if not sp_df.empty:
        sp_df["trigger_price"] = (sp_df["cmp"] * 1.005).round(2)
        sp_df["stop_loss"] = (sp_df["ema_20"] * 0.985).round(2)
        sp_df["risk_pct"] = ((sp_df["cmp"] / sp_df["stop_loss"] - 1.0) * 100).round(2)
        sp_df["setup_type"] = "Spike-Pause"
        sp_df["why_now"] = "Prior 2x+ RVOL surge or 10%+ blast followed by low-volume pause resting on 10/20 EMA"
        sort_col = "ticket_ratio" if "ticket_ratio" in sp_df.columns else "delivery_pct"
        sp_df = sp_df.sort_values([sort_col, "delivery_pct"], ascending=[False, False]).head(
            QUEUE_DISPLAY_CAPS["spike_pause"]
        )





    macro_pulse = get_macro_pulse(Path(db_path))
    data = {
        "ready": True,
        "trade_date": trade_date_str,
        "macro_pulse": macro_pulse,
        "exposure": {
            "pct": exposure_pct,
            "state": exposure_state,
            "badge": exposure_badge,
            "guidance": exposure_guidance,
            "adv_pct": adv_pct,
            "ab20_pct": ab20_pct,
            "ab50_pct": ab50_pct,
            "ab200_pct": ab200_pct,
            "breadth_source": breadth_source,
            "as_of": breadth_as_of,
            "vix": vix_val,
            "vix_1d_pct": vix_1d_pct,
            "vix_available": gate["vix_available"],
            "vix_na": gate["vix_na"],
            "vix_label": gate["vix_label"],
            "count_52w_highs": count_52w_highs,
            "count_52w_lows": count_52w_lows,
            "net_highs": net_highs,
            "total_stocks": total_stocks,
        },
        "themes": top_sectors,
        "darvas_count": darvas_count,
        "darvas_count_weekly": darvas_count_weekly,
        "darvas_weekly_enabled": use_weekly,
        "queues": {
            "vcp": vcp_df,
            "pullback": pb_df,
            "episodic": ep_df,
            "high52": h52_df,
            "darvas": darvas_df,
            "darvas_weekly": darvas_weekly_df,
            "silent_coil": sc_df,
            "stair_step": vss_df,
            "spike_pause": sp_df,
        },
        "tv_lists": {
            "vcp": to_tv_list(vcp_df["symbol"].tolist()) if not vcp_df.empty else "",
            "pullback": to_tv_list(pb_df["symbol"].tolist()) if not pb_df.empty else "",
            "episodic": to_tv_list(ep_df["symbol"].tolist()) if not ep_df.empty else "",
            "high52": to_tv_list(h52_df["symbol"].tolist()) if not h52_df.empty else "",
            "darvas": to_tv_list(darvas_df["symbol"].tolist()) if not darvas_df.empty else "",
            "darvas_weekly": to_tv_list(darvas_weekly_df["symbol"].tolist()) if not darvas_weekly_df.empty else "",
            "silent_coil": to_tv_list(sc_df["symbol"].tolist()) if not sc_df.empty else "",
            "stair_step": to_tv_list(vss_df["symbol"].tolist()) if not vss_df.empty else "",
            "spike_pause": to_tv_list(sp_df["symbol"].tolist()) if not sp_df.empty else "",
            "all_focus": to_tv_list(
                list(dict.fromkeys(
                    vcp_df["symbol"].tolist()
                    + pb_df["symbol"].tolist()
                    + ep_df["symbol"].tolist()
                    + h52_df["symbol"].tolist()
                    + darvas_df["symbol"].tolist()
                    + (sc_df["symbol"].tolist() if not sc_df.empty else [])
                    + (vss_df["symbol"].tolist() if not vss_df.empty else [])
                    + (sp_df["symbol"].tolist() if not sp_df.empty else [])
                ))
            ),
        }

    }

    set_cached(key, data)
    return data


def render_inline_candlestick_chart(db_path: Path | str, symbol: str, is_darvas: bool = False) -> None:
    cdata = query_stock_candlestick_data(Path(db_path), symbol, limit=90)
    if not cdata:
        ui.label(f"No historical candlestick data available for {symbol}.").classes("text-sm text-[var(--mp-muted)] p-4")
        return

    if is_darvas and cdata.get("is_darvas_squeeze"):
        with ui.row().classes("w-full items-center justify-between px-3 py-1.5 rounded bg-emerald-950/40 border border-emerald-500/50 text-emerald-300 text-xs font-mono mb-2"):
            ui.label("🎯 DARVAS 10 EMA SQUEEZE (OHLC INSIDE BOX)").classes("font-bold text-emerald-400 tracking-wide")
            cr = f" · Candle Range: {cdata['candle_range_pct']:.1f}%" if cdata.get('candle_range_pct') is not None else ""
            top_txt = f" · Green Line: ₹{cdata['latest_darvas_top']:,.1f}" if cdata.get('latest_darvas_top') else ""
            ema_txt = f" · 10 EMA: ₹{cdata['ema10'][-1]:,.1f}" if cdata.get('ema10') and cdata['ema10'][-1] else ""
            ui.label(f"Spread: {cdata['darvas_squeeze_pct']:.1f}%{cr}{top_txt}{ema_txt}").classes("font-semibold")

    # Squeeze corridor highlight markArea
    squeeze_mark_area = None
    if is_darvas and cdata.get("latest_darvas_top"):
        top_val = cdata["latest_darvas_top"]
        ema_val = cdata["ema10"][-1] if cdata.get("ema10") and cdata["ema10"][-1] else None
        bot_val = cdata.get("latest_darvas_bottom")
        lower_bound = ema_val if ema_val is not None else bot_val
        if lower_bound:
            recent_idx = max(0, len(cdata["dates"]) - 15)
            start_d = cdata["dates"][recent_idx]
            end_d = cdata["dates"][-1]
            squeeze_mark_area = {
                "silent": True,
                "itemStyle": {
                    "color": "rgba(16, 185, 129, 0.09)",
                    "borderColor": "rgba(16, 185, 129, 0.45)",
                    "borderWidth": 1.5,
                    "borderType": "dashed",
                },
                "data": [
                    [
                        {
                            "name": "🎯 Squeeze Zone",
                            "coord": [start_d, top_val],
                            "label": {
                                "show": True,
                                "color": "#34d399",
                                "fontSize": 10,
                                "position": "insideTopRight",
                                "formatter": f"🎯 Darvas Squeeze ({cdata.get('darvas_squeeze_pct', 0):.1f}%)" if cdata.get("darvas_squeeze_pct") else "🎯 Darvas Squeeze",
                            },
                        },
                        {"coord": [end_d, min(top_val, lower_bound)]},
                    ]
                ],
            }

    legend_items = ["Price", "10 EMA", "20 EMA", "50 EMA", "200 EMA"]
    series = [
        {
            "name": "Price",
            "type": "candlestick",
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "data": cdata["ohlc"],
            "itemStyle": {
                "color": "#10b981",
                "color0": "#ef4444",
                "borderColor": "#10b981",
                "borderColor0": "#ef4444"
            },
            "markArea": squeeze_mark_area,
        },
    ]

    if is_darvas:
        legend_items.insert(1, "Darvas Top")
        legend_items.insert(2, "Darvas Bottom")
        series.extend([
            {
                "name": "Darvas Top",
                "type": "line",
                "step": "end",
                "xAxisIndex": 0,
                "yAxisIndex": 0,
                "data": cdata.get("darvas_top", []),
                "lineStyle": {"color": "#22c55e", "width": 2.5},
                "showSymbol": False,
            },
            {
                "name": "Darvas Bottom",
                "type": "line",
                "step": "end",
                "xAxisIndex": 0,
                "yAxisIndex": 0,
                "data": cdata.get("darvas_bottom", []),
                "lineStyle": {"color": "#ef4444", "width": 1.5},
                "showSymbol": False,
            },
        ])

    series.extend([
        {"name": "10 EMA", "type": "line", "xAxisIndex": 0, "yAxisIndex": 0, "data": cdata["ema10"], "smooth": True, "lineStyle": {"color": "#ffffff", "width": 2.0}, "showSymbol": False},
        {"name": "20 EMA", "type": "line", "xAxisIndex": 0, "yAxisIndex": 0, "data": cdata["ema20"], "smooth": True, "lineStyle": {"color": "#fbbf24", "width": 1.5}, "showSymbol": False},
        {"name": "50 EMA", "type": "line", "xAxisIndex": 0, "yAxisIndex": 0, "data": cdata["ema50"], "smooth": True, "lineStyle": {"color": "#f97316", "width": 1.5}, "showSymbol": False},
        {"name": "200 EMA", "type": "line", "xAxisIndex": 0, "yAxisIndex": 0, "data": cdata["ema200"], "smooth": True, "lineStyle": {"color": "#ec4899", "width": 1.5}, "showSymbol": False},
        {
            "name": "Volume",
            "type": "bar",
            "xAxisIndex": 1,
            "yAxisIndex": 1,
            "data": cdata["volume"],
            "itemStyle": {"color": "#475569"}
        },
        {
            "name": "RSI(14)",
            "type": "line",
            "xAxisIndex": 2,
            "yAxisIndex": 2,
            "data": cdata["rsi"],
            "lineStyle": {"color": "#a855f7", "width": 1.5},
            "showSymbol": False
        }
    ])

    total_bars = len(cdata["dates"])
    zoom_20d_pct = max(0.0, round(((total_bars - 22) / max(total_bars, 1)) * 100.0, 1))
    zoom_45d_pct = max(0.0, round(((total_bars - 45) / max(total_bars, 1)) * 100.0, 1))
    zoom_start_pct = zoom_20d_pct

    echart_opt = {
        "backgroundColor": "transparent",
        "animation": False,
        "tooltip": {
            "trigger": "axis",
            "axisPointer": {"type": "cross"},
            "confine": True,
        },
        "legend": {
            "data": legend_items,
            "textStyle": {"color": "#94a3b8", "fontSize": 10},
            "top": 0
        },
        "grid": [
            {"left": "5%", "right": "3%", "top": "7%", "height": "60%"},
            {"left": "5%", "right": "3%", "top": "70%", "height": "12%"},
            {"left": "5%", "right": "3%", "top": "84%", "height": "10%"},
        ],
        "xAxis": [
            {"type": "category", "gridIndex": 0, "data": cdata["dates"], "boundaryGap": False, "scale": True, "axisLine": {"onZero": False, "lineStyle": {"color": "#334155"}}, "axisLabel": {"show": False}},
            {"type": "category", "gridIndex": 1, "data": cdata["dates"], "boundaryGap": False, "scale": True, "axisLine": {"onZero": False, "lineStyle": {"color": "#334155"}}, "axisLabel": {"show": False}},
            {"type": "category", "gridIndex": 2, "data": cdata["dates"], "boundaryGap": False, "scale": True, "axisLine": {"onZero": False, "lineStyle": {"color": "#334155"}}, "axisLabel": {"color": "#94a3b8", "fontSize": 9}},
        ],
        "yAxis": [
            {"scale": True, "gridIndex": 0, "splitLine": {"lineStyle": {"color": "#1e293b"}}, "axisLabel": {"color": "#94a3b8", "fontSize": 10}},
            {"scale": True, "gridIndex": 1, "splitLine": {"show": False}, "axisLabel": {"show": False}},
            {"scale": True, "gridIndex": 2, "min": 0, "max": 100, "splitLine": {"lineStyle": {"color": "#1e293b"}}, "axisLabel": {"color": "#94a3b8", "fontSize": 9}},
        ],
        "dataZoom": [
            {
                "type": "inside",
                "xAxisIndex": [0, 1, 2],
                "start": zoom_start_pct,
                "end": 100,
                "minValueSpan": 10,
                "zoomOnMouseWheel": True,
                "moveOnMouseMove": True,
            },
            {
                "type": "slider",
                "xAxisIndex": [0, 1, 2],
                "start": zoom_start_pct,
                "end": 100,
                "height": 18,
                "bottom": 2,
                "borderColor": "#334155",
                "fillerColor": "rgba(16, 185, 129, 0.18)",
                "handleStyle": {"color": "#10b981", "borderColor": "#059669"},
                "moveHandleStyle": {"color": "#10b981"},
                "dataBackground": {
                    "lineStyle": {"color": "#64748b"},
                    "areaStyle": {"color": "rgba(100, 116, 139, 0.2)"},
                },
                "selectedDataBackground": {
                    "lineStyle": {"color": "#10b981"},
                    "areaStyle": {"color": "rgba(16, 185, 129, 0.3)"},
                },
                "textStyle": {"color": "#94a3b8", "fontSize": 10},
            },
        ],
        "series": series
    }
    chart_elem = ui.echart(echart_opt).classes("w-full h-[500px]")

    with ui.row().classes("w-full items-center justify-end gap-2 my-1 text-xs"):
        ui.label("Zoom Focus:").classes("text-[var(--mp-muted)] font-mono")
        ui.button("🎯 20D (Squeeze Focus)", on_click=lambda: chart_elem.run_chart_method('dispatchAction', {'type': 'dataZoom', 'dataZoomIndex': 0, 'start': zoom_20d_pct, 'end': 100})).props("dense outline size=xs").classes("mp-button")
        ui.button("⏳ 45D (Base)", on_click=lambda: chart_elem.run_chart_method('dispatchAction', {'type': 'dataZoom', 'dataZoomIndex': 0, 'start': zoom_45d_pct, 'end': 100})).props("dense outline size=xs").classes("mp-button")
        ui.button("📊 90D (All)", on_click=lambda: chart_elem.run_chart_method('dispatchAction', {'type': 'dataZoom', 'dataZoomIndex': 0, 'start': 0, 'end': 100})).props("dense outline size=xs").classes("mp-button")


def render_queue_chart_preview(
    db_path: Path | str,
    df: pd.DataFrame,
    queue_name: str,
    *,
    is_darvas: bool = False,
    is_vcp: bool = False,
    copy_text: Callable | None = None,
) -> None:
    if df.empty or "symbol" not in df.columns:
        return

    sym_list = [str(s) for s in df["symbol"].dropna().tolist()]
    if not sym_list:
        return

    default_sym = sym_list[0]
    with ui.card().classes("w-full mp-card p-3 mt-4 border border-[var(--mp-border)] bg-[var(--mp-surface-raised)]"):
        with ui.row().classes("w-full items-center justify-between pb-2 border-b border-[var(--mp-border)] flex-wrap gap-2"):
            with ui.row().classes("items-center gap-2"):
                ui.label(f"📈 {queue_name} Interactive Chart Preview").classes("text-xs font-bold tracking-wider text-[var(--mp-primary)] uppercase")
                sel = ui.select(sym_list, value=default_sym, label="Candidate").classes("w-44").props("dense outlined")
            with ui.row().classes("items-center gap-2"):
                ui.button("Open Stock 360 ↗", on_click=lambda: open_stock_360_modal(Path(db_path), str(sel.value), copy_text=copy_text)).classes("mp-button text-xs").props("dense outline")

        chart_host = ui.column().classes("w-full mt-2")

        def update_chart():
            chart_host.clear()
            sym = str(sel.value or "").strip().upper()
            if not sym:
                return
            with chart_host:
                if is_vcp:
                    render_vcp_ohlc(Path(db_path), sym)
                else:
                    render_inline_candlestick_chart(db_path, sym, is_darvas=is_darvas)

        sel.on_value_change(lambda _: update_chart())
        update_chart()


def build_action_desk_page(
    db_path: Path | str,
    section_header: Callable,
    table_from_df: Callable,
    copy_text: Callable | None = None,
) -> None:
    """Build the Action Desk view inside NiceGUI (3-Column Master-Detail Cockpit)."""
    render_market_health_strip(Path(db_path))
    data = fetch_action_desk_data(db_path)
    if not data.get("ready"):
        ui.label(data.get("reason", "Action Desk initializing...")).classes("text-sm text-[var(--mp-muted)] p-4")
        return

    exp = data["exposure"]
    themes = data["themes"]
    queues = data["queues"]
    tv = data["tv_lists"]

    # =========================================================================
    # MACRO PULSE: TODAY'S LEADING & LAGGING THEMES
    # =========================================================================
    pulse = data.get("macro_pulse", {})
    top_themes = pulse.get("top", [])
    bottom_themes = pulse.get("bottom", [])
    with ui.row().classes("w-full items-center justify-between px-3 py-2 rounded bg-[var(--mp-surface-raised)] border border-[var(--mp-border)] mb-3 flex-wrap gap-2 text-xs"):
        with ui.row().classes("items-center gap-2 flex-wrap"):
            if top_themes:
                ui.label("🔥 TOP THEMES:").classes("font-bold text-emerald-400 tracking-wider")
                for item in top_themes[:3]:
                    ui.label(f"{item['name']} ({item['return_1d']:+.2f}%)").classes("font-semibold text-emerald-300 bg-emerald-950/80 px-2 py-0.5 rounded border border-emerald-500/30")
            if bottom_themes:
                ui.label("❄️ LAGGING:").classes("font-bold text-rose-400 tracking-wider")
                for item in bottom_themes[:2]:
                    ui.label(f"{item['name']} ({item['return_1d']:+.2f}%)").classes("font-semibold text-rose-300 bg-rose-950/80 px-2 py-0.5 rounded border border-rose-500/30")
        with ui.row().classes("items-center gap-2 ml-auto"):
            ui.button("📖 Trading Playbook & Field Guide", on_click=open_playbook_modal).classes("mp-button text-xs bg-emerald-500 text-slate-950 font-bold hover:bg-emerald-400").props("dense unelevated")

    queue_meta = dict(QUEUE_META)
    if darvas_v2_enabled():
        darvas_meta = dict(queue_meta["darvas"])
        darvas_meta["desc"] = (
            "Close inside, wick ≤1.5% under stacked 10/20 floor, squeezed into Green Line (TopBox)."
        )
        queue_meta["darvas"] = darvas_meta

    # Initial selection
    initial_queue = "vcp"
    initial_sym = ""
    for q_key in ("vcp", "pullback", "episodic", "high52", "darvas", "silent_coil", "stair_step", "spike_pause"):
        q_df = queues.get(q_key, pd.DataFrame())
        if not q_df.empty and "symbol" in q_df.columns:
            if not initial_sym:
                initial_queue = q_key
                initial_sym = str(q_df["symbol"].iloc[0])
                break

    state = {
        "active_queue": initial_queue,
        "selected_symbol": initial_sym,
        "real_inst_flow_only": False,
        "darvas_tf": "Daily",
    }

    # Display columns for the matrix
    display_cols = [
        "symbol", "ticket_flow", "band_fmt", "away_10ema", "deal_flow", "rvol_trail", "theme", "cmp", "trigger_price", "stop_loss", 
        "day_pct", "rvol", "delivery_pct", "rs_percentile", "sector"
    ]

    # Cockpit 3-column split-pane layout
    with ui.element("div").classes("mp-cockpit-container w-full"):

        # =====================================================================
        # COLUMN 1: FUNNEL & QUEUES (Left Column - 250px)
        # =====================================================================
        with ui.column().classes("mp-funnel-col"):

            # Card 1: Market Exposure Gate
            with ui.card().classes("w-full mp-card p-3 border border-[var(--mp-border)] bg-[var(--mp-surface)]"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("STEP 1: EXPOSURE GATE").classes("text-[11px] font-bold tracking-wider text-[var(--mp-primary)] uppercase")
                    ui.label(str(data["trade_date"])).classes("text-[10px] text-[var(--mp-muted)] font-mono")

                with ui.row().classes("w-full items-center justify-between mt-2"):
                    ui.label("EXPOSURE:").classes("text-xs text-[var(--mp-muted)] font-semibold")
                    ui.label(exp["pct"]).classes(f"text-sm font-black px-2 py-0.5 rounded {exp['badge']}")

                ui.label(exp["state"]).classes("text-xs font-semibold text-[var(--mp-text)] mt-1")
                ui.label(exp["guidance"]).classes("text-[11px] text-[var(--mp-muted)] mt-1 leading-snug font-mono")

                # Market Breadth Strip — one labeled universe (strip row or indicators fallback)
                with ui.column().classes("w-full gap-1 mt-2 pt-2 border-t border-[var(--mp-border)] text-xs"):
                    src = exp.get("breadth_source") or ""
                    src_label = "indicators_daily fallback" if src == "indicators_daily" else (src or "breadth")
                    as_of = exp.get("as_of") or data["trade_date"]
                    ui.label(f"{as_of} · {src_label}").classes("text-[10px] text-[var(--mp-muted)] font-mono")
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label("Net Advance:").classes("text-[var(--mp-muted)] text-[11px]")
                        ui.label(_fmt_exp_pct(exp.get("adv_pct"))).classes("font-mono font-bold text-[11px] " + _exp_pct_tone(exp.get("adv_pct"), 50))
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label("> 20 EMA:").classes("text-[var(--mp-muted)] text-[11px]")
                        ui.label(_fmt_exp_pct(exp.get("ab20_pct"))).classes("font-mono font-bold text-[11px] text-[var(--mp-text)]")
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label("> 50 EMA:").classes("text-[var(--mp-muted)] text-[11px]")
                        ui.label(_fmt_exp_pct(exp.get("ab50_pct"))).classes("font-mono font-bold text-[11px] text-[var(--mp-text)]")
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label("> 200 EMA:").classes("text-[var(--mp-muted)] text-[11px]")
                        ui.label(_fmt_exp_pct(exp.get("ab200_pct"))).classes("font-mono font-bold text-[11px] text-[var(--mp-text)]")
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label("India VIX:").classes("text-[var(--mp-muted)] text-[11px]")
                        if exp.get("vix") is None or exp.get("vix_na"):
                            ui.label(exp.get("vix_label") or "VIX n/a").classes("font-mono font-bold text-[11px] text-amber-400")
                        else:
                            vix_sign = "+" if exp.get("vix_1d_pct", 0) > 0 else ""
                            ui.label(f"{exp['vix']} ({vix_sign}{exp.get('vix_1d_pct', 0):.1f}%)").classes("font-mono font-bold text-[11px] " + ("text-emerald-400" if exp['vix'] < 15 else "text-amber-400"))
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label("Net 52W Highs:").classes("text-[var(--mp-muted)] text-[11px]")
                        net_h = exp.get("net_highs", 0)
                        ui.label(f"{'+' if net_h > 0 else ''}{net_h} ({exp.get('count_52w_highs', 0)}H / {exp.get('count_52w_lows', 0)}L)").classes("font-mono font-bold text-[11px] " + ("text-emerald-400" if net_h >= 0 else "text-rose-400"))

                if copy_text and tv.get("all_focus"):
                    ui.button(
                        "📋 Copy All Focus (TV)",
                        on_click=lambda: copy_text("All Focus (TV)", tv["all_focus"]),
                    ).classes("mp-button w-full text-[11px] mt-2").props("dense outline")

            # Card 2: Leading Sector Themes
            with ui.card().classes("w-full mp-card p-3 border border-[var(--mp-border)] bg-[var(--mp-surface)]"):
                ui.label("STEP 2: LEADING SECTORS").classes("text-[11px] font-bold tracking-wider text-[var(--mp-primary)] uppercase mb-2")
                ui.label("Δ SHARE 5D").classes("text-[10px] text-[var(--mp-muted)] uppercase tracking-wider mb-1")
                with ui.column().classes("w-full gap-2"):
                    for idx, (_, sec) in enumerate(themes.iterrows(), 1):
                        grp_name = str(sec.get("group_name") or sec.get("sector") or "—")
                        delta = float(sec.get("turnover_share_delta_5d") or 0.0)
                        to_cr = float(sec.get("turnover_1d_cr") or sec.get("total_to_cr") or 0.0)
                        leaders_raw = str(sec.get("leader_symbols") or sec.get("leaders") or "")
                        with ui.column().classes("w-full p-2 rounded bg-[var(--mp-surface-raised)] border border-[var(--mp-border)] gap-0.5"):
                            with ui.row().classes("w-full items-center justify-between"):
                                ui.label(f"#{idx} {grp_name}").classes("font-bold text-xs text-[var(--mp-text)] truncate")
                                ui.label(f"{delta:+.2f} pp").classes(
                                    "text-[11px] font-mono font-bold " + ("text-emerald-400" if delta >= 0 else "text-rose-400")
                                )
                            with ui.row().classes("w-full items-center justify-between text-[10px] text-[var(--mp-muted)] font-mono"):
                                ui.label("Δ SHARE 5D")
                                ui.label(f"₹{to_cr:,.0f}Cr")
                            if leaders_raw:
                                top_syms = [s.strip() for s in leaders_raw.split(",") if s.strip()][:3]
                                with ui.row().classes("w-full items-center gap-1 mt-1"):
                                    for sym in top_syms:
                                        ui.button(
                                            sym,
                                            on_click=lambda s=sym: select_symbol(s),
                                        ).props("dense flat size=xs").classes("font-mono text-[10px] text-sky-400 px-1 py-0 hover:underline")

            # Card 3: Setup Queues Navigation
            queue_nav_card = ui.card().classes("w-full mp-card p-3 border border-[var(--mp-border)] bg-[var(--mp-surface)]")

        # =====================================================================
        # COLUMN 2: CANDIDATE MATRIX (Center Column - 52% / flex-1)
        # =====================================================================
        matrix_host = ui.column().classes("mp-matrix-col")

        # =====================================================================
        # COLUMN 3: EMBEDDED STOCK INSPECTOR (Right Column - 440px)
        # =====================================================================
        inspector_host = ui.column().classes("mp-inspector-col")

    # Reactive interaction functions
    def select_symbol(sym: str) -> None:
        sym = str(sym or "").strip().upper()
        if not sym:
            return
        state["selected_symbol"] = sym
        render_inspector()
        render_matrix()

    def _darvas_is_weekly() -> bool:
        return bool(data.get("darvas_weekly_enabled")) and state.get("darvas_tf") == "Weekly"

    def _queue_frame(q_key: str) -> pd.DataFrame:
        if q_key == "darvas" and _darvas_is_weekly():
            return queues.get("darvas_weekly", pd.DataFrame())
        return queues.get(q_key, pd.DataFrame())

    def set_queue(q_key: str) -> None:
        state["active_queue"] = q_key
        q_df = _queue_frame(q_key)
        if not q_df.empty and "symbol" in q_df.columns:
            state["selected_symbol"] = str(q_df["symbol"].iloc[0])
        render_queue_nav()
        render_matrix()
        render_inspector()

    def render_queue_nav() -> None:
        with queue_nav_card:
            queue_nav_card.clear()
            ui.label("STEP 3: SETUP QUEUES").classes("text-[11px] font-bold tracking-wider text-[var(--mp-primary)] uppercase mb-2")
            with ui.column().classes("w-full gap-1.5"):
                for q_key, q_info in queue_meta.items():
                    q_df = _queue_frame(q_key)
                    if q_key == "darvas":
                        if _darvas_is_weekly():
                            count = int(data.get("darvas_count_weekly") or 0)
                        else:
                            count = int(data.get("darvas_count") or 0)
                    else:
                        count = len(q_df) if not q_df.empty else 0
                    is_active = (q_key == state["active_queue"])
                    
                    with ui.button(
                        on_click=lambda k=q_key: set_queue(k)
                    ).classes(
                        "w-full justify-between items-center px-2.5 py-1.5 rounded text-xs font-semibold text-left transition-colors " +
                        ("bg-emerald-600/20 text-emerald-300 border border-emerald-500/40" if is_active else "bg-[var(--mp-surface-raised)] text-[var(--mp-text)] border border-[var(--mp-border)] hover:bg-[var(--mp-surface-2)]")
                    ).props("dense flat no-caps"):
                        ui.label(q_info["short_title"]).classes("truncate")
                        ui.label(str(count)).classes(
                            "text-[10px] font-mono px-1.5 py-0.2 rounded font-bold " +
                            ("bg-emerald-500 text-slate-950" if is_active and count > 0 else "bg-slate-800 text-slate-300")
                        )

    def render_matrix() -> None:
        with matrix_host:
            matrix_host.clear()

            q_key = state["active_queue"]
            q_info = queue_meta.get(q_key, queue_meta["vcp"])
            q_df = _queue_frame(q_key)
            if state.get("real_inst_flow_only") and not q_df.empty and "deal_flow" in q_df.columns:
                q_df = q_df[q_df["deal_flow"].astype(str).str.strip().ne("—")]
            if q_key == "darvas" and _darvas_is_weekly():
                tv_text = tv.get("darvas_weekly", "")
            else:
                tv_text = to_tv_list(q_df["symbol"].tolist()) if (not q_df.empty and "symbol" in q_df.columns) else tv.get(q_info["tv_key"], "")

            # Header Banner
            with ui.card().classes("w-full mp-card p-3 border border-[var(--mp-border)] bg-[var(--mp-surface)]"):
                with ui.row().classes("w-full items-center justify-between flex-wrap gap-2"):
                    with ui.column().classes("gap-0.5"):
                        ui.label(q_info["title"]).classes("text-sm font-bold text-[var(--mp-text)]")
                        ui.label(q_info["desc"]).classes("text-xs text-[var(--mp-muted)]")
                    with ui.row().classes("items-center gap-2"):
                        if q_key == "darvas" and data.get("darvas_weekly_enabled"):
                            def _on_darvas_tf(e):
                                state["darvas_tf"] = e.value
                                q_new = _queue_frame("darvas")
                                if not q_new.empty and "symbol" in q_new.columns:
                                    state["selected_symbol"] = str(q_new["symbol"].iloc[0])
                                render_queue_nav()
                                render_matrix()
                                render_inspector()
                            tf_toggle = ui.toggle(
                                ["Daily", "Weekly"],
                                value=state.get("darvas_tf", "Daily"),
                            ).props("dense unelevated").classes("mp-toggle text-xs")
                            tf_toggle.on_value_change(_on_darvas_tf)
                        if copy_text and tv_text:
                            ui.button(
                                f"📋 Copy {q_info['short_title']} (TV)",
                                on_click=lambda *_, t=tv_text, lbl=f"{q_info['short_title']} (TV)": copy_text(lbl, t),
                            ).classes("mp-button text-xs").props("dense outline")

                # Quality Filter Strip
                is_classic_rs = q_key in ("vcp", "pullback", "high52")
                rules_txt = (
                    "Rules: MCap > ₹1000Cr · Circuit > 5% · Stage 2 Uptrend · Within 25% 52W · RS >= 70"
                    if is_classic_rs else
                    "Evidence-Based Rules: MCap > ₹1000Cr · 10/20 EMA Support · VDU & High Deliv · Institutional Footprint · No Stop-Loss Cutoff"
                )
                with ui.row().classes("w-full items-center justify-between text-[11px] text-[var(--mp-muted)] font-mono mt-2 pt-2 border-t border-[var(--mp-border)] flex-wrap gap-2"):
                    ui.label(rules_txt).classes("truncate")
                    with ui.row().classes("items-center gap-3"):
                        ui.label("Stop Loss: Off (No filter)").classes("font-bold text-emerald-400 font-mono")
                        ui.button(
                            "🏛️ Real Inst Flow Only",
                            on_click=lambda: (
                                state.update({"real_inst_flow_only": not state.get("real_inst_flow_only", False)}),
                                render_matrix(),
                            ),
                        ).props("dense size=xs").classes(
                            "font-mono font-bold px-2 py-0.5 rounded transition-all " +
                            ("bg-emerald-600 text-white shadow" if state.get("real_inst_flow_only") else "bg-slate-800 text-slate-400 border border-slate-700 hover:bg-slate-700")
                        )

                render_inline_field_guide_banner(q_key)

            # Candidate Quick Selector Chips
            if not q_df.empty and "symbol" in q_df.columns:
                symbols = [str(s) for s in q_df["symbol"].dropna().tolist()]
                with ui.row().classes("w-full items-center gap-1.5 flex-wrap p-2 rounded bg-[var(--mp-surface-raised)] border border-[var(--mp-border)]"):
                    ui.label("INSPECT:").classes("text-[10px] font-bold text-[var(--mp-muted)] uppercase tracking-wider")
                    for sym in symbols:
                        is_sel = (sym == state["selected_symbol"])
                        deal_str = ""
                        if "deal_flow" in q_df.columns:
                            match_row = q_df[q_df["symbol"] == sym]
                            if not match_row.empty:
                                deal_val = str(match_row["deal_flow"].iloc[0])
                                if deal_val and deal_val != "—":
                                    deal_str = f" {deal_val}"
                        ui.button(
                            f"{sym}{deal_str}",
                            on_click=lambda s=sym: select_symbol(s),
                        ).props("dense unelevated size=sm").classes(
                            "font-mono font-bold text-xs px-2 py-0.5 rounded transition-all " +
                            ("bg-emerald-600 text-white shadow" if is_sel else "bg-slate-800 text-slate-300 hover:bg-slate-700")
                        )

            # Candidates Table
            if q_df.empty:
                with ui.card().classes("w-full mp-card p-8 text-center border border-[var(--mp-border)] bg-[var(--mp-surface)]"):
                    ui.label(f"No {q_info['short_title']} setups currently active in this session.").classes("text-sm text-[var(--mp-muted)]")
            else:
                matrix_cols = display_cols
                if q_key == "darvas" and (darvas_v2_enabled() or _darvas_is_weekly()):
                    squeeze_cols = [
                        "squeeze_pct", "candle_range_pct", "darvas_top",
                        "tightening", "squeeze_age", "failed_low",
                    ]
                    matrix_cols = ["symbol"] + squeeze_cols + [c for c in display_cols if c != "symbol"]
                table_cols = [c for c in matrix_cols if c in q_df.columns]
                tbl = table_from_df(q_df[table_cols], "", pagination=10)
                if tbl is not None:
                    def on_table_click(e):
                        try:
                            args = e.args
                            row = args[1] if isinstance(args, (list, tuple)) and len(args) > 1 else (args if isinstance(args, dict) else {})
                            s = row.get("symbol")
                            if s:
                                select_symbol(str(s))
                        except Exception:
                            pass
                    tbl.on("rowClick", on_table_click)
                    tbl.on("row-click", on_table_click)

    def render_inspector() -> None:
        with inspector_host:
            inspector_host.clear()
            sym = state["selected_symbol"]
            render_stock_inspector_panel(
                Path(db_path),
                sym,
                copy_text=copy_text,
            )

    # Initial render
    render_queue_nav()
    render_matrix()
    render_inspector()

