"""NSE trading calendar: observed sessions (from archives) + official holiday list."""
from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

HOLIDAY_API = "https://www.nseindia.com/api/holiday-master?type=trading"
_BHAV_RE = re.compile(r"sec_bhavdata_full_(\d{2})(\d{2})(\d{4})")

# (path, size, mtime) -> parsed DATE1, so repeated calls (e.g. summarize() during a
# single backfill run) don't re-read every bhavcopy file from disk.
_DATE1_CACHE: dict[tuple[str, int, int], date | None] = {}


def parse_holiday_payload(payload: dict, segment: str = "CM") -> list[date]:
    rows = payload.get(segment)
    if rows is None:
        rows = next((v for v in payload.values() if isinstance(v, list)), [])
    out = [datetime.strptime(r["tradingDate"], "%d-%b-%Y").date() for r in rows if r.get("tradingDate")]
    return sorted(set(out))


def _read_bhav_date1(path: Path) -> date | None:
    """Read the DATE1 value from the first data row of a sec_bhavdata_full_*.csv file.

    NSE sometimes serves a byte-identical copy of the prior session's bhavcopy under a
    non-trading day's filename (weekends, weekday holidays through 2024, and the Muhurat
    session), so the filename date cannot be trusted — DATE1 is the actual trade date.
    """
    try:
        stat = path.stat()
        cache_key = (str(path), stat.st_size, int(stat.st_mtime))
    except OSError:
        return None
    if cache_key in _DATE1_CACHE:
        return _DATE1_CACHE[cache_key]

    result: date | None = None
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.reader(handle, skipinitialspace=True)
            header = next(reader, None)
            if header is not None:
                columns = [str(c).strip().upper() for c in header]
                if "DATE1" in columns:
                    idx = columns.index("DATE1")
                    row = next(reader, None)
                    if row is not None and idx < len(row):
                        value = row[idx].strip()
                        if value:
                            result = datetime.strptime(value, "%d-%b-%Y").date()
    except (OSError, ValueError, StopIteration):
        result = None

    _DATE1_CACHE[cache_key] = result
    return result


def observed_sessions(manifest: dict[tuple[str, str], dict], bhav_dirs: list[Path]) -> set[date]:
    """Sessions actually observed in the downloaded bhavcopy archives.

    A `manifest` "ok" record is not sufficient by itself: NSE's CDN returned HTTP 200
    with a duplicate prior-session file on many non-trading days (see module docstring
    of `_read_bhav_date1`), so the session date comes from the file's internal DATE1,
    not the filename or the manifest status. A manifest-listed file that is missing on
    disk contributes nothing.
    """
    sessions: set[date] = set()
    for folder in bhav_dirs:
        folder = Path(folder)
        if not folder.exists():
            continue
        for path in folder.rglob("sec_bhavdata_full_*.csv"):
            d = _read_bhav_date1(path)
            if d is not None:
                sessions.add(d)
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
