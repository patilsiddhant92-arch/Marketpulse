"""Operator-facing EOD and decision snapshot diagnostics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import duckdb
import pandas as pd
from nicegui import ui

try:
    from pipeline_health import assess_pipeline
except ModuleNotFoundError:
    from Scripts.pipeline_health import assess_pipeline

try:
    from App.market_status import load_market_status
except ModuleNotFoundError:
    from market_status import load_market_status  # type: ignore

try:
    from App.evidence_read_model import summarize_signal_outcomes
except ModuleNotFoundError:
    from evidence_read_model import summarize_signal_outcomes  # type: ignore


def _migration_state(user_db: Path) -> str:
    if not user_db.exists():
        return "not initialized"
    try:
        with duckdb.connect(str(user_db), read_only=True) as db:
            row = db.execute(
                "SELECT setting_value FROM portfolio_settings WHERE setting_key = 'legacy_market_data_migrated'"
            ).fetchone()
        return "complete" if row else "pending"
    except Exception:
        return "unreadable"


def build_data_health_page(
    db_path: Path,
    status_path: Path,
    user_db: Path,
    section_header: Callable,
    table_from_df: Callable,
    compact_kpi: Callable,
) -> None:
    market_status = load_market_status(db_path, status_path)
    report = market_status.report
    section_header(
        "Data Health",
        "Freshness and provenance checks for the market database, NSE PR reports, focused-v2 decisions, and user data.",
    )
    tone = "good" if report.status == "Healthy" else "bad" if report.status in {"Failed", "Missing DB"} else "warn"
    with ui.row().classes("gap-2 flex-wrap mp-toolbar"):
        compact_kpi("Status", report.status)
        compact_kpi("Market date", report.database_date or "—")
        compact_kpi("Decision date", report.focused_v2_date or "—")
        compact_kpi("Decision version", "focused-v2")
        compact_kpi("User data", _migration_state(user_db))
    ui.label(report.message).classes(f"mp-badge mp-{tone} mt-2")
    if not market_status.actionable:
        ui.label(
            f"Decision surfaces are non-actionable until the expected session {market_status.expected_session} is available."
        ).classes("mp-badge mp-bad mt-2")
    details = report.details or {}
    counts = report.row_counts or {}
    count_frame = pd.DataFrame([{"dataset": key, "rows": value} for key, value in counts.items()])
    if not count_frame.empty:
        table_from_df(count_frame, "Loaded datasets", pagination=20, copy_symbols=False, page_key="data-health-counts")
    steps = details.get("steps") or []
    if steps:
        step_frame = pd.DataFrame(
            [
                {
                    "step": item.get("step", ""),
                    "status": "OK" if item.get("ok") else "FAILED",
                    "message": item.get("message") or item.get("error") or "",
                }
                for item in steps
                if isinstance(item, dict)
            ]
        )
        table_from_df(step_frame, "Latest pipeline steps", pagination=20, copy_symbols=False, page_key="data-health-steps")
    if report.last_error:
        ui.label(f"Last error: {report.last_error}").classes("text-sm text-red-700 mt-2")
    if report.log_file:
        ui.label(f"Log: {report.log_file}").classes("text-xs text-[var(--mp-muted)]")

    evidence = summarize_signal_outcomes(db_path, score_version="focused-v2")
    ui.label("Decision evidence").classes("mp-section-title mt-5")
    if evidence.empty:
        ui.label(
            "Evidence unavailable · no resolved walk-forward outcomes are stored yet. "
            "Do not infer hit rate from the candidate queue."
        ).classes("mp-badge mp-warn mt-2")
    else:
        display = evidence.copy()
        for column in ("hit_rate_pct", "avg_forward_return_pct", "median_forward_return_pct", "avg_mfe_pct", "avg_mae_pct"):
            if column in display.columns:
                display[column] = pd.to_numeric(display[column], errors="coerce").round(2)
        table_from_df(
            display,
            "Signal evidence · resolved outcomes",
            pagination=20,
            copy_symbols=False,
            page_key="data-health-evidence",
        )


__all__ = ["build_data_health_page"]
