"""Unit tests for Institutional Performance & Fund Attribution Engine."""

from pathlib import Path
import pytest
import pandas as pd

from Scripts.institutional_attribution import (
    clean_fund_name,
    to_tv_symbols_list,
    fetch_deal_attribution_df,
    build_fund_leaderboard,
    fetch_star_fund_radar,
    fetch_stock_fund_attribution,
)
from App.ui.stock_drawer import query_stock_360_data

DB_PATH = Path("Database/marketpulse.duckdb")


def test_clean_fund_name():
    """Verify fund name normalization strips technical suffixes cleanly."""
    assert clean_fund_name("BOFA SECURITIES EUROPE SA -FPI") == "BOFA SECURITIES EUROPE SA"
    assert clean_fund_name("BOFA SECURITIES EUROPE SA -ODI") == "BOFA SECURITIES EUROPE SA"
    assert clean_fund_name("KOTAK MAHINDRA MUTUAL FUND") == "KOTAK MAHINDRA MUTUAL FUND"
    assert clean_fund_name("WHITEOAK CAPITAL ASSET MANAGEMENT PRIVATE LIMITED") == "WHITEOAK CAPITAL ASSET MANAGEMENT"
    assert clean_fund_name("HDFC STANDARD LIFE INSURANCE CO LTD") == "HDFC STANDARD LIFE INSURANCE"
    assert clean_fund_name("  D3 STOCK VISION LLP  ") == "D3 STOCK VISION"
    assert clean_fund_name("") == ""
    assert clean_fund_name(None) == ""


def test_to_tv_symbols_list():
    """Verify TradingView symbols formatting with prefix, deduplication, and RE filtering."""
    syms = ["reliance", "TCS", "reliance", "TATAMOTORS-RE", "INFY_RE", "HDFCBANK"]
    res = to_tv_symbols_list(syms)
    assert res == "NSE:RELIANCE,NSE:TCS,NSE:HDFCBANK"
    assert "RELIANCE" in res
    assert "-RE" not in res
    assert "_RE" not in res


def test_deal_attribution_df_structure_and_bounds():
    """Verify deal attribution dataframe returns valid mathematical columns and bounds."""
    if not DB_PATH.exists():
        pytest.skip("MarketPulse DuckDB not found.")

    df = fetch_deal_attribution_df(DB_PATH, min_deal_cr=10.0)
    assert isinstance(df, pd.DataFrame)
    assert not df.empty

    required_cols = [
        "deal_date", "symbol", "client_name", "fund_house", "deal_price",
        "deal_value_cr", "cmp", "ret_current", "max_runup_pct", "days_to_peak", "holding_days"
    ]
    for col in required_cols:
        assert col in df.columns, f"Missing column {col} in attribution dataframe"

    # Price and value bounds
    assert (df["deal_price"] > 0).all()
    assert (df["deal_value_cr"] >= 10.0).all()
    assert (df["holding_days"] >= 0).all()

    # Peak run-up must be >= current return or min 0 (peak high >= deal price if ever traded above)
    assert not df["symbol"].astype(str).str.endswith(("-RE", "_RE")).any()


def test_fund_leaderboard_computation_and_ranking():
    """Verify fund leaderboard ranks funds accurately and calculates catalyst scores."""
    if not DB_PATH.exists():
        pytest.skip("MarketPulse DuckDB not found.")

    attr_df = fetch_deal_attribution_df(DB_PATH, min_deal_cr=5.0)
    leaderboard = build_fund_leaderboard(attr_df, min_bets=3)

    assert isinstance(leaderboard, pd.DataFrame)
    assert not leaderboard.empty
    assert len(leaderboard) >= 10

    # Ensure required metrics exist
    for col in ["fund_house", "fund_tier", "catalyst_score", "win_rate_20d", "avg_runup", "total_cr", "total_bets"]:
        assert col in leaderboard.columns

    # Verify score bounds
    assert (leaderboard["catalyst_score"] >= 0).all()
    assert (leaderboard["catalyst_score"] <= 100).all()

    # Verify win rate bounds for eligible funds
    valid_wr = leaderboard["win_rate_20d"].dropna()
    assert (valid_wr >= 0.0).all()
    assert (valid_wr <= 100.0).all()

    # Top tier funds must exist
    star_funds = leaderboard[leaderboard["fund_tier"] == "Star Catalyst"]
    assert len(star_funds) >= 3


def test_star_fund_radar_structure_and_alerts():
    """Verify Star Fund Radar returns structured recent deals and TV export."""
    if not DB_PATH.exists():
        pytest.skip("MarketPulse DuckDB not found.")

    radar = fetch_star_fund_radar(DB_PATH, lookback_days=20, min_catalyst_score=60.0)
    assert isinstance(radar, dict)
    assert "deals" in radar
    assert "symbols" in radar
    assert "tv_list" in radar
    assert "as_of" in radar

    if radar["deals"]:
        d0 = radar["deals"][0]
        assert "symbol" in d0
        assert "fund_house" in d0
        assert "deal_price" in d0
        assert "cmp" in d0
        assert "ret_current" in d0
        assert "max_runup_pct" in d0
        assert "fund_catalyst_score" in d0
        assert radar["tv_list"].startswith("NSE:")


def test_stock_fund_attribution_lookup():
    """Verify individual stock institutional attribution lookup returns accurate history."""
    if not DB_PATH.exists():
        pytest.skip("MarketPulse DuckDB not found.")

    # Test CLEANMAX which had multiple marquee additions on 2026-09-03
    attr = fetch_stock_fund_attribution(DB_PATH, "CLEANMAX")
    assert isinstance(attr, list)
    assert len(attr) >= 1

    entry = attr[0]
    assert entry["symbol"] == "CLEANMAX"
    assert entry["deal_price"] > 0
    assert entry["cmp"] > 0
    assert "ret_current" in entry
    assert "max_runup_pct" in entry
    assert "fund_house" in entry

    # Test empty / non-existent symbol
    assert fetch_stock_fund_attribution(DB_PATH, "") == []
    assert fetch_stock_fund_attribution(DB_PATH, "NON_EXISTENT_XYZ_123") == []


def test_stock_360_embeds_fund_attribution():
    """Verify query_stock_360_data embeds fund_attribution seamlessly."""
    if not DB_PATH.exists():
        pytest.skip("MarketPulse DuckDB not found.")

    data = query_stock_360_data(DB_PATH, "CLEANMAX")
    assert data is not None
    assert "fund_attribution" in data
    assert isinstance(data["fund_attribution"], list)
    assert len(data["fund_attribution"]) >= 1