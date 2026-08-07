"""
Refresh high_52w / low_52w / away_52w_* on existing indicators_daily using
point-in-time NSE snapshots (as-of) + 252d fallback. No full rebuild.

Does not change Momentum UI. Safe to re-run.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import duckdb
import pandas as pd

from config import DB_PATH, ROOT_DIR
from reference_history import asof_reference, load_reference_history


def main() -> int:
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        return 1

    print("Loading dated 52W / mcap / PE / band snapshots (downloads + archive + daily)...")
    ref = load_reference_history(ROOT_DIR)
    if ref.empty:
        print("No reference history files found under Input/downloads|archive|daily.")
        return 1
    n_dates = ref["effective_date"].nunique()
    n_52 = ref["high_52w"].notna().sum()
    print(f"  reference rows: {len(ref):,} | distinct dates: {n_dates} | 52W values: {n_52:,}")

    print("Loading indicator keys from database...")
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        keys = con.execute(
            """
            SELECT symbol, trade_date, close_price,
                   high_252d, low_252d
            FROM indicators_daily
            ORDER BY symbol, trade_date
            """
        ).fetchdf()

    keys["trade_date"] = pd.to_datetime(keys["trade_date"])
    print(f"  indicator rows: {len(keys):,}")

    print("As-of joining official 52W (never future)...")
    joined = asof_reference(ref, keys[["symbol", "trade_date"]])
    high = pd.to_numeric(joined.get("high_52w"), errors="coerce")
    low = pd.to_numeric(joined.get("low_52w"), errors="coerce")
    # 252d fallback where NSE snapshot missing
    high = high.fillna(pd.to_numeric(keys["high_252d"], errors="coerce"))
    low = low.fillna(pd.to_numeric(keys["low_252d"], errors="coerce"))
    close = pd.to_numeric(keys["close_price"], errors="coerce")
    away_high = (close / high - 1.0) * 100.0
    away_low = (close / low - 1.0) * 100.0

    out = pd.DataFrame(
        {
            "symbol": keys["symbol"].astype(str).str.upper(),
            "trade_date": keys["trade_date"],
            "high_52w": high.to_numpy(),
            "low_52w": low.to_numpy(),
            "away_52w_high_pct": away_high.to_numpy(),
            "away_52w_low_pct": away_low.to_numpy(),
        }
    )

    # Sanity: latest day should still be near official snapshot
    latest = out["trade_date"].max()
    sample = out[out["trade_date"] == latest].dropna(subset=["high_52w"]).head(3)
    print(f"  sample latest {latest.date()}:")
    print(sample[["symbol", "high_52w", "away_52w_high_pct"]].to_string(index=False))

    # Distinct highs over history for a liquid name
    rel = out[out["symbol"] == "RELIANCE"]
    if not rel.empty:
        print(
            f"  RELIANCE distinct high_52w values across history: "
            f"{rel['high_52w'].round(2).nunique()} (was 1 when painted latest-only)"
        )

    backup = DB_PATH.with_suffix(".pre52w.backup.duckdb")
    print(f"Backup → {backup.name}")
    shutil.copy2(DB_PATH, backup)

    print("Writing updates into DuckDB...")
    with duckdb.connect(str(DB_PATH)) as con:
        con.register("ref_52w_upd", out)
        # Ensure columns exist
        cols = {r[1] for r in con.execute("PRAGMA table_info(indicators_daily)").fetchall()}
        for col, typ in [
            ("high_52w", "DOUBLE"),
            ("low_52w", "DOUBLE"),
            ("away_52w_high_pct", "DOUBLE"),
            ("away_52w_low_pct", "DOUBLE"),
        ]:
            if col not in cols:
                con.execute(f"ALTER TABLE indicators_daily ADD COLUMN {col} {typ}")
        con.execute(
            """
            UPDATE indicators_daily AS i
            SET high_52w = u.high_52w,
                low_52w = u.low_52w,
                away_52w_high_pct = u.away_52w_high_pct,
                away_52w_low_pct = u.away_52w_low_pct
            FROM ref_52w_upd AS u
            WHERE i.symbol = u.symbol AND i.trade_date = u.trade_date
            """
        )
        # Optional: persist reference history table for audit
        con.execute("DROP TABLE IF EXISTS security_reference_history")
        con.register("ref_hist", ref)
        con.execute("CREATE TABLE security_reference_history AS SELECT * FROM ref_hist")

    print("Done. 52W is now point-in-time (as-of) where files exist; 252d fallback otherwise.")
    print(f"Backup: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
