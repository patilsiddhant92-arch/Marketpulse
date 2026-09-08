"""Sector Rotation & Money Flow Workspace — Mantis-Grade 5-Panel Decision Desk.

Combines:
1. Sector Ranking / Money Flow Matrix (Turnover, % Chg, Share %, Delta Share, RS, Breadth, Leaders)
2. 15-Session Turnover Heatmaps (Market Share % and Turnover vs Own History)
3. Relative Strength Leadership (T0 vs T-5 Comparative Momentum)
4. Official Sectoral Indices Desk (21 NSE Sectoral/Thematic Indices)
5. Constituent Stock Drilldown with 1-Click Stock 360 inspection
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
import duckdb
import pandas as pd
from nicegui import ui

try:
    from App.market_status import load_market_status, non_actionable_message
    from App.market_summary import group_tape, group_trend, movers
    from App.sector_read_model import (
        format_vs_nifty_cell,
        query_index_session_count,
        query_sector_rotation_overview,
        vs_nifty_is_displayable,
    )
    from App.thematic_engine import build_thematic_leaderboard, get_index_constituents
    from App.ui.columns import get_quasar_column_def
    from App.ui.stock_drawer import open_stock_360_modal
    from App.ui.widgets import chart_panel, grouped_line_chart, return_heatmap
except ModuleNotFoundError:
    from market_status import load_market_status, non_actionable_message  # type: ignore
    from market_summary import group_tape, group_trend, movers  # type: ignore
    from sector_read_model import (  # type: ignore
        format_vs_nifty_cell,
        query_index_session_count,
        query_sector_rotation_overview,
        vs_nifty_is_displayable,
    )
    from thematic_engine import build_thematic_leaderboard, get_index_constituents  # type: ignore
    from ui.columns import get_quasar_column_def  # type: ignore
    from ui.stock_drawer import open_stock_360_modal  # type: ignore
    from ui.widgets import chart_panel, grouped_line_chart, return_heatmap  # type: ignore


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or pd.isna(v):
            return default
        return float(v)
    except (ValueError, TypeError):
        return default


def _fmt_pct(v: Any, signed: bool = True) -> str:
    if v is None or pd.isna(v):
        return "—"
    try:
        val = float(v)
        sign = "+" if signed and val > 0 else ""
        return f"{sign}{val:.1f}%"
    except (ValueError, TypeError):
        return "—"


def _fmt_vs_nifty(v: Any, *, index_sessions: int | None = None) -> str:
    return format_vs_nifty_cell(v, index_sessions=index_sessions)


def _fmt_money(v: Any) -> str:
    val = _safe_float(v)
    if val >= 1000:
        return f"₹{val / 1000:,.1f}k Cr"
    return f"₹{val:,.1f} Cr"


def query_sectoral_indices(db_path: Path) -> pd.DataFrame:
    """Fetch official NSE sectoral and thematic indices from index_daily."""
    with duckdb.connect(str(db_path), read_only=True) as db:
        sql = """
        WITH latest AS (SELECT max(trade_date) AS max_d FROM index_daily)
        SELECT index_name, close_price, return_1d_pct, return_5d_pct, return_20d_pct,
               distance_ema_20_pct, trend_state
        FROM index_daily i
        JOIN latest l ON i.trade_date = l.max_d
        WHERE (index_name LIKE 'NIFTY%' AND index_name NOT LIKE '%100%' AND index_name NOT LIKE '%200%' 
               AND index_name NOT LIKE '%500%' AND index_name NOT LIKE 'Nifty 50%')
        ORDER BY return_1d_pct DESC
        """
        try:
            return db.execute(sql).fetchdf()
        except Exception:
            return pd.DataFrame()


def query_turnover_heatmaps_data(db_path: Path, level: str = "Sector", days: int = 15) -> dict[str, Any]:
    """Calculate 15-session turnover market share and turnover expansion multiple."""
    with duckdb.connect(str(db_path), read_only=True) as db:
        try:
            dates = [r[0] for r in db.execute(
                "SELECT DISTINCT trade_date FROM sector_rotation WHERE level = ? ORDER BY trade_date DESC LIMIT ?",
                [level, days]
            ).fetchall()]
            if not dates:
                return {}
            dates = sorted(dates)
            start_d = dates[0]

            df = db.execute(
                """
                SELECT trade_date, group_name, turnover_1d_cr,
                       coalesce(turnover_5d_cr / NULLIF(turnover_20d_cr / 4.0, 0), 1.0) AS vs_history
                FROM sector_rotation
                WHERE level = ? AND trade_date >= ?
                ORDER BY trade_date ASC
                """,
                [level, start_d],
            ).fetchdf()

            if df.empty:
                return {}

            # Pivot turnover share
            pivot_to = df.pivot(index="group_name", columns="trade_date", values="turnover_1d_cr").fillna(0)
            share_pivot = pivot_to.div(pivot_to.sum(axis=0), axis=1) * 100.0

            # Pivot vs history multiple
            hist_pivot = df.pivot(index="group_name", columns="trade_date", values="vs_history").fillna(1.0)

            # Sort groups by latest turnover share
            latest_col = dates[-1]
            if latest_col in share_pivot.columns:
                share_pivot = share_pivot.sort_values(latest_col, ascending=False)
                hist_pivot = hist_pivot.reindex(share_pivot.index)

            date_labels = [str(pd.to_datetime(d).strftime("%d-%m")) for d in dates]

            return {
                "dates": dates,
                "date_labels": date_labels,
                "share_df": share_pivot,
                "hist_df": hist_pivot,
            }
        except Exception:
            return {}


def query_rs_leadership_data(db_path: Path, level: str = "Sector") -> pd.DataFrame:
    """Fetch average RS rank at T0 vs T-5 for the RS Leadership chart."""
    with duckdb.connect(str(db_path), read_only=True) as db:
        try:
            dates = [str(r[0])[:10] for r in db.execute(
                "SELECT DISTINCT trade_date FROM sector_rotation WHERE level = ? ORDER BY trade_date DESC LIMIT 6",
                [level],
            ).fetchall()]
            if len(dates) < 2:
                return pd.DataFrame()
            t0, t5 = dates[0], dates[-1]
            sql = f"""
            SELECT
                r0.group_name,
                round(r0.rs_percentile, 1) AS rs_t0,
                round(coalesce(r5.rs_percentile, r0.rs_percentile), 1) AS rs_t5,
                round(r0.rs_percentile - coalesce(r5.rs_percentile, r0.rs_percentile), 1) AS rs_change
            FROM sector_rotation r0
            LEFT JOIN sector_rotation r5 ON r0.group_name = r5.group_name AND r0.level = r5.level AND r5.trade_date = '{t5}'
            WHERE r0.level = ? AND r0.trade_date = '{t0}'
            ORDER BY r0.rs_percentile DESC
            """
            return db.execute(sql, [level]).fetchdf()
        except Exception:
            return pd.DataFrame()


def build_sector_board_page(
    db_path: Path,
    *,
    copy_text: Callable[[str, str], None] | None = None,
    table_from_df: Callable[..., Any] | None = None,
) -> None:
    db_path = Path(db_path)

    state = {
        "level": "Sector",
        "timeframe": "Daily",
        "active_section": "matrix",
        "selected_group": "",
        "selected_index": "",
        "thematic_filter": "All",
    }

    with ui.column().classes("w-full mp-sector-page gap-4"):
        # Header with As-of and Status
        st = load_market_status(db_path, db_path.parent / "status.json")
        with ui.row().classes("w-full items-center justify-between gap-3 flex-wrap border-b border-[var(--mp-border)] pb-2"):
            with ui.column().classes("gap-0"):
                ui.label("Sector Rotation & Money Flow").classes("text-xl font-bold text-[var(--mp-text)]")
                ui.label("Institutional turnover distribution, 52-week high counts, trend momentum, 15-session heatmaps, and leadership.").classes("text-xs text-[var(--mp-muted)]")

            with ui.row().classes("items-center gap-3"):
                if not st.actionable:
                    ui.label(non_actionable_message(st)).classes("mp-badge mp-bad text-xs")
                else:
                    ui.label(f"EOD · {st.database_date or 'Live'}").classes("text-xs text-[var(--mp-muted)]")

        # Controls & Section Nav Toolbar
        with ui.row().classes("w-full items-center justify-between gap-3 flex-wrap mp-toolbar"):
            with ui.row().classes("items-center gap-2"):
                ui.label("Scope:").classes("text-xs font-semibold text-[var(--mp-text-muted)]")
                level_toggle = ui.toggle(
                    {"Sector": "Sector (22)", "Industry": "Industry (58)"},
                    value=state["level"]
                ).props("dense unelevated").classes("mp-toggle text-xs")

                timeframe_toggle = ui.toggle(
                    ["Daily", "Weekly"],
                    value=state["timeframe"]
                ).props("dense unelevated").classes("mp-toggle text-xs ml-2")

            with ui.row().classes("items-center gap-1"):
                section_tabs = ui.toggle(
                    {
                        "matrix": "Money Flow & Breadth",
                        "breadth_52w": "52W High Radar",
                        "heatmaps": "15-Day Heatmaps",
                        "rs_leadership": "RS Leadership",
                        "indices": "Thematic & Sectoral (44)",
                    },
                    value=state["active_section"]
                ).props("dense unelevated").classes("mp-toggle text-xs")

        # Dynamic Content Container
        content_host = ui.column().classes("w-full gap-4")

        # Drilldown Container (Persistent at bottom)
        drilldown_host = ui.column().classes("w-full mt-2 border-t border-[var(--mp-border)] pt-4")

        def select_group(group_name: str) -> None:
            state["selected_group"] = group_name
            state["selected_index"] = ""
            render_drilldown()

        def select_index(index_name: str) -> None:
            state["selected_index"] = index_name
            state["selected_group"] = ""
            render_drilldown()

        def _quick_toggle_wl_symbol(sym: str) -> None:
            sym = (sym or "").strip().upper()
            if not sym:
                return
            try:
                from App.ui.stock_drawer import toggle_watchlist_symbol
            except ModuleNotFoundError:
                from ui.stock_drawer import toggle_watchlist_symbol  # type: ignore
            try:
                added = toggle_watchlist_symbol(db_path, 1, sym)
                if added:
                    ui.notify(f"★ Added {sym} to Watchlist (WL1)", type="positive", color="amber-9")
                else:
                    ui.notify(f"Removed {sym} from Watchlist (WL1)", type="info")
            except Exception as exc:
                ui.notify(f"Watchlist error: {exc}", type="negative")

        def render_drilldown() -> None:
            drilldown_host.clear()
            if not state["selected_group"] and not state["selected_index"]:
                return

            if state.get("selected_index"):
                idx_name = state["selected_index"]
                user_db_path = db_path.parent / "marketpulse_user.duckdb"
                sub = get_index_constituents(db_path, user_db_path, idx_name)
                with drilldown_host:
                    with ui.row().classes("w-full items-center justify-between gap-2 mb-2"):
                        with ui.row().classes("items-center gap-2"):
                            ui.label(f"Constituent Stocks · {idx_name} ({len(sub)} Stocks)").classes("text-base font-bold text-[var(--mp-text)]")
                            ui.label("(Mapped Stocks · Click star to toggle WL1 · Click symbol for Stock 360)").classes("text-xs text-[var(--mp-muted)]")
                        ui.button("Close Drilldown", on_click=lambda: select_index("")).props("flat dense").classes("text-xs text-[var(--mp-muted)]")

                    if sub.empty:
                        ui.label(f"No active constituents mapped for {idx_name}.").classes("text-xs text-[var(--mp-muted)]")
                    else:
                        display_cols = [c for c in ["symbol", "company_name", "close_price", "day_pct", "rs_percentile", "turnover_cr", "theme"] if c in sub.columns]
                        table_data = sub[display_cols].copy()
                        table_data["close_price"] = table_data["close_price"].map(lambda x: f"₹{x:,.2f}" if pd.notna(x) else "—")
                        table_data["day_pct"] = table_data["day_pct"].map(lambda x: f"{x:+.2f}%" if pd.notna(x) else "—")
                        table_data["rs_percentile"] = table_data["rs_percentile"].map(lambda x: f"{x:.0f}" if pd.notna(x) else "—")
                        table_data["turnover_cr"] = table_data["turnover_cr"].map(lambda x: f"₹{x:,.1f} Cr" if pd.notna(x) else "—")

                        cols_def = [get_quasar_column_def(c) for c in display_cols]
                        with ui.element("div").classes("w-full mp-table-scroll"):
                            with ui.table(columns=cols_def, rows=table_data.to_dict("records"), pagination=15).classes("w-full mp-table") as t:
                                t.add_slot(
                                    "body-cell-symbol",
                                    """
                                    <q-td :props="props" class="symbol-col mp-sticky-col">
                                        <div class="mp-symbol-cell">
                                            <button type="button" class="mp-symbol-star" @click.stop="$parent.$emit('quick_wl', props.value)" title="Quick add/remove from Watchlist (WL1)">★</button>
                                            <q-btn flat dense no-caps size="sm" color="primary" class="mp-symbol" :label="props.value" @click="$parent.$emit('open_stock', props.value)" />
                                            <q-btn dense flat no-caps class="mp-symbol-open" @click.stop="$parent.$emit('open_stock', props.value)" title="Open stock box">↗</q-btn>
                                        </div>
                                    </q-td>
                                    """
                                )
                                t.on("open_stock", lambda e: open_stock_360_modal(db_path, str(e.args)))
                                t.on("quick_wl", lambda e: _quick_toggle_wl_symbol(str(e.args)))
                return

            grp = state["selected_group"]
            is_weekly = state["timeframe"] == "Weekly"
            with drilldown_host:
                with ui.row().classes("w-full items-center justify-between gap-2 mb-2"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(f"Constituent Stocks · {grp}").classes("text-base font-bold text-[var(--mp-text)]")
                        mode_lbl = "Sorted by Weekly Momentum (5D %)" if is_weekly else "Sorted by Turnover"
                        ui.label(f"({mode_lbl}) · Click star to toggle WL1 · Click symbol for Stock 360").classes("text-xs text-[var(--mp-muted)]")
                    ui.button("Close Drilldown", on_click=lambda: select_group("")).props("flat dense").classes("text-xs text-[var(--mp-muted)]")

                mv = movers(db_path)
                col = "sector" if state["level"] == "Sector" else "industry"
                if not mv.empty and col in mv.columns:
                    sort_key = "week_pct" if is_weekly else ("t_o_today" if "t_o_today" in mv.columns else "turnover_cr")
                    sub = mv[mv[col].astype(str).str.casefold() == grp.casefold()].sort_values(sort_key, ascending=False)
                    if sub.empty:
                        ui.label(f"No active constituents found for {grp} in latest session.").classes("text-xs text-[var(--mp-muted)]")
                    else:
                        if "t_o_today" in sub.columns and "turnover_cr" not in sub.columns:
                            sub["turnover_cr"] = sub["t_o_today"]
                        display_cols = [c for c in ["symbol", "close_price", "day_pct", "week_pct", "month_pct", "turnover_cr", "away_52w_high_pct", "rvol", "rs_percentile", "market_cap_cr"] if c in sub.columns]
                        table_data = sub[display_cols].copy()
                        table_data["close_price"] = table_data["close_price"].map(lambda x: f"₹{x:,.2f}" if pd.notna(x) else "—")
                        table_data["day_pct"] = table_data["day_pct"].map(lambda x: f"{x:+.2f}%" if pd.notna(x) else "—")
                        table_data["week_pct"] = table_data["week_pct"].map(lambda x: f"{x:+.1f}%" if pd.notna(x) else "—")
                        table_data["month_pct"] = table_data["month_pct"].map(lambda x: f"{x:+.1f}%" if pd.notna(x) else "—")
                        table_data["turnover_cr"] = table_data["turnover_cr"].map(lambda x: f"₹{x:,.1f} Cr" if pd.notna(x) else "—")
                        table_data["away_52w_high_pct"] = table_data["away_52w_high_pct"].map(lambda x: f"{x:+.1f}%" if pd.notna(x) else "—")
                        table_data["rvol"] = table_data["rvol"].map(lambda x: f"{x:.2f}x" if pd.notna(x) else "—")
                        table_data["rs_percentile"] = table_data["rs_percentile"].map(lambda x: f"{x:.0f}" if pd.notna(x) else "—")
                        table_data["market_cap_cr"] = table_data["market_cap_cr"].map(lambda x: f"₹{x:,.0f} Cr" if pd.notna(x) else "—")

                        cols_def = [get_quasar_column_def(c) for c in display_cols]
                        with ui.element("div").classes("w-full mp-table-scroll"):
                            with ui.table(columns=cols_def, rows=table_data.to_dict("records"), pagination=15).classes("w-full mp-table") as t:
                                t.add_slot(
                                    "body-cell-symbol",
                                    """
                                    <q-td :props="props" class="symbol-col mp-sticky-col">
                                        <div class="mp-symbol-cell">
                                            <button type="button" class="mp-symbol-star" @click.stop="$parent.$emit('quick_wl', props.value)" title="Quick add/remove from Watchlist (WL1)">★</button>
                                            <q-btn flat dense no-caps size="sm" color="primary" class="mp-symbol" :label="props.value" @click="$parent.$emit('open_stock', props.value)" />
                                            <q-btn dense flat no-caps class="mp-symbol-open" @click.stop="$parent.$emit('open_stock', props.value)" title="Open stock box">↗</q-btn>
                                        </div>
                                    </q-td>
                                    """
                                )
                                t.on("open_stock", lambda e: open_stock_360_modal(db_path, str(e.args)))
                                t.on("quick_wl", lambda e: _quick_toggle_wl_symbol(str(e.args)))

        def render_section() -> None:
            content_host.clear()
            sec = state["active_section"]
            lvl = state["level"]
            is_weekly = state["timeframe"] == "Weekly"

            with content_host:
                if is_weekly:
                    with ui.row().classes("w-full items-center gap-2 bg-[var(--mp-primary-bg)] border border-[var(--mp-primary)]/40 px-3 py-1.5 rounded-md mb-1"):
                        ui.icon("calendar_view_week", color="warning").classes("text-sm")
                        ui.label("Weekly Mode Active: Ranking, return trends, and constituent performance reflect 5-day rolling weekly momentum.").classes("text-xs font-semibold text-[var(--mp-primary)]")

                index_sessions = query_index_session_count(db_path)
                if not vs_nifty_is_displayable(index_sessions):
                    with ui.row().classes("w-full items-center gap-2 bg-amber-950/40 border border-amber-500/30 px-3 py-1.5 rounded-md mb-1"):
                        ui.label("vs-Nifty: insufficient index history").classes("text-xs font-semibold text-amber-300")

                if sec == "matrix":
                    # ==================== 1. MONEY FLOW & ROTATION MATRIX ====================
                    res = query_sector_rotation_overview(db_path, level=lvl)
                    df = res.get("leaderboard", pd.DataFrame())
                    index_sessions = int(res.get("index_sessions") or index_sessions)

                    if df.empty:
                        ui.label("No sector rotation records found.").classes("text-sm text-[var(--mp-muted)]")
                        return

                    if "rotation_rank" in df.columns:
                        df["rs_rank"] = df["rotation_rank"]

                    if is_weekly and "return_5d_pct" in df.columns:
                        # Re-sort table by weekly return in weekly mode
                        df = df.sort_values(by="return_5d_pct", ascending=False).reset_index(drop=True)
                        df["rotation_rank"] = range(1, len(df) + 1)
                        df["rs_rank"] = df["rotation_rank"]

                    # Top Focus Cards Row
                    top_focus = res.get("top_focus", [])
                    if top_focus:
                        with ui.row().classes("w-full gap-3 flex-wrap mb-2"):
                            for item in top_focus[:4]:
                                grp_name = str(item.get("group_name", "—"))
                                state_str = str(item.get("rotation_state", "Neutral"))
                                tone = "emerald" if state_str in ("Leading", "Improving") else "amber" if state_str == "Weakening" else "slate"
                                with ui.card().classes(
                                    f"p-3 rounded-lg bg-[var(--mp-surface-raised)] border border-{tone}-500/30 flex-1 min-w-[220px] cursor-pointer hover:border-[var(--mp-primary)] transition-all"
                                ).on("click", lambda _, g=grp_name: select_group(g)):
                                    with ui.row().classes("w-full items-center justify-between"):
                                        ui.label(grp_name).classes("font-bold text-sm text-[var(--mp-text)] truncate")
                                        ui.label(state_str.upper()).classes(f"mp-badge mp-{tone} text-[10px]")
                                    with ui.row().classes("w-full items-center justify-between mt-2 text-xs"):
                                        rank_lbl = f"Wk Rank #{int(item.get('rotation_rank') or 0)}" if is_weekly else f"Rank #{int(item.get('rotation_rank') or 0)}"
                                        ui.label(rank_lbl).classes("font-semibold")
                                        chg = _safe_float(item.get("rank_change_5d"))
                                        ui.label(f"{chg:+.0f} 5D").classes("text-emerald-400" if chg > 0 else "text-rose-400" if chg < 0 else "text-slate-400")
                                    with ui.row().classes("w-full items-center justify-between text-xs text-[var(--mp-muted)] mt-1"):
                                        ui.label(f"Share {_safe_float(item.get('turnover_share_pct')):.1f}%")
                                        n_52 = int(item.get("near_52w_highs") or 0)
                                        ui.label(f"52W: {n_52}").classes("font-bold text-emerald-400 font-mono")
                                        ret_5d = _fmt_pct(item.get('return_5d_pct'))
                                        ui.label(f"5D {ret_5d}").classes("font-bold text-amber-400" if is_weekly else "")

                    # Visual Panels: Return Trend and Heatmap
                    trend = group_trend(db_path, str(lvl.lower()), top_n=6, days=21)
                    if not trend.empty:
                        with ui.element("div").classes("mp-sector-visuals w-full grid grid-cols-1 lg:grid-cols-2 gap-3 mb-3"):
                            chart_title = "5-Day Rolling Trend" if is_weekly else "Return Trend"
                            chart_sub = "Top groups by weekly return · 21 sessions" if is_weekly else "Top groups by turnover · 21 sessions"
                            val_col = "week_pct" if (is_weekly and "week_pct" in trend.columns) else "day_pct"
                            with chart_panel(chart_title, chart_sub, tone="info"):
                                grouped_line_chart(trend, date_col="trade_date", group_col="grp", value_col=val_col)
                            with chart_panel("Return Heatmap", "Group returns with tile intensity following signed movement", tone="neutral"):
                                return_heatmap(df.rename(columns={"group_name": "grp"}), name_col="grp", value_col="return_5d_pct")

                    # Main Ranking Table
                    cols = [
                        get_quasar_column_def("rotation_rank", label_override="WK RANK" if is_weekly else "RANK"),
                        get_quasar_column_def("group_name", width_override=200),
                        get_quasar_column_def("rotation_state"),
                        get_quasar_column_def("turnover_1d_cr", label_override="TURNOVER"),
                        get_quasar_column_def("turnover_share_pct", label_override="T/O SHARE"),
                        get_quasar_column_def("turnover_expansion", label_override="VS 20D"),
                        get_quasar_column_def("near_52w_highs", label_override="NEAR 52W"),
                        get_quasar_column_def("vcp_candidates", label_override="VCP SETUPS"),
                        get_quasar_column_def("above_50ema_pct", label_override=">50 EMA"),
                        get_quasar_column_def("above_200ema_pct", label_override=">200 EMA"),
                        get_quasar_column_def("return_5d_pct", label_override="★ 5D % (WK)" if is_weekly else "5D %"),
                        get_quasar_column_def("return_1m_pct", label_override="1M %"),
                        get_quasar_column_def("rs_vs_nifty_21d", label_override="21D VS NIFTY", width_override=180),
                        get_quasar_column_def("rs_vs_nifty_63d", label_override="63D VS NIFTY", width_override=180),
                        get_quasar_column_def("rs_percentile", label_override="RS"),
                        get_quasar_column_def("top_leaders", width_override=260, sortable=False),
                    ]

                    # Prepare display records
                    vs_nifty_aliased = "rs_vs_nifty_21d" in df.columns
                    records = []
                    for _, r in df.iterrows():
                        n_stocks = int(r.get("stocks") or 0)
                        n_52w = int(r.get("near_52w_highs") or 0)
                        pct_52w = f" ({n_52w * 100 // n_stocks}%)" if n_stocks > 0 and n_52w > 0 else ""
                        n_vcp = int(r.get("vcp_candidates") or 0)
                        rec = {
                            "rotation_rank": int(r.get("rotation_rank") or 99),
                            "rs_rank": int(r.get("rotation_rank") or 99),
                            "group_name": str(r.get("group_name") or ""),
                            "rotation_state": str(r.get("rotation_state") or "Neutral"),
                            "turnover_1d_cr": f"₹{_safe_float(r.get('turnover_1d_cr')) / 1000:,.1f}k Cr" if _safe_float(r.get('turnover_1d_cr')) >= 1000 else f"₹{_safe_float(r.get('turnover_1d_cr')):,.0f} Cr",
                            "turnover_share_pct": f"{_safe_float(r.get('turnover_share_pct')):.1f}%",
                            "turnover_expansion": f"{_safe_float(r.get('turnover_expansion')):,.2f}x",
                            "near_52w_highs": f"{n_52w}{pct_52w}" if n_52w > 0 else "0",
                            "vcp_candidates": str(n_vcp) if n_vcp > 0 else "0",
                            "above_50ema_pct": f"{_safe_float(r.get('above_50ema_pct')):.0f}%",
                            "above_200ema_pct": f"{_safe_float(r.get('above_200ema_pct')):.0f}%",
                            "return_5d_pct": _fmt_pct(r.get("return_5d_pct")),
                            "return_1m_pct": (
                                _fmt_vs_nifty(r.get("rs_vs_nifty_21d"), index_sessions=index_sessions)
                                if vs_nifty_aliased
                                else _fmt_pct(r.get("return_1m_pct"))
                            ),
                            "rs_vs_nifty_21d": _fmt_vs_nifty(
                                r.get("rs_vs_nifty_21d") if "rs_vs_nifty_21d" in df.columns else None,
                                index_sessions=index_sessions,
                            ),
                            "rs_vs_nifty_63d": _fmt_vs_nifty(
                                r.get("rs_vs_nifty_63d") if "rs_vs_nifty_63d" in df.columns else None,
                                index_sessions=index_sessions,
                            ),
                            "rs_percentile": f"{_safe_float(r.get('rs_percentile')):.0f}",
                            "top_leaders": str(r.get("top_leaders") or ""),
                        }
                        records.append(rec)

                    with ui.element("div").classes("w-full mp-table-scroll"):
                        with ui.table(columns=cols, rows=records, pagination=25).classes("w-full mp-table") as matrix_tbl:
                            matrix_tbl.add_slot(
                                "body-cell-group_name",
                                """
                                <q-td :props="props" class="mp-sticky-col">
                                    <q-btn flat dense no-caps size="sm" color="white" :label="props.value" @click="$parent.$emit('select_group', props.value)" />
                                </q-td>
                                """,
                            )
                            matrix_tbl.add_slot(
                                "body-cell-rotation_state",
                                """
                                <q-td :props="props">
                                    <q-badge :color="props.value === 'Leading' ? 'positive' : props.value === 'Improving' ? 'info' : props.value === 'Weakening' ? 'warning' : 'grey'" :label="props.value" />
                                </q-td>
                                """,
                            )
                            matrix_tbl.on("select_group", lambda e: select_group(str(e.args)))

                elif sec == "breadth_52w":
                    # ==================== 52-WEEK HIGH & BREADTH RADAR ====================
                    res = query_sector_rotation_overview(db_path, level=lvl)
                    df = res.get("leaderboard", pd.DataFrame())
                    if df.empty:
                        ui.label("No sector records found.").classes("text-sm text-[var(--mp-muted)]")
                        return

                    # Sort by near_52w_highs descending
                    df_52w = df.sort_values(by="near_52w_highs", ascending=False).reset_index(drop=True)

                    top_52w = df_52w.iloc[0] if not df_52w.empty else {}
                    top_to = df.sort_values(by="turnover_1d_cr", ascending=False).iloc[0] if not df.empty else {}
                    top_vcp = df.sort_values(by="vcp_candidates", ascending=False).iloc[0] if not df.empty else {}
                    top_ab50 = df.sort_values(by="above_50ema_pct", ascending=False).iloc[0] if not df.empty else {}

                    with ui.row().classes("w-full gap-3 flex-wrap mb-3"):
                        # Card 1: 52W High Leader
                        with ui.card().classes("p-3 rounded-lg bg-[var(--mp-surface-raised)] border border-emerald-500/40 flex-1 min-w-[220px]"):
                            ui.label("🏔️ MOST 52W HIGHS").classes("text-[10px] font-bold text-emerald-400 tracking-wider uppercase")
                            ui.label(f"{top_52w.get('group_name', '—')}").classes("text-base font-bold text-[var(--mp-text)] truncate mt-1")
                            with ui.row().classes("w-full items-center justify-between mt-1 text-xs"):
                                ui.label(f"{int(top_52w.get('near_52w_highs', 0))} stocks near 52W").classes("font-mono font-bold text-emerald-400")
                                ui.label(f"of {int(top_52w.get('stocks', 0))} total").classes("text-[var(--mp-muted)]")

                        # Card 2: Turnover Dominance
                        with ui.card().classes("p-3 rounded-lg bg-[var(--mp-surface-raised)] border border-sky-500/40 flex-1 min-w-[220px]"):
                            ui.label("🏛️ TURNOVER LEADER").classes("text-[10px] font-bold text-sky-400 tracking-wider uppercase")
                            ui.label(f"{top_to.get('group_name', '—')}").classes("text-base font-bold text-[var(--mp-text)] truncate mt-1")
                            with ui.row().classes("w-full items-center justify-between mt-1 text-xs"):
                                to_val = _safe_float(top_to.get('turnover_1d_cr', 0))
                                ui.label(f"₹{to_val:,.0f} Cr ({_safe_float(top_to.get('turnover_share_pct', 0)):.1f}%)").classes("font-mono font-bold text-sky-400")
                                ui.label(f"{_safe_float(top_to.get('turnover_expansion', 1)):.2f}x vs 20D").classes("text-[var(--mp-muted)]")

                        # Card 3: VCP Base Density
                        with ui.card().classes("p-3 rounded-lg bg-[var(--mp-surface-raised)] border border-purple-500/40 flex-1 min-w-[220px]"):
                            ui.label("🌀 VCP SETUP DENSITY").classes("text-[10px] font-bold text-purple-400 tracking-wider uppercase")
                            ui.label(f"{top_vcp.get('group_name', '—')}").classes("text-base font-bold text-[var(--mp-text)] truncate mt-1")
                            with ui.row().classes("w-full items-center justify-between mt-1 text-xs"):
                                ui.label(f"{int(top_vcp.get('vcp_candidates', 0))} Coiled Setups").classes("font-mono font-bold text-purple-400")
                                ui.label(f"RS {_safe_float(top_vcp.get('rs_percentile', 0)):.0f}").classes("text-[var(--mp-muted)]")

                        # Card 4: Intermediate Breadth (>50 EMA)
                        with ui.card().classes("p-3 rounded-lg bg-[var(--mp-surface-raised)] border border-amber-500/40 flex-1 min-w-[220px]"):
                            ui.label("📈 INTERMEDIATE BREADTH").classes("text-[10px] font-bold text-amber-400 tracking-wider uppercase")
                            ui.label(f"{top_ab50.get('group_name', '—')}").classes("text-base font-bold text-[var(--mp-text)] truncate mt-1")
                            with ui.row().classes("w-full items-center justify-between mt-1 text-xs"):
                                ui.label(f"{_safe_float(top_ab50.get('above_50ema_pct', 0)):.1f}% > 50 EMA").classes("font-mono font-bold text-amber-400")
                                ui.label(f"{_safe_float(top_ab50.get('above_200ema_pct', 0)):.1f}% > 200").classes("text-[var(--mp-muted)]")

                    # Dedicated 52W High Radar Table
                    with chart_panel(
                        f"52-Week High & Breadth Ranking ({lvl})",
                        "Sectors and industries ranked by leadership breadth: stocks printing/testing 52W highs, VCP setup counts, and EMA health.",
                        tone="good"
                    ):
                        cols_52w = [
                            {"name": "rank_52w", "label": "RANK", "field": "rank_52w", "align": "center", "style": "width:54px;min-width:48px;", "headerStyle": "width:54px;"},
                            get_quasar_column_def("group_name", width_override=210),
                            {"name": "stocks", "label": "STOCKS", "field": "stocks", "align": "center", "style": "width:68px;min-width:60px;"},
                            {"name": "near_52w_highs", "label": "NEAR 52W", "field": "near_52w_highs", "align": "right", "style": "width:88px;min-width:80px;"},
                            {"name": "pct_52w", "label": "52W %", "field": "pct_52w", "align": "right", "style": "width:78px;min-width:70px;"},
                            {"name": "vcp_candidates", "label": "VCP SETUPS", "field": "vcp_candidates", "align": "right", "style": "width:88px;min-width:80px;"},
                            {"name": "above_50ema_pct", "label": "> 50 EMA", "field": "above_50ema_pct", "align": "right", "style": "width:84px;min-width:76px;"},
                            {"name": "above_200ema_pct", "label": "> 200 EMA", "field": "above_200ema_pct", "align": "right", "style": "width:88px;min-width:80px;"},
                            {"name": "turnover_1d_cr", "label": "TURNOVER", "field": "turnover_1d_cr", "align": "right", "style": "width:104px;min-width:92px;"},
                            {"name": "turnover_share_pct", "label": "T/O SHARE", "field": "turnover_share_pct", "align": "right", "style": "width:84px;min-width:76px;"},
                            get_quasar_column_def("top_leaders", width_override=280, sortable=False),
                        ]
                        rows_52w = []
                        for idx, (_, r) in enumerate(df_52w.iterrows(), 1):
                            n_stk = int(r.get("stocks") or 0)
                            n_52 = int(r.get("near_52w_highs") or 0)
                            p_52 = (n_52 / n_stk * 100) if n_stk > 0 else 0.0
                            to_c = _safe_float(r.get("turnover_1d_cr"))
                            rows_52w.append({
                                "rank_52w": idx,
                                "group_name": str(r.get("group_name") or ""),
                                "stocks": n_stk,
                                "near_52w_highs": n_52,
                                "pct_52w": f"{p_52:.1f}%",
                                "vcp_candidates": int(r.get("vcp_candidates") or 0),
                                "above_50ema_pct": f"{_safe_float(r.get('above_50ema_pct')):.1f}%",
                                "above_200ema_pct": f"{_safe_float(r.get('above_200ema_pct')):.1f}%",
                                "turnover_1d_cr": f"₹{to_c / 1000:,.1f}k Cr" if to_c >= 1000 else f"₹{to_c:,.0f} Cr",
                                "turnover_share_pct": f"{_safe_float(r.get('turnover_share_pct')):.1f}%",
                                "top_leaders": str(r.get("top_leaders") or ""),
                            })

                        with ui.element("div").classes("w-full mp-table-scroll"):
                            with ui.table(columns=cols_52w, rows=rows_52w, pagination=25).classes("w-full mp-table") as tbl_52:
                                tbl_52.add_slot(
                                    "body-cell-group_name",
                                    """
                                    <q-td :props="props" class="mp-sticky-col">
                                        <q-btn flat dense no-caps size="sm" color="white" :label="props.value" @click="$parent.$emit('select_group', props.value)" />
                                    </q-td>
                                    """
                                )
                                tbl_52.on("select_group", lambda e: select_group(str(e.args)))

                elif sec == "heatmaps":
                    # ==================== 2. 15-SESSION TURNOVER HEATMAPS ====================
                    hm = query_turnover_heatmaps_data(db_path, level=lvl, days=15)
                    if not hm:
                        ui.label("No turnover history found for heatmaps.").classes("text-sm text-[var(--mp-muted)]")
                        return

                    share_df = hm["share_df"]
                    hist_df = hm["hist_df"]
                    dates = hm["dates"]
                    date_labels = hm["date_labels"]

                    with chart_panel("Share of Total Market Turnover", "Daily sector turnover % of total market over the last 15 trading sessions", tone="info"):
                        # Build heatmap table
                        cols = [get_quasar_column_def("group_name", field="group", width_override=200)]
                        for d, dl in zip(dates, date_labels):
                            cols.append({
                                "name": str(d),
                                "label": dl,
                                "field": str(d),
                                "align": "right",
                                "style": "width:76px;min-width:70px;white-space:nowrap;",
                                "headerStyle": "width:76px;min-width:70px;white-space:normal;line-height:1.2;",
                                "classes": "numeric",
                                "headerClasses": "numeric mp-th",
                            })

                        rows = []
                        for grp, row in share_df.iterrows():
                            rec = {"group": str(grp)}
                            for d in dates:
                                val = row.get(d, 0.0)
                                rec[str(d)] = f"{val:.1f}%" if val > 0 else "—"
                            rows.append(rec)

                        with ui.element("div").classes("w-full mp-table-scroll"):
                            with ui.table(columns=cols, rows=rows, pagination=22).classes("w-full mp-table text-xs") as tbl:
                                tbl.add_slot(
                                    "body-cell-group",
                                    """
                                    <q-td :props="props" class="mp-sticky-col">
                                        <q-btn flat dense no-caps size="xs" color="primary" :label="props.value" @click="$parent.$emit('select_group', props.value)" />
                                    </q-td>
                                    """
                                )
                                tbl.on("select_group", lambda e: select_group(str(e.args)))

                    with chart_panel("Turnover vs Own History", "Today's turnover relative to the group's trailing average (>1.0x indicates expansion)", tone="good"):
                        cols_hist = [get_quasar_column_def("group_name", field="group", width_override=200)]
                        for d, dl in zip(dates, date_labels):
                            cols_hist.append({
                                "name": str(d),
                                "label": dl,
                                "field": str(d),
                                "align": "right",
                                "style": "width:76px;min-width:70px;white-space:nowrap;",
                                "headerStyle": "width:76px;min-width:70px;white-space:normal;line-height:1.2;",
                                "classes": "numeric",
                                "headerClasses": "numeric mp-th",
                            })

                        rows_hist = []
                        for grp, row in hist_df.iterrows():
                            rec = {"group": str(grp)}
                            for d in dates:
                                val = row.get(d, 1.0)
                                rec[str(d)] = f"{val:.2f}x"
                            rows_hist.append(rec)

                        with ui.element("div").classes("w-full mp-table-scroll"):
                            with ui.table(columns=cols_hist, rows=rows_hist, pagination=22).classes("w-full mp-table text-xs") as tbl_hist:
                                tbl_hist.add_slot(
                                    "body-cell-group",
                                    """
                                    <q-td :props="props" class="mp-sticky-col">
                                        <q-btn flat dense no-caps size="xs" color="primary" :label="props.value" @click="$parent.$emit('select_group', props.value)" />
                                    </q-td>
                                    """
                                )
                                tbl_hist.on("select_group", lambda e: select_group(str(e.args)))

                elif sec == "rs_leadership":
                    # ==================== 3. RELATIVE STRENGTH LEADERSHIP ====================
                    rs_df = query_rs_leadership_data(db_path, level=lvl)
                    if rs_df.empty:
                        ui.label("No relative strength data found for leadership chart.").classes("text-sm text-[var(--mp-muted)]")
                        return

                    with chart_panel("Relative-Strength Leadership", "Average RS percentile today (T0) vs 5 sessions ago (T-5), sorted by today's strength", tone="info"):
                        cols_rs = [
                            get_quasar_column_def("group_name", width_override=210),
                            get_quasar_column_def("rs", field="rs_t0", label_override="RS TODAY (T0)"),
                            get_quasar_column_def("rs", field="rs_t5", label_override="RS 5D AGO (T-5)"),
                            get_quasar_column_def("rank_change_5d", field="rs_change", label_override="MOMENTUM Δ"),
                        ]
                        records_rs = []
                        for _, r in rs_df.iterrows():
                            chg = _safe_float(r.get("rs_change"))
                            records_rs.append({
                                "group_name": str(r.get("group_name")),
                                "rs_t0": f"{_safe_float(r.get('rs_t0')):.1f}",
                                "rs_t5": f"{_safe_float(r.get('rs_t5')):.1f}",
                                "rs_change": f"{chg:+.1f}",
                            })

                        with ui.element("div").classes("w-full mp-table-scroll"):
                            with ui.table(columns=cols_rs, rows=records_rs, pagination=22).classes("w-full mp-table") as tbl_rs:
                                tbl_rs.add_slot(
                                    "body-cell-group_name",
                                    """
                                    <q-td :props="props" class="mp-sticky-col">
                                        <q-btn flat dense no-caps size="sm" color="primary" :label="props.value" @click="$parent.$emit('select_group', props.value)" />
                                    </q-td>
                                    """
                                )
                                tbl_rs.on("select_group", lambda e: select_group(str(e.args)))

                elif sec == "indices":
                    # ==================== 4. 44 OFFICIAL THEMATIC & SECTORAL INDICES ====================
                    raw_df = build_thematic_leaderboard(db_path)
                    if raw_df.empty:
                        ui.label("No index records available.").classes("text-sm text-[var(--mp-muted)]")
                        return

                    tf_cat = state.get("thematic_filter", "All")
                    if tf_cat != "All":
                        idx_df = raw_df[raw_df["category"] == tf_cat].copy().reset_index(drop=True)
                    else:
                        idx_df = raw_df.copy().reset_index(drop=True)

                    with chart_panel(
                        "44 Official Thematic & Sectoral Indices",
                        "Official NSE Sectoral & Thematic momentum tracking with RSI, EMA stack, and 4-week RS trails",
                        tone="neutral"
                    ):
                        # Filter Row
                        with ui.row().classes("w-full items-center justify-between mb-3 gap-2 flex-wrap"):
                            def _on_filter_changed(val: str) -> None:
                                state["thematic_filter"] = val
                                render_section()

                            ui.toggle(
                                {"All": "All (44)", "Thematic": "Thematic (28)", "Sectoral": "Sectoral (16)"},
                                value=tf_cat,
                                on_change=lambda e: _on_filter_changed(str(e.value))
                            ).props("dense unelevated").classes("mp-toggle text-xs")
                            ui.label("💡 Click any index name to drill down into constituent stocks").classes("text-xs text-[var(--mp-muted)]")

                        cols_idx = [
                            get_quasar_column_def("rank"),
                            get_quasar_column_def("clean_name", label_override="INDEX"),
                            get_quasar_column_def("close_price", label_override="CMP"),
                            get_quasar_column_def("return_1d_pct", label_override="1D %"),
                            get_quasar_column_def("rsi_14", label_override="RS"),
                            get_quasar_column_def("ema_stack", label_override="EMA STACK"),
                            get_quasar_column_def("distance_ema_20_pct", label_override="VS 20EMA"),
                            get_quasar_column_def("return_5d_pct", label_override="5D %"),
                            get_quasar_column_def("return_20d_pct", label_override="20D %"),
                            get_quasar_column_def("rs_trail", label_override="RS TRAIL (4W)"),
                            get_quasar_column_def("trend_state", label_override="STATE"),
                        ]
                        records_idx = []
                        for _, r in idx_df.iterrows():
                            trail = r.get("trail_vals", [50, 50, 50, 50])
                            trail_str = f"{trail[0]} → {trail[1]} → {trail[2]} → {trail[3]}"
                            records_idx.append({
                                "rank": int(r.get("rank") or 0),
                                "index_name": str(r.get("index_name")),
                                "clean_name": str(r.get("clean_name")),
                                "close_price": f"₹{_safe_float(r.get('close_price')):,.2f}",
                                "return_1d_pct": _fmt_pct(r.get("return_1d_pct")),
                                "rsi_14": f"{_safe_float(r.get('rsi_14')):,.1f}",
                                "ema_stack": f"{r.get('stack_count')}/4",
                                "above_10": bool(r.get("above_10")),
                                "above_20": bool(r.get("above_20")),
                                "above_50": bool(r.get("above_50")),
                                "above_200": bool(r.get("above_200")),
                                "distance_ema_20_pct": _fmt_pct(r.get("distance_ema_20_pct")),
                                "return_5d_pct": _fmt_pct(r.get("return_5d_pct")),
                                "return_20d_pct": _fmt_pct(r.get("return_20d_pct")),
                                "rs_trail": trail_str,
                                "trail_vals": trail,
                                "net_momentum": int(r.get("net_momentum") or 0),
                                "trend_state": str(r.get("trend_state") or "Neutral"),
                            })

                        with ui.element("div").classes("w-full mp-table-scroll"):
                            with ui.table(columns=cols_idx, rows=records_idx, pagination=25).classes("w-full mp-table") as tbl_idx:
                                tbl_idx.add_slot(
                                    "body-cell-clean_name",
                                    """
                                    <q-td :props="props" class="mp-sticky-col">
                                        <q-btn flat dense no-caps size="sm" color="white" :label="props.value" @click="$parent.$emit('select_index', props.row.index_name)">
                                            <q-tooltip class="text-xs">Click to view constituent stocks</q-tooltip>
                                        </q-btn>
                                    </q-td>
                                    """
                                )
                                tbl_idx.add_slot(
                                    "body-cell-ema_stack",
                                    """
                                    <q-td :props="props">
                                        <div class="row items-center justify-center q-gutter-xs text-[11px] font-mono">
                                            <span :class="props.row.above_10 ? 'text-emerald-400 font-bold bg-emerald-950/60 px-1 rounded' : 'text-zinc-600 px-1'">10</span>
                                            <span :class="props.row.above_20 ? 'text-emerald-400 font-bold bg-emerald-950/60 px-1 rounded' : 'text-zinc-600 px-1'">20</span>
                                            <span :class="props.row.above_50 ? 'text-emerald-400 font-bold bg-emerald-950/60 px-1 rounded' : 'text-zinc-600 px-1'">50</span>
                                            <span :class="props.row.above_200 ? 'text-emerald-400 font-bold bg-emerald-950/60 px-1 rounded' : 'text-zinc-600 px-1'">200</span>
                                        </div>
                                    </q-td>
                                    """
                                )
                                tbl_idx.add_slot(
                                    "body-cell-rs_trail",
                                    """
                                    <q-td :props="props">
                                        <div class="row items-center justify-center text-xs font-mono">
                                            <span>{{ props.row.trail_vals[0] }}</span>
                                            <span :class="props.row.trail_vals[1] > props.row.trail_vals[0] ? 'text-emerald-400 font-bold' : props.row.trail_vals[1] < props.row.trail_vals[0] ? 'text-rose-400 font-bold' : 'text-zinc-500'"> &rarr; </span>
                                            <span>{{ props.row.trail_vals[1] }}</span>
                                            <span :class="props.row.trail_vals[2] > props.row.trail_vals[1] ? 'text-emerald-400 font-bold' : props.row.trail_vals[2] < props.row.trail_vals[1] ? 'text-rose-400 font-bold' : 'text-zinc-500'"> &rarr; </span>
                                            <span>{{ props.row.trail_vals[2] }}</span>
                                            <span :class="props.row.trail_vals[3] > props.row.trail_vals[2] ? 'text-emerald-400 font-bold' : props.row.trail_vals[3] < props.row.trail_vals[2] ? 'text-rose-400 font-bold' : 'text-zinc-500'"> &rarr; </span>
                                            <span class="font-bold text-white">{{ props.row.trail_vals[3] }}</span>
                                            <span :class="props.row.net_momentum >= 0 ? 'text-emerald-400 bg-emerald-950/60' : 'text-rose-400 bg-rose-950/60'" class="ml-1 text-[10px] px-1 rounded font-bold">
                                                {{ props.row.net_momentum >= 0 ? '+' + props.row.net_momentum : props.row.net_momentum }}
                                            </span>
                                        </div>
                                    </q-td>
                                    """
                                )
                                tbl_idx.add_slot(
                                    "body-cell-trend_state",
                                    """
                                    <q-td :props="props">
                                        <q-badge :color="props.value === 'Leading' ? 'positive' : props.value === 'Improving' ? 'info' : props.value === 'Weakening' ? 'warning' : 'grey'" :label="props.value" />
                                    </q-td>
                                    """
                                )
                                tbl_idx.on("select_index", lambda e: select_index(str(e.args)))

        def _on_level_change(e):
            state["level"] = str(e.value)
            render_section()

        def _on_timeframe_change(e):
            state["timeframe"] = str(e.value)
            render_section()

        def _on_section_change(e):
            state["active_section"] = str(e.value)
            render_section()

        level_toggle.on_value_change(_on_level_change)
        timeframe_toggle.on_value_change(_on_timeframe_change)
        section_tabs.on_value_change(_on_section_change)

        render_section()
