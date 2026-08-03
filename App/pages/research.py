from __future__ import annotations

from collections.abc import Callable

from nicegui import ui


def render_research(specialist_pages: dict[str, Callable[[], None]]) -> None:
    ui.label("Research").classes("text-2xl font-bold")
    if not specialist_pages:
        ui.label("Research pages are not available.")
        return
    selected = ui.select(list(specialist_pages), value=list(specialist_pages)[0], label="Research area").classes("w-72")
    panel = ui.column().classes("w-full")

    def render_selected() -> None:
        panel.clear()
        with panel:
            specialist_pages[selected.value]()

    selected.on_value_change(lambda _: render_selected())
    render_selected()
