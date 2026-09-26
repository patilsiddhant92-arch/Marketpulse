"""Read-only dry-run report for split/bonus/consolidation price adjustments.

Loads `prices_daily` (and, if present, `corporate_actions`) read-only from a DuckDB file, runs
`adjust_prices` against the on-disk PR zips / mcap CSVs under `--root`, and prints a summary:
counts by confidence/applied, the applied events table, the largest `unexplained_gap` rows, and
a raw-vs-adjusted close comparison for a handful of named symbols around their ex-date.

Writes nothing -- the DB connection is opened `read_only=True` and no output file is produced.

Usage:
  python Scripts/adjustment_report.py [--db PATH] [--root PATH] [--symbols SYM,SYM,...]
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import duckdb
import pandas as pd

from config import DB_PATH, ROOT_DIR
from price_adjustment import actions_from_corporate_actions_table, adjust_prices

# The five events Task 9 asks to spot-check: GOODLUCK/PGIL bonuses, TDPOWERSYS/KIRLPNU/TCC splits.
DEFAULT_SYMBOLS = ["GOODLUCK", "PGIL", "TDPOWERSYS", "KIRLPNU", "TCC"]
# Extra symbols worth a one-line confidence check (a pending-ex-date bonus, and two events that
# must NOT show up as applied bonuses).
DEFAULT_CHECK_SYMBOLS = ["AASTHA", "MPEL", "SUNREST"]


def _load_table(db_path: Path, name: str) -> pd.DataFrame:
    """Read a whole table from `db_path` read-only; empty frame if the table doesn't exist."""
    with duckdb.connect(str(db_path), read_only=True) as con:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        if name not in tables:
            return pd.DataFrame()
        return con.execute(f"SELECT * FROM {name}").fetchdf()


def _load_extra_actions(db_path: Path) -> pd.DataFrame | None:
    """Corporate actions from the live DB, re-parsed for `adjust_prices`' `extra_actions` param.

    Mirrors `append_database._load_extra_actions`: returns `None` (which `adjust_prices` treats
    as "no extra actions") when the table is absent, empty, or unparseable, printing a warning
    rather than failing the read-only report.
    """
    try:
        corp = _load_table(db_path, "corporate_actions")
        if corp.empty:
            return None
        return actions_from_corporate_actions_table(corp)
    except Exception as exc:  # noqa: BLE001 - reported, not fatal for a dry-run report
        print(f"Warning: corporate_actions table unusable ({exc}); no extra actions fed to adjust_prices.")
        return None


def _print_counts(adjustments: pd.DataFrame) -> None:
    print("\n=== Counts by confidence ===")
    if adjustments.empty:
        print("(no adjustment rows)")
    else:
        print(adjustments["confidence"].value_counts().to_string())

    print("\n=== Counts by applied ===")
    if adjustments.empty:
        print("(no adjustment rows)")
    else:
        print(adjustments["applied"].astype(bool).value_counts().to_string())


def _print_applied_events(adjustments: pd.DataFrame) -> None:
    print("\n=== Applied events ===")
    if adjustments.empty:
        print("(none applied)")
        return
    applied = adjustments[adjustments["applied"].astype(bool)]
    if applied.empty:
        print("(none applied)")
        return
    cols = ["symbol", "ex_date", "kind", "factor", "source", "confidence"]
    applied = applied.sort_values(["ex_date", "symbol"])[cols]
    print(applied.to_string(index=False))


def _print_unexplained_gaps(adjustments: pd.DataFrame, top_n: int) -> None:
    gaps = pd.DataFrame() if adjustments.empty else adjustments[adjustments["kind"] == "unexplained_gap"]
    print(f"\n=== unexplained_gap rows: {len(gaps)} total ===")
    if gaps.empty:
        return
    # `factor` holds the raw close/prev_close gap_ratio for unexplained_gap rows (see
    # price_adjustment.reconcile); rank by distance from 1.0 (no gap) to surface the largest.
    gaps = gaps.assign(_deviation=(gaps["factor"] - 1).abs()).sort_values("_deviation", ascending=False)
    print(f"Largest {min(top_n, len(gaps))}:")
    print(gaps.head(top_n)[["symbol", "ex_date", "factor"]].rename(columns={"factor": "gap_ratio"}).to_string(index=False))


