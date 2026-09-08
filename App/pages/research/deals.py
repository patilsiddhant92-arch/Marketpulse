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
    res = build_deals_telegram_report(lookback_days=lookback_days, min_mcap_cr=900.0, db_path=db_path)
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


def _prepare_tier_table_df(df_in: pd.DataFrame) -> pd.DataFrame:
    if df_in.empty:
        return pd.DataFrame()
    out = df_in.copy()
    if "categories" in out.columns:
        out["clientele"] = out["categories"].map(
            lambda c: "/".join(sorted(list(c))) if isinstance(c, (set, list)) else str(c)
        )
    if "trend_stage" in out.columns:
        out["trend"] = out["trend_stage"]
    elif "close_price" in out.columns and "ema_200" in out.columns:
        out["trend"] = out.apply(
            lambda r: "🟢 >200 EMA" if pd.notna(r.get("close_price")) and pd.notna(r.get("ema_200")) and float(r["close_price"]) >= float(r["ema_200"]) else "🟡 Base / Turnaround",
            axis=1,
        )
    cols = [
        "symbol",
        "trend",
        "deal_days",
        "clientele",
        "net_cr",
        "buy_cr",
        "close_price",
        "ema_200",
        "away_52w_high_pct",
        "rs_percentile",
        "market_cap_cr",
        "sector",
    ]
    avail_cols = [c for c in cols if c in out.columns]
    return out[avail_cols]


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
    hub_state = {"lookback_days": 20, "setup_filter": "ALL"}

    hub_container = ui.column().classes("w-full mb-3")

    def render_telegram_hub() -> None:
        hub_container.clear()
        with hub_container:
            days = int(hub_state["lookback_days"])
            report = fetch_deals_telegram_data(db_path, days)
            tv_map = report.get("tv_strings", {})
            as_of = report.get("as_of") or "—"
            tiers = report.get("tiers", {})

            conviction_df = tiers.get("conviction", pd.DataFrame())
            fresh_radar_df = tiers.get("fresh_radar", pd.DataFrame())
            prop_only_df = tiers.get("prop_only", pd.DataFrame())
            quarantined_df = tiers.get("quarantined", pd.DataFrame())
            distribution_df = tiers.get("distribution", pd.DataFrame())

            master_tv = tv_map.get("master_tv", "")
            conviction_tv = tv_map.get("conviction_tv", "")
            fresh_radar_tv = tv_map.get("fresh_radar_tv", "")
            prop_tv = tv_map.get("prop_tv", "")
            quarantined_tv = tv_map.get("quarantined_tv", "")

            # Apply dynamic setup filter if active
            active_filter = hub_state.get("setup_filter", "ALL")
            if active_filter == "ABOVE_200":
                if not conviction_df.empty and "is_above_200" in conviction_df.columns:
                    conviction_df = conviction_df[conviction_df["is_above_200"]].copy()
                if not fresh_radar_df.empty and "is_above_200" in fresh_radar_df.columns:
                    fresh_radar_df = fresh_radar_df[fresh_radar_df["is_above_200"]].copy()
                active_master_tv = tv_map.get("above_200_tv") or to_tv_list(conviction_df["symbol"].tolist() + fresh_radar_df["symbol"].tolist())
            elif active_filter == "TURNAROUND":
                if not conviction_df.empty and "is_above_200" in conviction_df.columns:
                    conviction_df = conviction_df[~conviction_df["is_above_200"]].copy()
                if not fresh_radar_df.empty and "is_above_200" in fresh_radar_df.columns:
                    fresh_radar_df = fresh_radar_df[~fresh_radar_df["is_above_200"]].copy()
                active_master_tv = tv_map.get("turnaround_tv") or to_tv_list(conviction_df["symbol"].tolist() + fresh_radar_df["symbol"].tolist())
            else:
                active_master_tv = master_tv

            with ui.card().classes("w-full mp-card p-4 border border-[var(--mp-border)]"):
                # Header row: Title + Lookback & Setup selectors
                with ui.row().classes("w-full items-center justify-between gap-3 flex-wrap mb-2"):
                    with ui.column().classes("gap-0.5"):
                        with ui.row().classes("items-center gap-2"):
                            ui.label("📡 Institutional Deals Desk · Action Radar (3-Tier)").classes("mp-section-title m-0 text-base font-bold")
                            ui.label(f"As of {as_of}").classes("mp-badge mp-pill text-xs")
                        ui.label(f"Complete institutional deal flow across last {days} sessions. Zero duplicate tickers.").classes("text-xs text-[var(--mp-muted)]")

                    # Selectors: Lookback + Setup Filter
                    with ui.row().classes("items-center gap-2 flex-wrap"):
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

                        # Setup filter selector pills
                        with ui.row().classes("items-center gap-1 bg-[var(--mp-surface)] p-1 rounded-lg border border-[var(--mp-border)]"):
                            ui.label("Setup:").classes("text-xs text-[var(--mp-muted)] px-2 font-medium")
                            curr_f = hub_state.get("setup_filter", "ALL")
                            for f_val, f_label in [("ALL", "All Setups"), ("ABOVE_200", "Stage 2 (>200 EMA)"), ("TURNAROUND", "Base / Turnaround")]:
                                is_active = (curr_f == f_val)
                                btn_classes = "mp-primary text-xs" if is_active else "text-xs text-[var(--mp-muted)]"
                                def _make_filter_setter(f: str):
                                    def _setter() -> None:
                                        hub_state["setup_filter"] = f
                                        render_telegram_hub()
                                    return _setter
                                ui.button(f_label, on_click=_make_filter_setter(f_val)).classes(btn_classes).props("dense unelevated" if is_active else "dense flat")

                # Master Quick Actions
                with ui.row().classes("w-full items-center gap-2 flex-wrap p-2.5 bg-[var(--mp-surface)] rounded-lg border border-[var(--mp-border)] mb-3"):
                    ui.label("⚡ Quick Export:").classes("text-xs font-semibold text-[var(--mp-text)]")
                    total_master_count = len(conviction_df) + len(fresh_radar_df)
                    if active_master_tv:
                        ui.button(f"📋 Copy Master TV ({total_master_count} Stocks)", on_click=lambda t=active_master_tv: copy_text("Master Deals TV", t)).classes("mp-primary text-xs font-bold").props("dense")
                    conv_syms = conviction_df["symbol"].tolist() if not conviction_df.empty else []
                    c_str = to_tv_list(conv_syms, header="💎 Conviction Accumulation") if conv_syms else ""
                    if c_str or conviction_tv:
                        ui.button(f"📋 Copy Conviction Only ({len(conv_syms)})", on_click=lambda t=(c_str or conviction_tv): copy_text("Conviction Deals TV", t)).classes("mp-button text-xs text-emerald-400 font-semibold").props("dense outline")
                    fresh_syms = fresh_radar_df["symbol"].tolist() if not fresh_radar_df.empty else []
                    f_str = to_tv_list(fresh_syms, header="⚡ Fresh Whale Radar") if fresh_syms else ""
                    if f_str or fresh_radar_tv:
                        ui.button(f"📋 Copy Fresh Radar ({len(fresh_syms)})", on_click=lambda t=(f_str or fresh_radar_tv): copy_text("Fresh Radar TV", t)).classes("mp-button text-xs text-sky-400").props("dense outline")
                    if tv_map.get("above_200_tv"):
                        ui.button("📋 Stage 2 (>200 EMA)", on_click=lambda t=tv_map["above_200_tv"]: copy_text("Stage 2 Deals TV", t)).classes("mp-button text-xs text-teal-400").props("dense outline")
                    if tv_map.get("turnaround_tv"):
                        ui.button("📋 Turnaround (<200 EMA)", on_click=lambda t=tv_map["turnaround_tv"]: copy_text("Turnaround Deals TV", t)).classes("mp-button text-xs text-amber-400").props("dense outline")
                    if prop_tv:
                        ui.button("📋 Copy Prop HFT Only", on_click=lambda t=prop_tv: copy_text("Prop HFT Deals TV", t)).classes("mp-button text-xs text-amber-400/80").props("dense outline")
                    if quarantined_tv:
                        ui.button("📋 Copy Quarantined (5% Band)", on_click=lambda t=quarantined_tv: copy_text("Quarantined Deals TV", t)).classes("mp-button text-xs text-rose-400").props("dense outline")

                # Tabs for Clean Inspection
                with ui.tabs().classes("w-full bg-[var(--mp-surface)] rounded-t-lg border border-[var(--mp-border)]") as hub_tabs:
                    t1 = ui.tab(f"💎 Tier 1: Conviction Accumulation ({len(conviction_df)})")
                    t2 = ui.tab(f"⚡ Tier 2: Fresh Whale Radar ({len(fresh_radar_df)})")
                    t3 = ui.tab(f"🎯 Tier 3A: Prop HFT Churn ({len(prop_only_df)})")
                    t4 = ui.tab(f"📉 Tier 3B: Quarantined ({len(quarantined_df)})")
                    t5 = ui.tab(f"🔴 Distribution ({len(distribution_df)})")

                with ui.tab_panels(hub_tabs, value=t1).classes("w-full bg-transparent p-2 border border-t-0 border-[var(--mp-border)] rounded-b-lg"):
                    # Tab 1: Conviction Accumulation
                    with ui.tab_panel(t1).classes("p-2 gap-2"):
                        with ui.row().classes("w-full items-center justify-between mb-2"):
                            ui.label("🔥 Primary Swing Watchlist: Multi-day persistence (2+ days) or Whale Inflows (≥₹25Cr) with genuine institutional sponsorship (FII/DII/HNI). Includes both Stage 2 momentum and high-conviction Stage 1 turnarounds.").classes("text-xs text-[var(--mp-muted)]")
                            if c_str:
                                ui.button("📋 Copy TV List", on_click=lambda t=c_str: copy_text("Conviction TV", t)).classes("text-xs").props("dense outline")
                        if conviction_df.empty:
                            ui.label("No stocks meet Tier 1 conviction accumulation criteria in this window.").classes("text-xs text-[var(--mp-muted)] py-4")
                        else:
                            table_from_df(_prepare_tier_table_df(conviction_df), "", pagination=15, compact=True)

                    # Tab 2: Fresh Whale Radar
                    with ui.tab_panel(t2).classes("p-2 gap-2"):
                        with ui.row().classes("w-full items-center justify-between mb-2"):
                            ui.label("⚡ Early Radar: Day-1 institutional entry with genuine institutional sponsorship. Watch for follow-through.").classes("text-xs text-[var(--mp-muted)]")
                            if f_str:
                                ui.button("📋 Copy TV List", on_click=lambda t=f_str: copy_text("Fresh Radar TV", t)).classes("text-xs").props("dense outline")
                        if fresh_radar_df.empty:
                            ui.label("No fresh institutional entries in this window.").classes("text-xs text-[var(--mp-muted)] py-4")
                        else:
                            table_from_df(_prepare_tier_table_df(fresh_radar_df), "", pagination=15, compact=True)

                    # Tab 3: Prop HFT Churn
                    with ui.tab_panel(t3).classes("p-2 gap-2"):
                        with ui.row().classes("w-full items-center justify-between mb-2"):
                            ui.label("🎯 Prop & Algo Scalp Only: Trading desks (Jump, AlphaGrep, Silverleaf, etc.) with NO FII/DII institutional backing. Kept separate from swing accumulation.").classes("text-xs text-amber-400/80")
                            if prop_tv:
                                ui.button("📋 Copy TV List", on_click=lambda t=prop_tv: copy_text("Prop HFT TV", t)).classes("text-xs").props("dense outline")
                        if prop_only_df.empty:
                            ui.label("No prop-only churn stocks in this window.").classes("text-xs text-[var(--mp-muted)] py-4")
                        else:
                            table_from_df(_prepare_tier_table_df(prop_only_df), "", pagination=15, compact=True)

                    # Tab 4: Quarantined
                    with ui.tab_panel(t4).classes("p-2 gap-2"):
                        with ui.row().classes("w-full items-center justify-between mb-2"):
                            ui.label("📉 Quarantined from Swings: MCap ≥ 900 Cr but locked in tight ≤5% circuit bands (illiquid collar risk).").classes("text-xs text-rose-400/80")
                            if quarantined_tv:
                                ui.button("📋 Copy TV List", on_click=lambda t=quarantined_tv: copy_text("Quarantined TV", t)).classes("text-xs").props("dense outline")
                        if quarantined_df.empty:
                            ui.label("No quarantined stocks in this window.").classes("text-xs text-[var(--mp-muted)] py-4")
                        else:
                            table_from_df(_prepare_tier_table_df(quarantined_df), "", pagination=15, compact=True)

                    # Tab 5: Distribution
                    with ui.tab_panel(t5).classes("p-2 gap-2"):
                        with ui.row().classes("w-full items-center justify-between mb-2"):
                            ui.label("🔴 Heavy Institutional Distribution / Exits across the window.").classes("text-xs text-rose-400")
                            sec_top_sells = tv_map.get("top_sells", "")
                            if sec_top_sells:
                                ui.button("📋 Copy TV List", on_click=lambda t=sec_top_sells: copy_text("Distribution TV", t)).classes("text-xs").props("dense outline")
                        if distribution_df.empty:
                            ui.label("No institutional distribution recorded in this window.").classes("text-xs text-[var(--mp-muted)] py-4")
                        else:
                            table_from_df(_prepare_tier_table_df(distribution_df), "", pagination=15, compact=True)

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
            desk = query_deals_desk_default(db_path, min_mcap_cr=900.0, exclude_hft=hft_state["exclude_hft"])

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
                    min_mcap_cr=900.0,
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

