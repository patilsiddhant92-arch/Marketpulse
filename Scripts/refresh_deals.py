"""
Refresh deals tables from archive + daily bulk/block CSVs without rebuilding prices.

Also deletes empty/NO-RECORDS bulk and block junk files from Input/archive.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import duckdb
import pandas as pd

from build_database import (
    build_enrichment,
    enrich_deals,
    make_screener_results,
    read_all_deals,
    read_deals,
    write_database,
)
from config import ARCHIVE_DIR, DB_PATH


def _is_empty_deal_file(path: Path) -> bool:
    """True when file is junk (header only, NO RECORDS, or no parseable deals)."""
    name = path.name.lower()
    if name.startswith("bulk-deals") or name.startswith("block-deals"):
        # Never auto-delete historical range exports
        return False
    if path.stat().st_size <= 150:
        return True
    kind = "Bulk" if name.startswith("bulk") else "Block" if name.startswith("block") else None
    if kind is None:
        return False
    parsed = read_deals(path, kind)
    return parsed.empty


def clean_empty_archive_deals(dry_run: bool = False) -> list[Path]:
    deleted: list[Path] = []
    if not ARCHIVE_DIR.exists():
        return deleted
    candidates: list[Path] = []
    for pattern in ("bulk*.csv", "block*.csv", "Bulk*.csv", "Block*.csv"):
        candidates.extend(ARCHIVE_DIR.glob(pattern))
    # unique by resolve
    seen = set()
    unique = []
    for p in candidates:
        key = str(p.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)

    for path in sorted(unique, key=lambda p: p.name.lower()):
        try:
            if not _is_empty_deal_file(path):
                continue
        except Exception as exc:
            print(f"  skip check {path.name}: {exc}")
            continue
        deleted.append(path)
        if dry_run:
            print(f"  [dry-run] would delete {path.name} ({path.stat().st_size} bytes)")
        else:
            print(f"  deleted empty {path.name} ({path.stat().st_size} bytes)")
            path.unlink(missing_ok=True)
    return deleted


def _load_table(name: str) -> pd.DataFrame:
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        return con.execute(f"SELECT * FROM {name}").fetchdf()


def refresh_deals(clean: bool = True) -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}. Run a full build first.")

    if clean:
        print("Cleaning empty bulk/block files in archive...")
        removed = clean_empty_archive_deals(dry_run=False)
        print(f"  removed {len(removed)} empty files")

    print("Reading deal CSVs (archive + daily + downloads)...")
    deals_raw = read_all_deals()
    if deals_raw.empty:
        raise SystemExit(
            "No deals parsed. Check bulk/block CSVs in Input/archive, Input/daily, and Input/downloads."
        )

    print(
        f"  raw deals after dedupe: {len(deals_raw):,} rows | "
        f"{deals_raw['trade_date'].min().date()} → {deals_raw['trade_date'].max().date()} | "
        f"{deals_raw['trade_date'].nunique()} days"
    )
    print(deals_raw.groupby("deal_type").size().to_string())

    print("Loading prices / indicators / master from existing database...")
    prices = _load_table("prices_daily")
    indicators = _load_table("indicators_daily")
    master = _load_table("stocks_master")
    breadth_daily = _load_table("breadth_daily")
    sector_rotation = _load_table("sector_rotation")
    try:
        enrichment = _load_table("daily_enrichment")
    except Exception:
        enrichment = pd.DataFrame()

    prices["trade_date"] = pd.to_datetime(prices["trade_date"])
    indicators["trade_date"] = pd.to_datetime(indicators["trade_date"])

    print("Enriching deals...")
    deals = enrich_deals(deals_raw, prices, indicators, master)

    print("Rebuilding screener_results (deal-aware screens)...")
    screener_results = make_screener_results(indicators, master, deals, sector_rotation)

    # Refresh has_deal on enrichment from latest deal day when possible
    if not enrichment.empty and not deals.empty:
        latest_deal_day = deals["trade_date"].max()
        latest_syms = set(deals.loc[deals["trade_date"] == latest_deal_day, "symbol"])
        if "has_deal" in enrichment.columns:
            enrichment = enrichment.copy()
            enrichment["has_deal"] = enrichment["symbol"].isin(latest_syms)
        else:
            enrichment = enrichment.copy()
            enrichment["has_deal"] = enrichment["symbol"].isin(latest_syms)

    backup = DB_PATH.with_suffix(".predeals.backup.duckdb")
    print(f"Backing up database → {backup.name}")
    shutil.copy2(DB_PATH, backup)

    print("Writing database (prices/indicators unchanged, deals refreshed)...")
    write_database(
        prices,
        master,
        enrichment if not enrichment.empty else master[["symbol"]].assign(
            security_name="",
            market_cap_cr=pd.NA,
            market_cap_date=pd.NaT,
            band=pd.NA,
            band_remarks="",
            pe=pd.NA,
            adjusted_pe=pd.NA,
            series="",
            high_52w=pd.NA,
            high_52w_date=pd.NaT,
            low_52w=pd.NA,
            low_52w_date=pd.NaT,
            has_deal=False,
        ),
        indicators,
        deals,
        breadth_daily,
        sector_rotation,
        screener_results,
    )

    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        summary = con.execute(
            """
            SELECT min(trade_date) AS min_d, max(trade_date) AS max_d,
                   count(*) AS rows, count(DISTINCT trade_date) AS days
            FROM deals
            """
        ).fetchdf()
        by_type = con.execute("SELECT deal_type, count(*) c FROM deals GROUP BY 1 ORDER BY 1").fetchdf()
    print("Done.")
    print(summary.to_string(index=False))
    print(by_type.to_string(index=False))
    print(f"Backup kept at: {backup}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh MarketPulse deals from CSV files.")
    parser.add_argument("--no-clean", action="store_true", help="Do not delete empty archive deal files.")
    parser.add_argument("--clean-only", action="store_true", help="Only delete empty files; do not touch DB.")
    args = parser.parse_args()
    if args.clean_only:
        print("Cleaning empty bulk/block files in archive...")
        removed = clean_empty_archive_deals(dry_run=False)
        print(f"Removed {len(removed)} files.")
        return
    refresh_deals(clean=not args.no_clean)


if __name__ == "__main__":
    main()
