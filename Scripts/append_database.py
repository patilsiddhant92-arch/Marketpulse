import argparse
import shutil
import sys
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
from config import DAILY_DIR, DB_PATH


def _load_table(name: str) -> pd.DataFrame:
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        return con.execute(f"SELECT * FROM {name}").fetchdf()


def _new_daily_prices(universe: set[str], latest_date: pd.Timestamp) -> pd.DataFrame:
    frames = []
    for path in sorted(Path(DAILY_DIR).glob("sec_bhavdata_full_*.csv")):
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Append new daily MarketPulse files without reparsing the full archive.")
    parser.add_argument("--force-full", action="store_true", help="Run a normal full rebuild instead of append.")
    args = parser.parse_args()

    if args.force_full or not DB_PATH.exists():
        from build_database import main as full_build

        print("Running full rebuild.")
        sys.argv = [sys.argv[0]]
        full_build()
        return

    equity = read_equity_symbols()
    universe = set(equity["symbol"])
    existing_prices = _load_table("prices_daily")
    latest_date = pd.to_datetime(existing_prices["trade_date"]).max()
    new_prices = _new_daily_prices(universe, latest_date)
    if new_prices.empty:
        print(f"No new bhavcopy rows found after {latest_date.date()}. Database unchanged.")
        return

    print(f"Appending {len(new_prices):,} price rows from {new_prices['trade_date'].min().date()} to {new_prices['trade_date'].max().date()}.")
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
    indicators = calc_indicators(prices, enrichment)
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
    print(f"Append update complete. Backup: {backup}")


if __name__ == "__main__":
    main()
