"""Shared market-session freshness state used by every decision surface."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

try:
    from Scripts.pipeline_health import HealthReport, assess_pipeline
except ModuleNotFoundError:  # App/app.py can be launched as a script.
    from pipeline_health import HealthReport, assess_pipeline  # type: ignore


@dataclass(frozen=True)
class MarketStatus:
    status: str
    message: str
    database_date: str | None
    decision_date: str | None
    expected_session: str
    actionable: bool
    report: HealthReport


def expected_nse_session(
    reference_date: date | None = None,
    holidays: set[date] | None = None,
) -> date:
    """Return the latest expected NSE session on or before ``reference_date``.

    The local EOD app does not currently maintain a holiday calendar, so the
    default handles weekends and accepts an optional holiday set for callers
    that do have an exchange calendar available.
    """

    current = reference_date or date.today()
    blocked = holidays or set()
    while current.weekday() >= 5 or current in blocked:
        current -= timedelta(days=1)
    return current


def load_market_status(
    db_path: Path,
    status_path: Path | None = None,
    *,
    today: date | None = None,
    holidays: set[date] | None = None,
) -> MarketStatus:
    """Load one canonical freshness status for header, Health, and Screener."""

    expected = expected_nse_session(today, holidays)
    report = assess_pipeline(db_path, status_path=status_path, expected_session=expected)
    return MarketStatus(
        status=report.status,
        message=report.message,
        database_date=report.database_date,
        decision_date=report.focused_v2_date,
        expected_session=expected.isoformat(),
        actionable=report.status == "Healthy",
        report=report,
    )


def non_actionable_message(status: MarketStatus) -> str:
    """Return the single operator-facing freshness guard used across pages."""

    database_date = status.database_date or "—"
    return (
        f"NON-ACTIONABLE · {status.status} · database {database_date} · expected {status.expected_session}. "
        "Use this snapshot for research only; do not treat it as live trade instructions."
    )


__all__ = ["MarketStatus", "expected_nse_session", "load_market_status", "non_actionable_message"]
