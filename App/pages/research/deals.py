"""Deal Flow Desk — Institutional Intelligence 2.0 (PR-DEALS 2.0)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
from nicegui import ui

try:
    from App.deals_read_model import query_deals_advanced, query_deals_desk_default
    from App.market_status import load_market_status, non_actionable_message
    from App.ui.shell import empty_state, filter_bar, page_shell
    from App.ui.stock_drawer import open_stock_360_modal
    from App.ui.styles import add_deals_desk_styles
    from App.ui.widgets import compact_kpi_row, deal_flow_card, flow_spark, symbol_chip_strip
    from App.cache_manager import get_cached, set_cached, cache_key
    from Scripts.telegram_deals import build_deals_telegram_report, to_tv_list
except ModuleNotFoundError:
    from deals_read_model import query_deals_advanced, query_deals_desk_default  # type: ignore
    from market_status import load_market_status, non_actionable_message  # type: ignore
    from ui.shell import empty_state, filter_bar, page_shell  # type: ignore
    from ui.stock_drawer import open_stock_360_modal  # type: ignore
    from ui.styles import add_deals_desk_styles  # type: ignore
    from ui.widgets import compact_kpi_row, deal_flow_card, flow_spark, symbol_chip_strip  # type: ignore
    from cache_manager import get_cached, set_cached, cache_key  # type: ignore
    from telegram_deals import build_deals_telegram_report, to_tv_list  # type: ignore


def fetch_deals_telegram_data(db_path: Path, lookback_days: int) -> dict:
    """Fetch cached Telegram deal intelligence and TradingView lists."""
    ckey = cache_key(db_path, None, "deals_tg_report", lookback_days)
    cached = get_cached(ckey)
    if cached is not None:
        return cached
    res = build_deals_telegram_report(lookback_days=lookback_days, min_mcap_cr=1000.0, db_path=db_path)
    set_cached(ckey, res)
    return res


def tradingview_url(symbol: str) -> str:
    tok = str(symbol).strip().upper().replace("-", "_")
    return f"https://www.tradingview.com/chart/?symbol=NSE:{tok}"


def prepare_institution_leaderboard(clients_df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Prepare compact institution rows while retaining the full copy payload."""
    view = clients_df.copy()

    def preview(value: object) -> str:
        if value is None or pd.isna(value):
            return ""
        tokens = [token.strip() for token in str(value).split(",") if token.strip()]
        names = [token.split(":", 1)[1] if ":" in token else token for token in tokens]
        shown = ", ".join(names[:5])
        remaining = len(names) - 5
        return f"{shown} +{remaining} more" if remaining > 0 else shown

    symbol_values = view["symbol_list"] if "symbol_list" in view.columns else pd.Series("", index=view.index)
    view["symbol_preview"] = symbol_values.map(preview)
    view["copy_symbols"] = ""
    columns = [
        "client_name",
        "tier",
        "category",
        "latest_deal_date",
        "buy_value_cr",
        "sell_value_cr",
        "net_value_cr",
        "active_days",
        "copy_symbols",
        "symbol_preview",
    ]
    return view, [column for column in columns if column in view.columns]


