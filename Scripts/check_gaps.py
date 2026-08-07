"""
Report missing trading sessions between DB max date and latest available bhavcopy / NSE.

Usage:
  python Scripts/check_gaps.py
  python Scripts/check_gaps.py --download-missing
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd

from config import ARCHIVE_DIR, DAILY_DIR, DB_PATH, INPUT_DIR, ROOT_DIR


def _bhav_dates_on_disk() -> set[pd.Timestamp]:
    dates: set[pd.Timestamp] = set()
    for folder in (ARCHIVE_DIR, DAILY_DIR, INPUT_DIR / "downloads"):
        if not folder.exists():
            continue
        paths = folder.rglob("sec_bhavdata_full_*.csv") if folder.name == "downloads" else folder.glob("sec_bhavdata_full_*.csv")
        for path in paths:
            import re

            m = re.search(r"(\d{8})", path.name)
            if not m:
                continue
            try:
                dates.add(pd.to_datetime(m.group(1), format="%d%m%Y").normalize())
            except ValueError:
                continue
    return dates


def _db_date_range() -> tuple[pd.Timestamp | None, pd.Timestamp | None, set[pd.Timestamp]]:
    if not DB_PATH.exists():
        return None, None, set()
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        mn, mx = con.execute("SELECT min(trade_date), max(trade_date) FROM prices_daily").fetchone()
        rows = con.execute("SELECT DISTINCT trade_date FROM prices_daily ORDER BY 1").fetchall()
    present = {pd.to_datetime(r[0]).normalize() for r in rows}
    return (pd.to_datetime(mn).normalize() if mn else None, pd.to_datetime(mx).normalize() if mx else None, present)


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect missing bhavcopy sessions vs DB.")
    parser.add_argument(
        "--download-missing",
        action="store_true",
        help="For each gap date present as a file hole after DB max, run download for that DDMMYYYY.",
    )
    args = parser.parse_args()

    disk = _bhav_dates_on_disk()
    db_min, db_max, db_dates = _db_date_range()

    print("=== MarketPulse gap check ===")
    print(f"Root: {ROOT_DIR}")
    print(f"Bhavcopy files on disk: {len(disk)} sessions")
    if disk:
        print(f"  disk range: {min(disk).date()} → {max(disk).date()}")
    if db_max is None:
        print("Database: missing or empty")
    else:
        print(f"Database: {db_min.date()} → {db_max.date()} ({len(db_dates)} sessions)")

    # Holes inside DB range (true missing trading days that exist on disk but not in DB)
    on_disk_not_in_db = sorted(d for d in disk if d not in db_dates)
    if on_disk_not_in_db:
        print()
        print(f"ON DISK but NOT in DB ({len(on_disk_not_in_db)}) — append will pick these up:")
        for d in on_disk_not_in_db:
            print(f"  {d.date().isoformat()}")
    else:
        print()
        print("No on-disk bhavcopy sessions missing from DB.")

    # Calendar gaps after db_max through latest disk / today
    end = max(disk) if disk else pd.Timestamp(datetime.now().date())
    start = db_max + pd.Timedelta(days=1) if db_max is not None else (min(disk) if disk else None)
    missing_after = []
    if start is not None:
        cur = start
        while cur <= end:
            # only report weekdays as candidates (holidays still may appear if file exists)
            if cur.weekday() < 5 and cur not in db_dates and cur not in disk:
                missing_after.append(cur)
            cur += pd.Timedelta(days=1)

    if missing_after:
        print()
        print(f"Possible MISSING sessions after DB (weekday, no file on disk) ({len(missing_after)}):")
        for d in missing_after[:30]:
            print(f"  {d.date().isoformat()}  →  Run_MarketPulse_Auto.bat --date {d.strftime('%d%m%Y')}")
        if len(missing_after) > 30:
            print(f"  ... +{len(missing_after) - 30} more")
        print()
        print("Then: Run_MarketPulse_Auto.bat   (or Rebuild_MarketPulse.bat for full rebuild)")
    else:
        print("No obvious weekday gaps without files after DB max.")

    if args.download_missing and missing_after:
        from download_nse_reports import parse_date, run as download_run

        for d in missing_after:
            day = datetime(d.year, d.month, d.day)
            print(f"\nDownloading {day.strftime('%d-%m-%Y')}...")
            try:
                rc = download_run(day, dry_run=False)
                print(f"  exit {rc}")
            except Exception as exc:
                print(f"  failed (holiday or NSE not published): {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
