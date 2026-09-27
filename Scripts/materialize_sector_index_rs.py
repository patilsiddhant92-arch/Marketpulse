"""One-shot: seed index_constituents, stock-vs-index RS, index_bench_rs_daily."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "Scripts"
APP = ROOT / "App"
for p in (ROOT, SCRIPTS, APP):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from config import DB_PATH  # noqa: E402
from index_constituents import (  # noqa: E402
    DEFAULT_MEMBERSHIP_CSV,
    SECTOR_INDEX_COLUMNS,
    ensure_index_constituents,
    load_membership_csv,
)
from sector_index_rs import attach_sector_index_rs, compute_index_bench_rs  # noqa: E402


def materialize(db_path: Path = DB_PATH, *, latest_only: bool = False) -> None:
    mem = load_membership_csv(DEFAULT_MEMBERSHIP_CSV)
    with duckdb.connect(str(db_path)) as con:
        n = ensure_index_constituents(con, DEFAULT_MEMBERSHIP_CSV)
        print(f"index_constituents rows={n}")

        index_daily = con.execute(
            "select trade_date, index_name, close_price from index_daily"
        ).fetchdf()
        master = con.execute(
            "select symbol, sector, industry from stocks_master"
        ).fetchdf()

        # Index vs bench
        bench_rs = compute_index_bench_rs(index_daily)
        con.register("index_bench_rs_df", bench_rs)
        con.execute("DROP TABLE IF EXISTS index_bench_rs_daily")
        con.execute("CREATE TABLE index_bench_rs_daily AS SELECT * FROM index_bench_rs_df")
        latest_nn = con.execute(
            """
            select count(*) from index_bench_rs_daily
            where trade_date = (select max(trade_date) from index_bench_rs_daily)
              and rs_vs_midsml400_63d is not null
            """
        ).fetchone()[0]
        print(f"index_bench_rs_daily rows={len(bench_rs):,} latest MidSml63d non-null={latest_nn}")

        for col in SECTOR_INDEX_COLUMNS:
            if col == "sector_index_name":
                con.execute(
                    "alter table indicators_daily add column if not exists sector_index_name varchar"
                )
            else:
                con.execute(
                    f"alter table indicators_daily add column if not exists {col} double"
                )

        if latest_only:
            mx = con.execute("select max(trade_date) from indicators_daily").fetchone()[0]
            # Need history for lag — load all closes for symbols on latest, but compute needs history
            stock = con.execute(
                "select symbol, trade_date, close_price from indicators_daily order by symbol, trade_date"
            ).fetchdf()
            updated = attach_sector_index_rs(stock, index_daily, mem, master)
            mx_date = pd.Timestamp(mx).date()
            slim = updated.loc[
                pd.to_datetime(updated["trade_date"]).dt.date == mx_date,
                ["symbol", "trade_date", *SECTOR_INDEX_COLUMNS],
            ].copy()
        else:
            stock = con.execute(
                "select symbol, trade_date, close_price from indicators_daily order by symbol, trade_date"
            ).fetchdf()
            print(f"Computing sector-index RS on {len(stock):,} rows...", flush=True)
            updated = attach_sector_index_rs(stock, index_daily, mem, master)
            slim = updated[["symbol", "trade_date", *SECTOR_INDEX_COLUMNS]].copy()

        slim["trade_date"] = pd.to_datetime(slim["trade_date"]).dt.date
        chunk = 50_000
        total = len(slim)
        for start in range(0, total, chunk):
            part = slim.iloc[start : start + chunk]
            con.register("sec_rs_upd", part)
            con.execute(
                """
                update indicators_daily i
                set sector_index_name = u.sector_index_name,
                    rs_vs_sector_index_21d = u.rs_vs_sector_index_21d,
                    rs_vs_sector_index_63d = u.rs_vs_sector_index_63d
                from sec_rs_upd u
                where i.symbol = u.symbol and i.trade_date = u.trade_date
                """
            )
            con.unregister("sec_rs_upd")
            print(f"  updated {min(start+chunk, total):,}/{total:,}", flush=True)

        sample = con.execute(
            """
            select symbol, sector_index_name, rs_vs_sector_index_63d,
                   rs_vs_midsml400_63d, rs_vs_nifty50_63d
            from indicators_daily
            where trade_date = (select max(trade_date) from indicators_daily)
              and symbol in ('RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'DIXON')
            """
        ).fetchdf()
        print(sample.to_string(index=False))
        mapped = con.execute(
            """
            select count(*) from indicators_daily
            where trade_date = (select max(trade_date) from indicators_daily)
              and sector_index_name is not null
            """
        ).fetchone()[0]
        print(f"Latest session mapped symbols: {mapped}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", type=Path, default=DB_PATH)
    p.add_argument("--latest-only", action="store_true")
    args = p.parse_args()
    materialize(args.db, latest_only=args.latest_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