def build_deals_page(
    db_path: Path,
    *,
    copy_text: Callable[[str, str], None],
    table_from_df: Callable[..., Any],
    metric_card: Callable[..., Any] | None = None,
) -> None:
    """Institutional Deal Flow Desk 2.0."""
    add_deals_desk_styles()
    page_shell(
        "Institutional Deals",
        "EOD deal flow with PROP, FII, and DII clientele visible",
        eyebrow="Research · Institutional Intelligence",
    )
    deals_status = load_market_status(db_path, Path(db_path).parent / "status.json")
    if not deals_status.actionable:
        ui.label(non_actionable_message(deals_status)).classes("mp-badge mp-bad w-full mt-2")

    hft_state = {"exclude_hft": False}
    confluence_state = {"active": False}
    hub_state = {"lookback_days": 20}

    hub_container = ui.column().classes("w-full mb-3")

    def render_telegram_hub() -> None:
        hub_container.clear()
        with hub_container:
            days = int(hub_state["lookback_days"])
            report = fetch_deals_telegram_data(db_path, days)
            tv_map = report.get("tv_strings", {})
            as_of = report.get("as_of") or "—"
            p_data = report.get("persistence", {})
            c_data = report.get("clientele", {})
            h_data = report.get("highest", {})

            four_plus = p_data.get("four_plus", pd.DataFrame())
            three = p_data.get("three", pd.DataFrame())
            two = p_data.get("two", pd.DataFrame())
            fii = c_data.get("FII", pd.DataFrame())
            dii = c_data.get("DII", pd.DataFrame())
            others = c_data.get("Others", pd.DataFrame())
            prop = c_data.get("PROP", pd.DataFrame())
            top_buys = h_data.get("buys", pd.DataFrame())
            top_sells = h_data.get("sells", pd.DataFrame())

            with ui.card().classes("w-full mp-card p-4 border border-[var(--mp-border)]"):
                # Header row: Title + Lookback selector
                with ui.row().classes("w-full items-center justify-between gap-3 flex-wrap mb-2"):
                    with ui.column().classes("gap-0.5"):
                        with ui.row().classes("items-center gap-2"):
                            ui.label("📡 Institutional Deals Hub · TradingView Exporter").classes("mp-section-title m-0 text-base font-bold")
                            ui.label(f"As of {as_of}").classes("mp-badge mp-pill text-xs")
                        ui.label(f"Direct Telegram-matched breakdown (Persistence, Clientele, Turnover) across last {days} sessions.").classes("text-xs text-[var(--mp-muted)]")

                    # Lookback selector pills
                    with ui.row().classes("items-center gap-1 bg-[var(--mp-surface)] p-1 rounded-lg border border-[var(--mp-border)]"):
                        ui.label("Lookback:").classes("text-xs text-[var(--mp-muted)] px-2 font-medium")
                        for d_val, d_label in [(10, "10 Days"), (20, "20 Days (Default)"), (30, "30 Days")]:
                            is_active = (days == d_val)
                            btn_classes = "mp-primary text-xs" if is_active else "text-xs text-[var(--mp-muted)]"
                            def _make_setter(v: int):
                                def _setter() -> None:
                                    hub_state["lookback_days"] = v
                                    render_telegram_hub()
                                return _setter
                            ui.button(d_label, on_click=_make_setter(d_val)).classes(btn_classes).props("dense unelevated" if is_active else "dense flat")

                # Master Quick Actions
                with ui.row().classes("w-full items-center gap-2 flex-wrap p-2.5 bg-[var(--mp-surface)] rounded-lg border border-[var(--mp-border)] mb-3"):
                    ui.label("⚡ Quick Export:").classes("text-xs font-semibold text-[var(--mp-text)]")
                    if tv_map.get("quality_buckets"):
                        ui.button("📋 Copy Quality Buckets (TV)", on_click=lambda t=tv_map["quality_buckets"]: copy_text("Quality Buckets (TV)", t)).classes("mp-primary text-xs").props("dense")
                    if tv_map.get("all_deal_buckets"):
                        ui.button("📋 Copy All Buckets (TV)", on_click=lambda t=tv_map["all_deal_buckets"]: copy_text("All Deal Buckets (TV)", t)).classes("mp-button text-xs").props("dense outline")
                    if tv_map.get("persistence_buckets"):
                        ui.button("📋 Persistence (TV)", on_click=lambda t=tv_map["persistence_buckets"]: copy_text("Persistence Buckets (TV)", t)).classes("mp-button text-xs").props("dense outline")
                    if tv_map.get("clientele_buckets"):
                        ui.button("📋 Clientele (TV)", on_click=lambda t=tv_map["clientele_buckets"]: copy_text("Clientele Buckets (TV)", t)).classes("mp-button text-xs").props("dense outline")
                    if tv_map.get("four_plus"):
                        ui.button("📋 4+ Days (TV)", on_click=lambda t=tv_map["four_plus"]: copy_text("4+ Deal Days TV", t)).classes("mp-button text-xs").props("dense outline")
                    if tv_map.get("top_buys"):
                        ui.button("📋 Top Buys (TV)", on_click=lambda t=tv_map["top_buys"]: copy_text("Top Buys TV", t)).classes("mp-button text-xs").props("dense outline")
                    if tv_map.get("below_200ema"):
                        ui.button("📋 Below 200EMA (TV)", on_click=lambda t=tv_map["below_200ema"]: copy_text("Below 200EMA TV", t)).classes("mp-button text-xs text-amber-400").props("dense outline")
                    if tv_map.get("below_1000cr"):
                        ui.button("📋 <1000 Cr (TV)", on_click=lambda t=tv_map["below_1000cr"]: copy_text("<1000 Cr TV", t)).classes("mp-button text-xs text-amber-400").props("dense outline")
                    if tv_map.get("prop"):
                        ui.button("📋 PROP Only (TV)", on_click=lambda t=tv_map["prop"]: copy_text("PROP Only TV", t)).classes("mp-button text-xs text-amber-400").props("dense outline")
                    if tv_map.get("all_buys"):
                        ui.button("📋 All Quality Buys (Flat)", on_click=lambda t=tv_map["all_buys"]: copy_text("All Quality Buys (Flat TV)", t)).classes("mp-button text-xs").props("dense outline")

                # 3 Responsive Columns: Persistence | Clientele | Turnover Leaders
                with ui.row().classes("w-full gap-3 items-start flex-wrap lg:flex-nowrap"):
                    # 1. PERSISTENCE
                    with ui.card().classes("flex-1 min-w-[300px] p-3 mp-card border border-[var(--mp-border)]"):
                        with ui.row().classes("w-full items-center justify-between mb-1"):
                            ui.label("🔥 Persistence by Count").classes("text-sm font-bold text-[var(--mp-text)]")
                            if tv_map.get("persistence_buckets"):
                                ui.button("Copy Buckets (TV)", on_click=lambda t=tv_map["persistence_buckets"]: copy_text("Persistence Buckets (TV)", t)).classes("text-xs").props("dense flat")
                        ui.label(f"Quality accumulation across {days} deal sessions (Mcap ≥ 1000 Cr, Above 200 EMA)").classes("text-[11px] text-[var(--mp-muted)] mb-2")

                        # 4+ Deal Days
                        with ui.column().classes("w-full gap-1 p-2 mb-2 bg-[var(--mp-surface)] rounded border border-[var(--mp-border)]"):
                            with ui.row().classes("w-full items-center justify-between"):
                                with ui.row().classes("items-center gap-1.5"):
                                    ui.label("💎 4+ Deal Days").classes("text-xs font-bold text-emerald-400")
                                    ui.label(f"{len(four_plus)} stocks").classes("mp-badge mp-good text-[10px]")
                                if tv_map.get("four_plus"):
                                    ui.button("📋 Copy TV", on_click=lambda t=tv_map["four_plus"]: copy_text("4+ Days TV", t)).classes("text-[11px]").props("dense outline")
                            if four_plus.empty:
                                ui.label("No stocks with 4+ deal days.").classes("text-[11px] text-[var(--mp-muted)]")
                            else:
                                with ui.row().classes("gap-1 flex-wrap mt-1"):
                                    for _, r in four_plus.head(6).iterrows():
                                        sign = "+" if r.get("net_cr", 0) >= 0 else "-"
                                        val = abs(r.get("net_cr", 0))
                                        ui.chip(f"{r['symbol']} ({r['deal_days']}d · {sign}₹{val:,.1f}Cr)").props("dense outline").classes("text-[10px]")

                        # 3 Deal Days
                        with ui.column().classes("w-full gap-1 p-2 mb-2 bg-[var(--mp-surface)] rounded border border-[var(--mp-border)]"):
                            with ui.row().classes("w-full items-center justify-between"):
                                with ui.row().classes("items-center gap-1.5"):
                                    ui.label("⚡ 3 Deal Days").classes("text-xs font-semibold text-blue-400")
                                    ui.label(f"{len(three)} stocks").classes("mp-badge text-[10px]")
                                if tv_map.get("three"):
                                    ui.button("📋 Copy TV", on_click=lambda t=tv_map["three"]: copy_text("3 Days TV", t)).classes("text-[11px]").props("dense outline")
                            if three.empty:
                                ui.label("No stocks with 3 deal days.").classes("text-[11px] text-[var(--mp-muted)]")
                            else:
                                with ui.row().classes("gap-1 flex-wrap mt-1"):
                                    for _, r in three.head(5).iterrows():
                                        sign = "+" if r.get("net_cr", 0) >= 0 else "-"
                                        val = abs(r.get("net_cr", 0))
                                        ui.chip(f"{r['symbol']} ({sign}₹{val:,.1f}Cr)").props("dense outline").classes("text-[10px]")

                        # 2 Deal Days
                        with ui.column().classes("w-full gap-1 p-2 bg-[var(--mp-surface)] rounded border border-[var(--mp-border)]"):
                            with ui.row().classes("w-full items-center justify-between"):
                                with ui.row().classes("items-center gap-1.5"):
                                    ui.label("🎯 2 Deal Days").classes("text-xs font-semibold text-[var(--mp-text)]")
                                    ui.label(f"{len(two)} stocks").classes("mp-badge text-[10px]")
                                if tv_map.get("two"):
                                    ui.button("📋 Copy TV", on_click=lambda t=tv_map["two"]: copy_text("2 Days TV", t)).classes("text-[11px]").props("dense outline")
                            if two.empty:
                                ui.label("No stocks with 2 deal days.").classes("text-[11px] text-[var(--mp-muted)]")
                            else:
                                with ui.row().classes("gap-1 flex-wrap mt-1"):
                                    for _, r in two.head(5).iterrows():
                                        sign = "+" if r.get("net_cr", 0) >= 0 else "-"
                                        val = abs(r.get("net_cr", 0))
                                        ui.chip(f"{r['symbol']} ({sign}₹{val:,.1f}Cr)").props("dense outline").classes("text-[10px]")

                    # 2. CLIENTELE FLOW BREAKDOWN
                    with ui.card().classes("flex-1 min-w-[300px] p-3 mp-card border border-[var(--mp-border)]"):
                        with ui.row().classes("w-full items-center justify-between mb-1"):
                            ui.label("🏛 Clientele Flow").classes("text-sm font-bold text-[var(--mp-text)]")
                            if tv_map.get("clientele_buckets"):
                                ui.button("Copy Buckets (TV)", on_click=lambda t=tv_map["clientele_buckets"]: copy_text("Clientele Buckets (TV)", t)).classes("text-xs").props("dense flat")
                        ui.label(f"Segmented buying across {days} sessions").classes("text-[11px] text-[var(--mp-muted)] mb-2")

                        # FII
                        with ui.column().classes("w-full gap-1 p-2 mb-2 bg-[var(--mp-surface)] rounded border border-[var(--mp-border)]"):
                            with ui.row().classes("w-full items-center justify-between"):
                                with ui.row().classes("items-center gap-1.5"):
                                    ui.label("🌍 FII (Foreign)").classes("text-xs font-bold text-sky-400")
                                    ui.label(f"{len(fii)} stocks").classes("mp-badge text-[10px]")
                                if tv_map.get("fii"):
                                    ui.button("📋 Copy TV", on_click=lambda t=tv_map["fii"]: copy_text("FII Buys TV", t)).classes("text-[11px]").props("dense outline")
                            if fii.empty:
                                ui.label("No FII buys in window.").classes("text-[11px] text-[var(--mp-muted)]")
                            else:
                                with ui.row().classes("gap-1 flex-wrap mt-1"):
                                    for _, r in fii.head(5).iterrows():
                                        ui.chip(f"{r['symbol']} (₹{r['deal_value_cr']:,.1f}Cr)").props("dense outline").classes("text-[10px]")

                        # DII
                        with ui.column().classes("w-full gap-1 p-2 mb-2 bg-[var(--mp-surface)] rounded border border-[var(--mp-border)]"):
                            with ui.row().classes("w-full items-center justify-between"):
                                with ui.row().classes("items-center gap-1.5"):
                                    ui.label("🏦 DII (Domestic)").classes("text-xs font-bold text-amber-400")
                                    ui.label(f"{len(dii)} stocks").classes("mp-badge text-[10px]")
                                if tv_map.get("dii"):
                                    ui.button("📋 Copy TV", on_click=lambda t=tv_map["dii"]: copy_text("DII Buys TV", t)).classes("text-[11px]").props("dense outline")
                            if dii.empty:
                                ui.label("No DII buys in window.").classes("text-[11px] text-[var(--mp-muted)]")
                            else:
                                with ui.row().classes("gap-1 flex-wrap mt-1"):
                                    for _, r in dii.head(5).iterrows():
                                        ui.chip(f"{r['symbol']} (₹{r['deal_value_cr']:,.1f}Cr)").props("dense outline").classes("text-[10px]")

                        # Others
                        with ui.column().classes("w-full gap-1 p-2 mb-2 bg-[var(--mp-surface)] rounded border border-[var(--mp-border)]"):
                            with ui.row().classes("w-full items-center justify-between"):
                                with ui.row().classes("items-center gap-1.5"):
                                    ui.label("👥 Others (Promoters/HNIs)").classes("text-xs font-medium text-[var(--mp-text)]")
                                    ui.label(f"{len(others)} stocks").classes("mp-badge text-[10px]")
                                if tv_map.get("others"):
                                    ui.button("📋 Copy TV", on_click=lambda t=tv_map["others"]: copy_text("Others Buys TV", t)).classes("text-[11px]").props("dense outline")
                            if others.empty:
                                ui.label("No other buys in window.").classes("text-[11px] text-[var(--mp-muted)]")
                            else:
                                with ui.row().classes("gap-1 flex-wrap mt-1"):
                                    for _, r in others.head(4).iterrows():
                                        ui.chip(f"{r['symbol']} (₹{r['deal_value_cr']:,.1f}Cr)").props("dense outline").classes("text-[10px]")

                        # PROP
                        with ui.column().classes("w-full gap-1 p-2 bg-[var(--mp-surface)] rounded border border-[var(--mp-border)]"):
                            with ui.row().classes("w-full items-center justify-between"):
                                with ui.row().classes("items-center gap-1.5"):
                                    ui.label("⚡ PROP (Only Prop Trading)").classes("text-xs font-medium text-[var(--mp-muted)]")
                                    ui.label(f"{len(prop)} stocks").classes("mp-badge text-[10px]")
                                if tv_map.get("prop"):
                                    ui.button("📋 Copy TV", on_click=lambda t=tv_map["prop"]: copy_text("PROP Buys TV", t)).classes("text-[11px]").props("dense outline")

                    # 3. TURNOVER LEADERS
                    with ui.card().classes("flex-1 min-w-[300px] p-3 mp-card border border-[var(--mp-border)]"):
                        with ui.row().classes("w-full items-center justify-between mb-1"):
                            ui.label("💰 Turnover Leaders").classes("text-sm font-bold text-[var(--mp-text)]")
                            if tv_map.get("all_buys"):
                                ui.button("Copy All Buys TV", on_click=lambda t=tv_map["all_buys"]: copy_text("All Buys TV", t)).classes("text-xs").props("dense flat")
                        ui.label("Top capital inflows & outflows (Quality stocks)").classes("text-[11px] text-[var(--mp-muted)] mb-2")

                        # Top Buys
                        with ui.column().classes("w-full gap-1 p-2 mb-2 bg-[var(--mp-surface)] rounded border border-[var(--mp-border)]"):
                            with ui.row().classes("w-full items-center justify-between"):
                                ui.label("🟢 Highest Buy Inflows").classes("text-xs font-bold text-emerald-400")
                                if tv_map.get("top_buys"):
                                    ui.button("📋 Copy TV (Top 25)", on_click=lambda t=tv_map["top_buys"]: copy_text("Top Buys TV", t)).classes("text-[11px]").props("dense outline")
                            if top_buys.empty:
                                ui.label("No buy deals recorded.").classes("text-[11px] text-[var(--mp-muted)]")
                            else:
                                for idx, (_, r) in enumerate(top_buys.head(6).iterrows(), 1):
                                    with ui.row().classes("w-full items-center justify-between text-xs py-0.5 border-b border-[var(--mp-border)]/40"):
                                        ui.label(f"{idx}. {r['symbol']}").classes("font-mono font-semibold")
                                        ui.label(f"₹{r['deal_value_cr']:,.1f} Cr").classes("text-emerald-400 font-mono")

                        # Top Sells
                        with ui.column().classes("w-full gap-1 p-2 bg-[var(--mp-surface)] rounded border border-[var(--mp-border)]"):
                            with ui.row().classes("w-full items-center justify-between"):
                                ui.label("🔴 Highest Sell Outflows").classes("text-xs font-bold text-rose-400")
                                if tv_map.get("top_sells"):
                                    ui.button("📋 Copy TV (Top 25)", on_click=lambda t=tv_map["top_sells"]: copy_text("Top Sells TV", t)).classes("text-[11px]").props("dense outline")
                            if top_sells.empty:
                                ui.label("No sell deals recorded.").classes("text-[11px] text-[var(--mp-muted)]")
                            else:
                                for idx, (_, r) in enumerate(top_sells.head(5).iterrows(), 1):
                                    with ui.row().classes("w-full items-center justify-between text-xs py-0.5 border-b border-[var(--mp-border)]/40"):
                                        ui.label(f"{idx}. {r['symbol']}").classes("font-mono font-semibold")
                                        ui.label(f"₹{r['deal_value_cr']:,.1f} Cr").classes("text-rose-400 font-mono")

                # 4. QUARANTINED / FILTERED STREAMS
                f_data = report.get("filtered", {})
                below_200_df = f_data.get("below_200ema", pd.DataFrame())
                below_1000cr_df = f_data.get("below_1000cr", pd.DataFrame())
                with ui.row().classes("w-full gap-3 items-start flex-wrap lg:flex-nowrap mt-3"):
                    # Below 200 EMA / 5% Band
                    with ui.card().classes("flex-1 min-w-[300px] p-3 mp-card border border-[var(--mp-border)]"):
                        with ui.row().classes("w-full items-center justify-between mb-1"):
                            with ui.row().classes("items-center gap-1.5"):
                                ui.label("📉 Below 200 EMA & 5% Band").classes("text-sm font-bold text-amber-400")
                                ui.label(f"{len(below_200_df)} stocks").classes("mp-badge text-[10px]")
                            if tv_map.get("below_200ema"):
                                ui.button("📋 Copy TV", on_click=lambda t=tv_map["below_200ema"]: copy_text("Below 200EMA TV", t)).classes("text-xs").props("dense outline")
                        ui.label("Stocks below 200 EMA or locked in 5% circuit bands (Quarantined from main swing list)").classes("text-[11px] text-[var(--mp-muted)] mb-2")
                        if below_200_df.empty:
                            ui.label("No stocks below 200 EMA in window.").classes("text-[11px] text-[var(--mp-muted)]")
                        else:
                            with ui.row().classes("gap-1 flex-wrap mt-1"):
                                for _, r in below_200_df.head(10).iterrows():
                                    ui.chip(f"{r['symbol']} (₹{r.get('buy_cr', 0):,.1f}Cr)").props("dense outline").classes("text-[10px]")

                    # <1000 Cr Micro-caps
                    with ui.card().classes("flex-1 min-w-[300px] p-3 mp-card border border-[var(--mp-border)]"):
                        with ui.row().classes("w-full items-center justify-between mb-1"):
                            with ui.row().classes("items-center gap-1.5"):
                                ui.label("🪙 <1000 Cr Mcap").classes("text-sm font-bold text-amber-400")
                                ui.label(f"{len(below_1000cr_df)} stocks").classes("mp-badge text-[10px]")
                            if tv_map.get("below_1000cr"):
                                ui.button("📋 Copy TV", on_click=lambda t=tv_map["below_1000cr"]: copy_text("<1000 Cr TV", t)).classes("text-xs").props("dense outline")
                        ui.label("Micro-cap names with market cap under ₹1,000 Cr (Quarantined from main swing list)").classes("text-[11px] text-[var(--mp-muted)] mb-2")
                        if below_1000cr_df.empty:
                            ui.label("No micro-caps in window.").classes("text-[11px] text-[var(--mp-muted)]")
                        else:
                            with ui.row().classes("gap-1 flex-wrap mt-1"):
                                for _, r in below_1000cr_df.head(10).iterrows():
                                    ui.chip(f"{r['symbol']} (₹{r.get('buy_cr', 0):,.1f}Cr)").props("dense outline").classes("text-[10px]")

    desk_host = ui.column().classes("w-full")

    def _toggle_hft(val: bool) -> None:
        hft_state["exclude_hft"] = bool(val)
        render_desk()

    def _toggle_confluence(val: bool) -> None:
        confluence_state["active"] = bool(val)
        render_desk()

    def render_desk() -> None:
        desk_host.clear()
        with desk_host:
            desk = query_deals_desk_default(db_path, exclude_hft=hft_state["exclude_hft"])

            # --- Action strip ---
            with ui.card().classes("w-full mp-card mb-3 p-4"):
                with ui.row().classes("w-full items-center justify-between gap-3 flex-wrap mp-desk-action"):
                    with ui.row().classes("items-center gap-3"):
                        ui.label(f"Session {desk.as_of or '—'}").classes("mp-section-title m-0")
                        compact_kpi_row(
                            [
                                ("BUY names", desk.buy_count),
                                ("Universe", desk.universe_label),
                            ]
                        )
                        if desk.buy_tv:
                            ui.button(
                                "Copy BUY TV list",
                                on_click=lambda t=desk.buy_tv: copy_text("Deals BUY TV", t),
                            ).classes("mp-primary").props("dense")

                    with ui.row().classes("items-center gap-3"):
                        hft_chk = ui.checkbox(
                            "Exclude PROP",
                            value=hft_state["exclude_hft"],
                            on_change=lambda e: _toggle_hft(e.value),
                        ).props("dense")
                        confluence_chk = ui.checkbox(
                            "Setup Confluence (Bullish / Near High)",
                            value=confluence_state["active"],
                            on_change=lambda e: _toggle_confluence(e.value),
                        ).props("dense")
                    ui.label(desk.filter_notes).classes("text-xs text-[var(--mp-muted)] mt-1")

                if desk.buy_count == 0:
                    empty_state(
                        "No buy-side deals for the latest session",
                        "After the next EOD pipeline run, names that pass MCap / structure filters appear here.",
                    )
                else:
                    symbol_chip_strip(list(desk.symbols_for_tv), preview=24)

            # --- Flow spark ---
            with ui.card().classes("w-full mp-card mb-3 p-3"):
                ui.label("Institutional Deal Flow (10 sessions)").classes("text-sm font-semibold mb-1")
                if not desk.flow.empty:
                    net = float(
                        pd.to_numeric(desk.flow.get("buy_cr"), errors="coerce").fillna(0).sum()
                        - pd.to_numeric(desk.flow.get("sell_cr"), errors="coerce").fillna(0).sum()
                    )
                    ui.label(f"Net window ≈ ₹{net:,.0f} Cr").classes("text-xs text-[var(--mp-muted)] mb-1")
                flow_spark(desk.flow)

            # --- DealFlow cards (top-N of full set) ---
            with ui.row().classes("w-full items-center justify-between mt-2 mb-1"):
                ui.label("Top Institutional Flow (Latest Session)").classes("mp-section-title")
                ui.label("Inst love = 3+ funds or 3+ buy sessions. 52W % is vs the 52-week high.").classes("text-sm text-[var(--mp-muted)]")

            display_cards = desk.cards
            if confluence_state["active"] and not display_cards.empty:
                if "rs_percentile" in display_cards.columns and "away_52w_high_pct" in display_cards.columns:
                    display_cards = display_cards[
                        (display_cards["rs_percentile"].fillna(0) >= 50) |
                        (display_cards["away_52w_high_pct"].fillna(-99) >= -20)
                    ]

            if display_cards.empty:
                ui.label("No cards match the active filters.").classes("text-sm text-[var(--mp-muted)]")
            else:
                with ui.row().classes("w-full gap-3 flex-wrap"):
                    for _, row in display_cards.iterrows():
                        sym = str(row.get("symbol") or "")
                        buy_cr = float(row.get("buy_value_cr") or 0)
                        sell_cr = float(row.get("sell_value_cr") or 0)
                        net_cr = float(row.get("net_value_cr") or 0)
                        clients = row.get("buy_client_count")
                        inst_names = str(row.get("inst_clients") or "")
                        rs = row.get("rs_percentile")
                        away = row.get("away_52w_high_pct")
                        cost_basis = row.get("cmp_vs_inst_entry_pct")
                        raw_when = row.get("deal_when")
                        when = "" if raw_when is None or (isinstance(raw_when, float) and pd.isna(raw_when)) else str(raw_when)

                        def _tv(s=sym):
                            url = tradingview_url(s)
                            ui.run_javascript(f'window.open({url!r}, "_blank")')

                        def _copy(s=sym):
                            copy_text(f"Symbol {s}", f"NSE:{s.replace('-', '_')}")

                        def _drawer(s=sym):
                            open_stock_360_modal(db_path, s, copy_text=copy_text)

                        deal_flow_card(
                            sym,
                            buy_cr,
                            sell_cr=sell_cr,
                            net_cr=net_cr,
                            clients=int(clients) if clients is not None and pd.notna(clients) else None,
                            rs=float(rs) if rs is not None and pd.notna(rs) else None,
                            away_52w=float(away) if away is not None and pd.notna(away) else None,
                            inst_names=inst_names if inst_names else None,
                            cost_basis_pct=float(cost_basis) if cost_basis is not None and pd.notna(cost_basis) else None,
                            deal_when=when or None,
                            on_tv=_tv,
                            on_copy=_copy,
                            on_click=_drawer,
                        )

            ui.label("Advanced institutional research & cluster radar").classes("mp-section-title mt-4")
            ui.label(
                "Always on. Cluster radar and institution leaderboard sit side by side. Side defaults to BUY and SELL."
            ).classes("text-xs text-[var(--mp-muted)] mb-2")
            with filter_bar():
                clientele_sel = ui.select(
                    ["ALL", "PROP", "FII", "DII", "HNI", "CORPORATE", "OTHER"],
                    value="ALL",
                    label="Clientele",
                ).classes("w-64")
                side = ui.select(["BUY", "SELL", "BOTH"], value="BOTH", label="Side").classes("w-28")
                min_value = ui.number("Min Activity Cr", value=5).classes("w-32")
                days_back = ui.number("Lookback Days", value=10, min=1, max=60).classes("w-32")
                client = ui.input("Institution contains", value="").classes("w-56")
                run_btn = ui.button("Run research").classes("mp-primary").props("dense")
            adv_host = ui.column().classes("w-full mt-2")

            def run_advanced() -> None:
                adv_host.clear()
                client_name = (client.value or "").strip() or None
                data = query_deals_advanced(
                    db_path,
                    side=str(side.value or "BOTH"),
                    min_value_cr=float(min_value.value or 0),
                    lookback_days=int(days_back.value or 10),
                    client_name=client_name,
                    tier_filter=None,
                    clientele=None if clientele_sel.value == "ALL" else (str(clientele_sel.value),),
                    exclude_hft=hft_state["exclude_hft"],
                )
                with adv_host:
                    clients_df = data["clients"]
                    stocks_df = data["stocks"]
                    cluster_df = data["cluster"]

                    if metric_card:
                        with ui.row().classes("gap-3 flex-wrap"):
                            metric_card("Institutions", len(clients_df), "info")
                            metric_card("Stocks Traded", len(stocks_df), "info")
                            metric_card("Cluster Buys (2+ Funds)", len(cluster_df), "good")

                    with ui.row().classes("w-full gap-4 items-start flex-wrap mp-deals-split"):
                        with ui.column().classes("flex-1 min-w-[420px]"):
                            if cluster_df.empty:
                                ui.label("No cluster buys (2+ funds) in this window.").classes("text-sm text-[var(--mp-muted)]")
                            else:
                                ccols = [
                                    c
                                    for c in (
                                        "symbol",
                                        "institutions_count",
                                        "total_buy_cr",
                                        "avg_buy_price",
                                        "close_price",
                                        "cmp_vs_inst_entry_pct",
                                        "rs_percentile",
                                        "away_52w_high_pct",
                                        "deal_when",
                                        "latest_deal_date",
                                        "institutions_list",
                                    )
                                    if c in cluster_df.columns
                                ]
                                table_from_df(cluster_df[ccols], "Cluster buying radar", pagination=15)
                        with ui.column().classes("flex-1 min-w-[420px]"):
                            if clients_df.empty:
                                ui.label("No institutions in window.").classes("text-sm text-[var(--mp-muted)]")
                            else:
                                clients_view, cols = prepare_institution_leaderboard(clients_df)
                                table_cols = [*cols, "symbol_list"] if "symbol_list" in clients_view.columns else cols
                                table_from_df(
                                    clients_view[table_cols],
                                    "Institution leaderboard",
                                    pagination=20,
                                    copy_symbols=True,
                                    hidden_cols={"symbol_list"},
                                    compact=True,
                                )

                    if stocks_df.empty:
                        ui.label("No stocks in window.").classes("text-sm text-[var(--mp-muted)]")
                    else:
                        scols = [
                            c
                            for c in (
                                "symbol",
                                "latest_deal_date",
                                "buy_value_cr",
                                "sell_value_cr",
                                "net_value_cr",
                                "buy_client_count",
                                "inst_vwap",
                                "close_price",
                                "cmp_vs_inst_entry_pct",
                                "rs_percentile",
                                "away_52w_high_pct",
                                "deal_when",
                                "industry",
                            )
                            if c in stocks_df.columns
                        ]
                        table_from_df(stocks_df[scols], "Stock deals (window)", pagination=25)

            run_btn.on_click(run_advanced)
            run_advanced()

    def _toggle_hft(val: bool) -> None:
        hft_state["exclude_hft"] = val
        render_desk()

    render_telegram_hub()
    render_desk()


__all__ = ["build_deals_page", "prepare_institution_leaderboard"]

