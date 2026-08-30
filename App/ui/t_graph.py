"""Render Minervini 1T–4T graph and Trend Template stamp."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nicegui import ui

try:
    from Scripts.minervini_geometry import (
        detect_contractions,
        ema_stack_label,
        evaluate_trend_template,
        load_ohlcv,
        load_template_context,
        t_graph_svg,
    )
except ModuleNotFoundError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "Scripts"))
    from minervini_geometry import (  # type: ignore
        detect_contractions,
        ema_stack_label,
        evaluate_trend_template,
        load_ohlcv,
        load_template_context,
        t_graph_svg,
    )


def geometry_for_symbol(db_path: Path, symbol: str) -> dict[str, Any]:
    ctx = load_template_context(db_path, symbol)
    template = evaluate_trend_template(ctx)
    ohlcv = load_ohlcv(db_path, symbol)
    seq = detect_contractions(ohlcv)
    return {
        "ctx": ctx,
        "template": template,
        "seq": seq,
        "ema_label": ema_stack_label(ctx),
        "t_label": seq.contractions[-1].label if seq.contractions else "—",
    }


def render_template_stamp(template: dict[str, Any]) -> None:
    ui.label(f"Minervini Trend Template · SMA  {template['label']}").classes("mp-paper-kicker")
    for _key, label, passed in template["rows"]:
        tone = "mp-pass" if passed else "mp-fail"
        with ui.row().classes("w-full justify-between text-xs mono"):
            ui.label(label)
            ui.label("PASS" if passed else "FAIL").classes(tone)


def render_t_panel(db_path: Path, symbol: str) -> None:
    geo = geometry_for_symbol(db_path, symbol)
    seq = geo["seq"]
    with ui.element("div").classes("mp-paper w-full"):
        with ui.row().classes("w-full items-baseline justify-between"):
            ui.label(f"VCP footprint · {symbol}").classes("mp-paper-title")
            ui.label(seq.footprint).classes("mono text-xs")
        try:
            ui.html(t_graph_svg(seq), sanitize=False)
        except TypeError:
            ui.html(t_graph_svg(seq))
        with ui.row().classes("w-full gap-2 mt-2"):
            filled = {c.label for c in seq.contractions}
            for name in ("1T", "2T", "3T", "4T"):
                on = name in filled
                ui.label(name).classes("mp-t-slot mp-t-on" if on else "mp-t-slot")
        render_template_stamp(geo["template"])
        ui.label(f"EMA ribbon (extension, not the template): {geo['ema_label']}").classes("text-xs mt-3")
        if seq.pivot and seq.stop:
            ui.label(
                f"Pivot ₹{seq.pivot:,.2f}  ·  Stop ₹{seq.stop:,.2f}  ·  1R {(seq.pivot - seq.stop) / seq.pivot * 100:.1f}% of pivot"
            ).classes("text-xs mt-2 mono")
