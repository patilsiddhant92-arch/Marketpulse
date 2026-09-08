"""
Action Desk: Executive Swing Trading Command Center.
Provides a 3-step actionable workflow:
1. Market Exposure Gate (Recommended Exposure % and Stop Discipline)
2. Leading Sector Themes (Institutional Money Flow)
3. The 5 Actionable Setup Queues (VCP Breakout, EMA Pullback, Episodic Pivot, 52W Breakout, Darvas 10 EMA Squeeze)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import duckdb
import numpy as np
import pandas as pd
from nicegui import ui

from App.cache_manager import get_cached, set_cached, cache_key
from App.indicators.darvas import calculate_darvas_box, is_darvas_10ema_squeeze
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


def resolve_india_vix(con: duckdb.DuckDBPyConnection, trade_date: Any) -> tuple[float | None, float]:
    """Load India VIX for the session. Missing row is (None, 0.0) — never a silent 11.3."""
    try:
        vix_res = con.execute(
            """
            SELECT close_price,
                   (close_price / nullif(prev_close, 0) - 1.0) * 100 AS vix_1d_pct
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
    """Four live exposure branches. VIX n/a skips every vix-threshold branch."""
    vix_available = vix is not None
    vix_spike = bool(vix_available and vix_1d_pct >= 10.0)

    if (
        adv_pct >= 58.0
        and ab20_pct >= 48.0
        and ab200_pct >= 45.0
        and vix_available
        and vix < 15.0
        and not vix_spike
        and not net_lows_expanding
    ):
        exposure_pct = "75% - 100%"
        exposure_state = "Aggressive / Full Trend"
        exposure_badge = "mp-badge-good"
        exposure_guidance = "Broad market participation is strong and volatility is low (<15 VIX). Deploy normal swing size (10-15% per position), use 3-5% stops, and let winning leaders compound."
    elif (
        adv_pct >= 45.0
        and ab20_pct >= 38.0
        and vix_available
        and vix < 18.0
        and not (vix_spike and net_lows_expanding)
    ):
        exposure_pct = "50% - 75%"
        exposure_state = "Constructive / Selective"
        exposure_badge = "mp-badge-good"
        exposure_guidance = "Market is constructive but selective. Focus strictly on top relative strength leaders in leading sectors. Maintain normal 3-5% stops."
    elif adv_pct >= 35.0 and vix_available and vix < 22.0:
        exposure_pct = "25% - 50%"
        exposure_state = "Selective / Caution"
        exposure_badge = "mp-badge-warn"
        if net_lows_expanding:
            exposure_guidance = f"Net 52W Lows expanding ({count_52w_lows} lows vs {count_52w_highs} highs). Cut position sizes in half, take quick 2R profits, and trail stops tightly."
        elif vix_spike:
            exposure_guidance = f"VIX surge of +{vix_1d_pct:.1f}% indicates sudden volatility expansion. Avoid chasing breakouts; wait for calm base resets."
        else:
            exposure_guidance = "Diverging market breadth. Cut position size in half, take quick partial profits at 2R to 3R, and trail stops tightly."
    else:
        exposure_pct = "0% - 15%"
        exposure_state = "Risk-Off / Defensive"
        exposure_badge = "mp-badge-bad"
        exposure_guidance = "Net distribution, breadth breakdown, or high volatility. Protect capital in cash. Do not force new breakout buys until breadth recovers above 20 EMA."

    return {
        "pct": exposure_pct,
        "state": exposure_state,
        "badge": exposure_badge,
        "guidance": exposure_guidance,
        "vix": vix,
        "vix_1d_pct": vix_1d_pct,
        "vix_available": vix_available,
        "vix_label": "VIX n/a" if not vix_available else f"{vix}",
        "vix_spike": vix_spike,
    }


