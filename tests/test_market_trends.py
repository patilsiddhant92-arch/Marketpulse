from datetime import date
from pathlib import Path
import duckdb
import pandas as pd
import pytest

from App.pages.market_trends import query_benchmark_trends

DB_PATH = Path("Database/marketpulse.duckdb")


@pytest.mark.skipif(not DB_PATH.exists(), reason="Database not built")
def test_query_benchmark_trends_real_db():
    df = query_benchmark_trends(DB_PATH, days=126)
    assert not df.empty, "Benchmark trends DataFrame must not be empty"
    assert "trade_date" in df.columns
    assert "index_name" in df.columns
    assert "close_price" in df.columns

    indices = set(df["index_name"].unique())
    expected = {"Nifty 50", "Nifty 500", "NIFTY MIDCAP 100", "NIFTY SMLCAP 100"}
    assert expected.issubset(indices), f"Expected all benchmark indices, got: {indices}"

    # Verify chronological ascending order
    dates = df["trade_date"].tolist()
    assert dates[-1] >= dates[0]

    # Verify pivot shape
    pivot = df.pivot(index="trade_date", columns="index_name", values="close_price").sort_index()
    assert len(pivot) > 100, f"Expected >100 trading sessions, got {len(pivot)}"


def test_query_benchmark_trends_synthetic_and_rebasing(tmp_path):
    db_file = tmp_path / "test_bench.duckdb"
    with duckdb.connect(str(db_file)) as con:
        con.execute(
            """
            CREATE TABLE index_daily (
                trade_date DATE,
                index_name VARCHAR,
                close_price DOUBLE,
                return_1d_pct DOUBLE,
                return_5d_pct DOUBLE,
                return_20d_pct DOUBLE,
                distance_ema_50_pct DOUBLE,
                distance_ema_200_pct DOUBLE,
                trend_state VARCHAR
            )
            """
        )
        # Create 5 dates for 4 indices, but NIFTY SMLCAP 100 is missing on the earliest date
        data = [
            ("2026-01-01", "Nifty 50", 1000.0, 0.0, 0.0, 0.0, 1.0, 2.0, "Uptrend"),
            ("2026-01-01", "Nifty 500", 500.0, 0.0, 0.0, 0.0, 1.0, 2.0, "Uptrend"),
            ("2026-01-01", "NIFTY MIDCAP 100", 200.0, 0.0, 0.0, 0.0, 1.0, 2.0, "Uptrend"),
            # Note: SMLCAP 100 not traded on 2026-01-01

            ("2026-01-02", "Nifty 50", 1010.0, 1.0, 1.0, 1.0, 1.1, 2.1, "Uptrend"),
            ("2026-01-02", "Nifty 500", 510.0, 2.0, 2.0, 2.0, 1.2, 2.2, "Uptrend"),
            ("2026-01-02", "NIFTY MIDCAP 100", 204.0, 2.0, 2.0, 2.0, 1.2, 2.2, "Uptrend"),
            ("2026-01-02", "NIFTY SMLCAP 100", 100.0, 0.0, 0.0, 0.0, 1.0, 2.0, "Uptrend"),

            ("2026-01-03", "Nifty 50", 1020.0, 1.0, 2.0, 2.0, 1.2, 2.2, "Uptrend"),
            ("2026-01-03", "Nifty 500", 520.0, 2.0, 4.0, 4.0, 1.4, 2.4, "Uptrend"),
            ("2026-01-03", "NIFTY MIDCAP 100", 210.0, 3.0, 5.0, 5.0, 1.5, 2.5, "Uptrend"),
            ("2026-01-03", "NIFTY SMLCAP 100", 105.0, 5.0, 5.0, 5.0, 1.5, 2.5, "Uptrend"),
        ]
        con.executemany("INSERT INTO index_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", data)

    res = query_benchmark_trends(db_file, days=3)
    assert not res.empty
    assert len(res["index_name"].unique()) == 4

    pivot = res.pivot(index="trade_date", columns="index_name", values="close_price").sort_index()
    # Test our per-column rebasing logic
    rebased_df = pd.DataFrame(index=pivot.index)
    for col in pivot.columns:
        s = pivot[col].dropna()
        if not s.empty and float(s.iloc[0]) != 0:
            rebased_df[col] = (pivot[col] / float(s.iloc[0])) * 100.0
        else:
            rebased_df[col] = pivot[col]

    # Verify Nifty 50 rebased from 1000 -> 100.0 on day 1, 102.0 on day 3
    assert rebased_df["Nifty 50"].iloc[0] == 100.0
    assert rebased_df["Nifty 50"].iloc[-1] == 102.0

    # Verify NIFTY SMLCAP 100 (which started on day 2 at 100) rebased to 100.0 on day 2 and 105.0 on day 3
    assert pd.isna(rebased_df["NIFTY SMLCAP 100"].iloc[0])
    assert rebased_df["NIFTY SMLCAP 100"].iloc[1] == 100.0
    assert rebased_df["NIFTY SMLCAP 100"].iloc[-1] == 105.0


def test_query_benchmark_trends_empty_db(tmp_path):
    empty_db = tmp_path / "empty.duckdb"
    res = query_benchmark_trends(empty_db, days=126)
    assert res.empty
