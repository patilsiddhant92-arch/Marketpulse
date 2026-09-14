"""Materialize true RS columns onto indicators_daily from current index_daily."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
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
        index_daily = con.execute("select * from index_daily").fetchdf()
        if latest_only:
            mx = con.execute("select max(trade_date) from indicators_daily").fetchone()[0]
            indicators = con.execute(
                "select * from indicators_daily where trade_date = ?", [mx]
            ).fetchdf()
        else:
            # pull only columns needed + pk for merge
            cols = con.execute("describe indicators_daily").fetchdf()["column_name"].tolist()
            need = ["symbol", "trade_date", "close_price"]
            extra = [c for c in TRUE_RS_COLUMNS if c in cols]
            indicators = con.execute(
                f"select {', '.join(need + extra)} from indicators_daily"
            ).fetchdf()

        updated = attach_true_rs_columns(indicators, index_daily)
        # ensure columns exist
        for col in TRUE_RS_COLUMNS:
            con.execute(f"alter table indicators_daily add column if not exists {col} double")

        # Update via temp table join
        slim = updated[["symbol", "trade_date", *TRUE_RS_COLUMNS]].copy()
        slim["trade_date"] = pd.to_datetime(slim["trade_date"]).dt.date
        con.register("true_rs_upd", slim)
        set_clause = ", ".join(f"{c} = u.{c}" for c in TRUE_RS_COLUMNS)
        con.execute(
            f"""
            update indicators_daily i
            set {set_clause}
            from true_rs_upd u
            where i.symbol = u.symbol and i.trade_date = u.trade_date
            """
        )
        print(f"Updated true RS on indicators_daily ({len(slim):,} rows touched).")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", type=Path, default=DB_PATH)
    p.add_argument("--latest-only", action="store_true")
    args = p.parse_args()
    materialize(args.db, latest_only=args.latest_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
