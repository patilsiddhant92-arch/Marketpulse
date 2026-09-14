"""Materialize true RS columns onto indicators_daily from current index_daily."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "Scripts"
for p in (ROOT, SCRIPTS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from config import DB_PATH  # noqa: E402
from true_rs import TRUE_RS_COLUMNS, attach_true_rs_columns  # noqa: E402


def materialize(db_path: Path = DB_PATH, *, latest_only: bool = False) -> None:
    with duckdb.connect(str(db_path)) as con:
        index_daily = con.execute(
            "select trade_date, index_name, close_price from index_daily"
        ).fetchdf()
        for col in TRUE_RS_COLUMNS:
            con.execute(f"alter table indicators_daily add column if not exists {col} double")

        if latest_only:
            mx = con.execute("select max(trade_date) from indicators_daily").fetchone()[0]
            dates = [mx]
        else:
            dates = [
                r[0]
                for r in con.execute(
                    "select distinct trade_date from indicators_daily order by trade_date"
                ).fetchall()
            ]

        # Need lookback history per symbol — load rolling window of closes, update only target dates.
        # Simpler robust path: load all symbol/date/close once, compute, update in chunks of dates.
        print(f"Loading indicators closes ({len(dates)} target dates)...", flush=True)
        stock = con.execute(
            "select symbol, trade_date, close_price from indicators_daily order by symbol, trade_date"
        ).fetchdf()
        print(f"Computing true RS on {len(stock):,} rows...", flush=True)
        updated = attach_true_rs_columns(stock, index_daily)
        slim = updated[["symbol", "trade_date", *TRUE_RS_COLUMNS]].copy()
        slim["trade_date"] = pd.to_datetime(slim["trade_date"]).dt.date
        if latest_only:
            mx_date = pd.Timestamp(dates[0]).date() if not isinstance(dates[0], type(pd.Timestamp("2020-01-01").date())) else dates[0]
            try:
                mx_date = pd.Timestamp(dates[0]).date()
            except Exception:
                mx_date = dates[0]
            slim = slim.loc[slim["trade_date"] == mx_date]

        chunk = 50_000
        total = len(slim)
        for start in range(0, total, chunk):
            part = slim.iloc[start : start + chunk]
            con.register("true_rs_upd", part)
            set_clause = ", ".join(f"{c} = u.{c}" for c in TRUE_RS_COLUMNS)
            con.execute(
                f"""
                update indicators_daily i
                set {set_clause}
                from true_rs_upd u
                where i.symbol = u.symbol and i.trade_date = u.trade_date
                """
            )
            con.unregister("true_rs_upd")
            print(f"  updated {min(start+chunk, total):,}/{total:,}", flush=True)

        # Spot check
        sample = con.execute(
            f"""
            select symbol, trade_date, rs_percentile,
                   {', '.join(TRUE_RS_COLUMNS)}
            from indicators_daily
            where trade_date = (select max(trade_date) from indicators_daily)
              and symbol in ('RELIANCE', 'TCS', 'MAXHEALTH', 'DIXON')
            """
        ).fetchdf()
        print(sample.to_string(index=False))
        nn = con.execute(
            f"select count(*) from indicators_daily where trade_date=(select max(trade_date) from indicators_daily) and rs_vs_nifty50_63d is not null"
        ).fetchone()[0]
        print(f"Latest session non-null rs_vs_nifty50_63d: {nn}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", type=Path, default=DB_PATH)
    p.add_argument("--latest-only", action="store_true")
    args = p.parse_args()
    materialize(args.db, latest_only=args.latest_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
