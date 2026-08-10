"""Operator-facing freshness and decision-snapshot health checks."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb


@dataclass(frozen=True)
class HealthReport:
    status: str
    message: str
    database_date: str | None = None
    candidate_date: str | None = None
    focused_v2_date: str | None = None
    row_counts: dict[str, int] = field(default_factory=dict)
    last_error: str | None = None
    log_file: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


def _date_text(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "date"):
        value = value.date()
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return None


def _load_status(status_path: Path | None) -> dict[str, Any]:
    if not status_path or not Path(status_path).exists():
        return {}
    try:
        payload = json.loads(Path(status_path).read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {"error": "status.json is unreadable"}


def assess_pipeline(db_path: Path, *, status_path: Path | None = None, expected_session: str | date | None = None, user_db: Path | None = None) -> HealthReport:
    db_path = Path(db_path)
    expected = _date_text(expected_session)
    status = _load_status(status_path)
    if not db_path.exists():
        return HealthReport("Missing DB", "Market database is missing; no decision snapshot is available.", last_error=status.get("error"), log_file=status.get("log_file"))

    try:
        with duckdb.connect(str(db_path), read_only=True) as db:
            tables = {str(row[0]) for row in db.execute("SHOW TABLES").fetchall()}
            counts: dict[str, int] = {}
            for table in ("prices_daily", "indicators_daily", "candidate_daily", "security_events", "corporate_actions", "security_risk_daily", "top_value_daily", "ingested_reports"):
                if table in tables:
                    counts[table] = int(db.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0])
            database_date = None
            for table in ("prices_daily", "indicators_daily"):
                if table in tables:
                    candidate = _date_text(db.execute(f'SELECT max(trade_date) FROM "{table}"').fetchone()[0])
                    if candidate and (database_date is None or candidate > database_date):
                        database_date = candidate
            candidate_date = _date_text(db.execute("SELECT max(trade_date) FROM candidate_daily").fetchone()[0]) if "candidate_daily" in tables else None
            focused_v2_date = _date_text(db.execute("SELECT max(trade_date) FROM candidate_daily WHERE score_version = 'focused-v2'").fetchone()[0]) if "candidate_daily" in tables else None
            versions = dict(db.execute("SELECT score_version, count(*) FROM candidate_daily GROUP BY score_version").fetchall()) if "candidate_daily" in tables else {}
    except Exception as exc:
        return HealthReport("Failed", f"Market database cannot be read: {exc}", last_error=str(exc))

    failed_steps = [step for step in status.get("steps", []) if isinstance(step, dict) and step.get("ok") is False]
    if status.get("ok") is False or status.get("error"):
        state = "Failed"
        message = str(status.get("message") or status.get("error") or "Pipeline failed.")
    elif failed_steps:
        state = "Partial"
        message = "One or more EOD steps failed."
    elif expected and database_date and database_date < expected:
        state = "Stale"
        message = f"Market database is through {database_date}; expected session is {expected}."
    elif database_date is None or focused_v2_date != database_date:
        state = "Partial"
        message = f"Market data is present, but the focused-v2 decision snapshot is missing or stale (market={database_date}, decision={focused_v2_date})."
    else:
        state = "Healthy"
        message = "Market data and focused-v2 decision snapshot are current."
    return HealthReport(state, message, database_date, candidate_date, focused_v2_date, counts, str(status.get("error")) if status.get("error") else (str(failed_steps[0].get("error")) if failed_steps else None), status.get("log_file"), {"steps": status.get("steps", []), "score_versions": versions})


__all__ = ["HealthReport", "assess_pipeline"]
