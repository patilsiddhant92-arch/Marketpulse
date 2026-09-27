"""Wires the Scripts/evidence tables (setup outcomes, market analogs, big-move studies, pre-move
watch) into the full build and the daily append.

Fail-soft like the derived step: evidence is research over the core and derived tables, so a
failure is reported loudly (``WARNING: EVIDENCE TABLES ...``) and the previous copy is kept; it
never blocks or undoes the price / indicator write. Runs in its own child process after the
derived step so its multi-million-row frames stay out of the build / append process.

    python Scripts/evidence_step.py --db <market.duckdb>
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pr_dir() -> Path | None:
    cand = ROOT / "Input" / "archive" / "backfill" / "pr"
    return cand if cand.exists() else None


def rebuild_in_place(con, db_path: Path, *, quiet: bool = False) -> dict[str, int]:
    """Build and write the evidence tables into ``con``; returns rows per table (empty on failure).
    Never raises."""
    started = time.perf_counter()
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from Scripts.evidence import build_evidence_tables, write_evidence_tables
        from Scripts.evidence.loaders import load_frames

        frames = load_frames(con, None, _pr_dir(), Path(db_path).parent)
        tables = build_evidence_tables(frames, consume=True)
        con.execute("BEGIN TRANSACTION")
        try:
            written = write_evidence_tables(con, tables)
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
    except Exception as exc:  # noqa: BLE001 - fail-soft
        print(f"WARNING: EVIDENCE TABLES NOT REBUILT ({type(exc).__name__}: {exc}); core tables are unaffected.", flush=True)
        return {}
    if not quiet:
        print(f"Evidence tables rebuilt in {time.perf_counter() - started:.0f}s: {len(written)} tables, "
              f"{sum(written.values()):,} rows", flush=True)
    return written


def run_isolated(db_path: Path, *, quiet: bool = False) -> int:
    """Rebuild the evidence tables of ``db_path`` in a child process (fail-soft). Skipped when
    MP_SKIP_EVIDENCE=1. The caller must not hold a DuckDB connection to ``db_path``."""
    if os.environ.get("MP_SKIP_EVIDENCE", "").strip() == "1":
        print("Evidence tables skipped (MP_SKIP_EVIDENCE=1).", flush=True)
        return 0
    cmd = [sys.executable, str(Path(__file__).resolve()), "--db", str(db_path)]
    if quiet:
        cmd.append("--quiet")
    try:
        done = subprocess.run(cmd, check=False)
    except Exception as exc:  # noqa: BLE001 - fail-soft
        print(f"WARNING: EVIDENCE TABLES NOT REBUILT - could not start the evidence step ({exc}).", flush=True)
        return -1
    if done.returncode != 0:
        print(f"WARNING: EVIDENCE TABLES NOT REBUILT - evidence step exited with code {done.returncode}; core tables are unaffected.", flush=True)
    return done.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild the Scripts/evidence tables of a MarketPulse DuckDB (fail-soft).")
    parser.add_argument("--db", required=True)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    import duckdb

    memory = os.environ.get("MP_BUILD_DUCKDB_MEMORY", "2GB") or "2GB"
    con = duckdb.connect(args.db, config={"memory_limit": memory})
    try:
        rebuild_in_place(con, Path(args.db), quiet=args.quiet)
        con.execute("CHECKPOINT")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
