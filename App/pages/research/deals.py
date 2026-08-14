"""Deal Flow Desk — Institutional Intelligence 2.0 (PR-DEALS 2.0)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
from nicegui import ui

try:
    from App.deals_read_model import query_deals_advanced, query_deals_desk_default
    from App.ui.shell import empty_state, filter_bar, page_shell
    from App.ui.stock_drawer import open_stock_360_modal
    from App.ui.styles import add_deals_desk_styles
    from App.ui.widgets import compact_kpi_row, deal_flow_card, flow_spark, symbol_chip_strip
except ModuleNotFoundError:
    from deals_read_model import query_deals_advanced, query_deals_desk_default  # type: ignore
    from ui.shell import empty_state, filter_bar, page_shell  # type: ignore
    from ui.stock_drawer import open_stock_360_modal  # type: ignore
    from ui.styles import add_deals_desk_styles  # type: ignore
    from ui.widgets import compact_kpi_row, deal_flow_card, flow_spark, symbol_chip_strip  # type: ignore


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
        "Clean institutional accumulation & cluster buying ready for TradingView",
        eyebrow="Research · Institutional Intelligence",
    )

    hft_state = {"exclude_hft": True}
    desk_host = ui.column().classes("w-full")

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
                                ("MCap gate", "≥ ₹1,000 Cr*"),
                            ]
                        )
                        if desk.buy_tv:
                            ui.button(
                                "Copy BUY TV list",
                                on_click=lambda t=desk.buy_tv: copy_text("Deals BUY TV", t),
                            ).classes("mp-primary").props("dense")

                    with ui.row().classes("items-center gap-2"):
                        hft_chk = ui.checkbox(
                            "Exclude HFT Arbitrage Churn",
                            value=hft_state["exclude_hft"],
                            on_change=lambda e: _toggle_hft(e.value),
                        ).props("dense")
                        ui.label("* HFT desks (Graviton, HRTI, etc.) filtered").classes("text-xs text-[var(--mp-muted)]")

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
                ui.label("Click card or 360° to inspect stock").classes("text-xs text-[var(--mp-muted)]")

            if desk.cards.empty:
                ui.label("No cards to show.").classes("text-sm text-[var(--mp-muted)]")
            else:
                with ui.row().classes("w-full gap-3 flex-wrap"):
                    for _, row in desk.cards.iterrows():
                        sym = str(row.get("symbol") or "")
                        buy_cr = float(row.get("buy_value_cr") or 0)
                        clients = row.get("buy_client_count")
                        inst_names = str(row.get("inst_clients") or "")
                        rs = row.get("rs_percentile")
                        away = row.get("away_52w_high_pct")
                        cost_basis = row.get("cmp_vs_inst_entry_pct")

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
                            clients=int(clients) if clients is not None and pd.notna(clients) else None,
                            rs=float(rs) if rs is not None and pd.notna(rs) else None,
                            away_52w=float(away) if away is not None and pd.notna(away) else None,
                            inst_names=inst_names if inst_names else None,
                            cost_basis_pct=float(cost_basis) if cost_basis is not None and pd.notna(cost_basis) else None,
                            on_tv=_tv,
                            on_copy=_copy,
                            on_click=_drawer,
                        )

            # --- Advanced Research & Cluster Radar ---
            with ui.expansion("Advanced institutional research & cluster radar", icon="hub").classes("w-full mt-4"):
                ui.label(
                    "Cluster buying radar (stocks accumulated by 2+ institutional funds), Tier-1 fund breakdowns, and full multi-day grids."
                ).classes("text-xs text-[var(--mp-muted)] mb-2")
                with filter_bar():
                    tier_sel = ui.select(
                        ["ALL", "DII (Domestic Institutional)", "FII (Foreign Institutional)", "Super Investor / HNI", "Corporate / Promoter / PE"],
                        value="ALL",
                        label="Institution Tier",
                    ).classes("w-64")
                    side = ui.select(["BUY", "SELL", "BOTH"], value="BUY", label="Side").classes("w-28")
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
                        side=str(side.value or "BUY"),
                        min_value_cr=float(min_value.value or 0),
                        lookback_days=int(days_back.value or 10),
                        client_name=client_name,
                        tier_filter=None if tier_sel.value == "ALL" else str(tier_sel.value),
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

                        # Cluster Buying Radar Table
                        if not cluster_df.empty:
                            ui.label("🎯 Cluster Buying Radar (2+ Institutional Funds Accumulating)").classes("mp-section-title mt-2")
                            ccols = [
                                c for c in (
                                    "symbol",
                                    "institutions_count",
                                    "total_buy_cr",
                                    "avg_buy_price",
                                    "close_price",
                                    "cmp_vs_inst_entry_pct",
                                    "rs_percentile",
                                    "away_52w_high_pct",
                                    "latest_deal_date",
                                    "institutions_list",
                                )
                                if c in cluster_df.columns
                            ]
                            table_from_df(cluster_df[ccols], "Cluster Buying Radar", pagination=15)

                        # Institution Leaderboard Table
                        if not clients_df.empty:
                            ui.label("🏛️ Institution Leaderboard").classes("mp-section-title mt-3")
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
                        else:
                            ui.label("No institutions in window.").classes("text-sm text-[var(--mp-muted)]")

                        # Stock Deals Table
                        if not stocks_df.empty:
                            ui.label("📊 Stock Deals Grid").classes("mp-section-title mt-3")
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
                                    "industry",
                                )
                                if c in stocks_df.columns
                            ]
                            table_from_df(stocks_df[scols], "Stock deals (window)", pagination=25)
                        else:
                            ui.label("No stocks in window.").classes("text-sm text-[var(--mp-muted)]")

                run_btn.on_click(run_advanced)

    def _toggle_hft(val: bool) -> None:
        hft_state["exclude_hft"] = val
        render_desk()

    render_desk()


__all__ = ["build_deals_page", "prepare_institution_leaderboard"]