def _print_named_symbols(adjusted: pd.DataFrame, adjustments: pd.DataFrame, symbols: list[str]) -> None:
    print("\n=== Named symbols: raw vs adjusted close around ex-date ===")
    for symbol in symbols:
        sym_adj = adjustments[adjustments["symbol"] == symbol] if not adjustments.empty else adjustments
        sym_prices = adjusted[adjusted["symbol"] == symbol].sort_values("trade_date")
        applied_events = sym_adj[sym_adj["applied"].astype(bool)] if not sym_adj.empty else sym_adj

        if applied_events.empty:
            print(f"\n{symbol}: no applied events.")
            if not sym_adj.empty:
                print(sym_adj[["ex_date", "kind", "factor", "source", "confidence", "applied"]]
                      .sort_values("ex_date").to_string(index=False))
            continue

        for _, ev in applied_events.sort_values("ex_date").iterrows():
            ex_date = pd.Timestamp(ev["ex_date"])
            before = sym_prices[sym_prices["trade_date"] < ex_date].tail(1)
            on = sym_prices[sym_prices["trade_date"] == ex_date].head(1)
            factor = ev["factor"]
            print(f"\n{symbol}  ex_date={ex_date.date()}  kind={ev['kind']}  factor={factor:.6f}  "
                  f"source={ev['source']}  confidence={ev['confidence']}")
            if before.empty or on.empty:
                print("  (missing day-before or on-ex-date price row -- can't compute move)")
                continue
            b_raw = float(before["close_price"].iloc[0])
            b_adj = float(before["adj_close_price"].iloc[0])
            o_raw = float(on["close_price"].iloc[0])
            o_adj = float(on["adj_close_price"].iloc[0])
            move_pct = (o_adj / b_adj - 1) * 100 if b_adj else float("nan")
            print(f"  day before ({pd.Timestamp(before['trade_date'].iloc[0]).date()}): raw={b_raw:.2f}  adj={b_adj:.2f}")
            print(f"  ex-date    ({pd.Timestamp(on['trade_date'].iloc[0]).date()}): raw={o_raw:.2f}  adj={o_adj:.2f}")
            print(f"  adjusted ex-date move: {move_pct:+.2f}%")


def _print_check_symbols(adjustments: pd.DataFrame, symbols: list[str]) -> None:
    """One-line confidence/applied status per extra symbol -- not the full before/after table,
    just enough to confirm a symbol is (or isn't) treated as an applied bonus/split."""
    print("\n=== Additional confidence checks ===")
    for symbol in symbols:
        rows = adjustments[adjustments["symbol"] == symbol] if not adjustments.empty else pd.DataFrame()
        if rows.empty:
            print(f"{symbol}: no adjustment rows found")
            continue
        print(f"\n{symbol}:")
        print(rows[["ex_date", "kind", "factor", "source", "confidence", "applied"]]
              .sort_values("ex_date").to_string(index=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=str(DB_PATH), help="DuckDB file to read prices_daily/corporate_actions from (opened read-only).")
    parser.add_argument("--root", default=str(ROOT_DIR), help="Root dir to resolve PR zips / mcap CSVs / overrides under (default: project root).")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS), help="Comma-separated symbols for the raw-vs-adjusted before/after table.")
    parser.add_argument("--check-symbols", default=",".join(DEFAULT_CHECK_SYMBOLS), help="Comma-separated symbols for a lighter confidence-only check.")
    parser.add_argument("--top-gaps", type=int, default=20, help="How many largest unexplained_gap rows to print.")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    root = Path(args.root)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    check_symbols = [s.strip().upper() for s in args.check_symbols.split(",") if s.strip()]

    print("=== MarketPulse price-adjustment dry-run report (READ-ONLY, writes nothing) ===")
    print(f"DB:   {db_path}")
    print(f"Root: {root}")

    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return 1

    prices = _load_table(db_path, "prices_daily")
    if prices.empty:
        print("prices_daily is empty or missing; nothing to adjust.")
        return 1
    prices["trade_date"] = pd.to_datetime(prices["trade_date"])

    extra_actions = _load_extra_actions(db_path)

    started = time.perf_counter()
    adjusted, adjustments = adjust_prices(prices, root, extra_actions=extra_actions)
    elapsed = time.perf_counter() - started

    _print_counts(adjustments)
    _print_applied_events(adjustments)
    _print_unexplained_gaps(adjustments, args.top_gaps)
    _print_named_symbols(adjusted, adjustments, symbols)
    _print_check_symbols(adjustments, check_symbols)

    print(f"\n=== Runtime ===\n{elapsed:.2f}s to run adjust_prices over {len(prices):,} price rows")
    print("\nRead-only dry run complete -- no files were written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
