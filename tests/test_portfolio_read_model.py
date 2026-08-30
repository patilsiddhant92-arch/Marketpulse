from __future__ import annotations

import pandas as pd


def test_portfolio_summary_reports_heat_concentration_and_missing_stops():
    from App.portfolio_read_model import portfolio_summary

    positions = pd.DataFrame(
        [
            {"symbol": "AAA", "market_value_inr": 60_000, "initial_risk_inr": 1_500, "current_open_risk_inr": 1_200, "sector": "Tech", "stop_price": 90},
            {"symbol": "BBB", "market_value_inr": 30_000, "initial_risk_inr": 1_000, "current_open_risk_inr": 900, "sector": "Tech", "stop_price": 0},
            {"symbol": "CCC", "market_value_inr": 10_000, "initial_risk_inr": 500, "current_open_risk_inr": 500, "sector": "Bank", "stop_price": 95},
        ]
    )

    result = portfolio_summary(positions, account_equity=100_000, max_risk_pct=2.0)

    assert result["market_value_inr"] == 100_000
    assert result["initial_risk_inr"] == 3_000
    assert result["current_open_risk_inr"] == 2_600
    assert result["current_heat_pct"] == 2.6
    assert result["largest_sector"] == "Tech"
    assert result["largest_sector_weight_pct"] == 90.0
    assert result["missing_stop_count"] == 1
    assert result["over_budget"] is True


def test_position_size_uses_risk_budget_and_never_returns_negative():
    from App.portfolio_read_model import suggested_quantity

    assert suggested_quantity(entry_price=100, stop_price=90, account_equity=100_000, max_risk_pct=1.0) == 100
    assert suggested_quantity(entry_price=100, stop_price=100, account_equity=100_000, max_risk_pct=1.0) == 0
    assert suggested_quantity(entry_price=100, stop_price=110, account_equity=100_000, max_risk_pct=1.0) == 0
