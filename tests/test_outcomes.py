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


def _split_prices():
    """AAA seen on Jan 1-2 around 100 raw; a 1:2 split goes ex on Jan 5 (raw ~52 afterwards).
    Adjusted history: every pre-split price is halved and carries price_factor 0.5; rows from
    the ex-date carry 1.0. Another symbol is interleaved so index labels are not contiguous."""
    rows = [
        (1, 100, 102, 98, 0.5), (2, 101, 103, 99, 0.5), (3, 102, 104, 100, 0.5), (4, 105, 106, 104, 0.5),
        (5, 52, 53, 51, 1.0), (6, 53, 54, 52, 1.0),
    ]
    out = []
    for d, c, h, lo, f in rows:
        out.append({"symbol": "AAA", "trade_date": date(2026, 1, d), "close_price": c * f,
                    "high_price": h * f, "low_price": lo * f, "price_factor": f})
        out.append({"symbol": "BBB", "trade_date": date(2026, 1, d), "close_price": 10.0,
                    "high_price": 10.0, "low_price": 10.0, "price_factor": 1.0})
    return pd.DataFrame(out)


def test_split_after_last_seen_date_does_not_fire_false_failure():
    """Ledger prices are on the last_seen_date scale (raw ~100); adjusted pre-split rows are
    halved (~50). Without rescaling, every adjusted low is below the raw invalidation 95 and
    time_to_failure fires on session 1."""
    from Scripts.outcomes import calculate_outcome

    signal = {"signal_id": "s1", "symbol": "AAA", "first_seen_date": date(2026, 1, 1),
              "last_seen_date": date(2026, 1, 2), "trigger_price": 102, "invalidation_price": 95}
    result = calculate_outcome(_split_prices(), signal, horizons=(4,))[0]

    assert result["resolved"] is True
    assert result["time_to_failure_sessions"] is None
    assert result["trigger_to_invalidation_return_pct"] == round((95 / 102 - 1) * 100, 6)


def test_real_failure_is_still_detected_on_the_adjusted_scale():
    from Scripts.outcomes import calculate_outcome

    # scaled invalidation 50.0; adjusted lows Jan 2..5 = 49.5, 50, 50.5, 51 -> fails on session 1
    signal = {"signal_id": "s1", "symbol": "AAA", "first_seen_date": date(2026, 1, 1),
              "last_seen_date": date(2026, 1, 2), "trigger_price": 102, "invalidation_price": 100}
    result = calculate_outcome(_split_prices(), signal, horizons=(4,))[0]

    assert result["time_to_failure_sessions"] == 1


def test_failure_session_count_is_positional():
    """time_to_failure counts sessions inside the window, not index-label distance (BBB rows are
    interleaved, so AAA's index labels step by 2)."""
    from Scripts.outcomes import calculate_outcome

    # last_seen Jan 3 (factor 0.5): scaled invalidation 51.5; lows Jan 4..6 = 52, 51, 52 -> session 2
    signal = {"signal_id": "s1", "symbol": "AAA", "first_seen_date": date(2026, 1, 3),
              "last_seen_date": date(2026, 1, 3), "trigger_price": 106, "invalidation_price": 103}
    result = calculate_outcome(_split_prices(), signal, horizons=(3,))[0]

    assert result["time_to_failure_sessions"] == 2


def test_ledger_scale_defaults_to_one_without_price_factor():
    from Scripts.outcomes import calculate_outcome

    # no price_factor column: invalidation used as-is; lows Jan 3, 4 = 102, 101 -> session 2
    signal = {"signal_id": "s1", "symbol": "AAA", "first_seen_date": date(2026, 1, 2),
              "last_seen_date": date(2026, 1, 2), "trigger_price": 104, "invalidation_price": 101}
    result = calculate_outcome(_prices(), signal, horizons=(2,))[0]

    assert result["time_to_failure_sessions"] == 2
