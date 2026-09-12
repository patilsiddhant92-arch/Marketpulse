"""Backfill historical NSE index data into index_daily for RS and vs-Nifty calculations.

Fetches 2+ years of historical EOD bars from Yahoo Finance for:
- Nifty 50 (^NSEI) — primary benchmark for relative strength and vs-Nifty
- Nifty 500 (^CRSLDX) — broad market index
- Key sectoral indices (Bank, IT, Auto, FMCG, Metal, Pharma, Realty, Energy, Infra, PSU Bank, Media, MNC, PSE, Services)

Merges with existing official NSE Market Activity (MA) files, computes all derived features
(return_63d, return_126d, return_252d, 20/50/200 EMAs, trend state), and re-materializes
benchmark relative strength columns in sector metrics and sector rotation.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

import duckdb
import numpy as np
import pandas as pd
import yfinance as yf

# Resolve Root
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS = ROOT / "Scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from config import DB_PATH
from index_history import INDEX_COLUMNS, build_index_features
from sector_metrics import compute_sector_metrics, _benchmark_returns

INDEX_TICKER_MAP = {
    "^NSEI": "Nifty 50",
    "^CRSLDX": "Nifty 500",
    "^NSEBANK": "Nifty Bank",
    "^CNXIT": "Nifty IT",
    "^CNXAUTO": "Nifty Auto",
    "^CNXFMCG": "Nifty FMCG",
    "^CNXMETAL": "Nifty Metal",
    "^CNXPHARMA": "Nifty Pharma",
    "^CNXREALTY": "Nifty Realty",
    "^CNXENERGY": "Nifty Energy",
    "^CNXINFRA": "Nifty Infra",
    "^CNXPSUBANK": "Nifty PSU Bank",
    "^CNXMEDIA": "Nifty Media",
    "^CNXMNC": "Nifty MNC",
    "^CNXPSE": "Nifty PSE",
    "^CNXSERVICE": "Nifty Serv Sector",
}


def fetch_historical_indices(start_date: str = "2024-05-01") -> pd.DataFrame:
    """Download historical index bars from Yahoo Finance and format to INDEX_COLUMNS."""
    tickers = list(INDEX_TICKER_MAP.keys())
    print(f"Downloading historical index data for {len(tickers)} indices starting from {start_date}...")
    
    try:
        raw_df = yf.download(tickers, start=start_date, group_by="ticker", progress=False)
    except Exception as exc:
        print(f"Error downloading from yfinance: {exc}")
        return pd.DataFrame(columns=INDEX_COLUMNS)

    rows = []
    for ticker, index_name in INDEX_TICKER_MAP.items():
        if ticker not in raw_df:
            continue
        sub = raw_df[ticker].dropna(subset=["Close"]).copy()
        if sub.empty:
            continue

        sub = sub.sort_index()
        sub["trade_date"] = pd.to_datetime(sub.index).tz_localize(None).normalize()
        sub["close_price"] = sub["Close"].astype(float)
        sub["open_price"] = sub["Open"].astype(float)
        sub["high_price"] = sub["High"].astype(float)
        sub["low_price"] = sub["Low"].astype(float)
        sub["previous_close"] = sub["close_price"].shift(1)
        sub["change_value"] = sub["close_price"] - sub["previous_close"]
        sub["return_1d_pct"] = (sub["close_price"] / sub["previous_close"] - 1.0) * 100.0
        sub["index_name"] = index_name

        # Drop first row where previous_close is NaN
        valid = sub.dropna(subset=["previous_close"]).copy()
        for _, r in valid.iterrows():
            rows.append({
                "trade_date": r["trade_date"],
                "index_name": index_name,
                "previous_close": float(r["previous_close"]),
                "open_price": float(r["open_price"]),
                "high_price": float(r["high_price"]),
                "low_price": float(r["low_price"]),
                "close_price": float(r["close_price"]),
                "change_value": float(r["change_value"]),
                "return_1d_pct": float(r["return_1d_pct"]),
            })

    result = pd.DataFrame(rows, columns=INDEX_COLUMNS)
    print(f"Downloaded {len(result):,} raw index rows across {result['index_name'].nunique()} indices.")
    return result


def backfill_and_update_db(db_path: Path = DB_PATH) -> dict[str, Any]:
    """Merge historical index data, recalculate features, and update sector metrics."""
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    with duckdb.connect(str(db_path)) as con:
        # Check date range of prices_daily
        min_date_row = con.execute("SELECT min(trade_date) FROM prices_daily").fetchone()
        min_date_str = str(min_date_row[0])[:10] if min_date_row and min_date_row[0] else "2024-05-01"

        # Load existing index_daily (from official NSE MA files)
        has_index_table = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'index_daily'").fetchone()[0]
        existing_df = con.execute("SELECT * FROM index_daily").fetchdf() if has_index_table else pd.DataFrame()

    # Download historical indices
    yf_df = fetch_historical_indices(start_date=min_date_str)
    if yf_df.empty and existing_df.empty:
        return {"ok": False, "error": "No index data available"}

    # Merge: keep official existing data where available, fill prior history with yfinance
    if not existing_df.empty:
        existing_basic = existing_df[[c for c in INDEX_COLUMNS if c in existing_df.columns]].copy()
        existing_basic["trade_date"] = pd.to_datetime(existing_basic["trade_date"]).dt.normalize()
        yf_df["trade_date"] = pd.to_datetime(yf_df["trade_date"]).dt.normalize()
        
        # Concat with existing taking precedence
        combined = pd.concat([yf_df, existing_basic], ignore_index=True)
        combined = combined.drop_duplicates(subset=["trade_date", "index_name"], keep="last")
    else:
        combined = yf_df

    combined = combined.sort_values(["index_name", "trade_date"]).reset_index(drop=True)
    print(f"Combined total index rows before feature calculation: {len(combined):,}")

    # Compute full rolling index features (63d, 126d, 252d returns, 20/50/200 EMAs)
    print("Computing rolling index features (returns, EMAs, trend states)...")
    index_features = build_index_features(combined)

    # Save back to DuckDB
    print(f"Writing updated index_daily ({len(index_features):,} rows) to DuckDB...")
    with duckdb.connect(str(db_path)) as con:
        con.register("index_features_df", index_features)
        con.execute("DROP TABLE IF EXISTS index_daily")
        con.execute("CREATE TABLE index_daily AS SELECT * FROM index_features_df")
        con.execute("CREATE INDEX IF NOT EXISTS idx_index_daily_date_name ON index_daily(trade_date, index_name)")

        # Verify new count of sessions
        session_cnt = con.execute("SELECT count(DISTINCT trade_date) FROM index_daily").fetchone()[0]
        print(f"index_daily now covers {session_cnt} distinct trading sessions!")

        # Update sector_rotation with benchmark returns
        has_sr = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'sector_rotation'").fetchone()[0]
        has_ind = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'indicators_daily'").fetchone()[0]
        has_mst = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'stocks_master'").fetchone()[0]

        if has_sr and has_ind and has_mst:
            print("Recomputing cap-weighted sector metrics & vs-Nifty relative strength...")
            indicators = con.execute("SELECT * FROM indicators_daily").fetchdf()
            master = con.execute("SELECT * FROM stocks_master").fetchdf()
            deals = con.execute("SELECT * FROM deals").fetchdf() if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'deals'").fetchone()[0] else None
            reference = con.execute("SELECT * FROM security_reference_daily").fetchdf() if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'security_reference_daily'").fetchone()[0] else None

            sector_metrics = compute_sector_metrics(
                indicators=indicators,
                master=master,
                reference=reference,
                index_daily=index_features,
                deals=deals,
            )

            if not sector_metrics.empty:
                con.register("sector_metrics_df", sector_metrics)
                con.execute("DROP TABLE IF EXISTS sector_metrics_daily")
                con.execute("CREATE TABLE sector_metrics_daily AS SELECT * FROM sector_metrics_df")
                con.execute("CREATE INDEX IF NOT EXISTS idx_sector_metrics_level_group_date ON sector_metrics_daily(level, group_name, trade_date)")

                # Also update sector_rotation with rs_vs_nifty_21d and rs_vs_nifty_63d
                con.execute("""
                    ALTER TABLE sector_rotation ADD COLUMN IF NOT EXISTS rs_vs_nifty_21d DOUBLE;
                    ALTER TABLE sector_rotation ADD COLUMN IF NOT EXISTS rs_vs_nifty_63d DOUBLE;
                """)
                con.execute("""
                    UPDATE sector_rotation sr
                    SET rs_vs_nifty_21d = sm.rs_vs_nifty_21d,
                        rs_vs_nifty_63d = sm.rs_vs_nifty_63d
                    FROM sector_metrics_daily sm
                    WHERE sr.trade_date = sm.trade_date 
                      AND sr.level = sm.level 
                      AND sr.group_name = sm.group_name;
                """)
                print("Successfully updated sector_rotation and sector_metrics_daily with vs-Nifty columns!")

    return {
        "ok": True,
        "session_count": session_cnt,
        "rows": len(index_features),
    }


if __name__ == "__main__":
    res = backfill_and_update_db()
    print("Backfill result:", res)
