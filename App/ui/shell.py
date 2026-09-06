"""Page shell primitives (PR-UI-KIT-B)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from nicegui import ui


def page_shell(title: str, subtitle: str = "", *, eyebrow: str = "") -> None:
    """Premium page header: optional eyebrow, title, muted subtitle."""
    with ui.element("header").classes("mp-page-header"):
        if eyebrow:
            ui.label(eyebrow).classes("text-xs font-semibold uppercase tracking-wide text-[var(--mp-primary)]")
        ui.label(title).classes("mp-page-title")
        if subtitle:
            ui.label(subtitle).classes("mp-page-subtitle")


def status_banner(message: str, *, tone: str = "info", action: str = "") -> None:
    """Render an explicit, compact data-state banner."""
    safe_tone = tone if tone in {"good", "bad", "warn", "info"} else "info"
    with ui.element("div").classes(f"mp-status-banner mp-status-{safe_tone}"):
        ui.label(message).classes("mp-status-message")
        if action:
            ui.label(action).classes("mp-status-action text-[var(--mp-muted)]")


@contextmanager
def section_panel(title: str = "", *, subtitle: str = "") -> Iterator[Any]:
    """Group a page section without adding duplicate wrapper spacing."""
    with ui.element("section").classes("mp-section mp-panel") as panel:
        if title:
            ui.label(title).classes("mp-section-title")
        if subtitle:
            ui.label(subtitle).classes("mp-page-subtitle")
        yield panel


def empty_state(message: str, hint: str = "") -> None:
    with ui.element("div").classes("w-full mp-empty-state"):
        ui.label(message).classes("text-base font-semibold")
        if hint:
            ui.label(hint).classes("text-sm text-[var(--mp-muted)]")


def skeleton_line(width: str = "w-full") -> None:
    ui.element("div").classes(f"h-3 rounded bg-[var(--mp-surface-offset)] {width} mp-skeleton-line")


def filter_bar() -> ui.row:
    return ui.row().classes("w-full items-end gap-3 flex-wrap mp-toolbar mp-control-bar")
