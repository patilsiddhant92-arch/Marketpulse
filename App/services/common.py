"""Shared result type and data-freshness logic for API v2 services."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from App.services import db

IST = timezone(timedelta(hours=5, minutes=30))
EOD_READY_HOUR_IST = 18  # bhavcopy + EOD run are expected by 18:00 IST

STATUS_OK = "ok"
STATUS_PARTIAL = "partial"
STATUS_UNAVAILABLE = "unavailable"


@dataclass
class Result:
    """What a service hands to a route. Rows are complete; the route pages them."""

    as_of: date | None
    rows: list[dict[str, Any]] = field(default_factory=list)
    status: str = STATUS_OK
    reason: str | None = None
    sources: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    metric_keys: list[str] = field(default_factory=list)


def unavailable(as_of: date | None, reason: str, sources: list[str] | None = None, **extra: Any) -> Result:
    """Normal envelope, no rows, never fabricated numbers."""
    return Result(as_of=as_of, rows=[], status=STATUS_UNAVAILABLE, reason=reason, sources=sources or [], extra=extra)


def no_session(as_of_requested: date | None) -> Result:
    if as_of_requested is None:
        return unavailable(None, "no sessions in indicators_daily", ["indicators_daily"])
    return unavailable(None, f"no trading session on or before {as_of_requested.isoformat()}", ["indicators_daily"])


# --------------------------------------------------------------------------
# Freshness
# --------------------------------------------------------------------------
def load_holidays() -> set[date]:
    path = db.holidays_path()
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    out: set[date] = set()
    rows: list[Any] = []
    if isinstance(payload, dict):
        for key in ("CM", "holidays", "data"):
            if isinstance(payload.get(key), list):
                rows = payload[key]
                break
    elif isinstance(payload, list):
        rows = payload
    for row in rows:
        raw = row.get("tradingDate") or row.get("date") if isinstance(row, dict) else row
        for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                out.add(datetime.strptime(str(raw), fmt).date())
                break
            except (TypeError, ValueError):
                continue
    return out


def is_trading_day(d: date, holidays: set[date]) -> bool:
    return d.weekday() < 5 and d not in holidays


def expected_session(now: datetime | None = None, holidays: set[date] | None = None) -> date:
    """Latest NSE session whose EOD data should already be in the DB."""
    holidays = holidays if holidays is not None else load_holidays()
    now_ist = (now or datetime.now(timezone.utc)).astimezone(IST)
    d = now_ist.date()
    if now_ist.hour < EOD_READY_HOUR_IST:
        d -= timedelta(days=1)
    while not is_trading_day(d, holidays):
        d -= timedelta(days=1)
    return d


def sessions_between(latest: date, expected: date, holidays: set[date]) -> int:
    """Trading days in (latest, expected]."""
    if latest >= expected:
        return 0
    n, d = 0, latest + timedelta(days=1)
    while d <= expected:
        if is_trading_day(d, holidays):
            n += 1
        d += timedelta(days=1)
    return n


def pipeline_status() -> dict[str, Any]:
    path = db.status_path()
    if not path.exists():
        return {"present": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"present": True, "readable": False}
    if not isinstance(payload, dict):
        return {"present": True, "readable": False}
    failed = [s.get("step") for s in payload.get("steps", []) if isinstance(s, dict) and s.get("ok") is False]
    return {
        "present": True,
        "readable": True,
        "ok": payload.get("ok"),
        "error": payload.get("error"),
        "failed_steps": failed,
        "finished_at": payload.get("finished_at"),
    }


def freshness(con: Any, as_of: date | None, now: datetime | None = None) -> dict[str, Any]:
    """Freshness of the market DB (always about the latest session, not as_of)."""
    holidays = load_holidays()
    latest = db.latest_session(con)
    expected = expected_session(now, holidays)
    status_doc = pipeline_status()
    degraded_reason = None
    if status_doc.get("present") and status_doc.get("readable") is False:
        degraded_reason = "status.json unreadable"
    elif status_doc.get("ok") is False or status_doc.get("error"):
        degraded_reason = "last EOD run failed"
    elif status_doc.get("failed_steps"):
        degraded_reason = "EOD steps failed: " + ", ".join(str(s) for s in status_doc["failed_steps"])
    if latest is None:
        state, behind = "unavailable", None
    else:
        behind = sessions_between(latest, expected, holidays)
        state = "fresh" if behind == 0 else "stale"
        if degraded_reason:
            state = "degraded"
    return {
        "status": state,
        "latest_session": latest,
        "expected_session": expected,
        "sessions_behind": behind,
        "history_mode": bool(as_of is not None and latest is not None and as_of < latest),
        "reason": degraded_reason,
    }
