"""Append new daily MarketPulse files without reparsing the full archive.

Single implementation used by CLI and `daily_pipeline` (PR-APPEND).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import duckdb
import pandas as pd

from build_database import (
    apply_reference_symbol_changes,
    build_breadth_daily,
    build_enrichment,
    build_master,
    build_sector_rotation,
    calc_indicators,
    enrich_deals,
    make_screener_results,
    parse_file_date,
    read_52_week,
    read_all_deals,
    read_bhavcopy,
    read_equity_symbols,
    read_market_cap,
    read_pe,
    read_price_band,
    read_sector,
    write_database,
)
from index_history import build_index_features, load_all_index_history
from sector_metrics import compute_sector_metrics
from config import DAILY_DIR, DB_PATH, ROOT_DIR
from price_adjustment import (
    actions_from_corporate_actions_table,
    adjust_prices,
    drop_stale_adjustment_columns,
    indicator_input,
    summarize_adjustments,
)
from reference_history import load_reference_history
from incremental_append import RAW_PRICE_COLUMNS, FullRecomputeRequired, incremental_append

NEW_PRICES_FILENAME_SLACK_DAYS = 10


@dataclass(frozen=True)
class AppendResult:
    action: str
    message: str
    db_date: str | None = None
    new_rows: int = 0
    backup: str | None = None
    duration_ms: int = 0


def _load_table(name: str) -> pd.DataFrame:
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        return con.execute(f"SELECT * FROM {name}").fetchdf()


def _load_extra_actions() -> pd.DataFrame | None:
    """Corporate actions from the live DB, re-parsed for `adjust_prices`' `extra_actions` param.

    Returns `None` (which `adjust_prices` treats as "no extra actions") when the table isn't
    available yet -- e.g. a database that predates the `corporate_actions` table, or one that
    simply has no rows in it yet -- printing a warning with the underlying exception rather
    than failing the whole append.
    """
    try:
        return actions_from_corporate_actions_table(_load_table("corporate_actions"))
    except Exception as exc:
        print(f"Warning: corporate_actions table unavailable ({exc}); no extra actions fed to adjust_prices.")
        return None


def _new_daily_prices(universe: set[str] | None, latest_date: pd.Timestamp) -> pd.DataFrame:
    """Any bhavcopy in daily, archive, or downloads newer than DB max is appended.

    ``universe=None`` (what the append uses) keeps every EQ/BE/BZ row, exactly like the full
    build, so a renamed symbol absent from EQUITY_L (HEG -> HEGAM) is not dropped.

    Files whose filename date is well before the DB max are skipped unparsed: NSE's DATE1
    session is never later than the filename date (holiday duplicates and the Muhurat file
    carry an earlier session), so they cannot hold new rows. The slack keeps the rule safe
    against an odd file dated a little earlier than its session.
    """
    from config import ARCHIVE_DIR, INPUT_DIR

    paths = set(Path(DAILY_DIR).glob("sec_bhavdata_full_*.csv"))
    paths |= set(Path(ARCHIVE_DIR).glob("sec_bhavdata_full_*.csv"))
    downloads = Path(INPUT_DIR) / "downloads"
    if downloads.exists():
        paths |= set(downloads.rglob("sec_bhavdata_full_*.csv"))
    cutoff = latest_date - pd.Timedelta(days=NEW_PRICES_FILENAME_SLACK_DAYS)
    frames = []
    for path in sorted(paths):
        file_date = parse_file_date(path)
        if file_date is not None and file_date < cutoff:
            continue
        frame = read_bhavcopy(path, universe)
        if frame.empty:
            continue
        frame = frame[frame["trade_date"] > latest_date]
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values(["symbol", "trade_date"]).drop_duplicates(["symbol", "trade_date"], keep="last")


def merge_new_prices(existing_prices: pd.DataFrame, new_prices: pd.DataFrame) -> pd.DataFrame:
    """Existing DB prices + newly parsed sessions, with symbol changes applied the same way as
    the full build: when a rename takes effect, the old symbol's history moves under the new
    symbol so the series is continuous (HEG history + HEGAM rows form one series)."""
    prices = pd.concat([existing_prices, new_prices], ignore_index=True)
    prices["trade_date"] = pd.to_datetime(prices["trade_date"])
    prices = prices.sort_values(["symbol", "trade_date"]).drop_duplicates(["symbol", "trade_date"], keep="last")
    prices = drop_stale_adjustment_columns(prices)
    return apply_reference_symbol_changes(prices)


def load_index_for_metrics(root_dir: Path, table_loader: Callable[[str], pd.DataFrame]) -> pd.DataFrame:
    """Index features for sector metrics, including the session being appended.

    The stored index_daily is rewritten from MA files only inside write_database, i.e. after
    sector metrics are computed, so it lacks the newest session.
    """
    try:
        raw = load_all_index_history(root_dir)
        if raw is not None and not raw.empty:
            return build_index_features(raw)
    except Exception as exc:
        print(f"Warning: index history unavailable ({exc}); using stored index_daily")
    try:
        return table_loader("index_daily")
    except Exception:
        return pd.DataFrame()


def append_session(*, force_full: bool = False, notify_telegram: bool = True) -> AppendResult:
    """Run one append (or full rebuild). Sole implementation for pipeline + CLI.

    Holds the DB writer lock for the whole read-merge-write cycle so no other writer can
    change the DB between reading prices_daily and swapping in the new file.
    """
    from db_lock import writer_lock

    with writer_lock(DB_PATH, owner="append_session"):
        return _append_session_locked(force_full=force_full, notify_telegram=notify_telegram)


def _append_session_locked(*, force_full: bool, notify_telegram: bool) -> AppendResult:
    started = time.perf_counter()

    if force_full or not DB_PATH.exists():
        from build_database import main as full_build

        print("Running full rebuild.")
        old_argv = sys.argv
        try:
            sys.argv = [old_argv[0]]
            full_build()
        finally:
            sys.argv = old_argv
        db_date = None
        try:
            with duckdb.connect(str(DB_PATH), read_only=True) as con:
                value = con.execute("SELECT max(trade_date) FROM prices_daily").fetchone()[0]
            if value is not None:
                db_date = pd.to_datetime(value).date().isoformat()
        except Exception:
            pass
        return AppendResult(
            action="full_rebuild",
            message="Created database from scratch." if not force_full else "Forced full rebuild complete.",
            db_date=db_date,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    equity = read_equity_symbols()
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        latest_date = pd.to_datetime(con.execute("SELECT max(trade_date) FROM prices_daily").fetchone()[0])
    new_prices = _new_daily_prices(None, latest_date)
    if new_prices.empty:
        msg = f"No new bhavcopy rows found after {latest_date.date()}. Database unchanged."
        print(msg)
        return AppendResult(
            action="noop",
            message=msg,
            db_date=latest_date.date().isoformat(),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    print(
        f"Appending {len(new_prices):,} price rows "
        f"from {new_prices['trade_date'].min().date()} to {new_prices['trade_date'].max().date()}."
    )
    mode = (os.environ.get("MP_APPEND_MODE", "incremental") or "incremental").strip().lower()
    try:
        if mode == "full":
            raise FullRecomputeRequired("MP_APPEND_MODE=full")
        summary = incremental_append(DB_PATH, new_prices, root=ROOT_DIR, equity=equity)
        backup = summary.get("backup")
        new_max = summary["db_date"]
        _materialize_after_append()
        how = "incremental"
    except FullRecomputeRequired as exc:
        print(f"Incremental append not possible ({exc}); running the full recompute (temp build + swap).")
        backup, new_max = _append_full_recompute(new_prices, equity)
        how = "full recompute"
    msg = f"Append update complete through {new_max} ({how}). Backup: {backup.name if backup else 'none'}"
    print(msg)

    if notify_telegram:
        try:
            from telegram_deals import notify_deals

            notify_deals(dry_run=False, lookback_days=10, min_mcap_cr=900.0)
        except Exception as exc:
            print(f"Telegram deals notify skipped/failed: {exc}")

    return AppendResult(
        action="append",
        message=msg,
        db_date=new_max,
        new_rows=int(len(new_prices)),
        backup=str(backup) if backup else None,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def _materialize_after_append() -> None:
    """Decision tables are materialized after every accepted append (as write_database does)."""
    try:
        from materialize_decision_tables import materialize_decision_tables

        materialize_decision_tables(DB_PATH)
    except Exception as exc:
        print(f"Warning: decision tables were not materialized: {exc}")


def _append_full_recompute(new_prices: pd.DataFrame, equity: pd.DataFrame) -> tuple[Path | None, str]:
    """The old append semantics - every table recomputed from the stored raw prices plus the
    new sessions - through the memory-bounded streaming build and the safe temp-build + swap.
    Used when the incremental path cannot reproduce a full recompute (and MP_APPEND_MODE=full)."""
    from build_database import compute_full_build, discard_staged

    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        have = {r[1] for r in con.execute("PRAGMA table_info('prices_daily')").fetchall()}
        cols = [c for c in RAW_PRICE_COLUMNS if c in have]
        existing_prices = con.execute(f"SELECT {', '.join(cols)} FROM prices_daily").fetchdf()
    prices = merge_new_prices(existing_prices, new_prices)
    del existing_prices
    extra_actions = _load_extra_actions()
    reference_history = load_reference_history(ROOT_DIR)
    if not reference_history.empty:
        reference_for_metrics = reference_history
    else:
        try:
            reference_for_metrics = _load_table("security_reference_daily")
        except Exception:
            reference_for_metrics = pd.DataFrame()
    index_for_metrics = load_index_for_metrics(ROOT_DIR, _load_table)
    frames = compute_full_build(
        quiet=True,
        db_path=DB_PATH,
        raw_prices=prices,
        extra_actions=extra_actions,
        metric_reference=reference_for_metrics,
        metric_index=index_for_metrics,
    )
    del prices
    try:
        # write_database takes the dated backup (Database/backups/) before its atomic swap.
        backup = write_database(**frames, with_derived=True)
    except BaseException:
        discard_staged(frames)
        raise
    staged = frames["prices"]
    max_date = staged.info.get("max_date") if hasattr(staged, "info") else pd.to_datetime(staged["trade_date"]).max()
    return backup, pd.Timestamp(max_date).date().isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description="Append new daily MarketPulse files without reparsing the full archive.")
    parser.add_argument("--force-full", action="store_true", help="Run a normal full rebuild instead of append.")
    args = parser.parse_args()
    result = append_session(force_full=args.force_full, notify_telegram=True)
    print(f"append_session action={result.action} duration_ms={result.duration_ms}")


if __name__ == "__main__":
    main()
