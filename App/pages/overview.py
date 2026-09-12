"""MarketPulse Overview Page — Macro Commentary, Institutional Flows, and Tactical Playbook."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
from nicegui import ui
import pandas as pd

from App.market_commentary_engine import generate_market_commentary
from App.market_status import load_market_status, non_actionable_message
from App.ui.stock_drawer import open_stock_360_modal

try:
    from App.pages.market_trends import (
        query_historical_breadth,
        query_market_turnover_trend,
        query_sector_money_flows,
        query_emerging_sector_rotations,
    )
except ModuleNotFoundError:
    from pages.market_trends import (
        query_historical_breadth,
        query_market_turnover_trend,
        query_sector_money_flows,
        query_emerging_sector_rotations,
    )  # type: ignore


def build_overview_page(
    db_path: Path | str,
    *,
    copy_text: Callable[[str, str], None] | None = None,
    table_from_df: Callable[..., Any] | None = None,
    on_select_symbol: Callable[[str], None] | None = None,
    show_page: Callable[[str], None] | None = None,
) -> None:
    """Render the executive Overview Cockpit with automated Market Commentary & Action Plan."""
    db_path = Path(db_path)
    st = load_market_status(db_path, db_path.parent / "status.json")

    # Generate the complete quantitative narrative & statistics
    comm = generate_market_commentary(db_path)
    if not comm.get("ok"):
        with ui.card().classes("w-full mp-card p-6 border border-rose-500/40 bg-rose-950/20"):
            ui.label("Error generating market commentary").classes("text-base font-bold text-rose-400")
            ui.label(comm.get("error", "Unknown error")).classes("text-xs text-[var(--mp-muted)]")
        return

    kpis = comm["kpis"]
    plan = comm["action_plan"]
    regime_tone = comm["regime_tone"]  # positive, info, warning, negative
    banner_border = (
        "border-emerald-500/50 bg-emerald-950/20 text-emerald-300"
        if regime_tone == "positive"
        else "border-sky-500/50 bg-sky-950/20 text-sky-300"
        if regime_tone == "info"
        else "border-amber-500/50 bg-amber-950/20 text-amber-300"
        if regime_tone == "warning"
        else "border-rose-500/50 bg-rose-950/20 text-rose-300"
    )
    badge_cls = (
        "mp-good" if regime_tone == "positive"
        else "mp-info" if regime_tone == "info"
        else "mp-warn" if regime_tone == "warning"
        else "mp-bad"
    )

    with ui.column().classes("w-full mp-page-overview gap-4"):
        # 1. Header Toolbar
        with ui.row().classes("w-full items-center justify-between border-b border-[var(--mp-border)] pb-3 flex-wrap gap-2"):
            with ui.column().classes("gap-0.5"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("insights", color="primary").classes("text-2xl")
                    ui.label("Market Overview & Tactical Playbook").classes("text-xl font-bold tracking-tight text-[var(--mp-text)]")
                    ui.label(f"EOD · {comm['date_str']}").classes(f"mp-badge {badge_cls} text-xs font-semibold")
                ui.label(
                    "Deterministic algorithmic synthesis of macros, breadth thrust, institutional deals, turnover velocity, and actionable setups."
                ).classes("text-xs text-[var(--mp-muted)]")

            with ui.row().classes("items-center gap-2"):
                if show_page:
                    ui.button("Action Desk ⚡", on_click=lambda: show_page("Action Desk")).props("dense unelevated size=sm color=primary").classes("font-semibold text-xs")
                    ui.button("Market Trends 📈", on_click=lambda: show_page("Market Trends")).props("dense outline size=sm color=primary").classes("font-semibold text-xs")
                    ui.button("Momentum Scanner 🚀", on_click=lambda: show_page("Momentum")).props("dense outline size=sm color=primary").classes("font-semibold text-xs")
                    ui.button("Sectors 📊", on_click=lambda: show_page("Sectors")).props("dense outline size=sm color=primary").classes("font-semibold text-xs")

        # 2. Executive KPI Ribbon
        with ui.grid(columns=6).classes("w-full gap-3 mp-kpi-grid"):
            # Nifty 50
            with ui.card().classes("p-3 mp-card border border-[var(--mp-border)] bg-[var(--mp-surface-raised)]"):
                ui.label("NIFTY 50").classes("text-[10px] font-bold text-[var(--mp-muted)] uppercase tracking-wider")
                ui.label(kpis["nifty_cmp"]).classes("text-lg font-bold font-mono text-[var(--mp-text)]")
                with ui.row().classes("items-center gap-1.5 text-xs font-mono"):
                    tone = "text-emerald-400" if "+" in kpis["nifty_1d"] else "text-rose-400"
                    ui.label(f"1D: {kpis['nifty_1d']}").classes(f"font-bold {tone}")
                    ui.label(f"· 5D: {kpis['nifty_5d']}").classes("text-[var(--mp-muted)]")

            # Market Breadth
            with ui.card().classes("p-3 mp-card border border-[var(--mp-border)] bg-[var(--mp-surface-raised)]"):
                ui.label("MARKET BREADTH").classes("text-[10px] font-bold text-[var(--mp-muted)] uppercase tracking-wider")
                ui.label(kpis["breadth_50ema"]).classes("text-lg font-bold font-mono text-[var(--mp-text)]")
                with ui.row().classes("items-center gap-1.5 text-xs font-mono"):
                    ui.label(f"> 50 EMA · {kpis['breadth_state']}").classes("text-[var(--mp-muted)]")

            # Advance / Decline
            with ui.card().classes("p-3 mp-card border border-[var(--mp-border)] bg-[var(--mp-surface-raised)]"):
                ui.label("ADVANCE / DECLINE").classes("text-[10px] font-bold text-[var(--mp-muted)] uppercase tracking-wider")
                ui.label(kpis["adv_ratio"]).classes("text-base font-bold font-mono text-slate-200 mt-0.5")
                ui.label("Nifty 500 & Broader Cash").classes("text-[10px] text-[var(--mp-muted)] font-mono")

            # Institutional Flow (7D)
            with ui.card().classes("p-3 mp-card border border-[var(--mp-border)] bg-[var(--mp-surface-raised)]"):
                ui.label("INSTITUTIONAL FLOW (7D)").classes("text-[10px] font-bold text-[var(--mp-muted)] uppercase tracking-wider")
                fii_tone = "text-emerald-400" if "+" in kpis["fii_7d_net"] else "text-rose-400"
                ui.label(f"FII: {kpis['fii_7d_net']}").classes(f"text-base font-bold font-mono {fii_tone}")
                ui.label(f"DII: {kpis['dii_7d_net']} net").classes("text-xs text-slate-300 font-mono")

            # Turnover & Top Sector
            with ui.card().classes("p-3 mp-card border border-[var(--mp-border)] bg-[var(--mp-surface-raised)]"):
                ui.label("CASH TURNOVER & SECTOR").classes("text-[10px] font-bold text-[var(--mp-muted)] uppercase tracking-wider")
                ui.label(kpis["turnover_cr"]).classes("text-base font-bold font-mono text-slate-200")
                ui.label(f"{kpis['turnover_ratio']} vs 20D · {kpis['top_sector'][:12]}").classes("text-[10px] text-amber-400 font-mono truncate")

            # Intermarket: VIX, G-Sec & Currency
            with ui.card().classes("p-3 mp-card border border-[var(--mp-border)] bg-[var(--mp-surface-raised)]"):
                ui.label("INTERMARKET & MACROS").classes("text-[10px] font-bold text-[var(--mp-muted)] uppercase tracking-wider")
                with ui.row().classes("items-center gap-1.5"):
                    ui.label(f"VIX {kpis.get('vix', '11.8')}").classes("text-sm font-bold font-mono text-sky-400")
                    ui.label(f"({kpis.get('vix_1d', '0.0%')})").classes("text-[10px] font-mono text-[var(--mp-muted)]")
                with ui.column().classes("gap-0 leading-tight mt-0.5"):
                    ui.label(f"10Y G-Sec: {kpis.get('gs10yr_state', 'Stable')}").classes("text-[10px] font-mono text-slate-300 truncate")
                    ui.label(f"Crude Spread: {kpis.get('crude_spread', '0.0%')}").classes("text-[10px] font-mono text-amber-300 truncate")

        # 3. Market Regime & Posture Headline Banner
        with ui.card().classes(f"w-full p-4 rounded-xl border {banner_border} shadow-sm"):
            with ui.row().classes("w-full items-start justify-between gap-3 flex-wrap"):
                with ui.column().classes("gap-1 max-w-[850px]"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label("🎯 ACTIVE MARKET REGIME:").classes("text-xs font-extrabold tracking-wider uppercase opacity-80")
                        ui.label(comm["regime_title"]).classes("text-base font-black tracking-wide uppercase")
                    ui.label(comm["headline"]).classes("text-sm font-semibold leading-relaxed")
                with ui.column().classes("items-end gap-0.5"):
                    ui.label("RECOMMENDED POSTURE").classes("text-[9px] font-bold tracking-wider uppercase opacity-75")
                    ui.label(plan["posture_title"]).classes("text-sm font-extrabold")
                    ui.label(f"Cash Stance: {plan['cash_recommendation']}").classes("text-xs font-mono font-bold")

        # 4. Deep Commentary & Tactical Plan Two-Column Grid
        with ui.grid(columns=2).classes("w-full gap-4 items-start"):
            # LEFT COLUMN: Macro & Price Action & Breadth
            with ui.column().classes("w-full gap-4"):
                # Macro & Index Narrative Card
                with ui.card().classes("w-full mp-card p-4 border border-[var(--mp-border)] bg-[var(--mp-surface)]"):
                    with ui.row().classes("items-center gap-2 mb-2 border-b border-[var(--mp-border)] pb-2"):
                        ui.icon("show_chart", color="primary").classes("text-lg")
                        ui.label("Macro Backdrop & Trend Structure").classes("text-sm font-bold text-[var(--mp-text)]")
                    ui.markdown(comm["macro_commentary"]).classes("text-xs text-slate-200 leading-relaxed font-sans")

                # Breadth & Thrust Narrative Card
                with ui.card().classes("w-full mp-card p-4 border border-[var(--mp-border)] bg-[var(--mp-surface)]"):
                    with ui.row().classes("items-center gap-2 mb-2 border-b border-[var(--mp-border)] pb-2"):
                        ui.icon("pie_chart", color="primary").classes("text-lg")
                        ui.label("Market Participation & Breadth Thrust").classes("text-sm font-bold text-[var(--mp-text)]")
                    ui.markdown(comm["breadth_commentary"]).classes("text-xs text-slate-200 leading-relaxed font-sans")

                # Sector Rotation Narrative Card
                with ui.card().classes("w-full mp-card p-4 border border-[var(--mp-border)] bg-[var(--mp-surface)]"):
                    with ui.row().classes("items-center gap-2 mb-2 border-b border-[var(--mp-border)] pb-2"):
                        ui.icon("sync_alt", color="primary").classes("text-lg")
                        ui.label("Sector Rotation & Capital Flight").classes("text-sm font-bold text-[var(--mp-text)]")
                    ui.markdown(comm["sector_commentary"]).classes("text-xs text-slate-200 leading-relaxed font-sans")

            # RIGHT COLUMN: Flows, Deals & Tactical Action Plan
            with ui.column().classes("w-full gap-4"):
                # Institutional Flows Card
                with ui.card().classes("w-full mp-card p-4 border border-[var(--mp-border)] bg-[var(--mp-surface)]"):
                    with ui.row().classes("items-center gap-2 mb-2 border-b border-[var(--mp-border)] pb-2"):
                        ui.icon("account_balance", color="primary").classes("text-lg")
                        ui.label("Institutional Deals & Smart Money Footprint").classes("text-sm font-bold text-[var(--mp-text)]")
                    ui.markdown(comm["flows_commentary"]).classes("text-xs text-slate-200 leading-relaxed font-sans")

                    # Quick click buttons for top accumulated symbols
                    if plan.get("top_accum"):
                        with ui.column().classes("w-full gap-1 mt-3 pt-2 border-t border-slate-800"):
                            ui.label("TOP ACCUMULATED STOCKS (Click to inspect):").classes("text-[10px] font-bold text-[var(--mp-muted)] tracking-wider")
                            with ui.row().classes("gap-1.5 flex-wrap"):
                                for acc in plan["top_accum"][:5]:
                                    asym = acc["symbol"]
                                    anet = acc["net_cr"]

                                    def make_open(sym=asym):
                                        if on_select_symbol:
                                            return lambda *_: on_select_symbol(sym)
                                        return lambda *_: open_stock_360_modal(db_path, sym, copy_text=copy_text)

                                    ui.button(
                                        f"{asym} (+₹{anet:,.0f}Cr)",
                                        on_click=make_open(asym)
                                    ).props("dense unelevated size=xs color=dark").classes(
                                        "text-[10px] font-mono border border-emerald-500/40 text-emerald-300 hover:border-emerald-400"
                                    )

                # TACTICAL ACTION PLAN CARD (Highlighted)
                with ui.card().classes("w-full mp-card p-4 border border-emerald-500/40 bg-[var(--mp-surface-raised)] shadow-md"):
                    with ui.row().classes("w-full items-center justify-between mb-2 border-b border-[var(--mp-border)] pb-2"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("verified_user", color="positive").classes("text-lg")
                            ui.label("Tactical Action Plan: What Should Be Planned?").classes("text-sm font-extrabold text-emerald-400 tracking-wide uppercase")
                        ui.label(plan["cash_recommendation"]).classes("mp-badge mp-neutral text-[10px] font-bold")

                    with ui.column().classes("w-full gap-2.5"):
                        for directive in plan["directives"]:
                            ui.markdown(directive).classes("text-xs text-slate-100 leading-relaxed")

                    # Focus Setup Chips: Darvas & Stage 1
                    with ui.column().classes("w-full gap-2 mt-3 pt-3 border-t border-[var(--mp-border)]"):
                        if plan.get("darvas_samples"):
                            with ui.row().classes("items-center gap-2 flex-wrap"):
                                ui.label("🎯 Darvas Squeezes:").classes("text-[10px] font-bold text-sky-400 font-mono")
                                for d_item in plan["darvas_samples"][:4]:
                                    dsym = d_item["symbol"]
                                    drs = d_item.get("rs_percentile", 0)

                                    def make_open_d(sym=dsym):
                                        if on_select_symbol:
                                            return lambda *_: on_select_symbol(sym)
                                        return lambda *_: open_stock_360_modal(db_path, sym, copy_text=copy_text)

                                    ui.button(f"{dsym} (RS {drs:.0f})", on_click=make_open_d(dsym)).props("dense outline size=xs color=primary").classes("text-[10px] font-mono")

                        if plan.get("stage1_samples"):
                            with ui.row().classes("items-center gap-2 flex-wrap"):
                                ui.label("🔄 Stage 1 Bottoms:").classes("text-[10px] font-bold text-amber-400 font-mono")
                                for s_item in plan["stage1_samples"][:4]:
                                    ssym = s_item["symbol"]
                                    srs = s_item.get("rs_percentile", 0)

                                    def make_open_s(sym=ssym):
                                        if on_select_symbol:
                                            return lambda *_: on_select_symbol(sym)
                                        return lambda *_: open_stock_360_modal(db_path, sym, copy_text=copy_text)

                                    ui.button(f"{ssym} (RS {srs:.0f})", on_click=make_open_s(ssym)).props("dense outline size=xs color=warning").classes("text-[10px] font-mono")

        # 5. Historical Trend & Sector Capital Flow Radar (Breadth, Turnover, Consecutive Inflows, Emerging Sectors)
        try:
            hb_df = query_historical_breadth(db_path, days=65)
            to_trend_df = query_market_turnover_trend(db_path, days=40)
            streak_df, _ = query_sector_money_flows(db_path, sessions=10)
            new_money_df, _ = query_emerging_sector_rotations(db_path)
        except Exception:
            hb_df, to_trend_df, streak_df, new_money_df = pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        with ui.column().classes("w-full gap-3 mt-4 pt-4 border-t border-[var(--mp-border)]"):
            with ui.row().classes("w-full items-center justify-between flex-wrap gap-2"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("ssid_chart", color="primary").classes("text-xl")
                    ui.label("Historical Trend & Sector Capital Flow Radar").classes("text-lg font-bold text-[var(--mp-text)] tracking-tight")
                    ui.label("Trailing 65-Day Depth").classes("mp-badge mp-neutral text-xs font-mono font-semibold")
                with ui.row().classes("items-center gap-2"):
                    if show_page:
                        ui.button("Open Deep Market Trends Studio 📈", on_click=lambda: show_page("Market Trends")).props("dense unelevated size=sm color=primary").classes("font-semibold text-xs")

            with ui.tabs().classes("w-full mp-tabs") as flow_tabs:
                tab_hb = ui.tab("Market Participation Trend (65D)")
                tab_to_bars = ui.tab("Turnover & Liquidity Trend (40D)")
                tab_stk = ui.tab("Consecutive Sector Inflows")
                tab_emerging = ui.tab("New Money Influx Radar")

            with ui.tab_panels(flow_tabs, value=tab_hb).classes("w-full bg-transparent p-0"):
                with ui.tab_panel(tab_hb).classes("p-0 w-full"):
                    if not hb_df.empty:
                        hb_dates = [str(pd.to_datetime(d).strftime("%m-%d")) for d in hb_df["trade_date"]]
                        hb_ab50 = [round(float(v), 1) if pd.notna(v) else 0.0 for v in hb_df["above_50ema_pct"]]
                        hb_ab20 = [round(float(v), 1) if pd.notna(v) else 0.0 for v in hb_df["above_20ema_pct"]]
                        hb_adv = [round(float(v), 1) if pd.notna(v) else 50.0 for v in hb_df["advance_pct"]]

                        hb_chart_opt = {
                            "backgroundColor": "transparent",
                            "animation": False,
                            "tooltip": {"trigger": "axis", "backgroundColor": "rgba(15, 23, 42, 0.95)", "borderColor": "#334155", "textStyle": {"color": "#f8fafc", "fontSize": 11, "fontFamily": "IBM Plex Mono"}},
                            "legend": {"data": ["> 50 EMA %", "> 20 EMA %", "Advancers %"], "textStyle": {"color": "#94a3b8", "fontSize": 10}, "top": 0},
                            "grid": {"left": "4%", "right": "3%", "top": "14%", "bottom": "10%", "containLabel": True},
                            "xAxis": {"type": "category", "data": hb_dates, "axisLabel": {"color": "#94a3b8", "fontSize": 10}},
                            "yAxis": {"type": "value", "min": 0, "max": 100, "axisLabel": {"color": "#94a3b8", "formatter": "{value}%"}, "splitLine": {"lineStyle": {"color": "#1e293b"}}},
                            "series": [
                                {"name": "> 50 EMA %", "type": "line", "data": hb_ab50, "lineStyle": {"width": 2, "color": "#38bdf8"}, "itemStyle": {"color": "#38bdf8"}},
                                {"name": "> 20 EMA %", "type": "line", "data": hb_ab20, "lineStyle": {"width": 1.5, "color": "#a855f7"}, "itemStyle": {"color": "#a855f7"}},
                                {"name": "Advancers %", "type": "line", "data": hb_adv, "lineStyle": {"width": 1.2, "color": "#10b981", "type": "dashed"}, "itemStyle": {"color": "#10b981"}},
                            ],
                        }
                        ui.echart(hb_chart_opt).classes("w-full h-56")
                    else:
                        ui.label("No historical breadth data found.").classes("text-xs text-[var(--mp-muted)] p-3")

                with ui.tab_panel(tab_to_bars).classes("p-0 w-full"):
                    if not to_trend_df.empty:
                        to_dates = [str(pd.to_datetime(d).strftime("%m-%d")) for d in to_trend_df["trade_date"]]
                        to_vals = [round(float(v), 0) if pd.notna(v) else 0.0 for v in to_trend_df["total_turnover_cr"]]
                        to_ma = [round(float(v), 0) if pd.notna(v) else 0.0 for v in to_trend_df.get("turnover_20d_ma", [])]
                        to_colors = ["#10b981" if float(adv) >= 50 else "#f43f5e" for adv in to_trend_df.get("advance_pct", [50] * len(to_dates))]

                        to_chart_opt = {
                            "backgroundColor": "transparent",
                            "animation": False,
                            "tooltip": {"trigger": "axis", "backgroundColor": "rgba(15, 23, 42, 0.95)", "borderColor": "#334155", "textStyle": {"color": "#f8fafc", "fontSize": 11, "fontFamily": "IBM Plex Mono"}},
                            "legend": {"data": ["Turnover (₹Cr)", "20D MA (₹Cr)"], "textStyle": {"color": "#94a3b8", "fontSize": 10}, "top": 0},
                            "grid": {"left": "4%", "right": "3%", "top": "14%", "bottom": "10%", "containLabel": True},
                            "xAxis": {"type": "category", "data": to_dates, "axisLabel": {"color": "#94a3b8", "fontSize": 10}},
                            "yAxis": {"type": "value", "axisLabel": {"color": "#94a3b8", "formatter": "₹{value}Cr"}, "splitLine": {"lineStyle": {"color": "#1e293b"}}},
                            "series": [
                                {
                                    "name": "Turnover (₹Cr)",
                                    "type": "bar",
                                    "data": [{"value": v, "itemStyle": {"color": c}} for v, c in zip(to_vals, to_colors)],
                                },
                                {
                                    "name": "20D MA (₹Cr)",
                                    "type": "line",
                                    "data": to_ma,
                                    "lineStyle": {"color": "#38bdf8", "width": 2},
                                    "itemStyle": {"color": "#38bdf8"},
                                },
                            ],
                        }
                        ui.echart(to_chart_opt).classes("w-full h-56")
                    else:
                        ui.label("No turnover history found.").classes("text-xs text-[var(--mp-muted)] p-3")

                with ui.tab_panel(tab_stk).classes("p-0 w-full"):
                    if not streak_df.empty:
                        stk_cols = [c for c in ["group_name", "streak_days", "current_share_pct", "delta_5d_pp", "inst_net_cr", "deal_count", "rotation_state", "leader_symbols"] if c in streak_df.columns]
                        stk_display = streak_df.head(10)[stk_cols].copy()
                        col_rename = {
                            "group_name": "Sector",
                            "streak_days": "Inflow Streak",
                            "current_share_pct": "Share %",
                            "delta_5d_pp": "5D Δ Share (pp)",
                            "inst_net_cr": "Block Net (Cr)",
                            "deal_count": "Deals",
                            "rotation_state": "State",
                            "leader_symbols": "Key Leaders",
                        }
                        stk_display = stk_display.rename(columns=col_rename)
                        if table_from_df:
                            table_from_df(stk_display, "Sectors with Consecutive Daily Inflows", pagination=10)
                        else:
                            ui.table.from_pandas(stk_display)
                    else:
                        ui.label("No active sector inflow streaks.").classes("text-xs text-[var(--mp-muted)] p-3")

                with ui.tab_panel(tab_emerging).classes("p-0 w-full"):
                    if not new_money_df.empty:
                        nm_cols = [c for c in ["group_name", "delta_5d_pp", "inst_net_cr", "streak_days", "rotation_state", "leader_symbols"] if c in new_money_df.columns]
                        nm_show = new_money_df.head(10)[nm_cols].copy()
                        col_rename_nm = {
                            "group_name": "Sector",
                            "delta_5d_pp": "5D Share Expansion (pp)",
                            "inst_net_cr": "Block Net (Cr)",
                            "streak_days": "Streak Days",
                            "rotation_state": "State",
                            "leader_symbols": "Breakout Candidates",
                        }
                        nm_show = nm_show.rename(columns=col_rename_nm)
                        if table_from_df:
                            table_from_df(nm_show, "New Money Flowing Into Emerging Sectors", pagination=10)
                        else:
                            ui.table.from_pandas(nm_show)
                    else:
                        ui.label("No emerging sector rotations detected.").classes("text-xs text-[var(--mp-muted)] p-3")

        # 6. Today's Tape & Market Movers Section (Gainers/Losers, Volume Shocks, Turnover, Near Highs)
        try:
            from App.market_summary import movers, stock_turnover, near_highs
            from App.market_flags import annotate, leadership_sets, deal_when_map
        except ModuleNotFoundError:
            from market_summary import movers, stock_turnover, near_highs  # type: ignore
            from market_flags import annotate, leadership_sets, deal_when_map  # type: ignore

        lead = leadership_sets(db_path)
        when = deal_when_map(db_path)
        mv = annotate(movers(db_path), db_path, flags=lead, when=when)
        to = annotate(stock_turnover(db_path), db_path, flags=lead, when=when)
        hi = annotate(near_highs(db_path), db_path, flags=lead, when=when)

        cols_move = [
            c for c in [
                "symbol", "day_pct", "week_pct", "month_pct", "t_o_today",
                "rvol", "delivery_pct", "rs_percentile", "away_52w_high_pct",
                "deal_when", "sector", "industry", "market_cap_cr"
            ] if not mv.empty and c in mv.columns
        ]
        to_cols = [
            c for c in [
                "symbol", "day_pct", "t_o_today", "t_o_1w", "t_o_1m", "vs_20d",
                "rs_percentile", "deal_when", "sector", "industry", "market_cap_cr"
            ] if not to.empty and c in to.columns
        ]
        hi_cols = [
            c for c in [
                "symbol", "day_pct", "away_52w_high_pct", "rs_percentile",
                "rvol", "t_o_today", "delivery_pct", "deal_when", "sector", "industry"
            ] if not hi.empty and c in hi.columns
        ]

        with ui.column().classes("w-full gap-3 mt-4 pt-4 border-t border-[var(--mp-border)]"):
            with ui.row().classes("w-full items-center justify-between flex-wrap gap-2"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("table_chart", color="primary").classes("text-xl")
                    ui.label("Today's Tape & Market Movers").classes("text-lg font-bold text-[var(--mp-text)] tracking-tight")
                ui.label("Real-time EOD momentum movers, volume expansion shocks, and liquidity leaders").classes("text-xs text-[var(--mp-muted)]")

            with ui.tabs().classes("w-full mp-tabs") as tape_tabs:
                tab_gainers_losers = ui.tab("Gainers & Losers (Up / Down)")
                tab_volume_shocks = ui.tab("Volume Shocks (RVOL)")
                tab_turnover = ui.tab("Turnover Leaders")
                tab_near_highs = ui.tab("Near 52W Highs")

            with ui.tab_panels(tape_tabs, value=tab_gainers_losers).classes("w-full bg-transparent p-0"):
                with ui.tab_panel(tab_gainers_losers).classes("p-0 w-full"):
                    with ui.element("div").classes("grid grid-cols-1 lg:grid-cols-2 gap-4 w-full"):
                        with ui.column().classes("w-full"):
                            if not mv.empty:
                                up_df = mv.sort_values("day_pct", ascending=False).head(15)[cols_move]
                                if table_from_df:
                                    table_from_df(up_df, "Top Gainers (Up)", pagination=15)
                                else:
                                    ui.table.from_pandas(up_df)
                        with ui.column().classes("w-full"):
                            if not mv.empty:
                                down_df = mv.sort_values("day_pct", ascending=True).head(15)[cols_move]
                                if table_from_df:
                                    table_from_df(down_df, "Top Losers (Down)", pagination=15)
                                else:
                                    ui.table.from_pandas(down_df)

                with ui.tab_panel(tab_volume_shocks).classes("p-0 w-full"):
                    if not mv.empty and "rvol" in mv.columns:
                        vol_df = mv.sort_values("rvol", ascending=False).head(20)[cols_move]
                        if table_from_df:
                            table_from_df(vol_df, "Volume Shock Leaders (Top RVOL)", pagination=20)
                        else:
                            ui.table.from_pandas(vol_df)

                with ui.tab_panel(tab_turnover).classes("p-0 w-full"):
                    if not to.empty:
                        to_show = to[to_cols].head(25)
                        if table_from_df:
                            table_from_df(to_show, "Cash Turnover Leaders (Today / 1W / 1M)", pagination=25)
                        else:
                            ui.table.from_pandas(to_show)

                with ui.tab_panel(tab_near_highs).classes("p-0 w-full"):
                    if not hi.empty:
                        hi_show = hi[hi_cols].head(20)
                        if table_from_df:
                            table_from_df(hi_show, "Near 52-Week High (Within 5%)", pagination=20)
                        else:
                            ui.table.from_pandas(hi_show)
                    else:
                        ui.label("No names currently within 5% of 52-week high in universe.").classes("text-sm text-[var(--mp-muted)] p-4")
