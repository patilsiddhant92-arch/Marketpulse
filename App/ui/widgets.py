"""Reusable desk widgets (PR-UI-KIT-B / PR-DEALS)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd
from nicegui import ui


def action_button(label: str, on_click: Callable[[], None], *, primary: bool = True) -> None:
    cls = "mp-primary" if primary else "mp-button"
    ui.button(label, on_click=on_click).classes(cls).props("dense")


def symbol_chip_strip(symbols: list[str], *, preview: int = 24) -> None:
    """Show a compact chip strip; does not truncate the copy source."""
    shown = symbols[:preview]
    with ui.element("div").classes("mp-chip-strip mt-2"):
        for sym in shown:
            ui.label(sym).classes("mp-symbol-chip")
        if len(symbols) > preview:
            ui.label(f"+{len(symbols) - preview} more in copy").classes("text-xs text-[var(--mp-muted)] self-center")


def deal_flow_card(
    symbol: str,
    buy_cr: float,
    *,
    clients: int | None = None,
    rs: float | None = None,
    away_52w: float | None = None,
    inst_names: str | None = None,
    cost_basis_pct: float | None = None,
    on_tv: Callable[[], None] | None = None,
    on_copy: Callable[[], None] | None = None,
    on_click: Callable[[], None] | None = None,
) -> None:
    card_el = ui.element("div").classes("mp-deal-card cursor-pointer hover:shadow-md transition-all")
    with card_el:
        with ui.row().classes("w-full items-center justify-between gap-2"):
            sym_lbl = ui.label(symbol).classes("sym hover:underline")
            if on_click:
                sym_lbl.on("click", lambda _=None: on_click())
            tone = "mp-pos" if buy_cr >= 0 else "mp-neg"
            ui.label(f"+{buy_cr:,.0f} Cr" if buy_cr >= 0 else f"{buy_cr:,.0f} Cr").classes(tone)
        meta_parts: list[str] = []
        if clients is not None:
            meta_parts.append(f"{int(clients)} inst")
        if rs is not None and pd.notna(rs):
            meta_parts.append(f"RS {float(rs):.0f}")
        if away_52w is not None and pd.notna(away_52w):
            meta_parts.append(f"{float(away_52w):+.1f}% 52W")
        if cost_basis_pct is not None and pd.notna(cost_basis_pct):
            tone_prefix = "+" if cost_basis_pct > 0 else ""
            meta_parts.append(f"{tone_prefix}{float(cost_basis_pct):.1f}% vs Entry")
        if meta_parts:
            ui.label(" · ".join(meta_parts)).classes("meta mt-1")
        if inst_names:
            ui.label(inst_names).classes("text-xs text-[var(--mp-muted)] truncate mt-1")
        with ui.row().classes("gap-2 mt-2"):
            if on_click:
                ui.button("360°", on_click=on_click).props("dense flat").classes("mp-button text-xs font-semibold")
            if on_tv:
                ui.button("TV", on_click=on_tv).props("dense flat").classes("mp-button text-xs")
            if on_copy:
                ui.button("Copy", on_click=on_copy).props("dense flat").classes("mp-button text-xs")



def flow_spark(flow: pd.DataFrame) -> None:
    """Compact buy vs sell bars for lookback window."""
    if flow is None or flow.empty:
        ui.label("No deal flow in window.").classes("text-sm text-[var(--mp-muted)]")
        return
    rows = flow.copy()
    rows["trade_date"] = pd.to_datetime(rows["trade_date"], errors="coerce").dt.strftime("%d-%b")
    x = rows["trade_date"].tolist()
    buy = pd.to_numeric(rows.get("buy_cr"), errors="coerce").fillna(0).round(1).tolist()
    sell = pd.to_numeric(rows.get("sell_cr"), errors="coerce").fillna(0).round(1).tolist()
    ui.echart(
        {
            "backgroundColor": "transparent",
            "tooltip": {"trigger": "axis"},
            "grid": {"left": 40, "right": 12, "top": 16, "bottom": 28},
            "legend": {"show": True, "top": 0, "right": 0, "textStyle": {"fontSize": 11}},
            "xAxis": {"type": "category", "data": x, "axisLabel": {"fontSize": 10}},
            "yAxis": {"type": "value", "axisLabel": {"fontSize": 10}},
            "series": [
                {"name": "BUY Cr", "type": "bar", "data": buy, "itemStyle": {"color": "#22c55e"}},
                {"name": "SELL Cr", "type": "bar", "data": sell, "itemStyle": {"color": "#ef4444"}},
            ],
        }
    ).classes("mp-flow-spark w-full")


def compact_kpi_row(items: list[tuple[str, Any]]) -> None:
    with ui.row().classes("gap-4 flex-wrap mp-desk-action"):
        for label, value in items:
            with ui.element("span").classes("mp-kpi-compact"):
                ui.label(label).classes("label")
                ui.label(str(value)).classes("value")
