"""Unit tests for SMA Template Stacks in Momentum scanner."""
from pathlib import Path
import duckdb
import pytest

DB_PATH = Path("Database/marketpulse.duckdb")


def test_sma_template_columns_present_and_populated():
    if not DB_PATH.exists():
        pytest.skip("Production database not present")

    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        # Check column names
        cols = {r[1] for r in con.execute("PRAGMA table_info(indicators_daily)").fetchall()}
        assert "sma_50" in cols
        assert "sma_150" in cols
        assert "sma_200" in cols
        assert "sma_200_rising" in cols

        # Check non-null values on latest date
        latest_d = con.execute("SELECT max(trade_date) FROM indicators_daily").fetchone()[0]
        res = con.execute("""
            SELECT count(*), count(sma_50), count(sma_150), count(sma_200), count(sma_200_rising)
            FROM indicators_daily
            WHERE trade_date = ?
        """, [latest_d]).fetchone()
        tot, s50, s150, s200, s200r = res
        assert tot > 1000
        assert s50 > 1000
        assert s150 > 1000
        assert s200 > 1000
        assert s200r > 1000


def test_sma_stack_filter_execution():
    if not DB_PATH.exists():
        pytest.skip("Production database not present")

    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        latest_d = con.execute("SELECT max(trade_date) FROM indicators_daily").fetchone()[0]

        # Test 50 > 150 SMA
        df_50_150 = con.execute("""
            SELECT symbol, close_price, sma_50, sma_150
            FROM indicators_daily
            WHERE trade_date = ?
              AND sma_50 IS NOT NULL AND sma_150 IS NOT NULL AND sma_50 > sma_150
            LIMIT 10
        """, [latest_d]).fetchdf()
        assert not df_50_150.empty
        assert (df_50_150["sma_50"] > df_50_150["sma_150"]).all()

        # Test 150 > 200 SMA
        df_150_200 = con.execute("""
            SELECT symbol, close_price, sma_150, sma_200
            FROM indicators_daily
            WHERE trade_date = ?
              AND sma_150 IS NOT NULL AND sma_200 IS NOT NULL AND sma_150 > sma_200
            LIMIT 10
        """, [latest_d]).fetchdf()
        assert not df_150_200.empty
        assert (df_150_200["sma_150"] > df_150_200["sma_200"]).all()

        # Test full Minervini/SMA template alignment
        df_full = con.execute("""
            SELECT symbol, close_price, sma_50, sma_150, sma_200, sma_200_rising
            FROM indicators_daily
            WHERE trade_date = ?
              AND close_price > sma_50
              AND close_price > sma_150
              AND close_price > sma_200
              AND sma_50 > sma_150
              AND sma_150 > sma_200
              AND sma_200_rising IS TRUE
            LIMIT 10
        """, [latest_d]).fetchdf()
        assert not df_full.empty
        assert (df_full["close_price"] > df_full["sma_50"]).all()
        assert (df_full["sma_50"] > df_full["sma_150"]).all()
        assert (df_full["sma_150"] > df_full["sma_200"]).all()
        assert df_full["sma_200_rising"].all()
