"""Focused-v2 Screener page; fundamentals are intentionally not imported."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Callable

import duckdb
import pandas as pd
from nicegui import ui

try:
    from App.decision_read_model import load_decision_snapshot
except ModuleNotFoundError:
    from decision_read_model import load_decision_snapshot  # type: ignore

try:
    from App.market_status import load_market_status
except ModuleNotFoundError:
    from market_status import load_market_status  # type: ignore


SWING_VIEW_COLUMNS = [
    "symbol",
    "candidate_state",
    "total_score",
    "sector",
    "trigger_price",
    "invalidation_price",
    "distance_to_trigger_pct",
    "reward_to_risk",
    "initial_risk_pct",
    "market_cap_cr",
    "event_risk",
    "market_regime",
    "sector_state",
    "industry_state",
    "why_now",
    "latest_change",
    "risk_summary",
    "warning_reasons",
    "blocking_reasons",
]


def _market_date(db_path: Path) -> date | None:
    try:
        with duckdb.connect(str(db_path), read_only=True) as db:
            value = db.execute("SELECT max(trade_date) FROM indicators_daily").fetchone()[0]
        return pd.Timestamp(value).date() if value is not None else None
    except Exception:
        return None


def build_screener_page(
    db_path: Path,
    section_header: Callable,
    table_from_df: Callable,
    compact_kpi: Callable,
) -> None:
    """Render Prepare/Observe/Blocked diagnostics from focused-v2 only."""
    market_status = load_market_status(db_path, db_path.parent / "status.json")
    snapshot = load_decision_snapshot(db_path, expected_date=_market_date(db_path))
    section_header(
        "Screener",
        "Focused-v2 EOD swing queue. Fundamental inputs are unavailable and are not part of the score.",
    )
    ui.label(
        "Fundamentals unavailable · this queue uses price/volume, market-cap, sector, regime, and event-risk inputs only."
    ).classes("mp-badge mp-warn w-full mt-2")
    with ui.row().classes("gap-2 flex-wrap mp-toolbar"):
        compact_kpi("As of", snapshot.as_of or "Missing")
        compact_kpi("Version", snapshot.score_version)
        compact_kpi("Prepare", int(snapshot.eligible.get("candidate_state", pd.Series(dtype=str)).eq("Prepare").sum()) if not snapshot.eligible.empty else 0)
        compact_kpi("Observe", int(snapshot.eligible.get("candidate_state", pd.Series(dtype=str)).eq("Observe").sum()) if not snapshot.eligible.empty else 0)
        compact_kpi("Blocked / DIAG", len(snapshot.blocked))
        compact_kpi("MCap out", snapshot.excluded_by_market_cap)

    if not market_status.actionable:
        ui.label(
            f"NON-ACTIONABLE · {market_status.status} · database {market_status.database_date or '—'} · expected {market_status.expected_session}. "
            "Use this snapshot for research only; do not treat Prepare rows as live trade instructions."
        ).classes("mp-badge mp-bad w-full mt-2")

    rows = {
        "Prepare": snapshot.eligible[
            snapshot.eligible.get("candidate_state", pd.Series(dtype=str)).astype(str).eq("Prepare")
        ] if not snapshot.eligible.empty else pd.DataFrame(),
        "Observe": snapshot.eligible[
            snapshot.eligible.get("candidate_state", pd.Series(dtype=str)).astype(str).eq("Observe")
        ] if not snapshot.eligible.empty else pd.DataFrame(),
        "Blocked / DIAG": snapshot.blocked,
    }
    current = {"value": "Prepare"}
    with ui.row().classes("gap-2 flex-wrap items-center mt-3 mp-desk-action"):
        buttons = {}
        for label in rows:
            buttons[label] = ui.button(label, on_click=lambda value=label: _select(value)).props("dense outline").classes("mp-button")

    host = ui.column().classes("w-full")

    def paint() -> None:
        host.clear()
        frame = rows[current["value"]].copy()
        view = frame[[column for column in SWING_VIEW_COLUMNS if column in frame.columns]].copy()
        with host:
            if view.empty:
                ui.label("No rows in this state for the current focused-v2 session.").classes("text-[var(--mp-muted)] text-sm mt-2")
            else:
                table_from_df(view, f"{current['value']} · {len(view)} rows", pagination=25, page_key="screener")

    def _select(value: str) -> None:
        current["value"] = value
        for label, button in buttons.items():
            if label == value:
                button.props(remove="outline")
            else:
                button.props("outline")
        paint()

    paint()


__all__ = ["SWING_VIEW_COLUMNS", "build_screener_page"]
