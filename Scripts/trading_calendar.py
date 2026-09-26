"""NSE trading calendar: observed sessions (from archives) + official holiday list."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

HOLIDAY_API = "https://www.nseindia.com/api/holiday-master?type=trading"
_BHAV_RE = re.compile(r"sec_bhavdata_full_(\d{2})(\d{2})(\d{4})")


def parse_holiday_payload(payload: dict, segment: str = "CM") -> list[date]:
    rows = payload.get(segment)
    if rows is None:
        rows = next((v for v in payload.values() if isinstance(v, list)), [])
    out = [datetime.strptime(r["tradingDate"], "%d-%b-%Y").date() for r in rows if r.get("tradingDate")]
    return sorted(set(out))


def observed_sessions(manifest: dict[tuple[str, str], dict], bhav_dirs: list[Path]) -> set[date]:
    sessions = {date.fromisoformat(d) for (d, kind), rec in manifest.items() if kind == "bhav" and rec.get("status") == "ok"}
    for folder in bhav_dirs:
        if not folder.exists():
            continue
        for path in folder.rglob("sec_bhavdata_full_*.csv"):
            m = _BHAV_RE.search(path.name)
            if m:
                dd, mm, yyyy = m.groups()
                sessions.add(date(int(yyyy), int(mm), int(dd)))
    return sessions


def build_calendar(start: date, end: date, sessions: set[date], holidays: set[date]) -> pd.DataFrame:
    rows = []
    d = start
    while d <= end:
        weekend = d.weekday() >= 5
        if d in sessions:
            reason = "special_session" if weekend else "session"
        elif d in holidays:
            reason = "holiday"
        elif weekend:
            reason = "weekend"
        else:
            reason = "unknown"
        rows.append({"trade_date": d, "is_session": d in sessions, "reason": reason})
        d += timedelta(days=1)
    return pd.DataFrame(rows, columns=["trade_date", "is_session", "reason"])


def expected_latest_session(now: datetime, sessions: set[date], holidays: set[date], close_hour: int = 18) -> date:
    """Find the most recent valid trading session.

    Naive datetimes are interpreted as IST wall-clock time.
    """
    if now.tzinfo is not None:
        now = now.astimezone(ZoneInfo("Asia/Kolkata"))

    day = now.date() if now.hour >= close_hour else now.date() - timedelta(days=1)
    while not (day in sessions or (day.weekday() < 5 and day not in holidays)):
        day -= timedelta(days=1)
    return day


def refresh_holidays(session, path: Path) -> list[date]:
    resp = session.get(HOLIDAY_API, timeout=30, headers={"accept": "application/json,*/*"})
    resp.raise_for_status()
    payload = resp.json()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return parse_holiday_payload(payload)


def load_holidays(path: Path) -> set[date]:
    if not path.exists():
        return set()
    return set(parse_holiday_payload(json.loads(path.read_text(encoding="utf-8"))))
