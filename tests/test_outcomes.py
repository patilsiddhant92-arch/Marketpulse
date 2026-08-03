from datetime import date

import pandas as pd


def _prices():
    return pd.DataFrame(
        [
            {"symbol": "AAA", "trade_date": date(2026, 1, i), "close_price": close, "high_price": high, "low_price": low}
            for i, close, high, low in [(1, 100, 102, 98), (2, 103, 106, 99), (3, 105, 108, 102), (4, 104, 107, 101)]
        ]
    )


def test_future_session_outcome_uses_exact_horizon():
    from Scripts.outcomes import calculate_outcome

    signal = {"signal_id": "s1", "symbol": "AAA", "first_seen_date": date(2026, 1, 1), "trigger_price": 102, "invalidation_price": 98}
    result = calculate_outcome(_prices(), signal, horizons=(2,))

    assert result[0]["forward_return_pct"] == 5.0
    assert result[0]["max_favourable_excursion_pct"] == 8.0
    assert result[0]["max_adverse_excursion_pct"] == -1.0
    assert result[0]["resolved"] is True


def test_unresolved_forward_window_is_excluded():
    from Scripts.outcomes import calculate_outcome

    signal = {"signal_id": "s1", "symbol": "AAA", "first_seen_date": date(2026, 1, 3), "trigger_price": 105, "invalidation_price": 100}
    result = calculate_outcome(_prices(), signal, horizons=(5,))

    assert result[0]["resolved"] is False
    assert result[0]["forward_return_pct"] is None
