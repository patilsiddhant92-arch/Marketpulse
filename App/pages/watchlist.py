from __future__ import annotations

from pathlib import Path

from nicegui import ui

from App.query_service import records_for_ui
from Scripts.watchlist_service import load_watchlist


def render_watchlist(db_path: Path) -> None:
    ui.label("Watchlist").classes("text-2xl font-bold")
    rows = load_watchlist(db_path)
    if rows.empty:
        ui.label("No persistent candidates yet.")
        return
    visible = [col for col in ["symbol", "candidate_state", "state_reason", "last_seen_date", "trigger_price", "invalidation_price", "setup_age_sessions"] if col in rows.columns]
    ui.table(columns=[{"name": col, "label": col.replace("_", " ").title(), "field": col} for col in visible], rows=records_for_ui(rows, visible), row_key="symbol").classes("w-full")
