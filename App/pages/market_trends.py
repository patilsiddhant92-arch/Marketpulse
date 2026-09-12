"""Market Trends & Historical Money Flow Workspace.

Exposes comprehensive multi-month and multi-year historical data from DuckDB:
1. Historical Market Breadth Timeline (Participation > 20/50/200 EMA, Adv/Dec ratio, 52W Highs/Lows)
2. Total Cash Market Turnover & Liquidity Expansion Trend (Trailing 60 sessions + 20D SMA)
3. Benchmark Performance Comparisons (Nifty 50, 500, Midcap 100, Smallcap 100 over 5D, 1M, 3M, 1Y)
4. Consecutive Sector Money Flow Streaks & Turnover Share Heatmap
5. New Money & Sector Rotation Influx Alerts (Fresh institutional buying and emerging sectors)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
import duckdb
import numpy as np
import pandas as pd
from nicegui import ui

from App.cache_manager import cache_key, get_cached, set_cached
from App.market_status import load_market_status, non_actionable_message
from App.ui.stock_drawer import open_stock_360_modal


def query_historical_breadth(db_path: Path, days: int = 180) -> pd.DataFrame:
    """Fetch trailing breadth history from breadth_daily."""
    ckey = cache_key(db_path, "latest", "hist_breadth", days)
    cached = get_cached(ckey)
    if cached is not None:
        return cached

    with duckdb.connect(str(db_path), read_only=True) as db:
        df = db.execute(
            """
            SELECT trade_date, stocks, advancers, decliners, advance_pct,
                   above_10ema_pct, above_20ema_pct, above_50ema_pct, above_200ema_pct,
                   new_20d_highs, near_52w_highs, vcp_candidates, breadth_state
            FROM breadth_daily
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            [days],
        ).fetchdf()

    if not df.empty:
        df = df.iloc[::-1].reset_index(drop=True)
    set_cached(ckey, df)
    return df


def query_market_turnover_trend(db_path: Path, days: int = 60) -> pd.DataFrame:
    """Fetch daily total market cash turnover and 20-day moving average."""
    ckey = cache_key(db_path, "latest", "hist_turnover", days)
    cached = get_cached(ckey)
    if cached is not None:
        return cached

    with duckdb.connect(str(db_path), read_only=True) as db:
        df = db.execute(
            """
            WITH daily_to AS (
                SELECT trade_date,
                       sum(turnover_cr) AS total_turnover_cr,
                       count(DISTINCT symbol) AS active_stocks
                FROM indicators_daily
                GROUP BY trade_date
            ),
            b AS (
                SELECT trade_date, advance_pct, breadth_state
                FROM breadth_daily
            )
            SELECT d.trade_date, d.total_turnover_cr, d.active_stocks,
                   coalesce(b.advance_pct, 50.0) AS advance_pct,
                   coalesce(b.breadth_state, 'Neutral') AS breadth_state
            FROM daily_to d
            LEFT JOIN b ON d.trade_date = b.trade_date
            ORDER BY d.trade_date DESC
            LIMIT ?
            """,
            [days + 25],
        ).fetchdf()

    if not df.empty:
        df = df.iloc[::-1].reset_index(drop=True)
        df["turnover_20d_ma"] = df["total_turnover_cr"].rolling(20, min_periods=5).mean()
        df = df.tail(days).reset_index(drop=True)

    set_cached(ckey, df)
    return df


