# Rebuild Step 2a — Archive Backfill & Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Download ~6.7 years of official NSE history (from 2020-01-01), and teach the builder to use it: a universe built from the bhavcopies themselves (delisted names kept, renames merged), all-index history from `ind_close_all`, and an NSE trading calendar.

**Architecture:** New small modules under `Scripts/`: `nse_archive.py` (URLs + resilient fetch), `backfill_archives.py` (resumable CLI), `trading_calendar.py`, `symbol_changes.py`, `universe.py`; `index_history.py` gains an `ind_close_all` parser and a canonical-name map. `build_database.py` switches its universe and index sources. **No database rebuild runs in this step** — the rebuild happens once, after Step 2b (price adjustment) lands, inside Step 2c's safe-rebuild path.

**Tech Stack:** Python 3.12, pandas, DuckDB, curl_cffi (existing `make_session`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-26-marketpulse-professional-rebuild-design.md` (§4.1 inputs & backfill, §4.3 universe/calendar/taxonomy, §11 testing).

## Probe results (2026-09-26, recorded so tasks use exact facts)

| File | URL pattern | Available from |
|---|---|---|
| `sec_bhavdata_full_DDMMYYYY.csv` | `https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{DDMMYYYY}.csv` | ≥ 2019-10-01 (2019-09-02 → 404). Backfill starts **2020-01-01**. |
| `ind_close_all_DDMMYYYY.csv` | `https://nsearchives.nseindia.com/content/indices/ind_close_all_{DDMMYYYY}.csv` | ≥ 2016 |
| `PRddmmyy.zip` | `https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR{ddmmyy}.zip` | ≥ 2016; members `Bc*.csv` (corp actions, PURPOSE text), `Bm*.txt`, `HL*.csv`, `Pd*.csv`, … ; `MCAP*.csv` only from **mid-2024** |
| `symbolchange.csv` | `https://nsearchives.nseindia.com/content/equities/symbolchange.csv` | current; no header; columns = company, old symbol, new symbol, date `DD-MON-YYYY` |
| Holidays | `https://www.nseindia.com/api/holiday-master?type=trading` (JSON, keyed by segment, e.g. `"CM"`, rows with `tradingDate` `DD-Mon-YYYY`) | current + upcoming year |
| Bulk/block deal history API | `https://www.nseindia.com/api/historical/bulk-deals?...` | **503 to scripts** — not automatable; ranges exported manually from the NSE site are already ingested by `read_all_deals` |
| `ind_close_all` columns | `Index Name, Index Date, Open Index Value, High Index Value, Low Index Value, Closing Index Value, Points Change, Change(%), Volume, Turnover (Rs. Cr.), P/E, P/B, Div Yield` | |
| Index-name overlap | Only 46 / 139 MA index names equal `ind_close_all` names after upper-casing and removing spaces (e.g. MA `NIFTY MIDSML 400` ≠ `NIFTY Midsmallcap 400`) | name map required |

## Global Constraints

- Backfill range default: `2020-01-01` → latest session; files land under `Input/archive/backfill/{bhav,index,pr}/` (git-ignored via `Input/archive/`).
- Network etiquette: ≥ 1.2 s between requests, ≤ 3 retries with exponential backoff + jitter on 5xx/HTML/timeouts; 404 is a definitive "not published" answer, not an error.
- Resumable: every attempted (date, kind) is recorded in `Input/archive/backfill/manifest.jsonl`; re-runs skip `ok` and `not_published` entries.
- Canonical index names stay the existing MA names (so `true_rs`, `sector_index_rs`, UI keep working); `ind_close_all`-only indices keep their own name.
- Universe = bhavcopy rows with series in `{"EQ", "BE", "BZ"}`; delisted and renamed symbols are kept (renames merged onto the current symbol).
- Tests use small fixture files in `tmp_path`; no test hits the network or `Database/`.
- Stage with plain `git add <paths>`; commit trailers end with `Co-Authored-By: <implementing model> <noreply@anthropic.com>`.
- Do not run DB writers (append/refresh/build). Task 7 runs the network backfill only after the user confirms.

---

### Task 1: `nse_archive.py` — URLs and resilient fetch

**Files:**
- Create: `Scripts/nse_archive.py`
- Test: `tests/test_nse_archive.py`

**Interfaces:**
- Produces:
  - `KINDS: dict[str, Callable[[date], str]]` with keys `"bhav"`, `"index"`, `"pr"` → URL for a date.
  - `class FetchResult(NamedTuple): status: str; data: bytes | None; detail: str` where `status ∈ {"ok", "not_published", "error"}`.
  - `fetch(session, url: str, *, retries: int = 3, base_delay: float = 2.0, sleep: Callable[[float], None] = time.sleep) -> FetchResult`.
  - `archive_filename(kind: str, day: date) -> str` (`sec_bhavdata_full_DDMMYYYY.csv`, `ind_close_all_DDMMYYYY.csv`, `PRddmmyy.zip`).

- [ ] **Step 1: Write the failing test** — `tests/test_nse_archive.py`:

```python
from __future__ import annotations

from datetime import date

import nse_archive
from nse_archive import FetchResult, KINDS, archive_filename, fetch


class FakeResponse:
    def __init__(self, status_code: int, content: bytes):
        self.status_code = status_code
        self.content = content


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, url, timeout=None, headers=None):
        self.calls += 1
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_urls_and_filenames():
    d = date(2021, 9, 24)
    assert KINDS["bhav"](d) == "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_24092021.csv"
    assert KINDS["index"](d) == "https://nsearchives.nseindia.com/content/indices/ind_close_all_24092021.csv"
    assert KINDS["pr"](d) == "https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR240921.zip"
    assert archive_filename("bhav", d) == "sec_bhavdata_full_24092021.csv"
    assert archive_filename("index", d) == "ind_close_all_24092021.csv"
    assert archive_filename("pr", d) == "PR240921.zip"


def test_ok_on_first_try():
    s = FakeSession([FakeResponse(200, b"SYMBOL, SERIES\nA, EQ\n")])
    r = fetch(s, "u", sleep=lambda _: None)
    assert r.status == "ok" and r.data.startswith(b"SYMBOL") and s.calls == 1


def test_404_is_not_published_without_retry():
    s = FakeSession([FakeResponse(404, b"<!DOCTYPE html>")])
    r = fetch(s, "u", sleep=lambda _: None)
    assert r.status == "not_published" and s.calls == 1


def test_html_200_and_503_are_retried_then_error():
    s = FakeSession([FakeResponse(503, b"x"), FakeResponse(200, b"<html>blocked</html>"), TimeoutError("t")])
    r = fetch(s, "u", retries=3, sleep=lambda _: None)
    assert r.status == "error" and s.calls == 3


def test_recovers_after_transient_failure():
    s = FakeSession([FakeResponse(503, b"x"), FakeResponse(200, b"PK\x03\x04zip")])
    r = fetch(s, "u", sleep=lambda _: None)
    assert r.status == "ok" and s.calls == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_nse_archive.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nse_archive'`.

- [ ] **Step 3: Implement** — `Scripts/nse_archive.py`:

```python
"""NSE archive URL builders and a polite, resilient fetch for one-off backfills."""
from __future__ import annotations

import random
import time
from datetime import date
from typing import Callable, NamedTuple

NSE_ARCHIVES = "https://nsearchives.nseindia.com"


def _ddmmyyyy(d: date) -> str:
    return d.strftime("%d%m%Y")


def _ddmmyy(d: date) -> str:
    return d.strftime("%d%m%y")


KINDS: dict[str, Callable[[date], str]] = {
    "bhav": lambda d: f"{NSE_ARCHIVES}/products/content/sec_bhavdata_full_{_ddmmyyyy(d)}.csv",
    "index": lambda d: f"{NSE_ARCHIVES}/content/indices/ind_close_all_{_ddmmyyyy(d)}.csv",
    "pr": lambda d: f"{NSE_ARCHIVES}/archives/equities/bhavcopy/pr/PR{_ddmmyy(d)}.zip",
}

_FILENAMES: dict[str, Callable[[date], str]] = {
    "bhav": lambda d: f"sec_bhavdata_full_{_ddmmyyyy(d)}.csv",
    "index": lambda d: f"ind_close_all_{_ddmmyyyy(d)}.csv",
    "pr": lambda d: f"PR{_ddmmyy(d)}.zip",
}


class FetchResult(NamedTuple):
    status: str  # "ok" | "not_published" | "error"
    data: bytes | None
    detail: str


def archive_filename(kind: str, day: date) -> str:
    return _FILENAMES[kind](day)


def _looks_like_html(data: bytes) -> bool:
    head = data[:500].lower()
    return b"<html" in head or b"<!doctype html" in head


def fetch(session, url: str, *, retries: int = 3, base_delay: float = 2.0,
          sleep: Callable[[float], None] = time.sleep) -> FetchResult:
    """404 means NSE did not publish the file (holiday / not yet archived): never retried."""
    last = "no attempt"
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=45)
            if resp.status_code == 404:
                return FetchResult("not_published", None, "HTTP 404")
            if resp.status_code == 200 and resp.content and not _looks_like_html(resp.content):
                return FetchResult("ok", resp.content, "HTTP 200")
            last = f"HTTP {resp.status_code}" + (" (html)" if resp.content and _looks_like_html(resp.content) else "")
        except Exception as exc:  # network errors are transient
            last = f"{type(exc).__name__}: {exc}"
        if attempt < retries - 1:
            sleep(base_delay * (2 ** attempt) + random.uniform(0, 1))
    return FetchResult("error", None, last)
```

- [ ] **Step 4: Run tests** — `.venv/Scripts/python -m pytest tests/test_nse_archive.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add Scripts/nse_archive.py tests/test_nse_archive.py
git commit -m "feat(backfill): NSE archive URL builders and resilient fetch"
```

---

### Task 2: `backfill_archives.py` — resumable downloader

**Files:**
- Create: `Scripts/backfill_archives.py`
- Test: `tests/test_backfill_archives.py`

**Interfaces:**
- Consumes: `KINDS`, `fetch`, `FetchResult`, `archive_filename` (Task 1).
- Produces:
  - `BACKFILL_DIR = ARCHIVE_DIR / "backfill"` (`ARCHIVE_DIR` from `config`).
  - `load_manifest(path: Path) -> dict[tuple[str, str], dict]` keyed by `(iso_date, kind)`.
  - `run_backfill(start: date, end: date, kinds: list[str], *, session, out_dir: Path, pause: float = 1.2, sleep=time.sleep, skip_weekends: bool = False) -> dict[str, int]` returning counts per status. Writes each `ok` file to `out_dir/<kind>/<filename>` and appends one JSON line per attempt to `out_dir/manifest.jsonl` with keys `date, kind, status, bytes, sha256, detail, at`.
  - CLI: `python Scripts/backfill_archives.py --from 2020-01-01 [--to YYYY-MM-DD] [--kinds bhav,index,pr] [--skip-weekends]`.

- [ ] **Step 1: Write the failing test** — `tests/test_backfill_archives.py`:

```python
from __future__ import annotations

import json
from datetime import date

import backfill_archives
from backfill_archives import load_manifest, run_backfill
from nse_archive import FetchResult


def fake_fetch_factory(table):
    calls = []

    def fake_fetch(session, url, **kw):
        calls.append(url)
        return table.get(url, FetchResult("not_published", None, "HTTP 404"))

    return fake_fetch, calls


def test_downloads_writes_files_and_manifest(tmp_path, monkeypatch):
    d = date(2021, 9, 24)
    url = backfill_archives.KINDS["bhav"](d)
    fake, calls = fake_fetch_factory({url: FetchResult("ok", b"SYMBOL, SERIES\n", "HTTP 200")})
    monkeypatch.setattr(backfill_archives, "fetch", fake)
    counts = run_backfill(d, d, ["bhav", "index"], session=None, out_dir=tmp_path, sleep=lambda _: None)
    assert counts == {"ok": 1, "not_published": 1, "error": 0, "skipped": 0}
    assert (tmp_path / "bhav" / "sec_bhavdata_full_24092021.csv").read_bytes() == b"SYMBOL, SERIES\n"
    lines = [json.loads(l) for l in (tmp_path / "manifest.jsonl").read_text().splitlines()]
    assert {(l["kind"], l["status"]) for l in lines} == {("bhav", "ok"), ("index", "not_published")}
    assert len(lines[0]["sha256"]) == 64 or lines[0]["status"] != "ok"


def test_rerun_skips_ok_and_not_published_but_retries_errors(tmp_path, monkeypatch):
    d = date(2021, 9, 24)
    first = {backfill_archives.KINDS["bhav"](d): FetchResult("error", None, "HTTP 503")}
    fake, _ = fake_fetch_factory(first)
    monkeypatch.setattr(backfill_archives, "fetch", fake)
    run_backfill(d, d, ["bhav", "index"], session=None, out_dir=tmp_path, sleep=lambda _: None)
    fake2, calls2 = fake_fetch_factory({backfill_archives.KINDS["bhav"](d): FetchResult("ok", b"x", "HTTP 200")})
    monkeypatch.setattr(backfill_archives, "fetch", fake2)
    counts = run_backfill(d, d, ["bhav", "index"], session=None, out_dir=tmp_path, sleep=lambda _: None)
    assert calls2 == [backfill_archives.KINDS["bhav"](d)]  # index was not_published → skipped
    assert counts["ok"] == 1 and counts["skipped"] == 1
    latest = load_manifest(tmp_path / "manifest.jsonl")
    assert latest[("2021-09-24", "bhav")]["status"] == "ok"


def test_skip_weekends(tmp_path, monkeypatch):
    fake, calls = fake_fetch_factory({})
    monkeypatch.setattr(backfill_archives, "fetch", fake)
    run_backfill(date(2021, 9, 25), date(2021, 9, 26), ["bhav"], session=None, out_dir=tmp_path,
                 sleep=lambda _: None, skip_weekends=True)
    assert calls == []
```

- [ ] **Step 2: Run to verify failure** — `.venv/Scripts/python -m pytest tests/test_backfill_archives.py -v` → FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** — `Scripts/backfill_archives.py`:

```python
"""Resumable one-off backfill of NSE archive files (bhavcopy, all-index close, PR zip)."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from config import ARCHIVE_DIR
from nse_archive import KINDS, archive_filename, fetch

BACKFILL_DIR = ARCHIVE_DIR / "backfill"
FINAL = {"ok", "not_published"}


def load_manifest(path: Path) -> dict[tuple[str, str], dict]:
    latest: dict[tuple[str, str], dict] = {}
    if not path.exists():
        return latest
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            latest[(rec["date"], rec["kind"])] = rec
    return latest


def _days(start: date, end: date, skip_weekends: bool):
    d = start
    while d <= end:
        if not (skip_weekends and d.weekday() >= 5):
            yield d
        d += timedelta(days=1)


def run_backfill(start: date, end: date, kinds: list[str], *, session, out_dir: Path,
                 pause: float = 1.2, sleep=time.sleep, skip_weekends: bool = False) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.jsonl"
    done = load_manifest(manifest_path)
    counts = {"ok": 0, "not_published": 0, "error": 0, "skipped": 0}
    with manifest_path.open("a", encoding="utf-8") as log:
        for day in _days(start, end, skip_weekends):
            for kind in kinds:
                key = (day.isoformat(), kind)
                if done.get(key, {}).get("status") in FINAL:
                    counts["skipped"] += 1
                    continue
                result = fetch(session, KINDS[kind](day), sleep=sleep)
                rec = {"date": day.isoformat(), "kind": kind, "status": result.status, "bytes": 0,
                       "sha256": "", "detail": result.detail, "at": datetime.now().isoformat(timespec="seconds")}
                if result.status == "ok":
                    dest = out_dir / kind / archive_filename(kind, day)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(result.data)
                    rec["bytes"] = len(result.data)
                    rec["sha256"] = hashlib.sha256(result.data).hexdigest()
                log.write(json.dumps(rec) + "\n")
                log.flush()
                counts[result.status] += 1
                sleep(pause)
    return counts


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--from", dest="start", required=True)
    p.add_argument("--to", dest="end", default=date.today().isoformat())
    p.add_argument("--kinds", default="bhav,index,pr")
    p.add_argument("--skip-weekends", action="store_true")
    args = p.parse_args(argv)
    from download_nse_reports import make_session

    counts = run_backfill(date.fromisoformat(args.start), date.fromisoformat(args.end),
                          [k.strip() for k in args.kinds.split(",") if k.strip()],
                          session=make_session(), out_dir=BACKFILL_DIR, skip_weekends=args.skip_weekends)
    print(json.dumps(counts))
    return 0 if counts["error"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests** — `.venv/Scripts/python -m pytest tests/test_backfill_archives.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add Scripts/backfill_archives.py tests/test_backfill_archives.py
git commit -m "feat(backfill): resumable NSE archive backfill CLI with manifest"
```

---

### Task 3: NSE trading calendar

**Files:**
- Create: `Scripts/trading_calendar.py`
- Create: `Input/reference/nse_holidays.json` (written by `refresh_holidays`; committed)
- Test: `tests/test_trading_calendar.py`

**Interfaces:**
- Consumes: `load_manifest` (Task 2).
- Produces:
  - `parse_holiday_payload(payload: dict, segment: str = "CM") -> list[date]` (falls back to the first list-valued key if `segment` is missing).
  - `observed_sessions(manifest: dict[tuple[str, str], dict], bhav_dirs: list[Path]) -> set[date]` — dates with an `ok` bhav manifest row, plus dates parsed from any `sec_bhavdata_full_DDMMYYYY.csv` filename in `bhav_dirs`.
  - `build_calendar(start: date, end: date, sessions: set[date], holidays: set[date]) -> pd.DataFrame` with columns `trade_date, is_session, reason` where reason ∈ `{"session", "special_session", "holiday", "weekend", "unknown"}` (`special_session` = weekend date with a session; `unknown` = weekday with neither a session nor a listed holiday, e.g. download error).
  - `expected_latest_session(now: datetime, sessions: set[date], holidays: set[date], close_hour: int = 18) -> date` — last weekday ≤ today (≤ yesterday before `close_hour` IST) that is not a listed holiday, or a later observed special session.
  - `refresh_holidays(session, path: Path) -> list[date]` — GETs the holiday API, writes the raw JSON to `path`, returns parsed dates.

- [ ] **Step 1: Write the failing test** — `tests/test_trading_calendar.py`:

```python
from __future__ import annotations

from datetime import date, datetime

from trading_calendar import build_calendar, expected_latest_session, observed_sessions, parse_holiday_payload

PAYLOAD = {"CM": [{"tradingDate": "26-Jan-2026", "weekDay": "Monday", "description": "Republic Day"},
                  {"tradingDate": "02-Oct-2026", "weekDay": "Friday", "description": "Gandhi Jayanti"}],
           "CBM": [{"tradingDate": "15-Jan-2026"}]}


def test_parse_holidays_prefers_cm_segment():
    assert parse_holiday_payload(PAYLOAD) == [date(2026, 1, 26), date(2026, 10, 2)]
    assert parse_holiday_payload({"XX": [{"tradingDate": "01-May-2026"}]}) == [date(2026, 5, 1)]


def test_observed_sessions_from_manifest_and_files(tmp_path):
    (tmp_path / "sec_bhavdata_full_25092026.csv").write_text("x")
    manifest = {("2026-09-24", "bhav"): {"status": "ok"}, ("2026-09-23", "bhav"): {"status": "error"},
                ("2026-09-22", "index"): {"status": "ok"}}
    assert observed_sessions(manifest, [tmp_path]) == {date(2026, 9, 24), date(2026, 9, 25)}


def test_build_calendar_reasons():
    sessions = {date(2026, 11, 6), date(2026, 11, 8)}  # Fri + Sunday Muhurat
    holidays = {date(2026, 11, 10)}
    cal = build_calendar(date(2026, 11, 6), date(2026, 11, 10), sessions, holidays).set_index("trade_date")
    assert cal.loc[date(2026, 11, 6), "reason"] == "session"
    assert cal.loc[date(2026, 11, 7), "reason"] == "weekend"
    assert cal.loc[date(2026, 11, 8), "reason"] == "special_session"
    assert cal.loc[date(2026, 11, 9), "reason"] == "unknown"
    assert cal.loc[date(2026, 11, 10), "reason"] == "holiday"
    assert bool(cal.loc[date(2026, 11, 8), "is_session"]) is True


def test_expected_latest_session_skips_weekend_and_holiday():
    holidays = {date(2026, 10, 2)}
    # Saturday 3-Oct evening → Thursday 1-Oct (Fri 2-Oct is a holiday)
    assert expected_latest_session(datetime(2026, 10, 3, 20, 0), set(), holidays) == date(2026, 10, 1)
    # Monday 5-Oct morning (before close) → still Thursday 1-Oct
    assert expected_latest_session(datetime(2026, 10, 5, 9, 0), set(), holidays) == date(2026, 10, 1)
    # Monday evening → Monday
    assert expected_latest_session(datetime(2026, 10, 5, 19, 0), set(), holidays) == date(2026, 10, 5)
    # Sunday Muhurat session already observed → that Sunday
    assert expected_latest_session(datetime(2026, 11, 8, 20, 0), {date(2026, 11, 8)}, set()) == date(2026, 11, 8)
```

- [ ] **Step 2: Run to verify failure** — `.venv/Scripts/python -m pytest tests/test_trading_calendar.py -v` → FAIL.

- [ ] **Step 3: Implement** — `Scripts/trading_calendar.py`:

```python
"""NSE trading calendar: observed sessions (from archives) + official holiday list."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

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
    day = now.date() if now.hour >= close_hour else now.date() - timedelta(days=1)
    if day in sessions:
        return day
    while day.weekday() >= 5 or day in holidays:
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
```

- [ ] **Step 4: Run tests** — `.venv/Scripts/python -m pytest tests/test_trading_calendar.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add Scripts/trading_calendar.py tests/test_trading_calendar.py
git commit -m "feat(calendar): NSE trading calendar from observed sessions and holiday list"
```

(`Input/reference/nse_holidays.json` is created and committed in Task 7.)

---

### Task 4: All-index history from `ind_close_all` + canonical names

**Files:**
- Modify: `Scripts/index_history.py` (add parser, name map, merged loader)
- Create: `Scripts/build_index_name_map.py`
- Test: `tests/test_index_close_all.py`

**Interfaces:**
- Produces in `Scripts/index_history.py`:
  - `EXTRA_INDEX_COLUMNS = ["volume", "turnover_cr", "pe", "pb", "div_yield"]`
  - `parse_ind_close_all(path: Path) -> pd.DataFrame` → `INDEX_COLUMNS + EXTRA_INDEX_COLUMNS` (`previous_close = close − points_change`, `return_1d_pct` from `Change(%)`, `index_name` stripped, `trade_date` from `Index Date` `DD-MM-YYYY`).
  - `load_index_name_map(path: Path) -> dict[str, str]` (CSV `source_name,canonical_name`; missing file → `{}`).
  - `load_all_index_history(root: Path, name_map_path: Path | None = None) -> pd.DataFrame` — concatenates every `ind_close_all_*.csv` under `root/Input/archive`, `root/Input/archive/backfill/index`, `root/Input/daily`, renames via the map, then fills any `(trade_date, index_name)` missing from that set using `load_all_market_activity_history(root)`; de-duplicates keeping the `ind_close_all` row.
- Produces `Scripts/build_index_name_map.py`: `derive_name_map(close_all: pd.DataFrame, ma: pd.DataFrame, min_overlap: int = 5, tol: float = 0.01) -> pd.DataFrame` (columns `source_name, canonical_name, overlap_days`) — for each `ind_close_all` name, the MA name whose `close_price` equals it within `tol` on ≥ `min_overlap` common dates, preferring the most matches; plus CLI writing `Input/reference/index_name_map.csv`.

- [ ] **Step 1: Write the failing test** — `tests/test_index_close_all.py`:

```python
from __future__ import annotations

import pandas as pd

from build_index_name_map import derive_name_map
from index_history import load_all_index_history, parse_ind_close_all

CSV = """Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,Points Change,Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield
Nifty 50,25-09-2026,25000.00,25100.00,24900.00,25050.00,50.00,0.20,300000000,25000.5,22.1,3.5,1.2
NIFTY Midsmallcap 400,25-09-2026,19000.00,19100.00,18900.00,19080.00,-20.00,-0.10,-,-,-,-,-
"""


def test_parse_ind_close_all(tmp_path):
    p = tmp_path / "ind_close_all_25092026.csv"
    p.write_text(CSV)
    df = parse_ind_close_all(p)
    row = df.set_index("index_name").loc["Nifty 50"]
    assert row["close_price"] == 25050.0 and row["previous_close"] == 25000.0
    assert row["return_1d_pct"] == 0.2 and row["volume"] == 300000000 and row["pe"] == 22.1
    assert str(df["trade_date"].iloc[0].date()) == "2026-09-25"
    assert pd.isna(df.set_index("index_name").loc["NIFTY Midsmallcap 400", "pe"])


def test_derive_name_map_by_matching_closes():
    dates = pd.to_datetime(["2026-09-2%d" % i for i in range(1, 7)])
    close_all = pd.DataFrame({"trade_date": list(dates) * 2,
                              "index_name": ["NIFTY Midsmallcap 400"] * 6 + ["Nifty 50"] * 6,
                              "close_price": [19000 + i for i in range(6)] + [25000 + i for i in range(6)]})
    ma = pd.DataFrame({"trade_date": list(dates) * 2,
                       "index_name": ["NIFTY MIDSML 400"] * 6 + ["Nifty 50"] * 6,
                       "close_price": [19000 + i for i in range(6)] + [25000 + i for i in range(6)]})
    m = derive_name_map(close_all, ma).set_index("source_name")
    assert m.loc["NIFTY Midsmallcap 400", "canonical_name"] == "NIFTY MIDSML 400"
    assert m.loc["Nifty 50", "canonical_name"] == "Nifty 50"


def test_load_all_prefers_close_all_and_fills_from_ma(tmp_path, monkeypatch):
    daily = tmp_path / "Input" / "daily"
    daily.mkdir(parents=True)
    (daily / "ind_close_all_25092026.csv").write_text(CSV)
    ref = tmp_path / "map.csv"
    ref.write_text("source_name,canonical_name\nNIFTY Midsmallcap 400,NIFTY MIDSML 400\n")
    ma = pd.DataFrame({"trade_date": pd.to_datetime(["2026-09-24", "2026-09-25"]),
                       "index_name": ["NIFTY MIDSML 400", "NIFTY MIDSML 400"],
                       "previous_close": [1.0, 1.0], "open_price": [1.0, 1.0], "high_price": [1.0, 1.0],
                       "low_price": [1.0, 1.0], "close_price": [18000.0, 99999.0], "change_value": [0.0, 0.0],
                       "return_1d_pct": [0.0, 0.0]})
    import index_history
    monkeypatch.setattr(index_history, "load_all_market_activity_history", lambda root: ma)
    out = load_all_index_history(tmp_path, ref).set_index(["trade_date", "index_name"])
    assert out.loc[(pd.Timestamp("2026-09-25"), "NIFTY MIDSML 400"), "close_price"] == 19080.0  # close_all wins
    assert out.loc[(pd.Timestamp("2026-09-24"), "NIFTY MIDSML 400"), "close_price"] == 18000.0  # MA fills gap
```

- [ ] **Step 2: Run to verify failure** — `.venv/Scripts/python -m pytest tests/test_index_close_all.py -v` → FAIL.

- [ ] **Step 3: Implement** — append to `Scripts/index_history.py`:

```python
EXTRA_INDEX_COLUMNS = ["volume", "turnover_cr", "pe", "pb", "div_yield"]


def parse_ind_close_all(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path, dtype=str)
    raw.columns = [str(c).strip() for c in raw.columns]
    num = lambda col: pd.to_numeric(raw[col].astype(str).str.replace(",", "").str.strip().replace({"-": None}), errors="coerce")
    out = pd.DataFrame({
        "trade_date": pd.to_datetime(raw["Index Date"].str.strip(), format="%d-%m-%Y", errors="coerce"),
        "index_name": raw["Index Name"].astype(str).str.strip(),
        "open_price": num("Open Index Value"),
        "high_price": num("High Index Value"),
        "low_price": num("Low Index Value"),
        "close_price": num("Closing Index Value"),
        "change_value": num("Points Change"),
        "return_1d_pct": num("Change(%)"),
        "volume": num("Volume"),
        "turnover_cr": num("Turnover (Rs. Cr.)"),
        "pe": num("P/E"),
        "pb": num("P/B"),
        "div_yield": num("Div Yield"),
    })
    out["previous_close"] = out["close_price"] - out["change_value"]
    out = out.dropna(subset=["trade_date", "close_price"])
    return out[INDEX_COLUMNS + EXTRA_INDEX_COLUMNS]


def load_index_name_map(path: Path) -> dict[str, str]:
    if path is None or not Path(path).exists():
        return {}
    m = pd.read_csv(path, dtype=str)
    return dict(zip(m["source_name"].str.strip(), m["canonical_name"].str.strip()))


def load_all_index_history(root: Path, name_map_path: Path | None = None) -> pd.DataFrame:
    root = Path(root)
    name_map_path = name_map_path or (root / "Input" / "reference" / "index_name_map.csv")
    folders = [root / "Input" / "archive", root / "Input" / "archive" / "backfill" / "index", root / "Input" / "daily"]
    frames = []
    for folder in folders:
        if folder.exists():
            for p in sorted(folder.glob("ind_close_all_*.csv")):
                try:
                    frames.append(parse_ind_close_all(p))
                except Exception as exc:
                    print(f"Skipped {p.name}: {exc}")
    close_all = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=INDEX_COLUMNS + EXTRA_INDEX_COLUMNS)
    name_map = load_index_name_map(name_map_path)
    close_all["index_name"] = close_all["index_name"].map(lambda n: name_map.get(n, n))
    close_all = close_all.drop_duplicates(["trade_date", "index_name"], keep="last")
    ma = load_all_market_activity_history(root)
    if ma is not None and not ma.empty:
        ma = ma.copy()
        ma["trade_date"] = pd.to_datetime(ma["trade_date"]).dt.normalize()
        have = set(zip(close_all["trade_date"], close_all["index_name"]))
        ma = ma[[(d, n) not in have for d, n in zip(ma["trade_date"], ma["index_name"])]]
        close_all = pd.concat([close_all, ma], ignore_index=True)
    return close_all.sort_values(["trade_date", "index_name"]).reset_index(drop=True)
```

Create `Scripts/build_index_name_map.py`:

```python
"""Derive ind_close_all → canonical (MA) index names by matching closing values on common dates."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from config import ROOT_DIR
from index_history import load_all_market_activity_history, parse_ind_close_all

MAP_PATH = ROOT_DIR / "Input" / "reference" / "index_name_map.csv"


def derive_name_map(close_all: pd.DataFrame, ma: pd.DataFrame, min_overlap: int = 5, tol: float = 0.01) -> pd.DataFrame:
    a = close_all[["trade_date", "index_name", "close_price"]].rename(columns={"index_name": "source_name", "close_price": "c1"})
    b = ma[["trade_date", "index_name", "close_price"]].rename(columns={"index_name": "canonical_name", "close_price": "c2"})
    j = a.merge(b, on="trade_date")
    j = j[(j["c1"] - j["c2"]).abs() <= tol]
    counts = j.groupby(["source_name", "canonical_name"]).size().rename("overlap_days").reset_index()
    counts = counts[counts["overlap_days"] >= min_overlap]
    best = counts.sort_values(["source_name", "overlap_days"], ascending=[True, False]).drop_duplicates("source_name")
    return best.reset_index(drop=True)


def main() -> int:
    folders = [ROOT_DIR / "Input" / "archive", ROOT_DIR / "Input" / "archive" / "backfill" / "index", ROOT_DIR / "Input" / "daily"]
    frames = [parse_ind_close_all(p) for f in folders if f.exists() for p in sorted(f.glob("ind_close_all_*.csv"))]
    if not frames:
        print("No ind_close_all files found; run the backfill first.")
        return 1
    m = derive_name_map(pd.concat(frames, ignore_index=True), load_all_market_activity_history(ROOT_DIR))
    MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    m.to_csv(MAP_PATH, index=False)
    print(f"Wrote {len(m)} mappings to {MAP_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests** — `.venv/Scripts/python -m pytest tests/test_index_close_all.py tests/test_index_history.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add Scripts/index_history.py Scripts/build_index_name_map.py tests/test_index_close_all.py
git commit -m "feat(index): ind_close_all parser, canonical name map, merged index history"
```

---

### Task 5: Universe from bhavcopies, renames merged

**Files:**
- Create: `Scripts/symbol_changes.py`, `Scripts/universe.py`
- Modify: `Scripts/build_database.py` (`read_bhavcopy`, `build_prices`)
- Test: `tests/test_universe.py`

**Interfaces:**
- Produces:
  - `symbol_changes.parse_symbol_changes(path: Path) -> pd.DataFrame` with `old_symbol, new_symbol, change_date` (headerless CSV: company, old, new, `DD-MON-YYYY`).
  - `symbol_changes.resolve_current_symbol(changes: pd.DataFrame) -> dict[str, str]` — follows chains (A→B, B→C ⇒ A→C, B→C); self-maps are removed by the parser; symbols in a cycle are left unmapped. Add to the test: `resolve_current_symbol(pd.DataFrame({"old_symbol": ["A", "B"], "new_symbol": ["B", "A"], "change_date": [None, None]})) == {}`.
  - `universe.SERIES_WHITELIST = frozenset({"EQ", "BE", "BZ"})`
  - `universe.apply_symbol_changes(prices: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame` — rewrites `symbol`, then de-duplicates `(symbol, trade_date)` preferring EQ.
  - `universe.build_universe_history(prices: pd.DataFrame, active_symbols: set[str]) -> pd.DataFrame` with `symbol, first_date, last_date, last_series, sessions, status` (`status = "active"` if in `active_symbols` else `"inactive"`).
  - `build_database.read_bhavcopy(path, universe: set[str] | None = None)` — when `universe is None`, keeps rows whose series is in `SERIES_WHITELIST` (the new default); passing a set keeps the old behaviour for existing callers/tests.
  - `build_database.build_prices(universe: set[str] | None = None)` — also globs `ARCHIVE_DIR / "backfill" / "bhav"`; when `universe is None` applies `apply_symbol_changes` using `Input/reference/symbolchange.csv` if present.

- [ ] **Step 1: Write the failing test** — `tests/test_universe.py`:

```python
from __future__ import annotations

import pandas as pd

from build_database import read_bhavcopy
from symbol_changes import parse_symbol_changes, resolve_current_symbol
from universe import apply_symbol_changes, build_universe_history

BHAV = """SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER
OLDCO, EQ, 24-Sep-2021, 10, 10, 11, 9, 10.5, 10.5, 10.2, 1000, 1.0, 10, 500, 50.0
DELISTED, BE, 24-Sep-2021, 5, 5, 5, 5, 5, 5, 5, 100, 0.05, 1, -, -
BONDX, N1, 24-Sep-2021, 100, 100, 100, 100, 100, 100, 100, 10, 0.01, 1, -, -
"""

CHANGES = """ OLD COMPANY LTD,OLDCO,MIDCO,01-JAN-2023
 MID COMPANY LTD,MIDCO,NEWCO,01-JAN-2025
 SELF LTD,SAME,SAME,01-JAN-2024
"""


def test_default_universe_is_series_whitelist(tmp_path):
    p = tmp_path / "sec_bhavdata_full_24092021.csv"
    p.write_text(BHAV)
    df = read_bhavcopy(p)
    assert set(df["symbol"]) == {"OLDCO", "DELISTED"}
    assert pd.isna(df.set_index("symbol").loc["DELISTED", "delivery_pct"])


def test_explicit_universe_still_supported(tmp_path):
    p = tmp_path / "sec_bhavdata_full_24092021.csv"
    p.write_text(BHAV)
    assert set(read_bhavcopy(p, {"OLDCO"})["symbol"]) == {"OLDCO"}


def test_symbol_change_chains(tmp_path):
    p = tmp_path / "symbolchange.csv"
    p.write_text(CHANGES)
    mapping = resolve_current_symbol(parse_symbol_changes(p))
    assert mapping == {"OLDCO": "NEWCO", "MIDCO": "NEWCO"}


def test_apply_changes_and_universe_history():
    prices = pd.DataFrame({
        "symbol": ["OLDCO", "NEWCO", "DELISTED"],
        "series": ["EQ", "EQ", "BE"],
        "trade_date": pd.to_datetime(["2021-09-24", "2025-09-24", "2021-09-24"]),
        "close_price": [10.5, 20.0, 5.0],
    })
    merged = apply_symbol_changes(prices, {"OLDCO": "NEWCO"})
    assert sorted(merged["symbol"]) == ["DELISTED", "NEWCO", "NEWCO"]
    uh = build_universe_history(merged, active_symbols={"NEWCO"}).set_index("symbol")
    assert uh.loc["NEWCO", "status"] == "active" and uh.loc["NEWCO", "sessions"] == 2
    assert str(uh.loc["NEWCO", "first_date"].date()) == "2021-09-24"
    assert uh.loc["DELISTED", "status"] == "inactive" and uh.loc["DELISTED", "last_series"] == "BE"
```

- [ ] **Step 2: Run to verify failure** — `.venv/Scripts/python -m pytest tests/test_universe.py -v` → FAIL.

- [ ] **Step 3: Implement** — `Scripts/symbol_changes.py`:

```python
"""NSE symbol change history (symbolchange.csv) → current-symbol mapping."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def parse_symbol_changes(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path, header=None, dtype=str, names=["company", "old_symbol", "new_symbol", "change_date"],
                      skipinitialspace=True, on_bad_lines="skip")
    raw["old_symbol"] = raw["old_symbol"].astype(str).str.strip().str.upper()
    raw["new_symbol"] = raw["new_symbol"].astype(str).str.strip().str.upper()
    raw["change_date"] = pd.to_datetime(raw["change_date"].astype(str).str.strip(), format="%d-%b-%Y", errors="coerce")
    raw = raw[(raw["old_symbol"] != "") & (raw["new_symbol"] != "") & (raw["old_symbol"] != raw["new_symbol"])]
    return raw[["old_symbol", "new_symbol", "change_date"]].sort_values("change_date").reset_index(drop=True)


def resolve_current_symbol(changes: pd.DataFrame) -> dict[str, str]:
    """Map every old symbol to its latest symbol, following chains; symbols in a cycle are skipped."""
    step = dict(zip(changes["old_symbol"], changes["new_symbol"]))
    resolved: dict[str, str] = {}
    for start in step:
        seen = {start}
        cur = step[start]
        while cur in step and cur not in seen:
            seen.add(cur)
            cur = step[cur]
        if cur in seen:  # A→B→A: ambiguous, leave unmapped
            continue
        resolved[start] = cur
    return resolved
```

`Scripts/universe.py`:

```python
"""Point-in-time equity universe built from the bhavcopies themselves (no survivorship filter)."""
from __future__ import annotations

import pandas as pd

SERIES_WHITELIST = frozenset({"EQ", "BE", "BZ"})


def apply_symbol_changes(prices: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    if not mapping or prices.empty:
        return prices
    out = prices.copy()
    out["symbol"] = out["symbol"].map(lambda s: mapping.get(s, s))
    out["_pri"] = (out.get("series", pd.Series("EQ", index=out.index)) != "EQ").astype(int)
    out = out.sort_values(["symbol", "trade_date", "_pri"]).drop_duplicates(["symbol", "trade_date"], keep="first")
    return out.drop(columns="_pri").reset_index(drop=True)


def build_universe_history(prices: pd.DataFrame, active_symbols: set[str]) -> pd.DataFrame:
    p = prices.sort_values(["symbol", "trade_date"])
    g = p.groupby("symbol")
    out = pd.DataFrame({
        "first_date": g["trade_date"].min(),
        "last_date": g["trade_date"].max(),
        "last_series": g["series"].last(),
        "sessions": g["trade_date"].nunique(),
    }).reset_index()
    out["status"] = out["symbol"].map(lambda s: "active" if s in active_symbols else "inactive")
    return out
```

In `Scripts/build_database.py`:
- change the signature to `def read_bhavcopy(path: Path, universe: set[str] | None = None) -> pd.DataFrame:` and replace `df = df[df["symbol"].isin(universe)]` with:

```python
    if universe is None:
        from universe import SERIES_WHITELIST
        df = df[df["series"].isin(SERIES_WHITELIST)]
    else:
        df = df[df["symbol"].isin(universe)]
```

- in `build_prices`, change the signature to `universe: set[str] | None = None`, add `files |= set((ARCHIVE_DIR / "backfill" / "bhav").glob("sec_bhavdata_full_*.csv"))`, and after the final de-duplication add:

```python
    if universe is None:
        changes_path = INPUT_DIR / "reference" / "symbolchange.csv"
        if changes_path.exists():
            from symbol_changes import parse_symbol_changes, resolve_current_symbol
            from universe import apply_symbol_changes
            prices = apply_symbol_changes(prices, resolve_current_symbol(parse_symbol_changes(changes_path)))
```

Do **not** change the existing call site in `main()` (it still passes `universe`); switching the rebuild to `universe=None` happens in Step 2c together with the safe rebuild.

- [ ] **Step 4: Run tests** — `.venv/Scripts/python -m pytest tests/test_universe.py tests/test_indicators_golden.py tests/test_reconciliation.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add Scripts/symbol_changes.py Scripts/universe.py Scripts/build_database.py tests/test_universe.py
git commit -m "feat(universe): bhavcopy-derived universe with series whitelist and symbol-change merge"
```

---

### Task 6: Use the merged index history in build and append

**Files:**
- Modify: `Scripts/build_database.py` (index ingestion inside `write_database`, ~"1. Ingest index_daily from all MA files")
- Modify: `Scripts/append_database.py` (`load_index_for_metrics`)
- Test: `tests/test_append_index_order.py` (extend), `tests/test_index_close_all.py` (reuse)

**Interfaces:**
- Consumes: `load_all_index_history(root, name_map_path=None)` (Task 4).
- Produces: `write_database` builds `index_daily` from `build_index_features(load_all_index_history(ROOT_DIR))`; `load_index_for_metrics` uses the same loader. The `index_daily` table gains columns `volume, turnover_cr, pe, pb, div_yield` (NULL for MA-only rows).

- [ ] **Step 1: Write the failing test** — add to `tests/test_append_index_order.py`:

```python
def test_load_index_for_metrics_uses_merged_loader(monkeypatch, tmp_path):
    fresh = pd.DataFrame({"trade_date": pd.to_datetime(["2026-09-25"]), "index_name": ["Nifty 50"], "close_price": [2.0]})
    monkeypatch.setattr(append_database, "load_all_index_history", lambda root: fresh)
    monkeypatch.setattr(append_database, "build_index_features", lambda raw: raw)
    out = append_database.load_index_for_metrics(tmp_path, lambda name: pd.DataFrame())
    assert out["trade_date"].max() == pd.Timestamp("2026-09-25")
```

Update the two existing tests in that file to monkeypatch `load_all_index_history` instead of `load_all_market_activity_history` (same fake frames; the failure test raises from `load_all_index_history`).

- [ ] **Step 2: Run to verify failure** — `.venv/Scripts/python -m pytest tests/test_append_index_order.py -v` → FAIL (`AttributeError: ... load_all_index_history`).

- [ ] **Step 3: Implement** — in `Scripts/append_database.py` change the import to `from index_history import build_index_features, load_all_index_history` and inside `load_index_for_metrics` replace `raw = load_all_market_activity_history(root_dir)` with `raw = load_all_index_history(root_dir)` (update the warning text to "index history unavailable"). In `Scripts/build_database.py` change `from index_history import build_index_features, load_all_market_activity_history` to also import `load_all_index_history`, and in `write_database` replace `index_raw = load_all_market_activity_history(ROOT_DIR)` with `index_raw = load_all_index_history(ROOT_DIR)` and update the printed message to "Ingested index_daily (ind_close_all + MA fallback)".

Check `build_index_features` keeps the extra columns (it copies the input frame, so they pass through); confirm with a quick assertion in `tests/test_index_close_all.py`:

```python
def test_features_keep_extra_columns(tmp_path):
    from index_history import build_index_features
    p = tmp_path / "ind_close_all_25092026.csv"
    p.write_text(CSV)
    feats = build_index_features(parse_ind_close_all(p))
    assert {"volume", "pe", "ema_200", "return_20d_pct"} <= set(feats.columns)
```

- [ ] **Step 4: Run tests** — `.venv/Scripts/python -m pytest tests/test_append_index_order.py tests/test_index_close_all.py tests/test_index_history.py tests/test_true_rs.py tests/test_sector_index_rs.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add Scripts/build_database.py Scripts/append_database.py tests/test_append_index_order.py tests/test_index_close_all.py
git commit -m "feat(index): build and append read ind_close_all history with MA fallback"
```

---

### Task 7: Run the backfill and generate reference files (network; user confirms first)

**Files:**
- Create (data, committed): `Input/reference/index_name_map.csv`, `Input/reference/nse_holidays.json`, `Input/reference/symbolchange.csv`
- Create (data, git-ignored): `Input/archive/backfill/**`

- [ ] **Step 1: Ask the user** — "Task 7 downloads about 6.7 years of NSE archive files (~2,470 days × 3 kinds, ~1.2 s apart ≈ 2.5–3 h, a few GB) into `Input/archive/backfill/`. It only reads public archive files. OK to start?" Proceed only on yes.

- [ ] **Step 2: Reference files**

```bash
.venv/Scripts/python - <<'EOF'
import sys; sys.path[:0] = ["Scripts"]
from pathlib import Path
from download_nse_reports import make_session
from trading_calendar import refresh_holidays
s = make_session()
print(len(refresh_holidays(s, Path("Input/reference/nse_holidays.json"))), "holidays")
r = s.get("https://nsearchives.nseindia.com/content/equities/symbolchange.csv", timeout=30)
assert r.status_code == 200 and b"<html" not in r.content[:300].lower()
Path("Input/reference/symbolchange.csv").write_bytes(r.content)
print(len(r.content), "bytes symbolchange")
EOF
```

- [ ] **Step 3: Backfill** (run in background; it is resumable — re-run the same command after any interruption):

```bash
.venv/Scripts/python Scripts/backfill_archives.py --from 2020-01-01 --kinds bhav,index,pr
```

Expected final line: JSON counts; `error` should be 0 after at most two re-runs. Then summarise the manifest:

```bash
.venv/Scripts/python -c "import sys,collections;sys.path[:0]=['Scripts'];from backfill_archives import load_manifest,BACKFILL_DIR;m=load_manifest(BACKFILL_DIR/'manifest.jsonl');print(collections.Counter((k,v['status']) for (d,k),v in m.items()))"
```

- [ ] **Step 4: Index name map** — `.venv/Scripts/python Scripts/build_index_name_map.py`, then check that the key benchmarks map: `grep -E "NIFTY MIDSML 400|Nifty 50,|NIFTY SMLCAP 250|NIFTY MIDCAP 150" Input/reference/index_name_map.csv`. Any MA name used by `Scripts/true_rs.py` or `Scripts/sector_index_rs.py` (grep for quoted index names there) that has no mapping must be listed in the report.

- [ ] **Step 5: Calendar sanity** — using `observed_sessions` + `load_holidays` + `build_calendar` from 2020-01-01 to the latest session, print counts per `reason`; every `unknown` weekday must be explained (download error to re-run, or a real holiday missing from the current-year-only holiday file — expected for past years).

- [ ] **Step 6: Commit reference files**

```bash
git add Input/reference/index_name_map.csv Input/reference/nse_holidays.json Input/reference/symbolchange.csv
git commit -m "data: NSE index-name map, holiday list and symbol-change reference files"
```

- [ ] **Step 7: Report** — manifest counts per kind/status, first and last `ok` date per kind, calendar reason counts, unmapped benchmark names, total bytes downloaded. No database rebuild in this step.
