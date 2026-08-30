"""Minervini tab: SMA Trend Template + real OHLC VCP (1T–4T on candles)."""

from __future__ import annotations

from pathlib import Path

from nicegui import ui

try:
    from App.market_summary import movers
    from App.ui.t_graph import geometry_for_symbol, render_template_stamp
    from App.ui.vcp_chart import render_vcp_ohlc
except ModuleNotFoundError:
    from market_summary import movers  # type: ignore
    from ui.t_graph import geometry_for_symbol, render_template_stamp  # type: ignore
    from ui.vcp_chart import render_vcp_ohlc  # type: ignore


def build_minervini_page(db_path: Path) -> None:
    db_path = Path(db_path)
    ui.label("Minervini").classes("mp-page-title")
    ui.label("SMA Trend Template (50/150/200) and VCP on real OHLC. Momentum tab stays the EMA 10-200 scanner.").classes("mp-page-subtitle")

    mv = movers(db_path)
    symbols = sorted(str(s) for s in mv["symbol"].tolist()) if not mv.empty and "symbol" in mv.columns else []
    default = "ACUTAAS" if "ACUTAAS" in symbols else (symbols[0] if symbols else "")
    picker = ui.select(symbols, value=default, label="Symbol", with_input=True).classes("w-72")
    host = ui.column().classes("w-full")

    def paint() -> None:
        host.clear()
        sym = str(picker.value or "").strip().upper()
        if not sym:
            return
        geo = geometry_for_symbol(db_path, sym)
        with host:
            with ui.row().classes("w-full items-start gap-4 flex-wrap"):
                with ui.column().classes("mp-paper w-80"):
                    ui.label(sym).classes("mp-paper-title")
                    render_template_stamp(geo["template"])
                    ui.label(f"EMA ribbon: {geo['ema_label']}").classes("text-xs mt-3")
                    if geo["seq"].pivot:
                        ui.label(
                            f"Pivot ₹{geo['seq'].pivot:,.2f}  Stop ₹{geo['seq'].stop:,.2f}"
                        ).classes("text-xs mono mt-2")
                with ui.column().classes("flex-1 min-w-[520px]"):
                    ui.label("VCP on OHLC — shaded Ts, SMA 50 / 150 / 200").classes("mp-section-title")
                    render_vcp_ohlc(db_path, sym)

    picker.on_value_change(lambda _: paint())
    paint()