def fetch_action_desk_data(db_path: Path | str) -> dict[str, Any]:
    """
    Query and assemble all datasets required for the Action Desk.
    Results are cached in memory for sub-millisecond response on subsequent tab visits.
    """
    key = cache_key(db_path, None, "action_desk_v9")
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

        # 2. Market Breadth & Exposure Gate
        breadth_row = con.execute(
            """
            SELECT 
                count(*) AS total_stocks,
                avg(CASE WHEN close_price > prev_close THEN 1.0 ELSE 0.0 END) * 100 AS advance_pct,
                avg(CASE WHEN close_price > ema_20 THEN 1.0 ELSE 0.0 END) * 100 AS above_20ema_pct,
                avg(CASE WHEN close_price > ema_50 THEN 1.0 ELSE 0.0 END) * 100 AS above_50ema_pct,
                avg(CASE WHEN close_price > ema_200 THEN 1.0 ELSE 0.0 END) * 100 AS above_200ema_pct
            FROM indicators_daily
            WHERE trade_date = ?
            """,
            [trade_date],
        ).fetchone()

        total_stocks = breadth_row[0] or 2400
        adv_pct = round(breadth_row[1] or 50.0, 1)
        ab20_pct = round(breadth_row[2] or 50.0, 1)
        ab50_pct = round(breadth_row[3] or 50.0, 1)
        ab200_pct = round(breadth_row[4] or 50.0, 1)

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

        # 3. Top Leading Themes (Sector Money Flow)
        top_sectors = con.execute(
            """
            WITH sec_stats AS (
                SELECT 
                    m.sector,
                    count(DISTINCT i.symbol) AS stock_count,
                    avg(i.rs_percentile) AS avg_rs,
                    avg(i.return_5d_pct) AS avg_5d_pct,
                    sum(i.turnover_cr) AS total_to_cr,
                    avg(CASE WHEN i.close_price > i.ema_50 THEN 1.0 ELSE 0.0 END) * 100 AS above_50_pct
                FROM indicators_daily i
                JOIN stocks_master m ON m.symbol = i.symbol
                WHERE i.trade_date = ? AND m.sector IS NOT NULL AND m.sector != ''
                GROUP BY m.sector
            ),
            leaders AS (
                SELECT 
                    m.sector,
                    string_agg(i.symbol, ', ' ORDER BY i.rs_percentile DESC) AS leader_symbols
                FROM indicators_daily i
                JOIN stocks_master m ON m.symbol = i.symbol
                WHERE i.trade_date = ? AND i.rs_percentile >= 80
                GROUP BY m.sector
            )
            SELECT s.*, coalesce(l.leader_symbols, '') AS leaders
            FROM sec_stats s
            LEFT JOIN leaders l ON l.sector = s.sector
            ORDER BY s.avg_rs DESC, s.avg_5d_pct DESC
            LIMIT 4
            """,
            [trade_date, trade_date],
        ).fetchdf()

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
                  AND m.market_cap_cr >= 1000.0
                  AND COALESCE(m.band, 20.0) > 5.0
                  AND i.symbol NOT LIKE '%-RE' AND i.symbol NOT LIKE '%_RE'
                  AND COALESCE(i.avg_traded_value_cr_20d, i.turnover_cr) >= 3.0
                  AND COALESCE(m.band_remarks, '') NOT LIKE '%GSM%'
                  AND COALESCE(m.band_remarks, '') NOT LIKE '%STAGE 2%'
            )
            SELECT * FROM pool
            """,
            [trade_date],
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

        # Trailing bars for Darvas Box calculation across setup pool
        darvas_hist = pd.DataFrame()
        if not setup_pool.empty:
            pool_symbols = setup_pool["symbol"].tolist()
            con.register("pool_syms_tbl", pd.DataFrame({"symbol": pool_symbols}))
            darvas_hist = con.execute(
                """
                WITH dates AS (
                    SELECT DISTINCT trade_date 
                    FROM indicators_daily 
                    ORDER BY trade_date DESC 
                    LIMIT 45
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
    # Queue 1: VCP / Coiling Base Breakout
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
        ].sort_values(["rs_percentile", "dist_to_trigger_pct"], ascending=[False, True]).head(15)
        vcp_df["setup_type"] = "VCP Breakout"
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
        ].sort_values("rs_percentile", ascending=False).head(15)
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
        ].sort_values(["rvol", "day_pct"], ascending=[False, False]).head(15)
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
        ].sort_values(["rs_percentile", "rvol"], ascending=[False, False]).head(15)
        h52_df["setup_type"] = "52W High Breakout"
        h52_df["why_now"] = "Printing fresh 52-week high with volume thrust and leadership RS"

    # -------------------------------------------------------------
    # Queue 5: Darvas Box & 10/20 EMA Squeeze (Decoupled from RS)
    # Squeeze into top box and 10 EMA / 20 EMA
    # -------------------------------------------------------------
    darvas_candidates = []
    if not darvas_hist.empty:
        for sym, group in darvas_hist.groupby("symbol"):
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
            last_ema20 = float(group["ema_20"].iloc[-1]) if "ema_20" in group.columns and pd.notna(group["ema_20"].iloc[-1]) else None
            if is_darvas_10ema_squeeze(
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
                darvas_candidates.append({
                    "symbol": sym,
                    "darvas_top": round(last_top, 2),
                    "darvas_bottom": round(last_btm, 2),
                    "squeeze_pct": sq_pct,
                    "candle_range_pct": cr_pct,
                })

    if darvas_candidates and not setup_pool.empty:
        darvas_cand_df = pd.DataFrame(darvas_candidates)
        darvas_df = setup_pool.merge(darvas_cand_df, on="symbol", how="inner")
        darvas_df["trigger_price"] = darvas_df["darvas_top"]
        darvas_df["stop_loss"] = (darvas_df["ema_10"] * 0.985).round(2)
        darvas_df["risk_pct"] = ((darvas_df["trigger_price"] / darvas_df["stop_loss"] - 1.0) * 100.0).round(2)
        darvas_df["setup_type"] = "Darvas Squeeze"
        darvas_df["why_now"] = [
            f"OHLC inside box · Squeezed {sq:.1f}% (Range {cr:.1f}%) into Green Line ₹{top:,.1f}"
            for sq, cr, top in zip(darvas_df["squeeze_pct"], darvas_df["candle_range_pct"], darvas_df["darvas_top"])
        ]
        darvas_df = darvas_df.sort_values(["squeeze_pct", "candle_range_pct"], ascending=[True, True]).head(150)
    else:
        darvas_df = pd.DataFrame()

    def _is_num(v: Any) -> bool:
        if v is None or v is np.ma.masked:
            return False
        try:
            f = float(v)
            return not (np.isnan(f) or np.isinf(f))
        except Exception:
            return False

    # -------------------------------------------------------------
    # Queue 6: Silent Coil (VDU at 10/20 EMA) — 82% Pre-Move Footprint
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
        sc_df = sc_df.sort_values([sort_col, "delivery_pct"], ascending=[False, False]).head(25)

    # -------------------------------------------------------------
    # Queue 7: Volume Stair-Step (RVOL Escalation) — 71% Pre-Move Footprint
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
        vss_df = vss_df.sort_values([sort_col, "rvol"], ascending=[False, False]).head(25)

    # -------------------------------------------------------------
    # Queue 8: Spike-Pause (Pre-Blast Consolidation) — 56% Pre-Move Footprint
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
        sp_df = sp_df.sort_values([sort_col, "delivery_pct"], ascending=[False, False]).head(25)





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
            "vix": vix_val,
            "vix_1d_pct": vix_1d_pct,
            "vix_available": gate["vix_available"],
            "vix_label": gate["vix_label"],
            "count_52w_highs": count_52w_highs,
            "count_52w_lows": count_52w_lows,
            "net_highs": net_highs,
            "total_stocks": total_stocks,
        },
        "themes": top_sectors,
        "queues": {
            "vcp": vcp_df,
            "pullback": pb_df,
            "episodic": ep_df,
            "high52": h52_df,
            "darvas": darvas_df,
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

    queue_meta = {
        "vcp": {
            "title": "1. VCP / Coiling Breakouts",
            "short_title": "1. VCP Breakouts",
            "desc": "Low-volatility contractions coiled <3.5% below 20D pivot with volume dry-up and tight <6% invalidation.",
            "tv_key": "vcp",
        },
        "pullback": {
            "title": "2. 10/20 EMA Pullbacks",
            "short_title": "2. EMA Pullbacks",
            "desc": "High-RS trend leaders resting orderly on 10/20 EMA support with dry pullback volume.",
            "tv_key": "pullback",
        },
        "episodic": {
            "title": "3. Episodic Pivots (High RVOL)",
            "short_title": "3. Episodic Pivots",
            "desc": "Explosive 2x+ RVOL surges out of base with tight day-low stop invalidation.",
            "tv_key": "episodic",
        },
        "high52": {
            "title": "4. 52W High Breakouts",
            "short_title": "4. 52W Breakouts",
            "desc": "Market leaders printing or testing fresh 52-week highs with volume thrust.",
            "tv_key": "high52",
        },
        "darvas": {
            "title": "5. Darvas 10/20 EMA Squeeze",
            "short_title": "5. Darvas Squeeze",
            "desc": "OHLC strictly inside the box in near range, squeezed into Green Line (TopBox) and rising 10/20 EMA.",
            "tv_key": "darvas",
        },
        "silent_coil": {
            "title": "6. Silent Coil (VDU at 10/20 EMA)",
            "short_title": "6. Silent Coil",
            "desc": "Severe volume dry-up (RVOL ≤ 0.70x) + tight consolidation at 10/20 EMA with high delivery accumulation (82% pre-move signature).",
            "tv_key": "silent_coil",
        },
        "stair_step": {
            "title": "7. Volume Stair-Step (RVOL Escalation)",
            "short_title": "7. Stair-Step",
            "desc": "RVOL expanding day-over-day at 10/20 EMA support before the breakout (71% pre-move signature).",
            "tv_key": "stair_step",
        },
        "spike_pause": {
            "title": "8. Spike-Pause (Pre-Blast Consolidation)",
            "short_title": "8. Spike-Pause",
            "desc": "Prior 2x+ RVOL surge or 10%+ blast followed by low-volume pause resting on 10/20 EMA (Qullamaggie High-Tight Flag).",
            "tv_key": "spike_pause",
        },
    }

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

                # Market Breadth Strip
                with ui.column().classes("w-full gap-1 mt-2 pt-2 border-t border-[var(--mp-border)] text-xs"):
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label("Net Advance:").classes("text-[var(--mp-muted)] text-[11px]")
                        ui.label(f"{exp['adv_pct']}%").classes("font-mono font-bold text-[11px] " + ("text-emerald-400" if exp['adv_pct'] >= 50 else "text-rose-400"))
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label("> 20 EMA:").classes("text-[var(--mp-muted)] text-[11px]")
                        ui.label(f"{exp['ab20_pct']}%").classes("font-mono font-bold text-[11px] text-[var(--mp-text)]")
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label("> 50 EMA:").classes("text-[var(--mp-muted)] text-[11px]")
                        ui.label(f"{exp['ab50_pct']}%").classes("font-mono font-bold text-[11px] text-[var(--mp-text)]")
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label("> 200 EMA:").classes("text-[var(--mp-muted)] text-[11px]")
                        ui.label(f"{exp['ab200_pct']}%").classes("font-mono font-bold text-[11px] text-[var(--mp-text)]")
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label("India VIX:").classes("text-[var(--mp-muted)] text-[11px]")
                        if exp.get("vix") is None:
                            ui.label("VIX n/a").classes("font-mono font-bold text-[11px] text-[var(--mp-muted)]")
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
                with ui.column().classes("w-full gap-2"):
                    for idx, (_, sec) in enumerate(themes.iterrows(), 1):
                        with ui.column().classes("w-full p-2 rounded bg-[var(--mp-surface-raised)] border border-[var(--mp-border)] gap-0.5"):
                            with ui.row().classes("w-full items-center justify-between"):
                                ui.label(f"#{idx} {sec['sector']}").classes("font-bold text-xs text-[var(--mp-text)] truncate")
                                sign = "+" if sec["avg_5d_pct"] >= 0 else ""
                                ui.label(f"{sign}{sec['avg_5d_pct']:.1f}%").classes(
                                    "text-[11px] font-mono font-bold " + ("text-emerald-400" if sec["avg_5d_pct"] >= 0 else "text-rose-400")
                                )
                            with ui.row().classes("w-full items-center justify-between text-[10px] text-[var(--mp-muted)] font-mono"):
                                ui.label(f"RS: {sec['avg_rs']:.0f}")
                                ui.label(f">50: {sec['above_50_pct']:.0f}%")
                                ui.label(f"₹{sec['total_to_cr']:,.0f}Cr")
                            if sec.get("leaders"):
                                top_syms = [s.strip() for s in sec["leaders"].split(",")][:3]
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

    def set_queue(q_key: str) -> None:
        state["active_queue"] = q_key
        q_df = queues.get(q_key, pd.DataFrame())
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
                    q_df = queues.get(q_key, pd.DataFrame())
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
            q_df = queues.get(q_key, pd.DataFrame())
            if state.get("real_inst_flow_only") and not q_df.empty and "deal_flow" in q_df.columns:
                q_df = q_df[q_df["deal_flow"].astype(str).str.strip().ne("—")]
            tv_text = to_tv_list(q_df["symbol"].tolist()) if (not q_df.empty and "symbol" in q_df.columns) else tv.get(q_info["tv_key"], "")

            # Header Banner
            with ui.card().classes("w-full mp-card p-3 border border-[var(--mp-border)] bg-[var(--mp-surface)]"):
                with ui.row().classes("w-full items-center justify-between flex-wrap gap-2"):
                    with ui.column().classes("gap-0.5"):
                        ui.label(q_info["title"]).classes("text-sm font-bold text-[var(--mp-text)]")
                        ui.label(q_info["desc"]).classes("text-xs text-[var(--mp-muted)]")
                    if copy_text and tv_text:
                        ui.button(
                            f"📋 Copy {q_info['short_title']} (TV)",
                            on_click=lambda t=tv_text, lbl=f"{q_info['short_title']} (TV)": copy_text(lbl, t),
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
                table_cols = [c for c in display_cols if c in q_df.columns]
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

