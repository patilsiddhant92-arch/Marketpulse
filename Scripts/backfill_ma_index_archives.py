"""Date-walk NSE CM Market Activity archives into Input/downloads/<ddmmyyyy>/MA*.csv.

Uses the same session/HTTP patterns as download_nse_reports.py.
Only downloads market-activity files (not full daily report sets).
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "Scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from download_nse_reports import (  # noqa: E402
    DOWNLOAD_ROOT,
    DownloadError,
    ddmmyy,
    ddmmyyyy,
    discover_daily_report_urls,
    download_first,
    make_session,
    report_specs,
)
from index_history import parse_market_activity  # noqa: E402


def ma_candidates_for_day(day: datetime) -> tuple[str, ...]:
    session = make_session()
    discovered = discover_daily_report_urls(session, day)
    specs = report_specs(day, discovered)
    for spec in specs:
        if spec.label == "market activity":
            return spec.candidates
    short = ddmmyy(day)
    return (
        f"https://nsearchives.nseindia.com/archives/equities/mkt/MA{short}.csv",
        f"https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/MA{short}.csv",
        f"https://nsearchives.nseindia.com/products/content/MA{short}.csv",
    )


def download_ma_for_date(day: datetime, *, sleep_s: float = 0.4) -> Path | None:
    """Download MA for one calendar day into Input/downloads/<ddmmyyyy>/. Return path or None."""
    stage = DOWNLOAD_ROOT / ddmmyyyy(day)
    stage.mkdir(parents=True, exist_ok=True)
    dest = stage / f"MA{ddmmyy(day)}.csv"
    if dest.exists() and dest.stat().st_size > 200:
        # validate it parses at least one index
        try:
            frame = parse_market_activity(dest, day.date())
            if not frame.empty:
                return dest
        except Exception:
            pass
    session = make_session()
    discovered = discover_daily_report_urls(session, day)
    specs = report_specs(day, discovered)
    candidates = ()
    for spec in specs:
        if spec.label == "market activity":
            candidates = spec.candidates
            break
    if not candidates:
        candidates = ma_candidates_for_day(day)
    try:
        download_first(session, candidates, dest)
        frame = parse_market_activity(dest, day.date())
        if frame.empty:
            dest.unlink(missing_ok=True)
            return None
        # require benches present when possible (warn only)
        names = set(frame["index_name"].astype(str))
        if "Nifty 50" not in names and "NIFTY MIDSML 400" not in names:
            # still keep file — other indices useful
            pass
        time.sleep(sleep_s)
        return dest
    except DownloadError:
        time.sleep(sleep_s)
        return None


def daterange(start: datetime, end: datetime):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def download_ma_for_dates(
    start: datetime,
    end: datetime,
    *,
    sleep_s: float = 0.4,
    weekdays_only: bool = True,
) -> list[Path]:
    paths: list[Path] = []
    for day in daterange(start, end):
        if weekdays_only and day.weekday() >= 5:
            continue
        path = download_ma_for_date(day, sleep_s=sleep_s)
        if path is not None:
            paths.append(path)
            print(f"  OK {path.name} ({day.strftime('%Y-%m-%d')})")
        else:
            print(f"  skip {day.strftime('%Y-%m-%d')}")
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill NSE CM Market Activity archives by date.")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--sleep", type=float, default=0.4)
    args = parser.parse_args(argv)
    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d")
    print(f"MA date-walk {args.start} → {args.end}")
    paths = download_ma_for_dates(start, end, sleep_s=args.sleep)
    print(f"Downloaded/kept {len(paths)} MA files under {DOWNLOAD_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
