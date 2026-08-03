from datetime import date

import pandas as pd


def test_split_adjustment_removes_false_return_spike():
    from Scripts.corporate_actions import apply_adjustment_factors, build_adjustment_factors

    prices = pd.DataFrame(
        [
            {"symbol": "AAA", "trade_date": date(2026, 1, 1), "open_price": 100, "high_price": 102, "low_price": 98, "close_price": 100, "volume": 1000},
            {"symbol": "AAA", "trade_date": date(2026, 1, 2), "open_price": 50, "high_price": 52, "low_price": 49, "close_price": 50, "volume": 2000},
        ]
    )
    actions = pd.DataFrame([{"symbol": "AAA", "ex_date": date(2026, 1, 2), "action_type": "split", "ratio_from": 1, "ratio_to": 2}])
    factors = build_adjustment_factors(actions, prices)
    adjusted = apply_adjustment_factors(prices, factors)

    assert adjusted.loc[0, "close_price_adjusted"] == 50
    assert adjusted.loc[1, "close_price_adjusted"] == 50
    assert adjusted.loc[0, "volume_adjusted"] == 2000
