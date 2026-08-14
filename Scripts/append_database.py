"""Append new daily MarketPulse files without reparsing the full archive.

Single implementation used by CLI and `daily_pipeline` (PR-APPEND).
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

from build_database import (
    build_breadth_daily,
    build_enrichment,
    build_master,
    build_sector_rotation,
    calc_indicators,
    enrich_deals,
    make_screener_results,
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
from config import DAILY_DIR, DB_PATH, ROOT_DIR
from reference_history import load_reference_history


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


def _new_daily_prices(universe: set[str], latest_date: pd.Timestamp) -> pd.DataFrame:
    """Any bhavcopy in daily, archive, or downloads newer than DB max is appended."""
    from config import ARCHIVE_DIR, INPUT_DIR

    paths = set(Path(DAILY_DIR).glob("sec_bhavdata_full_*.csv"))
    paths |= set(Path(ARCHIVE_DIR).glob("sec_bhavdata_full_*.csv"))
    downloads = Path(INPUT_DIR) / "downloads"
    if downloads.exists():
        paths |= set(downloads.rglob("sec_bhavdata_full_*.csv"))
    frames = []
    for path in sorted(paths):
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


def append_session(*, force_full: bool = False, notify_telegram: bool = True) -> AppendResult:
    """Run one append (or full rebuild). Sole implementation for pipeline + CLI."""
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
    universe = set(equity["symbol"])
    existing_prices = _load_table("prices_daily")
    latest_date = pd.to_datetime(existing_prices["trade_date"]).max()
    new_prices = _new_daily_prices(universe, latest_date)
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
    prices = pd.concat([existing_prices, new_prices], ignore_index=True)
    prices["trade_date"] = pd.to_datetime(prices["trade_date"])
    prices = prices.sort_values(["symbol", "trade_date"]).drop_duplicates(["symbol", "trade_date"], keep="last")

    sector = read_sector()
    mcap = read_market_cap()
    bands = read_price_band()
    pe = read_pe()
    high52 = read_52_week()
    enrichment = build_enrichment(mcap, bands, pe, high52, pd.DataFrame(), pd.DataFrame())
    master = build_master(equity, sector, prices, mcap, bands, pe)

    # Recompute derived tables from the merged price table. This avoids stale rolling
    # indicators while still skipping the slow archive CSV parse.
    reference_history = load_reference_history(ROOT_DIR)
    indicators = calc_indicators(prices, reference_history if not reference_history.empty else enrichment)
    deals_raw = read_all_deals()
    deals = enrich_deals(deals_raw, prices, indicators, master)
    latest_deals = deals[deals["trade_date"] == deals["trade_date"].max()] if not deals.empty else deals
    enrichment = build_enrichment(mcap, bands, pe, high52, latest_deals, pd.DataFrame())
    breadth_daily = build_breadth_daily(indicators)
    sector_rotation = build_sector_rotation(indicators, master)
    screener_results = make_screener_results(indicators, master, deals, sector_rotation)

    backup = DB_PATH.with_suffix(".preappend.backup.duckdb")
    shutil.copy2(DB_PATH, backup)
    write_database(prices, master, enrichment, indicators, deals, breadth_daily, sector_rotation, screener_results)
    new_max = pd.to_datetime(prices["trade_date"]).max().date().isoformat()
    msg = f"Append update complete through {new_max}. Backup: {backup.name}"
    print(msg)

    if notify_telegram:
        try:
            from telegram_deals import notify_deals

            notify_deals(dry_run=False, lookback_days=10, min_mcap_cr=1000.0)
        except Exception as exc:
            print(f"Telegram deals notify skipped/failed: {exc}")

    return AppendResult(
        action="append",
        message=msg,
        db_date=new_max,
        new_rows=int(len(new_prices)),
        backup=str(backup),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Append new daily MarketPulse files without reparsing the full archive.")
    parser.add_argument("--force-full", action="store_true", help="Run a normal full rebuild instead of append.")
    args = parser.parse_args()
    result = append_session(force_full=args.force_full, notify_telegram=True)
    print(f"append_session action={result.action} duration_ms={result.duration_ms}")


if __name__ == "__main__":
    main()