def query_benchmark_trends(db_path: Path, days: int = 126) -> pd.DataFrame:
    """Fetch historical daily close prices for key market benchmark indices."""
    ckey = cache_key(db_path, "latest", "hist_benchmarks", days)
    cached = get_cached(ckey)
    if cached is not None:
        return cached

    targets = ("Nifty 50", "Nifty 500", "NIFTY MIDCAP 100", "NIFTY SMLCAP 100")
    ph = ", ".join(f"'{t}'" for t in targets)
    with duckdb.connect(str(db_path), read_only=True) as db:
        df = db.execute(
            f"""
            SELECT trade_date, index_name, close_price, return_1d_pct, return_5d_pct, return_20d_pct,
                   distance_ema_50_pct, distance_ema_200_pct, trend_state
            FROM index_daily
            WHERE index_name IN ({ph})
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            [days * len(targets)],
        ).fetchdf()

    if not df.empty:
        df = df.iloc[::-1].reset_index(drop=True)
    set_cached(ckey, df)
    return df


def query_sector_money_flows(db_path: Path, sessions: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch consecutive day money flows and recent 10-session turnover share matrix."""
    ckey = cache_key(db_path, "latest", "hist_sector_flows", sessions)
    cached = get_cached(ckey)
    if cached is not None:
        return cached

    with duckdb.connect(str(db_path), read_only=True) as db:
        dates_df = db.execute(
            """
            SELECT DISTINCT trade_date
            FROM sector_rotation
            WHERE level = 'Sector'
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            [sessions],
        ).fetchdf()

        if dates_df.empty:
            return pd.DataFrame(), pd.DataFrame()

        min_date = dates_df["trade_date"].min()
        sec_df = db.execute(
            """
            SELECT trade_date, group_name, turnover_cr, turnover_share_pct,
                   turnover_share_delta_1d, turnover_share_delta_5d, rotation_rank,
                   rotation_state, leader_symbols
            FROM sector_rotation
            WHERE level = 'Sector' AND trade_date >= ?
            ORDER BY group_name, trade_date ASC
            """,
            [min_date],
        ).fetchdf()

        # Institutional Block Deals accumulation per sector over trailing 10 sessions
        deals_df = db.execute(
            """
            SELECT m.sector as group_name,
                   round(sum(CASE WHEN side = 'BUY' THEN COALESCE(deal_value_cr, quantity * price / 10000000.0) ELSE 0 END), 1) AS buy_cr,
                   round(sum(CASE WHEN side = 'SELL' THEN COALESCE(deal_value_cr, quantity * price / 10000000.0) ELSE 0 END), 1) AS sell_cr,
                   count(*) AS deal_count
            FROM deals d
            JOIN stocks_master m ON d.symbol = m.symbol
            WHERE d.trade_date >= ?
            GROUP BY m.sector
            """,
            [min_date],
        ).fetchdf()

    if sec_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    deal_map = {}
    if not deals_df.empty:
        for _, r in deals_df.iterrows():
            g = str(r["group_name"] or "")
            net = float(r["buy_cr"] or 0) - float(r["sell_cr"] or 0)
            deal_map[g] = {"buy_cr": float(r["buy_cr"] or 0), "net_cr": net, "deals": int(r["deal_count"])}

    # Calculate consecutive inflow streaks per sector
    streaks = []
    for grp, grp_rows in sec_df.groupby("group_name"):
        grp_sorted = grp_rows.sort_values("trade_date").reset_index(drop=True)
        n = len(grp_sorted)
        if n == 0:
            continue

        latest_row = grp_sorted.iloc[-1]
        # Count consecutive days of turnover_share_delta_1d > 0
        streak = 0
        for i in range(n - 1, -1, -1):
            delta = float(grp_sorted.iloc[i].get("turnover_share_delta_1d") or 0.0)
            if delta > 0:
                streak += 1
            else:
                break

        d_info = deal_map.get(grp, {"buy_cr": 0.0, "net_cr": 0.0, "deals": 0})
        share_now = float(latest_row.get("turnover_share_pct") or 0.0)
        delta_5d = float(latest_row.get("turnover_share_delta_5d") or 0.0)
        cum_to = float(grp_sorted["turnover_cr"].sum())
        lead_syms = str(latest_row.get("leader_symbols") or "")

        streaks.append({
            "group_name": grp,
            "streak_days": streak,
            "current_share_pct": share_now,
            "delta_5d_pp": delta_5d,
            "cum_turnover_cr": cum_to,
            "inst_net_cr": d_info["net_cr"],
            "deal_count": d_info["deals"],
            "rotation_state": str(latest_row.get("rotation_state") or "—"),
            "rotation_rank": int(latest_row.get("rotation_rank") or 99),
            "leader_symbols": lead_syms,
        })

    streak_df = pd.DataFrame(streaks).sort_values(["streak_days", "delta_5d_pp"], ascending=[False, False])
    set_cached(ckey, (sec_df, streak_df))
    return sec_df, streak_df


def query_emerging_sector_rotations(db_path: Path) -> pd.DataFrame:
    """Identify sectors receiving fresh capital influx (turnover share expansion, institutional deals, or positive streaks)."""
    _, streak_df = query_sector_money_flows(db_path, sessions=10)
    if streak_df.empty:
        return pd.DataFrame()
    emerging = streak_df[
        (streak_df["delta_5d_pp"] > 0)
        | (streak_df["inst_net_cr"] > 0)
        | (streak_df["streak_days"] >= 2)
    ].copy()
    return emerging


def build_market_trends_page(
    db_path: Path | str,
    *,
    copy_text: Callable[[str, str], None] | None = None,
    on_select_symbol: Callable[[str], None] | None = None,
) -> None:
    """Render the comprehensive Market Trends & Historical Money Flow workspace."""
    db_path = Path(db_path)
    st = load_market_status(db_path, db_path.parent / "status.json")

    # Load core datasets
    breadth_df = query_historical_breadth(db_path, days=180)
    to_df = query_market_turnover_trend(db_path, days=60)
    bench_df = query_benchmark_trends(db_path, days=90)
    sec_df, streak_df = query_sector_money_flows(db_path, sessions=10)

    # Current top-level numbers
    latest_b = breadth_df.iloc[-1].to_dict() if not breadth_df.empty else {}
    latest_to = to_df.iloc[-1].to_dict() if not to_df.empty else {}

    with ui.column().classes("w-full mp-page-research gap-4"):
        # 1. Header & Live Posture Ribbon
        with ui.row().classes("w-full items-center justify-between border-b border-[var(--mp-border)] pb-3 flex-wrap gap-2"):
            with ui.column().classes("gap-0.5"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("history_edu", color="primary").classes("text-2xl")
                    ui.label("Market Trends & Historical Money Flow").classes("text-xl font-bold tracking-tight text-[var(--mp-text)]")
                    ui.label(f"EOD · {st.database_date or 'Live'}").classes("mp-badge mp-neutral text-xs font-mono font-semibold")
                ui.label(
                    "Macro participation timeline, cash liquidity velocity, consecutive sector money flow streaks, and emerging capital radar."
                ).classes("text-xs text-[var(--mp-muted)]")

            with ui.row().classes("items-center gap-3"):
                if not st.actionable:
                    ui.label(non_actionable_message(st)).classes("mp-badge mp-bad text-xs font-semibold")

        # 2. Executive Historical Metric Strip
        with ui.grid(columns=5).classes("w-full gap-3 mp-kpi-grid"):
            # Metric 1: Cash Turnover Today vs 20D MA
            curr_to = float(latest_to.get("total_turnover_cr") or 0.0)
            avg_to = float(latest_to.get("turnover_20d_ma") or curr_to)
            ratio = (curr_to / avg_to) if avg_to > 0 else 1.0
            with ui.card().classes("p-3 mp-card border border-[var(--mp-border)] bg-[var(--mp-surface-raised)]"):
                ui.label("CASH LIQUIDITY TODAY").classes("text-[10px] font-bold text-[var(--mp-muted)] uppercase tracking-wider")
                ui.label(f"₹{curr_to:,.0f}Cr").classes("text-lg font-bold font-mono text-[var(--mp-text)]")
                with ui.row().classes("items-center gap-1.5 text-xs font-mono"):
                    t_color = "text-emerald-400" if ratio >= 1.0 else "text-amber-400"
                    ui.label(f"{ratio:.2f}x vs 20D MA").classes(f"font-bold {t_color}")

            # Metric 2: Market Participation (>50 EMA)
            ab50 = float(latest_b.get("above_50ema_pct") or 0.0)
            ab20 = float(latest_b.get("above_20ema_pct") or 0.0)
            with ui.card().classes("p-3 mp-card border border-[var(--mp-border)] bg-[var(--mp-surface-raised)]"):
                ui.label("BREADTH PARTICIPATION").classes("text-[10px] font-bold text-[var(--mp-muted)] uppercase tracking-wider")
                ui.label(f"{ab50:.1f}%").classes("text-lg font-bold font-mono text-[var(--mp-text)]")
                with ui.row().classes("items-center gap-1.5 text-xs font-mono"):
                    ui.label(f"> 50 EMA · {ab20:.1f}% > 20 EMA").classes("text-[var(--mp-muted)]")

            # Metric 3: Advance / Decline Ratio
            adv = float(latest_b.get("advance_pct") or 50.0)
            with ui.card().classes("p-3 mp-card border border-[var(--mp-border)] bg-[var(--mp-surface-raised)]"):
                ui.label("ADVANCE / DECLINE").classes("text-[10px] font-bold text-[var(--mp-muted)] uppercase tracking-wider")
                ui.label(f"{adv:.1f}% Adv").classes("text-lg font-bold font-mono text-[var(--mp-text)]")
                with ui.row().classes("items-center gap-1.5 text-xs font-mono"):
                    tone = "text-emerald-400" if adv >= 50 else "text-rose-400"
                    ui.label(latest_b.get("breadth_state", "Neutral")).classes(f"font-bold {tone}")

            # Metric 4: Net 52W Highs Count
            near_52w = int(latest_b.get("near_52w_highs") or 0)
            new_20d = int(latest_b.get("new_20d_highs") or 0)
            with ui.card().classes("p-3 mp-card border border-[var(--mp-border)] bg-[var(--mp-surface-raised)]"):
                ui.label("HIGH-WATER MOMENTUM").classes("text-[10px] font-bold text-[var(--mp-muted)] uppercase tracking-wider")
                ui.label(f"{near_52w} Stocks").classes("text-lg font-bold font-mono text-sky-400")
                ui.label(f"{new_20d} fresh 20-day breakout highs").classes("text-[10px] text-[var(--mp-muted)] font-mono")

            # Metric 5: Top Inflow Sector Streak
            top_streak_sec = streak_df.iloc[0] if not streak_df.empty else {}
            stk_name = str(top_streak_sec.get("group_name") or "—")
            stk_days = int(top_streak_sec.get("streak_days") or 0)
            with ui.card().classes("p-3 mp-card border border-[var(--mp-border)] bg-[var(--mp-surface-raised)]"):
                ui.label("TOP INFLOW STREAK").classes("text-[10px] font-bold text-[var(--mp-muted)] uppercase tracking-wider")
                ui.label(f"{stk_days} Days Inflow").classes("text-lg font-bold font-mono text-emerald-400")
                ui.label(f"{stk_name[:16]}").classes("text-[10px] font-bold text-slate-300 font-mono truncate")

        # 3. Primary Tabbed Workspaces
        with ui.tabs().classes("w-full mp-tabs border-b border-[var(--mp-border)]") as nav_tabs:
            tab_breadth = ui.tab("1. Market Participation & Breadth History 📈")
            tab_turnover = ui.tab("2. Cash Turnover & Liquidity Trend 💧")
            tab_benchmarks = ui.tab("3. Benchmark Trends & Multi-Timeframe Returns 📊")
            tab_streaks = ui.tab("4. Sector Consecutive Inflow Streaks 🔥")
            tab_new_money = ui.tab("5. New Money & Rotation Influx Radar 🚀")

        with ui.tab_panels(nav_tabs, value=tab_breadth).classes("w-full bg-transparent p-0"):
            # =================================================================
            # TAB 1: BREADTH HISTORY
            # =================================================================
            with ui.tab_panel(tab_breadth).classes("p-0 w-full gap-4"):
                if breadth_df.empty:
                    ui.label("No breadth history available.").classes("text-sm text-[var(--mp-muted)] p-4")
                else:
                    dates = [str(pd.to_datetime(d).strftime("%m-%d")) for d in breadth_df["trade_date"]]
                    ab20_vals = [round(float(v), 1) if pd.notna(v) else 0.0 for v in breadth_df["above_20ema_pct"]]
                    ab50_vals = [round(float(v), 1) if pd.notna(v) else 0.0 for v in breadth_df["above_50ema_pct"]]
                    ab200_vals = [round(float(v), 1) if pd.notna(v) else 0.0 for v in breadth_df["above_200ema_pct"]]
                    adv_vals = [round(float(v), 1) if pd.notna(v) else 50.0 for v in breadth_df["advance_pct"]]
                    h52_vals = [int(v) if pd.notna(v) else 0 for v in breadth_df["near_52w_highs"]]

                    dates_len = len(dates)
                    z_start = max(0, int(((dates_len - 65) / max(1, dates_len)) * 100))

                    breadth_opt = {
                        "backgroundColor": "transparent",
                        "animation": False,
                        "tooltip": {
                            "trigger": "axis",
                            "axisPointer": {"type": "cross"},
                            "backgroundColor": "rgba(15, 23, 42, 0.95)",
                            "borderColor": "#334155",
                            "textStyle": {"color": "#f8fafc", "fontSize": 11, "fontFamily": "IBM Plex Mono"},
                        },
                        "legend": {
                            "data": ["> 20 EMA %", "> 50 EMA %", "> 200 EMA %", "Advance %", "Near 52W Highs"],
                            "textStyle": {"color": "#94a3b8", "fontSize": 10},
                            "top": 0,
                        },
                        "grid": [
                            {"left": "5%", "right": "4%", "top": "12%", "height": "52%"},
                            {"left": "5%", "right": "4%", "top": "70%", "height": "22%"},
                        ],
                        "dataZoom": [
                            {"type": "inside", "xAxisIndex": [0, 1], "start": z_start, "end": 100},
                            {"type": "slider", "xAxisIndex": [0, 1], "bottom": 0, "height": 20, "borderColor": "#334155"},
                        ],
                        "xAxis": [
                            {"type": "category", "data": dates, "gridIndex": 0, "axisLabel": {"color": "#94a3b8", "fontSize": 10}},
                            {"type": "category", "data": dates, "gridIndex": 1, "axisLabel": {"show": False}},
                        ],
                        "yAxis": [
                            {"type": "value", "gridIndex": 0, "min": 0, "max": 100, "axisLabel": {"color": "#94a3b8", "formatter": "{value}%"}, "splitLine": {"lineStyle": {"color": "#1e293b"}}},
                            {"type": "value", "gridIndex": 1, "axisLabel": {"color": "#94a3b8"}, "splitLine": {"lineStyle": {"color": "#1e293b"}}},
                        ],
                        "series": [
                            {"name": "> 20 EMA %", "type": "line", "data": ab20_vals, "xAxisIndex": 0, "yAxisIndex": 0, "lineStyle": {"color": "#38bdf8", "width": 1.5}, "showSymbol": False},
                            {"name": "> 50 EMA %", "type": "line", "data": ab50_vals, "xAxisIndex": 0, "yAxisIndex": 0, "lineStyle": {"color": "#fbbf24", "width": 2}, "showSymbol": False},
                            {"name": "> 200 EMA %", "type": "line", "data": ab200_vals, "xAxisIndex": 0, "yAxisIndex": 0, "lineStyle": {"color": "#f43f5e", "width": 1.5}, "showSymbol": False},
                            {"name": "Advance %", "type": "line", "data": adv_vals, "xAxisIndex": 0, "yAxisIndex": 0, "lineStyle": {"color": "#10b981", "width": 1, "type": "dashed"}, "showSymbol": False},
                            {"name": "Near 52W Highs", "type": "bar", "data": h52_vals, "xAxisIndex": 1, "yAxisIndex": 1, "itemStyle": {"color": "#6366f1"}},
                        ],
                    }

                    with ui.card().classes("w-full mp-card p-4 border border-[var(--mp-border)] bg-[var(--mp-surface)]"):
                        with ui.row().classes("w-full items-center justify-between mb-2"):
                            ui.label("📈 Market Participation & Breadth Expansion (Trailing 180 Sessions)").classes("text-sm font-bold text-[var(--mp-text)]")
                            ui.label("50% Line = Bull/Bear Demarcation · Gold = >50 EMA · Cyan = >20 EMA · Violet = 52W Highs").classes("text-[10px] text-[var(--mp-muted)] font-mono")
                        ui.echart(breadth_opt).classes("w-full h-[400px]")

            # =================================================================
            # TAB 2: TURNOVER & LIQUIDITY TREND
            # =================================================================
            with ui.tab_panel(tab_turnover).classes("p-0 w-full gap-4"):
                if to_df.empty:
                    ui.label("No turnover history available.").classes("text-sm text-[var(--mp-muted)] p-4")
                else:
                    t_dates = [str(pd.to_datetime(d).strftime("%m-%d")) for d in to_df["trade_date"]]
                    to_vals = [round(float(v), 1) for v in to_df["total_turnover_cr"]]
                    ma_vals = [round(float(v), 1) if pd.notna(v) else to_vals[i] for i, v in enumerate(to_df["turnover_20d_ma"])]

                    # Color bars green if Advance % >= 50%, red if < 50%
                    bar_items = []
                    for idx, r in to_df.iterrows():
                        is_up = float(r.get("advance_pct", 50.0)) >= 50.0
                        bar_items.append({
                            "value": round(float(r["total_turnover_cr"]), 1),
                            "itemStyle": {"color": "#10b981" if is_up else "#f43f5e"},
                        })

                    to_opt = {
                        "backgroundColor": "transparent",
                        "animation": False,
                        "tooltip": {
                            "trigger": "axis",
                            "axisPointer": {"type": "shadow"},
                            "backgroundColor": "rgba(15, 23, 42, 0.95)",
                            "borderColor": "#334155",
                            "textStyle": {"color": "#f8fafc", "fontSize": 11, "fontFamily": "IBM Plex Mono"},
                        },
                        "legend": {"data": ["Cash Turnover (₹ Cr)", "20-Day Turnover MA"], "textStyle": {"color": "#94a3b8", "fontSize": 10}, "top": 0},
                        "grid": {"left": "5%", "right": "4%", "top": "12%", "bottom": "12%"},
                        "xAxis": {"type": "category", "data": t_dates, "axisLabel": {"color": "#94a3b8", "fontSize": 10}},
                        "yAxis": {"type": "value", "axisLabel": {"color": "#94a3b8", "formatter": "₹{value}Cr"}, "splitLine": {"lineStyle": {"color": "#1e293b"}}},
                        "series": [
                            {"name": "Cash Turnover (₹ Cr)", "type": "bar", "data": bar_items},
                            {"name": "20-Day Turnover MA", "type": "line", "data": ma_vals, "lineStyle": {"color": "#38bdf8", "width": 2}, "showSymbol": False},
                        ],
                    }

                    with ui.card().classes("w-full mp-card p-4 border border-[var(--mp-border)] bg-[var(--mp-surface)]"):
                        with ui.row().classes("w-full items-center justify-between mb-2"):
                            ui.label("💧 Cash Market Turnover & Volume Expansion Velocity (Trailing 60 Sessions)").classes("text-sm font-bold text-[var(--mp-text)]")
                            ui.label("Green = Accumulation Day (Adv > 50%) · Rose = Distribution Day (Adv < 50%) · Cyan = 20D MA").classes("text-[10px] text-[var(--mp-muted)] font-mono")
                        ui.echart(to_opt).classes("w-full h-[380px]")

            # =================================================================
            # TAB 3: BENCHMARK TRENDS & RETURNS
            # =================================================================
            with ui.tab_panel(tab_benchmarks).classes("p-0 w-full gap-4"):
                if bench_df.empty:
                    ui.label("No benchmark index history available.").classes("text-sm text-[var(--mp-muted)] p-4")
                else:
                    # Performance scorecard table
                    latest_bench = bench_df.groupby("index_name").last().reset_index()
                    scorecard_cols = [
                        {"name": "index_name", "label": "Index", "field": "index_name", "align": "left"},
                        {"name": "close_price", "label": "Close", "field": "close_price", "align": "right"},
                        {"name": "return_1d_pct", "label": "1D Return", "field": "return_1d_pct", "align": "right"},
                        {"name": "return_5d_pct", "label": "5D Return", "field": "return_5d_pct", "align": "right"},
                        {"name": "return_20d_pct", "label": "1M Return", "field": "return_20d_pct", "align": "right"},
                        {"name": "distance_ema_50_pct", "label": "vs 50 EMA", "field": "distance_ema_50_pct", "align": "right"},
                        {"name": "distance_ema_200_pct", "label": "vs 200 EMA", "field": "distance_ema_200_pct", "align": "right"},
                        {"name": "trend_state", "label": "Trend Regime", "field": "trend_state", "align": "center"},
                    ]
                    scorecard_rows = []
                    for _, r in latest_bench.iterrows():
                        r1 = float(r.get("return_1d_pct") or 0.0)
                        r5 = float(r.get("return_5d_pct") or 0.0)
                        r20 = float(r.get("return_20d_pct") or 0.0)
                        d50 = float(r.get("distance_ema_50_pct") or 0.0)
                        d200 = float(r.get("distance_ema_200_pct") or 0.0)
                        scorecard_rows.append({
                            "index_name": r["index_name"],
                            "close_price": f"₹{float(r['close_price']):,.2f}",
                            "return_1d_pct": f"{r1:+.2f}%",
                            "return_5d_pct": f"{r5:+.2f}%",
                            "return_20d_pct": f"{r20:+.2f}%",
                            "distance_ema_50_pct": f"{d50:+.1f}%",
                            "distance_ema_200_pct": f"{d200:+.1f}%",
                            "trend_state": r.get("trend_state", "—"),
                        })

                    with ui.card().classes("w-full mp-card p-4 border border-[var(--mp-border)] bg-[var(--mp-surface)]"):
                        ui.label("📊 Market Benchmark Performance Scorecard").classes("text-sm font-bold text-[var(--mp-text)] mb-2")
                        ui.table(columns=scorecard_cols, rows=scorecard_rows).classes("w-full mp-table text-xs font-mono")

            # =================================================================
            # TAB 4: SECTOR INFLOW STREAKS & HEATMAP
            # =================================================================
            with ui.tab_panel(tab_streaks).classes("p-0 w-full gap-4"):
                if streak_df.empty:
                    ui.label("No sector money flow streaks found.").classes("text-sm text-[var(--mp-muted)] p-4")
                else:
                    with ui.card().classes("w-full mp-card p-4 border border-[var(--mp-border)] bg-[var(--mp-surface)]"):
                        with ui.row().classes("w-full items-center justify-between mb-2"):
                            with ui.row().classes("items-center gap-2"):
                                ui.icon("local_fire_department", color="warning").classes("text-lg")
                                ui.label("🔥 Consecutive Sector Money Flow Streaks").classes("text-sm font-bold text-[var(--mp-text)]")
                            ui.label("Sectors ranked by consecutive sessions of rising market turnover share (Δ Share > 0)").classes("text-xs text-[var(--mp-muted)]")

                        with ui.grid(columns=3).classes("w-full gap-3"):
                            for _, r in streak_df.head(6).iterrows():
                                s_days = int(r["streak_days"])
                                s_name = str(r["group_name"])
                                s_delta = float(r["delta_5d_pp"])
                                s_share = float(r["current_share_pct"])
                                s_net = float(r["inst_net_cr"])
                                s_lead = str(r["leader_symbols"] or "")
                                top_lead = [s.strip() for s in s_lead.split(",") if s.strip()][:3]

                                streak_color = "border-emerald-500/50 bg-emerald-950/20" if s_days >= 2 else "border-[var(--mp-border)] bg-[var(--mp-surface-raised)]"
                                with ui.card().classes(f"p-3 mp-card border {streak_color} flex flex-col gap-1"):
                                    with ui.row().classes("w-full items-center justify-between"):
                                        ui.label(s_name).classes("font-bold text-xs text-[var(--mp-text)]")
                                        ui.label(f"{s_days}D Streak 🔥" if s_days >= 2 else f"{s_days}D").classes(
                                            "text-[10px] font-mono font-bold px-1.5 py-0.5 rounded " + ("bg-emerald-900/80 text-emerald-300" if s_days >= 2 else "bg-slate-800 text-slate-400")
                                        )

                                    with ui.row().classes("w-full items-center justify-between text-xs font-mono"):
                                        ui.label(f"Share: {s_share:.1f}% ({s_delta:+.2f} pp 5D)").classes("text-[11px] text-[var(--mp-muted)]")
                                        if s_net != 0:
                                            ui.label(f"Inst: ₹{s_net:,.0f}Cr").classes("text-[10px] text-amber-400")

                                    if top_lead:
                                        with ui.row().classes("w-full items-center gap-1 mt-1 pt-1 border-t border-slate-800"):
                                            ui.label("Leaders:").classes("text-[9px] text-[var(--mp-muted)]")
                                            for sym in top_lead:
                                                def make_open(s=sym):
                                                    if on_select_symbol:
                                                        return lambda: on_select_symbol(s)
                                                    return lambda: open_stock_360_modal(db_path, s, copy_text=copy_text)
                                                ui.button(sym, on_click=make_open(sym)).props("dense flat size=xs").classes("font-mono text-[9px] text-sky-400 p-0 hover:underline")

            # =================================================================
            # TAB 5: NEW MONEY & ROTATION RADAR
            # =================================================================
            with ui.tab_panel(tab_new_money).classes("p-0 w-full gap-4"):
                # Filter for sectors where delta 5D share is positive and state is Emerging or Improving
                new_money_secs = streak_df[
                    (streak_df["delta_5d_pp"] > 0)
                    | (streak_df["inst_net_cr"] > 0)
                    | (streak_df["streak_days"] >= 2)
                ].copy()

                with ui.card().classes("w-full mp-card p-4 border border-[var(--mp-border)] bg-[var(--mp-surface)]"):
                    with ui.row().classes("w-full items-center justify-between mb-3"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("radar", color="primary").classes("text-lg")
                            ui.label("🚀 Emerging Capital Flight & Sector Rotation Radar").classes("text-sm font-bold text-[var(--mp-text)]")
                        ui.label("Detecting sectors receiving fresh institutional block inflows or expanding turnover velocity").classes("text-xs text-[var(--mp-muted)]")

                    if new_money_secs.empty:
                        ui.label("No active new money rotation alerts detected in current session.").classes("text-xs text-[var(--mp-muted)] p-2")
                    else:
                        with ui.grid(columns=2).classes("w-full gap-3"):
                            for _, r in new_money_secs.iterrows():
                                grp = str(r["group_name"])
                                d5 = float(r["delta_5d_pp"])
                                net_inst = float(r["inst_net_cr"])
                                st_name = str(r["rotation_state"])
                                leads = [s.strip() for s in str(r["leader_symbols"] or "").split(",") if s.strip()][:4]

                                with ui.card().classes("p-3 mp-card border border-[var(--mp-border)] bg-[var(--mp-surface-raised)] flex flex-col gap-1"):
                                    with ui.row().classes("w-full items-center justify-between"):
                                        ui.label(grp).classes("text-sm font-bold text-[var(--mp-text)]")
                                        ui.label(st_name).classes(
                                            "mp-badge text-[10px] " + ("mp-good" if st_name == "Leading" else "mp-info" if st_name == "Emerging" else "mp-neutral")
                                        )

                                    with ui.row().classes("w-full items-center justify-between text-xs font-mono"):
                                        ui.label(f"5D Share Expansion: {d5:+.2f} pp").classes("text-emerald-400 font-bold")
                                        if net_inst > 0:
                                            ui.label(f"Inst Deals: +₹{net_inst:,.0f}Cr").classes("text-amber-400 font-bold")

                                    with ui.row().classes("w-full items-center gap-1 mt-2 pt-1 border-t border-slate-800"):
                                        ui.label("Breakout Candidates:").classes("text-[10px] text-[var(--mp-muted)]")
                                        for sym in leads:
                                            def make_clk(s=sym):
                                                if on_select_symbol:
                                                    return lambda: on_select_symbol(s)
                                                return lambda: open_stock_360_modal(db_path, s, copy_text=copy_text)
                                            ui.button(f"⚡ {sym}", on_click=make_clk(sym)).props("dense outline size=xs").classes("mp-button font-mono text-[10px]")
