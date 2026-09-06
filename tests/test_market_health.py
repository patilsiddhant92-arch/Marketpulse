"""Test Market Health Regime Strip and Summary Query."""

from pathlib import Path
import pytest
from App.ui.market_health import query_market_health_summary

DB_PATH = Path("Database/marketpulse.duckdb")


@pytest.mark.skipif(not DB_PATH.exists(), reason="Database not built")
def test_query_market_health_summary_returns_7_cards():
    data = query_market_health_summary(DB_PATH)
    assert data, "Market health data must not be empty"
    assert data["as_of"] is not None
    assert data["total_stocks"] > 0
    assert "cards" in data
    assert len(data["cards"]) == 7, "Must contain exactly 7 regime cards"
    
    card_keys = [c["key"] for c in data["cards"]]
    expected = ["ad_net", "above_20", "above_200", "rsi_60", "pivot", "near_52w", "breakout"]
    for k in expected:
        assert k in card_keys, f"Card {k} must be present"
