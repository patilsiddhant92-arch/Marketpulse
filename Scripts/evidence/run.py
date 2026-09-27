"""CLI: build evidence tables from a market DB (opened READ-ONLY) into a separate output DB.

    python -m Scripts.evidence.run --db <market.duckdb> --out <evidence.duckdb>
        [--derived-db <db with regime_daily/group_daily/setup_daily>] [--pr-dir Input/archive/backfill/pr]
        [--horizon 20] [--memory-limit 4GB] [--threads 4]

Never writes to --db. --out must be a different file (use a copy of the market DB to serve the API).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Scripts.evidence import LAST_RUN, build_evidence_tables, write_evidence_tables  # noqa: E402

def _default_pr_dir(db: Path) -> Path | None:
    # the DB's project, this checkout, and the main checkout when running from .claude/worktrees/<name>
    for base in (db.resolve().parent.parent, ROOT, *ROOT.parents[:3]):
        cand = Path(base) / "Input" / "archive" / "backfill" / "pr"
        if cand.exists():
            return cand
    return None


def _peak_rss_mb() -> float | None:
    """Peak working set of this process (Windows) / max RSS (POSIX), MB."""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            pmc = PMC()
            pmc.cb = ctypes.sizeof(PMC)
            h = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb)
            return round(pmc.PeakWorkingSetSize / 2**20, 1)
        import resource
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    except Exception:  # pragma: no cover
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, type=Path, help="market DB (read-only)")
    ap.add_argument("--out", required=True, type=Path, help="output DB for evidence tables (must differ from --db)")
    ap.add_argument("--derived-db", type=Path, default=None)
    ap.add_argument("--pr-dir", type=Path, default=None, help="PR zip archive; 'none' to skip")
    ap.add_argument("--horizon", type=int, default=20)
    ap.add_argument("--memory-limit", default="3GB")
    ap.add_argument("--threads", type=int, default=4)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.out.resolve() == args.db.resolve():
        ap.error("--out must be a different database than --db (the market DB is never written)")
    pr_dir = None if str(args.pr_dir).lower() == "none" else (args.pr_dir or _default_pr_dir(args.db))
    t0 = time.time()
    con = duckdb.connect(str(args.db), read_only=True)
    con.execute(f"SET memory_limit = '{args.memory_limit}'")
    con.execute(f"SET threads = {int(args.threads)}")
    dcon = duckdb.connect(str(args.derived_db), read_only=True) if args.derived_db else None
    try:
        tables = build_evidence_tables(con, derived_con=dcon, pr_dir=pr_dir, cache_dir=args.out.parent, horizon=args.horizon)
    finally:
        con.close()
        if dcon is not None:
            dcon.close()
    t1 = time.time()
    out = duckdb.connect(str(args.out))
    try:
        counts = write_evidence_tables(out, tables)
        out.execute("CHECKPOINT")
    finally:
        out.close()
    peak = _peak_rss_mb()
    summary = {"peak_rss_mb": peak, "build_s": round(t1 - t0, 1), "write_s": round(time.time() - t1, 1), "rows": counts,
               "timings_s": LAST_RUN.get("timings_s"), "pr_dir": str(pr_dir) if pr_dir else None}
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
