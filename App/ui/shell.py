"""Page shell primitives (PR-UI-KIT-B)."""

from __future__ import annotations

from nicegui import ui


def page_shell(title: str, subtitle: str = "", *, eyebrow: str = "") -> None:
    """Premium page header: optional eyebrow, title, muted subtitle."""
    if eyebrow:
        ui.label(eyebrow).classes("text-xs font-semibold uppercase tracking-wide text-[var(--mp-primary)] mb-1")
    ui.label(title).classes("mp-page-title")
    if subtitle:
        ui.label(subtitle).classes("mp-page-subtitle")


def empty_state(message: str, hint: str = "") -> None:
    with ui.card().classes("w-full mp-card p-6"):
        ui.label(message).classes("text-base font-semibold")
        if hint:
            ui.label(hint).classes("text-sm text-[var(--mp-muted)] mt-1")


def skeleton_line(width: str = "w-full") -> None:
    ui.element("div").classes(f"h-3 rounded bg-[var(--mp-surface-offset)] {width} mb-2")


def filter_bar() -> ui.row:
    return ui.row().classes("w-full items-end gap-3 flex-wrap mp-toolbar")
