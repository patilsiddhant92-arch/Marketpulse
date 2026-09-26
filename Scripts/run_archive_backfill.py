"""One-click launcher: refresh reference files, resume the archive backfill, rebuild the
index name map, then print/persist a summary. Safe to re-run — the underlying backfill is
resumable (see backfill_archives.run_backfill)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import build_index_name_map
from backfill_archives import BACKFILL_DIR, load_manifest, run_backfill
from config import ARCHIVE_DIR, DAILY_DIR, ROOT_DIR
from download_nse_reports import make_session
from trading_calendar import build_calendar, load_holidays, observed_sessions, refresh_holidays

SYMBOLCHANGE_URL = "https://nsearchives.nseindia.com/content/equities/symbolchange.csv"


def refresh_reference_files(session, ref_dir: Path) -> dict:
    """Refresh the NSE holiday list and the symbol-change map. Each step is independent:
    a failure in one is recorded and does not stop the other or the backfill."""
    ref_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, str] = {}

    try:
        refresh_holidays(session, ref_dir / "nse_holidays.json")
        result["holidays"] = "ok"
    except Exception as exc:  # noqa: BLE001 - recorded, not fatal
        result["holidays"] = f"failed: {exc}"

    try:
        resp = session.get(SYMBOLCHANGE_URL, timeout=30)
        content = resp.content
        head = content[:300].lower()
        if resp.status_code == 200 and b"<html" not in head:
            (ref_dir / "symbolchange.csv").write_bytes(content)
            result["symbolchange"] = "ok"
        else:
            result["symbolchange"] = f"failed: HTTP {resp.status_code}"
    except Exception as exc:  # noqa: BLE001 - recorded, not fatal
        result["symbolchange"] = f"failed: {exc}"

    return result


def summarize(manifest: dict, holidays: set[date], start: date, end: date, bhav_dirs: list[Path]) -> dict:
    by_kind_status: dict[str, int] = {}
    ok_dates_by_kind: dict[str, list[str]] = {}
    for (day_str, kind), rec in manifest.items():
        status = rec.get("status")
        key = f"{kind}:{status}"
        by_kind_status[key] = by_kind_status.get(key, 0) + 1
        if status == "ok":
            ok_dates_by_kind.setdefault(kind, []).append(day_str)

    first_last_ok = {}
    for kind, days in ok_dates_by_kind.items():
        days_sorted = sorted(days)
        first_last_ok[kind] = [days_sorted[0], days_sorted[-1]]

    sessions = observed_sessions(manifest, bhav_dirs)
    cal = build_calendar(start, end, sessions, holidays)
    calendar_reasons = {reason: int(count) for reason, count in cal["reason"].value_counts().items()}

    return {
        "by_kind_status": by_kind_status,
        "first_last_ok": first_last_ok,
        "calendar_reasons": calendar_reasons,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", default="2020-01-01")
    parser.add_argument("--to", dest="end", default=date.today().isoformat())
    parser.add_argument("--kinds", default="bhav,index,pr")
    parser.add_argument("--skip-reference", action="store_true")
    parser.add_argument("--skip-name-map", action="store_true")
    args = parser.parse_args(argv)

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]

    session = make_session()

    ref_dir = ROOT_DIR / "Input" / "reference"
    if not args.skip_reference:
        ref_result = refresh_reference_files(session, ref_dir)
        print(json.dumps({"reference": ref_result}))

    counts = run_backfill(start, end, kinds, session=session, out_dir=BACKFILL_DIR)
    print(json.dumps({"backfill": counts}))

    if not args.skip_name_map:
        rc = build_index_name_map.main()
        if rc:
            print(f"build_index_name_map exited with code {rc} (non-fatal)")

    holidays = load_holidays(ref_dir / "nse_holidays.json")
    bhav_dirs = [ARCHIVE_DIR, BACKFILL_DIR / "bhav", DAILY_DIR]
    manifest = load_manifest(BACKFILL_DIR / "manifest.jsonl")
    summary = summarize(manifest, holidays, start, end, bhav_dirs)
    print(json.dumps(summary, indent=1))
    BACKFILL_DIR.mkdir(parents=True, exist_ok=True)
    (BACKFILL_DIR / "last_run_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")

    return 0 if counts.get("error", 0) == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
