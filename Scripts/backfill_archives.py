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
