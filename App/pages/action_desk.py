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
    from App.ui.stock_drawer import open_stock_360_modal, query_stock_candlestick_data
except ModuleNotFoundError:
    from ui.stock_drawer import open_stock_360_modal, query_stock_candlestick_data  # type: ignore

try:
    from App.ui.vcp_chart import render_vcp_ohlc
except ModuleNotFoundError:
    from ui.vcp_chart import render_vcp_ohlc  # type: ignore


def fetch_action_desk_data(db_path: Path | str) -> dict[str, Any]:
    """
    Query and assemble all datasets required for the Action Desk.
    Results are cached in memory for sub-millisecond response on subsequent tab visits.
    """
    key = cache_key(db_path, None, "action_desk_v4")
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

        # India VIX
        vix_res = con.execute(
            "SELECT close_price FROM index_daily WHERE trade_date = ? AND index_name = 'India VIX'",
            [trade_date],
        ).fetchone()
        vix_val = round(vix_res[0], 2) if vix_res and vix_res[0] else 11.3

        # Exposure Decision Logic (Minervini / O'Neil Progressive Exposure)
        if adv_pct >= 58.0 and ab20_pct >= 48.0 and ab200_pct >= 45.0 and vix_val < 16.0:
            exposure_pct = "75% - 100%"
            exposure_state = "Aggressive / Full Trend"
            exposure_badge = "mp-badge-good"
            exposure_guidance = "Broad market participation is strong. Deploy normal swing size (10-15% per position), use 3-5% stops, and let winning leaders compound."
        elif adv_pct >= 45.0 and ab20_pct >= 38.0 and vix_val < 18.0:
            exposure_pct = "50% - 75%"
            exposure_state = "Constructive / Selective"
            exposure_badge = "mp-badge-good"
            exposure_guidance = "Market is constructive but selective. Focus strictly on top relative strength leaders in leading sectors. Maintain normal 3-5% stops."
        elif adv_pct >= 35.0 and vix_val < 22.0:
            exposure_pct = "25% - 50%"
            exposure_state = "Selective / Caution"
            exposure_badge = "mp-badge-warn"
            exposure_guidance = "Diverging market breadth. Cut position size in half, take quick partial profits at 2R to 3R, and trail stops tightly."
        else:
            exposure_pct = "0% - 15%"
            exposure_state = "Risk-Off / Defensive"
            exposure_badge = "mp-badge-bad"
            exposure_guidance = "Net distribution and breadth breakdown. Protect capital in cash. Do not force new breakout buys until breadth recovers above 20 EMA."

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

        # 4. Strict Quality Filtered Pool for Setups
        setup_pool = con.execute(
            """
            WITH pool AS (
                SELECT 
                    i.trade_date,
                    i.symbol,
                    m.security_name,
                    m.sector,
                    m.industry,
                    m.market_cap_cr,
                    COALESCE(m.band, 20.0) AS band,
                    i.close_price AS cmp,
                    (i.close_price / i.prev_close - 1.0) * 100 AS day_pct,
                    i.return_5d_pct,
                    i.return_1m_pct,
                    i.away_52w_high_pct,
                    i.rs_percentile,
                    i.rvol,
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
                    COALESCE(i.avg_traded_value_cr_20d, i.turnover_cr) AS to_cr
                FROM indicators_daily i
                JOIN stocks_master m ON m.symbol = i.symbol
                WHERE i.trade_date = ?
                  AND m.market_cap_cr >= 1000.0
                  AND COALESCE(m.band, 20.0) > 5.0
                  AND i.close_price > i.ema_200
                  AND i.ema_50 > i.ema_200
                  AND i.away_52w_high_pct >= -25.0
                  AND i.symbol NOT LIKE '%-RE' AND i.symbol NOT LIKE '%_RE'
                  AND COALESCE(i.avg_traded_value_cr_20d, i.turnover_cr) >= 5.0
                  AND i.rs_percentile >= 70.0
                  AND COALESCE(m.band_remarks, '') NOT LIKE '%GSM%'
                  AND COALESCE(m.band_remarks, '') NOT LIKE '%STAGE 2%'
            )
            SELECT * FROM pool
            """,
            [trade_date],
        ).fetchdf()

        # Attach macro theme tags to setup pool
        user_db_path = Path(db_path).parent / "marketpulse_user.duckdb"
        stock_tags = get_stock_thematic_tags(str(user_db_path))
        if not setup_pool.empty:
            setup_pool["theme"] = setup_pool["symbol"].map(lambda s: stock_tags.get(s, ["—"])[0])
        else:
            setup_pool["theme"] = pd.Series(dtype=str)

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
                SELECT i.symbol, i.trade_date, i.open_price, i.high_price, i.low_price, i.close_price, i.ema_10
                FROM indicators_daily i
                JOIN pool_syms_tbl p ON i.symbol = p.symbol
                JOIN dates d ON i.trade_date = d.trade_date
                ORDER BY i.symbol, i.trade_date ASC
                """
            ).fetchdf()

    # Classify the 5 Setup Queues
    # -------------------------------------------------------------
    # Queue 1: VCP / Coiling Base Breakout
    # -------------------------------------------------------------
    vcp_df = setup_pool.copy()
    vcp_df["trigger_price"] = vcp_df["high_20d"].round(2)
    vcp_df["stop_loss"] = vcp_df[["ema_20", "low_10d"]].max(axis=1).round(2)
    vcp_df["dist_to_trigger_pct"] = ((vcp_df["trigger_price"] / vcp_df["cmp"] - 1.0) * 100).round(2)
    vcp_df["risk_pct"] = ((vcp_df["trigger_price"] / vcp_df["stop_loss"] - 1.0) * 100).round(2)
    vcp_df = vcp_df[
        (vcp_df["dist_to_trigger_pct"].between(0.0, 3.5))
        & (vcp_df["risk_pct"] > 0)
        & (vcp_df["risk_pct"] <= 6.0)
    ].sort_values(["rs_percentile", "dist_to_trigger_pct"], ascending=[False, True]).head(10)
    vcp_df["setup_type"] = "VCP Breakout"
    vcp_df["why_now"] = "Coiling <3.5% below 20D pivot with tight <6% invalidation"

    # -------------------------------------------------------------
    # Queue 2: 10/20 EMA Pullback (Continuation)
    # -------------------------------------------------------------
    pb_df = setup_pool.copy()
    pb_df["trigger_price"] = (pb_df["cmp"] * 1.01).round(2)  # Trigger on breaking above previous bar
    pb_df["stop_loss"] = (pb_df["ema_20"] * 0.985).round(2)  # Stop just under 20 EMA
    pb_df["risk_pct"] = ((pb_df["cmp"] / pb_df["stop_loss"] - 1.0) * 100).round(2)
    pb_df = pb_df[
        ((pb_df["away_10ema_pct"].abs() <= 2.2) | (pb_df["away_20ema_pct"].abs() <= 2.2))
        & (pb_df["away_52w_high_pct"].between(-18.0, -2.5))
        & (pb_df["risk_pct"] > 0)
        & (pb_df["risk_pct"] <= 5.5)
    ].sort_values("rs_percentile", ascending=False).head(10)
    pb_df["setup_type"] = "EMA Pullback"
    pb_df["why_now"] = "Orderly rest on 10/20 EMA support in confirmed uptrend"

    # -------------------------------------------------------------
    # Queue 3: High RVOL Episodic Pivot
    # -------------------------------------------------------------
    ep_df = setup_pool.copy()
    ep_df["trigger_price"] = ep_df["high_price"].round(2)
    ep_df["stop_loss"] = ep_df["low_price"].round(2)
    ep_df["risk_pct"] = ((ep_df["cmp"] / ep_df["stop_loss"] - 1.0) * 100).round(2)
    ep_df = ep_df[
        (ep_df["rvol"] >= 2.0)
        & (ep_df["day_pct"] >= 2.5)
        & (ep_df["risk_pct"] > 0)
        & (ep_df["risk_pct"] <= 6.0)
    ].sort_values(["rvol", "day_pct"], ascending=[False, False]).head(10)
    ep_df["setup_type"] = "Episodic Pivot"
    ep_df["why_now"] = "Explosive 2x+ RVOL surge out of base with tight day-low stop"

    # -------------------------------------------------------------
    # Queue 4: 52-Week High Breakout
    # -------------------------------------------------------------
    h52_df = setup_pool.copy()
    h52_df["trigger_price"] = (h52_df["cmp"] * 1.005).round(2)
    h52_df["stop_loss"] = h52_df[["ema_20", "low_10d"]].max(axis=1).round(2)
    h52_df["risk_pct"] = ((h52_df["cmp"] / h52_df["stop_loss"] - 1.0) * 100).round(2)
    h52_df = h52_df[
        (h52_df["away_52w_high_pct"] >= -2.0)
        & (h52_df["rvol"] >= 1.2)
        & (h52_df["risk_pct"] > 0)
        & (h52_df["risk_pct"] <= 6.0)
    ].sort_values(["rs_percentile", "rvol"], ascending=[False, False]).head(10)
    h52_df["setup_type"] = "52W High Breakout"
    h52_df["why_now"] = "Printing fresh 52-week high with volume thrust and leadership RS"

    # -------------------------------------------------------------
    # Queue 5: Darvas Box & 10 EMA Squeeze (OHLC Inside Box in Near Range)
    # -------------------------------------------------------------
    darvas_candidates = []
    if not setup_pool.empty and not darvas_hist.empty:
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
            if is_darvas_10ema_squeeze(
                last_c,
                last_top,
                last_btm,
                last_ema10,
                high=last_h,
                low=last_l,
                open_price=last_o,
                max_squeeze_pct=3.5,
                max_candle_range_pct=3.5,
                require_ohlc_inside=True,
            ):
                sq_pct = round(((last_top - last_ema10) / last_top) * 100.0, 2)
                cr_pct = round(((last_h - last_l) / last_c) * 100.0, 2) if last_c > 0 else 0.0
                darvas_candidates.append({
                    "symbol": sym,
                    "darvas_top": round(last_top, 2),
                    "darvas_bottom": round(last_btm, 2),
                    "squeeze_pct": sq_pct,
                    "candle_range_pct": cr_pct,
                })

    if darvas_candidates:
        darvas_cand_df = pd.DataFrame(darvas_candidates)
        darvas_df = setup_pool.merge(darvas_cand_df, on="symbol", how="inner")
        darvas_df["trigger_price"] = darvas_df["darvas_top"]
        darvas_df["stop_loss"] = (darvas_df["ema_10"] * 0.985).round(2)
        darvas_df["risk_pct"] = ((darvas_df["trigger_price"] / darvas_df["stop_loss"] - 1.0) * 100.0).round(2)
        darvas_df["setup_type"] = "Darvas 10 EMA Squeeze"
        darvas_df["why_now"] = [
            f"OHLC inside box · Squeezed {sq:.1f}% (Range {cr:.1f}%) near Green Line ₹{top:,.1f}"
            for sq, cr, top in zip(darvas_df["squeeze_pct"], darvas_df["candle_range_pct"], darvas_df["darvas_top"])
        ]
        darvas_df = darvas_df[
            (darvas_df["risk_pct"] > 0) & (darvas_df["risk_pct"] <= 6.0)
        ].sort_values(["squeeze_pct", "candle_range_pct", "rs_percentile"], ascending=[True, True, False]).head(15)
    else:
        darvas_df = pd.DataFrame()

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
            "total_stocks": total_stocks,
        },
        "themes": top_sectors,
        "queues": {
            "vcp": vcp_df,
            "pullback": pb_df,
            "episodic": ep_df,
            "high52": h52_df,
            "darvas": darvas_df,
        },
        "tv_lists": {
            "vcp": to_tv_list(vcp_df["symbol"].tolist()) if not vcp_df.empty else "",
            "pullback": to_tv_list(pb_df["symbol"].tolist()) if not pb_df.empty else "",
            "episodic": to_tv_list(ep_df["symbol"].tolist()) if not ep_df.empty else "",
            "high52": to_tv_list(h52_df["symbol"].tolist()) if not h52_df.empty else "",
            "darvas": to_tv_list(darvas_df["symbol"].tolist()) if not darvas_df.empty else "",
            "all_focus": to_tv_list(
                list(dict.fromkeys(
                    vcp_df["symbol"].tolist()
                    + pb_df["symbol"].tolist()
                    + ep_df["symbol"].tolist()
                    + h52_df["symbol"].tolist()
                    + darvas_df["symbol"].tolist()
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
    """Build the Action Desk view inside NiceGUI."""
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
    if top_themes or bottom_themes:
        with ui.row().classes("w-full items-center justify-between px-3 py-2 rounded bg-[var(--mp-surface-raised)] border border-[var(--mp-border)] mb-3 flex-wrap gap-2 text-xs"):
            with ui.row().classes("items-center gap-2 flex-wrap"):
                ui.label("🔥 TOP MACRO THEMES:").classes("font-bold text-emerald-400 tracking-wider")
                for item in top_themes:
                    ui.label(f"{item['name']} ({item['return_1d']:+.2f}%)").classes("font-semibold text-emerald-300 bg-emerald-950/80 px-2 py-0.5 rounded border border-emerald-500/30")
            with ui.row().classes("items-center gap-2 flex-wrap"):
                ui.label("❄️ LAGGING THEMES:").classes("font-bold text-rose-400 tracking-wider")
                for item in bottom_themes:
                    ui.label(f"{item['name']} ({item['return_1d']:+.2f}%)").classes("font-semibold text-rose-300 bg-rose-950/80 px-2 py-0.5 rounded border border-rose-500/30")

    # =========================================================================
    # STEP 1: MARKET EXPOSURE GATE (Executive Decision)
    # =========================================================================
    with ui.card().classes("w-full mp-card p-4 border border-[var(--mp-border)] bg-[var(--mp-surface)] mb-4"):
        with ui.row().classes("w-full items-center justify-between flex-wrap gap-2"):
            with ui.row().classes("items-center gap-2"):
                ui.label("STEP 1: MARKET EXPOSURE GATE").classes("text-xs font-bold tracking-wider text-[var(--mp-primary)] uppercase")
                ui.label(f"Data: {data['trade_date']}").classes("text-xs text-[var(--mp-muted)]")
            with ui.row().classes("items-center gap-2"):
                ui.label("RECOMMENDED EXPOSURE:").classes("text-xs text-[var(--mp-muted)] font-semibold")
                ui.label(exp["pct"]).classes(f"text-base font-black px-2.5 py-0.5 rounded {exp['badge']}")
                ui.label(exp["state"]).classes("text-xs font-medium text-[var(--mp-text)]")

        ui.label(exp["guidance"]).classes("text-sm text-[var(--mp-text)] mt-2 leading-relaxed font-mono")

        # Breadth Strip
        with ui.row().classes("w-full items-center gap-6 mt-3 pt-3 border-t border-[var(--mp-border)] flex-wrap text-xs"):
            with ui.row().classes("items-center gap-1.5"):
                ui.label("Net Advance:").classes("text-[var(--mp-muted)]")
                ui.label(f"{exp['adv_pct']}%").classes("font-bold " + ("text-emerald-400" if exp['adv_pct'] >= 50 else "text-rose-400"))
            with ui.row().classes("items-center gap-1.5"):
                ui.label("Above 20 EMA:").classes("text-[var(--mp-muted)]")
                ui.label(f"{exp['ab20_pct']}%").classes("font-bold text-[var(--mp-text)]")
            with ui.row().classes("items-center gap-1.5"):
                ui.label("Above 50 EMA:").classes("text-[var(--mp-muted)]")
                ui.label(f"{exp['ab50_pct']}%").classes("font-bold text-[var(--mp-text)]")
            with ui.row().classes("items-center gap-1.5"):
                ui.label("Above 200 EMA:").classes("text-[var(--mp-muted)]")
                ui.label(f"{exp['ab200_pct']}%").classes("font-bold text-[var(--mp-text)]")
            with ui.row().classes("items-center gap-1.5"):
                ui.label("India VIX:").classes("text-[var(--mp-muted)]")
                ui.label(f"{exp['vix']}").classes("font-bold " + ("text-emerald-400" if exp['vix'] < 15 else "text-amber-400"))
            with ui.row().classes("items-center gap-1.5 ml-auto"):
                if copy_text and tv["all_focus"]:
                    ui.button(
                        "📋 Copy All Action Setups (TradingView)",
                        on_click=lambda: copy_text(tv["all_focus"]),
                    ).classes("mp-button text-xs").props("dense outline")

    # =========================================================================
    # STEP 2: LEADING SECTOR THEMES (Institutional Money Flow)
    # =========================================================================
    with ui.column().classes("w-full mb-4"):
        ui.label("STEP 2: LEADING SECTOR THEMES (Top Institutional Money Flow)").classes("text-xs font-bold tracking-wider text-[var(--mp-primary)] uppercase mb-2")
        with ui.grid(columns=len(themes) if len(themes) <= 4 else 4).classes("w-full gap-3"):
            for idx, (_, sec) in enumerate(themes.iterrows(), 1):
                with ui.card().classes("mp-card p-3 border border-[var(--mp-border)] bg-[var(--mp-surface-raised)] flex-col justify-between"):
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label(f"#{idx} {sec['sector']}").classes("font-bold text-sm text-[var(--mp-text)] truncate")
                        sign = "+" if sec["avg_5d_pct"] >= 0 else ""
                        ui.label(f"{sign}{sec['avg_5d_pct']:.1f}% 5D").classes(
                            "text-xs font-bold " + ("text-emerald-400" if sec["avg_5d_pct"] >= 0 else "text-rose-400")
                        )
                    with ui.row().classes("w-full items-center justify-between text-xs text-[var(--mp-muted)] mt-2"):
                        ui.label(f"RS: {sec['avg_rs']:.0f}")
                        ui.label(f">50 EMA: {sec['above_50_pct']:.0f}%")
                        ui.label(f"₹{sec['total_to_cr']:,.0f} Cr")
                    if sec.get("leaders"):
                        top_syms = [s.strip() for s in sec["leaders"].split(",")][:3]
                        with ui.row().classes("w-full items-center gap-1 mt-2"):
                            ui.label("Leaders:").classes("text-[10px] text-[var(--mp-muted)]")
                            for sym in top_syms:
                                ui.label(sym).classes("text-[11px] font-mono font-bold text-[var(--mp-primary)]")

    # =========================================================================
    # STEP 3: THE 5 ACTIONABLE SETUP QUEUES
    # =========================================================================
    ui.label("STEP 3: ACTIONABLE SWING SETUPS (Tight Risk <= 6%, Strict Quality Filters)").classes("text-xs font-bold tracking-wider text-[var(--mp-primary)] uppercase mb-2")

    # Filter quality banner
    with ui.row().classes("w-full items-center justify-between px-3 py-1.5 rounded bg-[var(--mp-surface-raised)] border border-[var(--mp-border)] text-xs text-[var(--mp-muted)] mb-3 flex-wrap gap-2"):
        ui.label("✓ Quality Rules Applied: MCap > ₹1000Cr · No 5% Circuit Band · > 200 EMA · 50>200 EMA · Within 25% 52W · 20D T/O > ₹5Cr · RS >= 70 · No _RE").classes("font-mono")
        ui.label("Max Risk Ceiling: 6.0%").classes("font-bold text-emerald-400 font-mono")

    # Display columns for the setups table
    display_cols = [
        "symbol", "theme", "cmp", "trigger_price", "stop_loss", "risk_pct", 
        "day_pct", "rvol", "rs_percentile", "sector", "why_now"
    ]

    with ui.tabs().classes("w-full mp-tabs mb-2") as setup_tabs:
        t_vcp = ui.tab("1. VCP / Coiling Breakouts")
        t_pb = ui.tab("2. 10/20 EMA Pullbacks")
        t_ep = ui.tab("3. Episodic Pivots (High RVOL)")
        t_h52 = ui.tab("4. 52W High Breakouts")
        t_darvas = ui.tab("5. Darvas 10 EMA Squeeze")

    chart_slots: dict[Any, Any] = {}
    chart_built: dict[Any, bool] = {}

    with ui.tab_panels(setup_tabs, value=t_vcp).classes("w-full bg-transparent p-0"):
        # PANEL 1: VCP Breakout
        with ui.tab_panel(t_vcp).classes("p-0"):
            with ui.row().classes("w-full items-center justify-between my-2"):
                ui.label("Low-volatility contractions coiled <3.5% below 20D pivot with dry-up volume.").classes("text-xs text-[var(--mp-muted)]")
                if copy_text and tv["vcp"]:
                    ui.button("📋 Copy VCP Setups (TV)", on_click=lambda: copy_text(tv["vcp"])).classes("mp-button text-xs").props("dense outline")
            df = queues["vcp"]
            if df.empty:
                ui.label("No VCP setups currently meeting strict <=6% risk criteria.").classes("text-sm text-[var(--mp-muted)] p-4")
            else:
                table_from_df(df[[c for c in display_cols if c in df.columns]], "", pagination=10)
                chart_slots[t_vcp] = ui.column().classes("w-full")

        # PANEL 2: EMA Pullback
        with ui.tab_panel(t_pb).classes("p-0"):
            with ui.row().classes("w-full items-center justify-between my-2"):
                ui.label("High-RS trend leaders resting on 10/20 EMA support with low pullback volume.").classes("text-xs text-[var(--mp-muted)]")
                if copy_text and tv["pullback"]:
                    ui.button("📋 Copy Pullback Setups (TV)", on_click=lambda: copy_text(tv["pullback"])).classes("mp-button text-xs").props("dense outline")
            df = queues["pullback"]
            if df.empty:
                ui.label("No EMA pullback setups currently meeting criteria.").classes("text-sm text-[var(--mp-muted)] p-4")
            else:
                table_from_df(df[[c for c in display_cols if c in df.columns]], "", pagination=10)
                chart_slots[t_pb] = ui.column().classes("w-full")

        # PANEL 3: Episodic Pivot
        with ui.tab_panel(t_ep).classes("p-0"):
            with ui.row().classes("w-full items-center justify-between my-2"):
                ui.label("High RVOL (2x+) explosive breakout surges with day-low invalidation.").classes("text-xs text-[var(--mp-muted)]")
                if copy_text and tv["episodic"]:
                    ui.button("📋 Copy Episodic Pivots (TV)", on_click=lambda: copy_text(tv["episodic"])).classes("mp-button text-xs").props("dense outline")
            df = queues["episodic"]
            if df.empty:
                ui.label("No high RVOL episodic pivots recorded today.").classes("text-sm text-[var(--mp-muted)] p-4")
            else:
                table_from_df(df[[c for c in display_cols if c in df.columns]], "", pagination=10)
                chart_slots[t_ep] = ui.column().classes("w-full")

        # PANEL 4: 52W Breakout
        with ui.tab_panel(t_h52).classes("p-0"):
            with ui.row().classes("w-full items-center justify-between my-2"):
                ui.label("Market leaders testing or printing new 52-week highs with volume thrust.").classes("text-xs text-[var(--mp-muted)]")
                if copy_text and tv["high52"]:
                    ui.button("📋 Copy 52W Breakouts (TV)", on_click=lambda: copy_text(tv["high52"])).classes("mp-button text-xs").props("dense outline")
            df = queues["high52"]
            if df.empty:
                ui.label("No 52-week high breakouts meeting criteria.").classes("text-sm text-[var(--mp-muted)] p-4")
            else:
                table_from_df(df[[c for c in display_cols if c in df.columns]], "", pagination=10)
                chart_slots[t_h52] = ui.column().classes("w-full")

        # PANEL 5: Darvas 10 EMA Squeeze
        with ui.tab_panel(t_darvas).classes("p-0"):
            with ui.row().classes("w-full items-center justify-between my-2"):
                ui.label("Stocks with full OHLC strictly inside the box in near range, squeezed between Green Line (TopBox) and rising 10 EMA (spread <= 3.5%).").classes("text-xs text-[var(--mp-muted)]")
                if copy_text and tv.get("darvas"):
                    ui.button("📋 Copy Darvas Squeeze Setups (TV)", on_click=lambda: copy_text(tv["darvas"])).classes("mp-button text-xs").props("dense outline")
            df = queues.get("darvas", pd.DataFrame())
            if df.empty:
                ui.label("No Darvas 10 EMA squeeze setups currently meeting criteria.").classes("text-sm text-[var(--mp-muted)] p-4")
            else:
                table_from_df(df[[c for c in display_cols if c in df.columns]], "", pagination=10)
                chart_slots[t_darvas] = ui.column().classes("w-full")

    queue_builders = {
        t_vcp: lambda: render_queue_chart_preview(db_path, queues["vcp"], "VCP / Coiling Breakouts", is_vcp=True, copy_text=copy_text),
        t_pb: lambda: render_queue_chart_preview(db_path, queues["pullback"], "10/20 EMA Pullbacks", is_darvas=False, copy_text=copy_text),
        t_ep: lambda: render_queue_chart_preview(db_path, queues["episodic"], "Episodic Pivots (High RVOL)", is_darvas=False, copy_text=copy_text),
        t_h52: lambda: render_queue_chart_preview(db_path, queues["high52"], "52W High Breakouts", is_darvas=False, copy_text=copy_text),
        t_darvas: lambda: render_queue_chart_preview(db_path, queues.get("darvas", pd.DataFrame()), "Darvas 10 EMA Squeeze", is_darvas=True, copy_text=copy_text),
    }

    def ensure_tab_chart(target_val: Any) -> None:
        for t_key, builder_fn in queue_builders.items():
            t_label = getattr(t_key, "label", None)
            if (
                target_val is t_key
                or target_val == t_key
                or target_val == t_label
                or str(target_val) == str(t_label)
                or (t_label and str(t_label) in str(target_val))
            ):
                if not chart_built.get(t_key):
                    chart_built[t_key] = True
                    slot = chart_slots.get(t_key)
                    if slot:
                        with slot:
                            builder_fn()

    setup_tabs.on_value_change(lambda e: ensure_tab_chart(e.value))
    ensure_tab_chart(t_vcp)
