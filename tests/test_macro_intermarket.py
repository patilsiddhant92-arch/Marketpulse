"""Unit tests for Macro Intermarket Transmission in Market Commentary."""
from pathlib import Path
import pytest
from App.market_commentary_engine import generate_market_commentary

DB_PATH = Path("Database/marketpulse.duckdb")


def test_generate_market_commentary_intermarket_fields():
    if not DB_PATH.exists():
        pytest.skip("Production database not present")

    comm = generate_market_commentary(DB_PATH)
    assert comm["ok"] is True
    assert "kpis" in comm
    kpis = comm["kpis"]

    # Verify Intermarket KPI keys
    assert "vix" in kpis
    assert "vix_1d" in kpis
    assert "vix_state" in kpis
    assert "gs10yr_cmp" in kpis
    assert "gs10yr_1d" in kpis
    assert "gs10yr_state" in kpis
    assert "usd_drift_5d" in kpis
    assert "oil_5d" in kpis
    assert "crude_spread" in kpis


def test_generate_market_commentary_intermarket_narrative():
    if not DB_PATH.exists():
        pytest.skip("Production database not present")

    comm = generate_market_commentary(DB_PATH)
    macro_text = comm["macro_commentary"]

    # Verify that Crude Oil, Currency, Bond Market, and VIX are covered
    assert "Intermarket Transmission" in macro_text
    assert "Crude Oil" in macro_text
    assert "Currency" in macro_text or "USD/INR" in macro_text
    assert "Sovereign Bond Market" in macro_text or "GS 10Yr" in macro_text
    assert "India VIX" in macro_text or "Volatility Regime" in macro_text

    # Verify upstream and downstream sensitivity references
    assert any(sym in macro_text for sym in ["OIL", "ONGC"])
    assert any(sym in macro_text for sym in ["ASIANPAINT", "BERGEPAINT", "INDIGO", "MRF", "Paints"])
