"""Validated full rebuild of the MarketPulse market DB.

Runs the FULL build (universe = bhavcopy EQ/BE/BZ rows, symbol changes applied) into
``<db>.tmp.duckdb``, carries over the preserved user/auxiliary tables, prints row counts and
date ranges per table, validates the result against the target DB, and only then takes a dated
backup and swaps it in with ``os.replace`` (see build_database.install_database). The target's
writer lock is held from the temp build to the swap.

Validation (any failure = no swap, temp kept for inspection, exit code 2):
  * prices_daily is non-empty;
  * its max trade_date is >= the target's current max trade_date;
  * every preserved table present in the target exists in the temp DB with >= as many rows.

Usage:
  python Scripts/safe_rebuild.py [--db PATH] [--dry-run] [--keep-temp] [--quiet]

--db defaults to the live DB (config.DB_PATH / MP_DB_PATH). Rehearse on a copy first:
  copy Database\\marketpulse.duckdb C:\\tmp\\mp\\marketpulse.duckdb
  python Scripts/safe_rebuild.py --db C:\\tmp\\mp\\marketpulse.duckdb --dry-run
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_database import (  # noqa: E402
    PRESERVED_TABLES,
    DatabaseSwapError,
    PreservationError,
    build_temp_database,
    compute_full_build,
    discard_staged,
    install_database,
    temp_db_path,
)
from config import DB_PATH  # noqa: E402

_DATE_COLUMNS = ("trade_date", "effective_date", "ex_date", "first_seen_date", "as_of_date")


def table_summary(db_path: Path) -> pd.DataFrame:
    """rows + min/max of the first date-like column, per table."""
    out = []
    with duckdb.connect(str(db_path), read_only=True) as con:
        tables = [row[0] for row in con.execute("SELECT table_name FROM information_schema.tables ORDER BY 1").fetchall()]
        for table in tables:
            rows = con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            cols = {row[1] for row in con.execute(f'PRAGMA table_info("{table}")').fetchall()}
            date_col = next((c for c in _DATE_COLUMNS if c in cols), None)
            lo = hi = None
            if date_col and rows:
                lo, hi = con.execute(f'SELECT min("{date_col}"), max("{date_col}") FROM "{table}"').fetchone()
            out.append({"table": table, "rows": int(rows), "date_col": date_col or "",
                        "min_date": _day(lo), "max_date": _day(hi)})
    return pd.DataFrame(out, columns=["table", "rows", "date_col", "min_date", "max_date"])


def _day(value) -> str:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    return pd.Timestamp(value).date().isoformat()


def _counts(db_path: Path) -> dict[str, int]:
    if not Path(db_path).exists():
        return {}
    with duckdb.connect(str(db_path), read_only=True) as con:
        tables = [row[0] for row in con.execute("SELECT table_name FROM information_schema.tables").fetchall()]
        return {t: int(con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]) for t in tables}


def _max_price_date(db_path: Path):
    if not Path(db_path).exists():
        return None
    with duckdb.connect(str(db_path), read_only=True) as con:
        has = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'prices_daily'").fetchone()[0]
        if not has:
            return None
        value = con.execute("SELECT max(trade_date) FROM prices_daily").fetchone()[0]
    return pd.Timestamp(value) if value is not None else None


def validate_temp(temp_db: Path, live_db: Path) -> list[str]:
    """Problems that must block the swap (empty list = OK)."""
    problems: list[str] = []
    temp_counts = _counts(temp_db)
    if temp_counts.get("prices_daily", 0) == 0:
        problems.append("prices_daily is empty in the rebuilt DB")
    live_max, temp_max = _max_price_date(live_db), _max_price_date(temp_db)
    if live_max is not None and (temp_max is None or temp_max < live_max):
        problems.append(f"rebuilt prices max date {_day(temp_max) or 'none'} is older than target max date {_day(live_max)}")
    live_counts = _counts(live_db)
    for table in PRESERVED_TABLES:
        if table not in live_counts:
            continue
        if table not in temp_counts:
            problems.append(f"preserved table {table} missing from rebuilt DB (target has {live_counts[table]:,} rows)")
        elif temp_counts[table] < live_counts[table]:
            problems.append(f"preserved table {table} has {temp_counts[table]:,} rows, target has {live_counts[table]:,}")
    return problems


def _print_summary(title: str, summary: pd.DataFrame, live: dict[str, int] | None = None) -> None:
    print(f"\n=== {title} ===")
    if summary.empty:
        print("(no tables)")
        return
    frame = summary.copy()
    if live is not None:
        frame["target_rows"] = frame["table"].map(lambda t: f"{live[t]:,}" if t in live else "-")
    frame["rows"] = frame["rows"].map(lambda n: f"{n:,}")
    print(frame.to_string(index=False))


def _materialize(db_path: Path) -> None:
    try:
        from materialize_decision_tables import materialize_decision_tables

        materialize_decision_tables(db_path)
    except Exception as exc:  # noqa: BLE001 - same policy as write_database
        print(f"Warning: decision tables were not materialized: {exc}")


def run(db_path: Path, *, dry_run: bool = False, keep_temp: bool = False, quiet: bool = False) -> int:
    from db_lock import writer_lock

    db_path = Path(db_path)
    started = time.perf_counter()
    print(f"Safe rebuild -> {db_path}{' (DRY RUN: no swap)' if dry_run else ''}")
    # Streaming build: prices_daily / indicators_daily are staged in <db>.stage.duckdb (beside
    # the target) and adopted as the temp DB by build_temp_database - no second full copy.
    frames = compute_full_build(quiet=quiet, db_path=db_path)
    try:
        with writer_lock(db_path, owner="safe_rebuild"):
            try:
                temp = build_temp_database(**frames, db_path=db_path, with_derived=True)
            except PreservationError as exc:
                print(f"ABORTED: {exc}. Target DB untouched.")
                return 2
            return _validate_and_install(temp, db_path, dry_run=dry_run, keep_temp=keep_temp, started=started)
    finally:
        discard_staged(frames)  # no-op once build_temp_database has adopted the staging file


def _validate_and_install(temp: Path, db_path: Path, *, dry_run: bool, keep_temp: bool, started: float) -> int:
    live_counts = _counts(db_path)
    _print_summary(f"Rebuilt DB ({temp.name})", table_summary(temp), live_counts)
    problems = validate_temp(temp, db_path)
    if problems:
        print("\nVALIDATION FAILED - not swapping:")
        for p in problems:
            print(f"  - {p}")
        print(f"Target DB untouched. Rebuilt DB kept for inspection at {temp}")
        return 2
    print("\nValidation passed.")
    if dry_run:
        if keep_temp:
            print(f"Dry run: rebuilt DB kept at {temp}; target not swapped.")
        else:
            temp.unlink(missing_ok=True)
            print("Dry run: temp DB removed; target not swapped.")
        print(f"Done in {time.perf_counter() - started:.0f}s.")
        return 0
    try:
        backup = install_database(temp, db_path)
    except DatabaseSwapError as exc:
        print(f"SWAP FAILED: {exc}")
        return 3
    print(f"Swapped. Backup of the previous DB: {backup or 'none (no previous DB)'}")
    _materialize(db_path)
    _print_summary(f"Installed DB ({db_path.name})", table_summary(db_path))
    print(f"Done in {time.perf_counter() - started:.0f}s.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=str(DB_PATH), help="Target DB path (default: the live DB).")
    parser.add_argument("--dry-run", action="store_true", help="Build and validate only; never swap.")
    parser.add_argument("--keep-temp", action="store_true", help="With --dry-run, keep the rebuilt temp DB.")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    return run(Path(args.db), dry_run=args.dry_run, keep_temp=args.keep_temp, quiet=args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
