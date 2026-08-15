"""Sector & Industry Leadership Desk — Standard Taxonomy & Next-Gen Tech Thematic Megatrends."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
import pandas as pd
from nicegui import ui

try:
    from App.sector_read_model import LEVEL_COLUMNS, query_sector_deep_dive, query_sector_rotation_overview
    from App.thematic_read_model import NEXTGEN_TECH_UNIVERSE, query_thematic_constituents, query_thematic_overview
    from App.ui.stock_drawer import open_stock_360_modal
except ModuleNotFoundError:
    from sector_read_model import LEVEL_COLUMNS, query_sector_deep_dive, query_sector_rotation_overview  # type: ignore
    from thematic_read_model import NEXTGEN_TECH_UNIVERSE, query_thematic_constituents, query_thematic_overview  # type: ignore
    from ui.stock_drawer import open_stock_360_modal  # type: ignore


def _fmt_pct(v: Any, plus: bool = True) -> str:
    if v is None or pd.isna(v):
        return "-"
    try:
        val = float(v)
        sign = "+" if plus and val > 0 else ""
        return f"{sign}{val:.1f}%"
    except (ValueError, TypeError):
        return "-"


def _fmt_num(v: Any, dec: int = 1) -> str:
    if v is None or pd.isna(v):
        return "-"
    try:
        return f"{float(v):.{dec}f}"
    except (ValueError, TypeError):
        return "-"


def build_sector_intel_page(
    db_path: Path,
    *,
    copy_text: Callable[[str, str], None] | None = None,
) -> None:
    """Render the 10/10 Sector, Industry & Thematic Megatrend Leadership Desk."""
    db_path = Path(db_path)

    # State container
    state = {
        "view_mode": "Thematic",  # "Taxonomy" or "Thematic"
        "level": "Sector",
        "thematic_pillar": "All Pillars",
        "min_mcap": 1000.0,
        "selected_sector": "",
    }

    # Top Header & Mode Toggle
    with ui.row().classes("w-full justify-between items-center mb-3 flex-wrap gap-2"):
        with ui.column().classes("gap-0"):
            ui.label("Sector & Thematic Leadership Desk").classes("text-2xl font-bold text-slate-800 tracking-tight")
            ui.label("Institutional rotation across NSE sectors and Next-Gen AI/Data Center/Semiconductor ecosystems.").classes("text-xs text-slate-500")

        # Mode Selector Pills
        with ui.row().classes("items-center gap-2 flex-wrap"):
            mode_toggle = ui.toggle(
                {
                    "Thematic": "⚡ Next-Gen Tech (AI / DC / Semi)",
                    "Taxonomy": "📊 Standard NSE Taxonomy",
                },
                value=state["view_mode"],
            ).props("dense unelevated rounded toggle-color=teal-8").classes("bg-slate-100 p-1 border border-slate-200 text-xs font-semibold")

            refresh_btn = ui.button("Refresh", icon="refresh").classes("bg-[#01696f] text-white").props("dense unelevated")

    # Main dynamic container
    main_container = ui.column().classes("w-full gap-6")

    def render_content() -> None:
        main_container.clear()
        mode = mode_toggle.value or "Thematic"

        if mode == "Thematic":
            _render_thematic_mode(main_container, db_path, state, copy_text)
        else:
            _render_taxonomy_mode(main_container, db_path, state, copy_text)

    mode_toggle.on_value_change(lambda _: render_content())
    refresh_btn.on_click(render_content)
    render_content()


# =========================================================================
# THEMATIC MEGATREND VIEW (AI / DATA CENTERS / SEMICONDUCTORS / ANCILLARIES)
# =========================================================================

def _render_thematic_mode(
    container: ui.column,
    db_path: Path,
    state: dict[str, Any],
    copy_text: Callable[[str, str], None] | None = None,
) -> None:
    """Render the Next-Gen Tech Thematic Megatrend dashboard."""
    overview = query_thematic_overview(db_path)
    if not overview.get("as_of"):
        with container:
            ui.label("No thematic market data available in database.").classes("text-slate-400 p-8")
        return

    as_of_str = overview["as_of"]
    pillars = overview["pillars"]
    total_stocks = overview["total_stocks"]
    all_symbols = overview["all_symbols"]

    # Calculate overall theme average RS
    theme_avg_rs = sum(p["avg_rs"] * p["stock_count"] for p in pillars) / max(total_stocks, 1)

    with container:
        # 1. Top Summary Banner
        with ui.row().classes("w-full justify-between items-center bg-gradient-to-r from-teal-50 via-slate-50 to-teal-50 p-4 rounded-xl border border-teal-200 shadow-xs"):
            with ui.column().classes("gap-1"):
                with ui.row().classes("items-center gap-2"):
                    ui.label("⚡ NEXT-GEN TECH MEGATREND").classes("text-xs font-bold text-teal-800 tracking-wider bg-teal-100 px-2 py-0.5 rounded")
                    ui.label(f"Session As Of: {as_of_str}").classes("text-xs font-semibold text-slate-600")
                ui.label(f"Tracking {total_stocks} Companies across 8 Pillars • AI Compute, Silicon Design, Data Center Cooling, Lithium Batteries & Liquid Piping").classes("text-xs text-slate-600 font-medium")

            # Quick Metrics & TV Copy Button
            with ui.row().classes("items-center gap-3 flex-wrap"):
                ui.label(f"Ecosystem RS: {_fmt_num(theme_avg_rs, 0)}").classes("text-xs font-bold bg-white border border-teal-200 text-teal-900 px-3 py-1.5 rounded-lg shadow-xs")
                if all_symbols and copy_text:
                    tv_all = ",".join(f"NSE:{s}" for s in all_symbols)
                    ui.button(
                        f"Copy All 70 Thematic Symbols (TV)",
                        icon="content_copy",
                        on_click=lambda t=tv_all: copy_text("Next-Gen Tech Universe", t),
                    ).classes("bg-[#01696f] text-white text-xs font-bold").props("dense unelevated")

        # 2. 8 Sub-Pillar Action Cards
        with ui.column().classes("w-full gap-2 mt-2"):
            with ui.row().classes("items-center gap-2"):
                ui.label("🎯 8 Thematic Value-Chain Pillars").classes("text-lg font-bold text-slate-800 tracking-tight")
                ui.label("(Click any pillar card to filter the constituent stocks table below)").classes("text-xs text-slate-500")

            with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4"):
                for p in pillars:
                    _render_thematic_pillar_card(p, state, db_path, copy_text, on_pillar_click=lambda: render_table_section())

        # 3. Dynamic Constituent Table Container
        table_container = ui.column().classes("w-full gap-3 mt-4")

        def render_table_section() -> None:
            table_container.clear()
            active_pillar = state.get("thematic_pillar", "All Pillars")
            min_mc = float(state.get("min_mcap", 0.0))

            const_df = query_thematic_constituents(db_path, pillar_name=active_pillar if active_pillar != "All Pillars" else None, min_mcap=min_mc, limit=75)

            with table_container:
                with ui.row().classes("w-full justify-between items-center flex-wrap gap-2 pb-2 border-b border-slate-200"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(f"📋 Constituent Stocks:").classes("text-base font-bold text-slate-700")
                        ui.label(active_pillar).classes("text-base font-bold text-[#01696f]")
                        ui.label(f"({len(const_df)} stocks)").classes("text-xs font-semibold text-slate-500")

                    # Pillar filter dropdown & TV copy button
                    with ui.row().classes("items-center gap-2"):
                        pillar_options = ["All Pillars"] + [p["pillar_name"] for p in pillars]
                        pillar_sel = ui.select(pillar_options, value=active_pillar, label="Filter Pillar").classes("w-56").props("dense outlined")
                        pillar_sel.on_value_change(lambda e: _set_pillar(e.value, state, render_table_section))

                        if not const_df.empty and copy_text:
                            sub_tv = ",".join(f"NSE:{s}" for s in const_df["symbol"])
                            ui.button(
                                f"Copy Filtered ({len(const_df)} TV)",
                                icon="content_copy",
                                on_click=lambda t=sub_tv, p=active_pillar: copy_text(f"{p} Symbols", t),
                            ).classes("bg-slate-700 text-white text-xs").props("dense unelevated")

                if const_df.empty:
                    ui.label("No constituent stocks found for selected filter.").classes("text-slate-400 p-4")
                else:
                    _render_thematic_stocks_table(db_path, const_df, copy_text)

        render_table_section()


def _set_pillar(p_name: str, state: dict[str, Any], on_update: Callable[[], None]) -> None:
    state["thematic_pillar"] = p_name
    on_update()


def _render_thematic_pillar_card(
    p: dict[str, Any],
    state: dict[str, Any],
    db_path: Path,
    copy_text: Callable[[str, str], None] | None,
    on_pillar_click: Callable[[], None],
) -> None:
    """Render an individual pillar card with leadership metrics and leader chips."""
    name = p["pillar_name"]
    is_active = state.get("thematic_pillar") == name
    border_cls = "border-2 border-[#01696f] shadow-md bg-teal-50/50" if is_active else "border border-slate-200 hover:border-teal-400 bg-white hover:shadow-sm"

    card = ui.card().classes(f"w-full p-4 rounded-xl {border_cls} cursor-pointer transition-all duration-150")
    with card:
        with ui.row().classes("w-full justify-between items-start"):
            ui.label(name).classes("text-sm font-bold text-slate-800 leading-snug flex-1 pr-1")
            ui.label(f"{p['stock_count']} stocks").classes("text-[10px] font-bold bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded")

        # KPI stats line
        with ui.row().classes("w-full justify-between items-center text-xs text-slate-600 mt-2 py-1.5 border-y border-slate-100"):
            ui.label(f"RS: {_fmt_num(p['avg_rs'], 0)}").classes("font-bold text-slate-800")
            ui.label(f"1M: {_fmt_pct(p['avg_1m_pct'])}").classes(
                "font-bold text-emerald-600" if p.get("avg_1m_pct", 0) > 0 else "font-bold text-rose-600"
            )
            ui.label(f">50 EMA: {_fmt_num(p['breadth_50_pct'], 0)}%").classes("font-semibold text-slate-500")

        # Top Stock Chips
        top_syms = p.get("top_symbols", [])
        if top_syms:
            with ui.column().classes("w-full mt-2 gap-1"):
                ui.label("TOP LEADERS:").classes("text-[10px] font-bold text-slate-400 tracking-wider")
                with ui.row().classes("items-center gap-1.5 flex-wrap"):
                    for sym in top_syms:
                        chip = ui.button(
                            sym,
                            on_click=lambda _, s=sym: open_stock_360_modal(db_path, s, copy_text=copy_text),
                        ).classes("bg-teal-50 hover:bg-teal-100 text-[#01696f] text-xs font-bold px-2 py-0.5 rounded border border-teal-200").props("dense unelevated")

        with ui.row().classes("w-full justify-end mt-2 pt-1 border-t border-slate-100"):
            ui.label("View All Stocks ➔").classes("text-[11px] font-bold text-[#01696f] hover:underline")

    card.on("click", lambda _, n=name: _set_pillar(n, state, on_pillar_click))


def _render_thematic_stocks_table(
    db_path: Path,
    df: pd.DataFrame,
    copy_text: Callable[[str, str], None] | None = None,
) -> None:
    """Render the thematic constituent stocks table with exact role descriptions and Stock 360 modal hooks."""
    cols = [
        {"name": "symbol", "label": "Symbol", "field": "symbol", "align": "left", "sortable": True},
        {"name": "security_name", "label": "Company Name", "field": "security_name", "align": "left"},
        {"name": "pillar", "label": "Pillar", "field": "pillar", "align": "left", "sortable": True},
        {"name": "role_desc", "label": "Role in Ecosystem", "field": "role_desc", "align": "left"},
        {"name": "close_price", "label": "CMP", "field": "close_price", "align": "right", "sortable": True},
        {"name": "return_5d_pct", "label": "5D %", "field": "return_5d_pct", "align": "right", "sortable": True},
        {"name": "return_1m_pct", "label": "1M %", "field": "return_1m_pct", "align": "right", "sortable": True},
        {"name": "rs_percentile", "label": "RS", "field": "rs_percentile", "align": "right", "sortable": True},
        {"name": "rvol", "label": "RVOL", "field": "rvol", "align": "right", "sortable": True},
        {"name": "delivery_pct", "label": "Deliv %", "field": "delivery_pct", "align": "right", "sortable": True},
        {"name": "candidate_state", "label": "Setup State", "field": "candidate_state", "align": "center"},
        {"name": "trigger_price", "label": "Trigger", "field": "trigger_price", "align": "right"},
        {"name": "stop_loss", "label": "Stop Loss", "field": "stop_loss", "align": "right"},
        {"name": "reward_to_risk", "label": "R:R", "field": "reward_to_risk", "align": "right"},
    ]

    rows = []
    for _, s in df.iterrows():
        rows.append({
            "symbol": str(s["symbol"]),
            "security_name": str(s.get("security_name") or s["symbol"]),
            "pillar": str(s.get("pillar") or "Thematic"),
            "role_desc": str(s.get("role_desc") or "Thematic Constituent"),
            "close_price": f"₹{float(s['close_price']):.2f}",
            "return_5d_pct": _fmt_pct(s.get("return_5d_pct")),
            "return_1m_pct": _fmt_pct(s.get("return_1m_pct")),
            "rs_percentile": _fmt_num(s.get("rs_percentile"), 1),
            "rvol": f"{_fmt_num(s.get('rvol'), 1)}x",
            "delivery_pct": f"{_fmt_num(s.get('delivery_pct'), 1)}%",
            "candidate_state": str(s.get("candidate_state") or "Monitor"),
            "trigger_price": f"₹{float(s['trigger_price']):.1f}" if pd.notna(s.get("trigger_price")) else "-",
            "stop_loss": f"₹{float(s['stop_loss']):.1f}" if pd.notna(s.get("stop_loss")) else "-",
            "reward_to_risk": f"{float(s['reward_to_risk']):.1f}x" if pd.notna(s.get("reward_to_risk")) else "-",
        })

    table = (
        ui.table(columns=cols, rows=rows, pagination=25)
        .classes("w-full mp-table")
        .props("dense flat bordered wrap-cells")
    )

    table.add_slot(
        "body-cell-symbol",
        """
        <q-td :props="props">
          <span class="mp-symbol cursor-pointer hover:underline text-[#01696f] font-bold"
                @click.stop="$parent.$emit('stock360', props.row.symbol || props.value)">
            {{ props.value }}
          </span>
          <a class="text-xs text-gray-400 hover:text-teal-600 ml-1" target="_blank"
             :href="'https://www.tradingview.com/chart/?symbol=NSE:' + String(props.value).replace('-', '_')"
             @click.stop>
            ↗
          </a>
        </q-td>
        """,
    )
    table.add_slot(
        "body-cell-candidate_state",
        """
        <q-td :props="props">
          <span :class="{
            'mp-mini-badge mp-state-leading': props.value === 'Ready' || props.value === 'Focus',
            'mp-mini-badge mp-state-emerging': props.value === 'Prepare',
            'mp-mini-badge mp-state-weakening': props.value === 'Observe',
            'mp-mini-badge mp-state-lagging': props.value === 'Blocked' || props.value === 'Monitor'
          }">
            {{ props.value }}
          </span>
        </q-td>
        """,
    )
    table.on(
        "stock360",
        lambda event: open_stock_360_modal(
            db_path,
            event.args if isinstance(event.args, str) else str((event.args or {}).get("symbol") or ""),
            copy_text=copy_text,
        ),
    )


# =========================================================================
# STANDARD NSE TAXONOMY VIEW (SECTOR / BROAD SECTOR / INDUSTRY)
# =========================================================================

def _render_taxonomy_mode(
    container: ui.column,
    db_path: Path,
    state: dict[str, Any],
    copy_text: Callable[[str, str], None] | None = None,
) -> None:
    """Render the standard NSE sector and industry taxonomy dashboard."""
    with container:
        # Toolbar
        with ui.row().classes("w-full justify-between items-center bg-slate-50 p-3 rounded-lg border border-slate-200 flex-wrap gap-2"):
            with ui.row().classes("items-center gap-2"):
                level_select = ui.select(
                    list(LEVEL_COLUMNS.keys()),
                    value=state["level"],
                    label="Taxonomy Level",
                ).classes("w-44").props("dense outlined")

                mcap_input = ui.number(
                    label="Min MCap (Cr)",
                    value=state["min_mcap"],
                    min=0,
                    max=50000,
                    step=500,
                ).classes("w-32").props("dense outlined")

        lvl = level_select.value or "Sector"
        min_mc = float(mcap_input.value or 0.0)

        overview = query_sector_rotation_overview(db_path, level=lvl)
        if not overview["as_of"]:
            ui.label("No sector rotation data available.").classes("text-slate-400 p-8")
            return

        as_of_str = overview["as_of"]
        top_focus_sectors = overview.get("top_focus", [])
        leaderboard_df = overview.get("leaderboard", pd.DataFrame())
        quadrants = overview.get("quadrants", {})

        if not state["selected_sector"] or state["selected_sector"] not in leaderboard_df["group_name"].values:
            if top_focus_sectors:
                state["selected_sector"] = top_focus_sectors[0]["group_name"]
            elif not leaderboard_df.empty:
                state["selected_sector"] = str(leaderboard_df.iloc[0]["group_name"])

        # Summary strip
        with ui.row().classes("w-full justify-between items-center bg-white p-3 rounded-lg border border-slate-200 mt-2"):
            with ui.row().classes("items-center gap-3 flex-wrap"):
                ui.label(f"Session: {as_of_str}").classes("text-xs font-semibold text-slate-600")
                ui.label(f"Groups: {overview['total']}").classes("text-xs text-slate-500")
                with ui.row().classes("gap-1.5 items-center"):
                    ui.label(f"🔥 Leading: {len(quadrants.get('Leading', []))}").classes("text-xs font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200")
                    ui.label(f"🚀 Improving: {len(quadrants.get('Improving', []))}").classes("text-xs font-bold text-blue-700 bg-blue-50 px-2 py-0.5 rounded border border-blue-200")
                    ui.label(f"⚠️ Weakening: {len(quadrants.get('Weakening', []))}").classes("text-xs font-bold text-amber-700 bg-amber-50 px-2 py-0.5 rounded border border-amber-200")
                    ui.label(f"❄️ Lagging: {len(quadrants.get('Lagging', []))}").classes("text-xs font-bold text-slate-600 bg-slate-100 px-2 py-0.5 rounded border border-slate-300")

        # Top Focus Cards
        with ui.column().classes("w-full gap-2 mt-4"):
            ui.label("🎯 Top Focus Sectors Today").classes("text-lg font-bold text-slate-800 tracking-tight")
            with ui.row().classes("w-full gap-4 flex-wrap items-stretch"):
                for item in top_focus_sectors:
                    _render_focus_card(item, state, render_deep_dive, db_path, copy_text)

        # Leaderboard Table
        with ui.column().classes("w-full gap-2 mt-4"):
            ui.label("📊 Complete Sector Leaderboard").classes("text-lg font-bold text-slate-800 tracking-tight")
            _render_leaderboard_table(leaderboard_df, state, render_deep_dive, copy_text)

        # Deep-Dive Section
        deep_dive_container = ui.column().classes("w-full gap-3 mt-6")

        def render_deep_dive() -> None:
            deep_dive_container.clear()
            grp = state.get("selected_sector", "")
            if not grp:
                return

            deep = query_sector_deep_dive(db_path, lvl, grp, min_mcap=min_mc, limit=20)
            g_stats = deep["group_stats"]
            stocks_df = deep["stocks"]
            sub_df = deep["sub_industries"]

            with deep_dive_container:
                with ui.card().classes("w-full p-5 border-2 border-teal-600/30 shadow-md bg-white rounded-xl"):
                    with ui.row().classes("w-full justify-between items-center mb-4 pb-3 border-b border-slate-200 flex-wrap gap-3"):
                        with ui.row().classes("items-center gap-3"):
                            ui.label("🎯 Active Focus:").classes("text-xs font-bold text-slate-400 uppercase tracking-wider")
                            ui.label(grp).classes("text-2xl font-bold text-[#01696f]")
                            r_state = str(g_stats.get("rotation_state") or "Neutral")
                            state_badge_cls = "bg-emerald-100 text-emerald-800 border-emerald-300" if r_state == "Leading" else "bg-blue-100 text-blue-800 border-blue-300" if r_state in ("Emerging", "Improving") else "bg-amber-100 text-amber-800 border-amber-300" if r_state == "Weakening" else "bg-slate-100 text-slate-700 border-slate-300"
                            ui.label(r_state).classes(f"text-xs font-bold px-2.5 py-1 rounded-md border {state_badge_cls}")

                        with ui.row().classes("items-center gap-2 flex-wrap"):
                            if g_stats.get("rs_percentile") is not None:
                                ui.label(f"RS Score: {_fmt_num(g_stats.get('rs_percentile'), 0)}").classes("text-xs font-bold bg-slate-50 border border-slate-200 px-2.5 py-1 rounded shadow-xs text-slate-700")
                            if g_stats.get("return_1m_pct") is not None:
                                ui.label(f"1M Return: {_fmt_pct(g_stats.get('return_1m_pct'))}").classes("text-xs font-bold bg-slate-50 border border-slate-200 px-2.5 py-1 rounded shadow-xs text-slate-700")

                            if not stocks_df.empty and copy_text:
                                sec_tv = ",".join(f"NSE:{s}" for s in stocks_df["symbol"])
                                ui.button(
                                    f"Copy {grp[:15]} Symbols ({len(stocks_df)} TV)",
                                    icon="content_copy",
                                    on_click=lambda t=sec_tv, g=grp: copy_text(f"{g} Leaders", t),
                                ).classes("bg-[#01696f] text-white text-xs").props("dense unelevated")

                    ui.label(f"Top Stage-2 Breakout Leaders in {grp} (Min MCap ≥ ₹{min_mc:.0f} Cr)").classes("text-xs font-bold text-slate-700 mb-2")
                    if stocks_df.empty:
                        ui.label(f"No stocks meet the ₹{min_mc:.0f} Cr market cap filter in {grp}.").classes("text-xs text-slate-400 py-3")
                    else:
                        _render_sector_stocks_table(db_path, stocks_df, copy_text)

        render_deep_dive()


def _render_focus_card(
    item: dict[str, Any],
    state: dict[str, Any],
    on_select: Callable[[], None],
    db_path: Path,
    copy_text: Callable[[str, str], None] | None = None,
) -> None:
    """Render a prominent high-conviction Focus Sector card with 'Why Focus' rationale and leader chips."""
    name = item["group_name"]
    is_selected = state.get("selected_sector") == name
    badge = item.get("status_badge", "FOCUS")
    badge_color = item.get("status_color", "emerald")

    border_cls = "border-2 border-[#01696f] shadow-md bg-teal-50/40" if is_selected else "border border-slate-200 hover:border-teal-400 bg-white hover:shadow-sm"

    card = ui.card().classes(f"flex-1 min-w-[280px] max-w-[360px] p-4 rounded-xl {border_cls} cursor-pointer transition-all duration-150")
    with card:
        with ui.row().classes("w-full justify-between items-start"):
            with ui.column().classes("gap-0.5 flex-1 pr-2"):
                badge_bg = "bg-emerald-100 text-emerald-800" if badge_color == "emerald" else "bg-blue-100 text-blue-800" if badge_color == "blue" else "bg-amber-100 text-amber-800"
                ui.label(f"● {badge}").classes(f"text-[10px] font-bold px-2 py-0.5 rounded w-fit {badge_bg}")
                ui.label(name).classes("text-sm font-bold text-slate-800 leading-snug mt-1")

            rank_chg = item.get("rank_change_5d", 0)
            if rank_chg > 0:
                ui.label(f"↑ +{int(rank_chg)}").classes("text-xs font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 rounded")
            elif rank_chg < 0:
                ui.label(f"↓ {int(rank_chg)}").classes("text-xs font-bold text-rose-700 bg-rose-50 border border-rose-200 px-1.5 py-0.5 rounded")

        # Quick stats line
        with ui.row().classes("w-full justify-between text-xs text-slate-600 mt-2 py-1 border-y border-slate-100"):
            ui.label(f"Rank #{item['rotation_rank']}").classes("font-semibold")
            ui.label(f"RS: {_fmt_num(item['rs_percentile'], 0)}").classes("font-bold text-slate-800")
            ui.label(f"1M: {_fmt_pct(item['return_1m_pct'])}").classes(
                "font-bold text-emerald-600" if (item.get("return_1m_pct") or 0) > 0 else "font-bold text-rose-600"
            )

        # Plain-English Why Focus
        why_text = item.get("why_focus", "Leading institutional relative strength")
        with ui.column().classes("w-full mt-2 gap-1"):
            ui.label("WHY FOCUS:").classes("text-[10px] font-bold text-slate-400 tracking-wider")
            ui.label(why_text).classes("text-xs text-slate-700 font-medium leading-tight")

        # Leader Stocks Chips
        leaders = item.get("top_leaders", "")
        if leaders:
            with ui.column().classes("w-full mt-2 gap-1"):
                ui.label("TOP STOCKS:").classes("text-[10px] font-bold text-slate-400 tracking-wider")
                with ui.row().classes("items-center gap-1.5 flex-wrap"):
                    for sym in leaders.split(",")[:3]:
                        sym_clean = sym.strip()
                        chip = ui.button(
                            sym_clean,
                            on_click=lambda _, s=sym_clean: open_stock_360_modal(db_path, s, copy_text=copy_text),
                        ).classes("bg-teal-50 hover:bg-teal-100 text-[#01696f] text-xs font-bold px-2 py-0.5 rounded border border-teal-200").props("dense unelevated")

        with ui.row().classes("w-full justify-end mt-3 pt-2 border-t border-slate-100"):
            ui.label("Inspect Sector Breakouts ➔").classes("text-xs font-bold text-[#01696f] hover:underline")

    card.on("click", lambda _, n=name: _select_group(n, state, on_select))


def _select_group(name: str, state: dict[str, Any], on_select: Callable[[], None]) -> None:
    state["selected_sector"] = name
    on_select()


def _render_leaderboard_table(
    heatmap_df: pd.DataFrame,
    state: dict[str, Any],
    on_select: Callable[[], None],
    copy_text: Callable[[str, str], None] | None = None,
) -> None:
    """Render the single comprehensive sector leaderboard table with 'Why Focus' column."""
    if heatmap_df.empty:
        ui.label("No sector performance data available.").classes("text-slate-400 p-4")
        return

    cols = [
        {"name": "rank_display", "label": "Rank & 5D Trend", "field": "rank_display", "align": "center", "sortable": True},
        {"name": "group_name", "label": "Sector / Group Name", "field": "group_name", "align": "left", "sortable": True},
        {"name": "rotation_state", "label": "Status", "field": "rotation_state", "align": "center", "sortable": True},
        {"name": "why_focus", "label": "Why Focus / Thesis", "field": "why_focus", "align": "left"},
        {"name": "rs_percentile", "label": "RS Score", "field": "rs_percentile", "align": "right", "sortable": True},
        {"name": "return_5d_pct", "label": "5D %", "field": "return_5d_pct", "align": "right", "sortable": True},
        {"name": "return_1m_pct", "label": "1M %", "field": "return_1m_pct", "align": "right", "sortable": True},
        {"name": "return_3m_pct", "label": "3M %", "field": "return_3m_pct", "align": "right", "sortable": True},
        {"name": "above_50ema_pct", "label": "% > 50EMA", "field": "above_50ema_pct", "align": "right", "sortable": True},
        {"name": "near_52w_highs", "label": "52W Highs", "field": "near_52w_highs", "align": "center", "sortable": True},
        {"name": "turnover_share_pct", "label": "Vol Share", "field": "turnover_share_pct", "align": "right", "sortable": True},
        {"name": "top_leaders", "label": "Top Leader Stocks", "field": "top_leaders", "align": "left"},
    ]

    rows = []
    for _, r in heatmap_df.iterrows():
        rank = int(r.get("rotation_rank") or 0)
        rank_chg = int(r.get("rank_change_5d") or 0)
        rank_str = f"#{rank}"
        if rank_chg > 0:
            rank_str += f" (↑ +{rank_chg})"
        elif rank_chg < 0:
            rank_str += f" (↓ {rank_chg})"

        rows.append({
            "rank_display": rank_str,
            "group_name": str(r["group_name"]),
            "rotation_state": str(r.get("rotation_state") or ""),
            "why_focus": str(r.get("why_focus") or ""),
            "rs_percentile": _fmt_num(r.get("rs_percentile"), 1),
            "return_5d_pct": _fmt_pct(r.get("return_5d_pct")),
            "return_1m_pct": _fmt_pct(r.get("return_1m_pct")),
            "return_3m_pct": _fmt_pct(r.get("return_3m_pct")),
            "above_50ema_pct": f"{_fmt_num(r.get('above_50ema_pct'), 0)}%",
            "near_52w_highs": int(r.get("near_52w_highs") or 0),
            "turnover_share_pct": f"{_fmt_num(r.get('turnover_share_pct'), 1)}%",
            "top_leaders": str(r.get("top_leaders") or ""),
        })

    table = (
        ui.table(columns=cols, rows=rows, pagination=25)
        .classes("w-full mp-table")
        .props("dense flat bordered wrap-cells")
    )

    table.add_slot(
        "body-cell-group_name",
        """
        <q-td :props="props">
          <span class="font-bold text-[#01696f] cursor-pointer hover:underline text-sm"
                @click.stop="$parent.$emit('selectSector', props.value)">
            {{ props.value }} ➔
          </span>
        </q-td>
        """,
    )
    table.add_slot(
        "body-cell-rotation_state",
        """
        <q-td :props="props">
          <span :class="{
            'mp-mini-badge mp-state-leading': props.value === 'Leading',
            'mp-mini-badge mp-state-emerging': props.value === 'Emerging' || props.value === 'Improving',
            'mp-mini-badge mp-state-weakening': props.value === 'Weakening',
            'mp-mini-badge mp-state-lagging': props.value === 'Lagging'
          }">
            {{ props.value }}
          </span>
        </q-td>
        """,
    )
    table.on("selectSector", lambda e: _select_group(e.args, state, on_select))


def _render_sector_stocks_table(
    db_path: Path,
    stocks_df: pd.DataFrame,
    copy_text: Callable[[str, str], None] | None = None,
) -> None:
    """Render the top breakout stocks table with Stock 360 drawer click handlers."""
    cols = [
        {"name": "symbol", "label": "Symbol", "field": "symbol", "align": "left", "sortable": True},
        {"name": "security_name", "label": "Company Name", "field": "security_name", "align": "left"},
        {"name": "close_price", "label": "CMP", "field": "close_price", "align": "right", "sortable": True},
        {"name": "return_1m_pct", "label": "1M %", "field": "return_1m_pct", "align": "right", "sortable": True},
        {"name": "rs_percentile", "label": "RS", "field": "rs_percentile", "align": "right", "sortable": True},
        {"name": "rvol", "label": "RVOL", "field": "rvol", "align": "right", "sortable": True},
        {"name": "delivery_pct", "label": "Deliv %", "field": "delivery_pct", "align": "right", "sortable": True},
        {"name": "vcp_state", "label": "VCP State", "field": "vcp_state", "align": "center"},
        {"name": "candidate_state", "label": "Setup State", "field": "candidate_state", "align": "center"},
        {"name": "trigger_price", "label": "Trigger", "field": "trigger_price", "align": "right"},
        {"name": "stop_loss", "label": "Stop Loss", "field": "stop_loss", "align": "right"},
        {"name": "reward_to_risk", "label": "R:R", "field": "reward_to_risk", "align": "right"},
        {"name": "why_now", "label": "Why Now Rationale", "field": "why_now", "align": "left"},
    ]

    rows = []
    for _, s in stocks_df.iterrows():
        rows.append({
            "symbol": str(s["symbol"]),
            "security_name": str(s.get("security_name") or s["symbol"]),
            "close_price": f"₹{float(s['close_price']):.2f}",
            "return_1m_pct": _fmt_pct(s.get("return_1m_pct")),
            "rs_percentile": _fmt_num(s.get("rs_percentile"), 1),
            "rvol": f"{_fmt_num(s.get('rvol'), 1)}x",
            "delivery_pct": f"{_fmt_num(s.get('delivery_pct'), 1)}%",
            "vcp_state": str(s.get("vcp_state") or "None"),
            "candidate_state": str(s.get("candidate_state") or "Monitor"),
            "trigger_price": f"₹{float(s['trigger_price']):.1f}" if pd.notna(s.get("trigger_price")) else "-",
            "stop_loss": f"₹{float(s['stop_loss']):.1f}" if pd.notna(s.get("stop_loss")) else "-",
            "reward_to_risk": f"{float(s['reward_to_risk']):.1f}x" if pd.notna(s.get("reward_to_risk")) else "-",
            "why_now": str(s.get("why_now") or "RS Leader"),
        })

    table = (
        ui.table(columns=cols, rows=rows, pagination=15)
        .classes("w-full mp-table")
        .props("dense flat bordered wrap-cells")
    )

    table.add_slot(
        "body-cell-symbol",
        """
        <q-td :props="props">
          <span class="mp-symbol cursor-pointer hover:underline text-[#01696f] font-bold"
                @click.stop="$parent.$emit('stock360', props.row.symbol || props.value)">
            {{ props.value }}
          </span>
          <a class="text-xs text-gray-400 hover:text-teal-600 ml-1" target="_blank"
             :href="'https://www.tradingview.com/chart/?symbol=NSE:' + String(props.value).replace('-', '_')"
             @click.stop>
            ↗
          </a>
        </q-td>
        """,
    )
    table.add_slot(
        "body-cell-candidate_state",
        """
        <q-td :props="props">
          <span :class="{
            'mp-mini-badge mp-state-leading': props.value === 'Ready' || props.value === 'Focus',
            'mp-mini-badge mp-state-emerging': props.value === 'Prepare',
            'mp-mini-badge mp-state-weakening': props.value === 'Observe',
            'mp-mini-badge mp-state-lagging': props.value === 'Blocked' || props.value === 'Monitor'
          }">
            {{ props.value }}
          </span>
        </q-td>
        """,
    )
    table.on(
        "stock360",
        lambda event: open_stock_360_modal(
            db_path,
            event.args if isinstance(event.args, str) else str((event.args or {}).get("symbol") or ""),
            copy_text=copy_text,
        ),
    )
