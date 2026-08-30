from __future__ import annotations

import numpy as np
import pandas as pd

from Scripts import indicators


def test_sma_matches_rolling_mean() -> None:
    close = pd.Series([10.0, 12.0, 11.0, 14.0, 13.0], name="close")
    actual = indicators.sma(close, 3)
    expected = close.rolling(3, min_periods=3).mean()
    pd.testing.assert_series_equal(actual, expected)


def test_ema_matches_standard_adjust_false_ewm() -> None:
    close = pd.Series([10.0, 12.0, 11.0, 14.0, 13.0], name="close")

    actual = indicators.ema(close, span=3)
    expected = close.ewm(span=3, adjust=False, min_periods=3).mean()

    pd.testing.assert_series_equal(actual, expected)


def test_rsi_wilder_matches_documented_rma_calculation() -> None:
    close = pd.Series([100.0, 102.0, 101.0, 103.0, 102.0, 104.0, 103.0], name="close")
    period = 3

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    expected = 100 - (100 / (1 + avg_gain / avg_loss.replace(0, np.nan)))

    actual = indicators.rsi_wilder(close, period=period)

    pd.testing.assert_series_equal(actual, expected)


def test_atr_sma_preserves_current_production_definition() -> None:
    high = pd.Series([11.0, 13.0, 14.0, 16.0, 17.0, 18.0])
    low = pd.Series([9.0, 10.0, 12.0, 13.0, 15.0, 16.0])
    close = pd.Series([10.0, 12.0, 13.0, 15.0, 16.0, 17.0])

    actual = indicators.atr_sma(high, low, close, period=5)

    # True range is [2, 3, 2, 3, 2, 2]; production waits for five rows
    # before exposing the 5-bar SMA.
    expected = pd.Series([np.nan, np.nan, np.nan, np.nan, 12 / 5, 12 / 5])
    pd.testing.assert_series_equal(actual, expected)


def test_atr_wilder_is_additive_and_does_not_alias_sma_atr() -> None:
    high = pd.Series([11.0, 13.0, 14.0, 16.0, 17.0, 18.0])
    low = pd.Series([9.0, 10.0, 12.0, 13.0, 15.0, 16.0])
    close = pd.Series([10.0, 12.0, 13.0, 15.0, 16.0, 17.0])

    actual = indicators.atr_wilder(high, low, close, period=3)
    expected = indicators.true_range(high, low, close).ewm(
        alpha=1 / 3, adjust=False, min_periods=3
    ).mean()

    pd.testing.assert_series_equal(actual, expected)
    assert not actual.equals(indicators.atr_sma(high, low, close, period=5))


def test_distance_below_high_clips_new_highs_to_zero() -> None:
    close = pd.Series([95.0, 105.0, 98.0])
    high = pd.Series([100.0, 100.0, 100.0])

    actual = indicators.distance_below_high(close, high)

    expected = pd.Series([5.0, 0.0, 2.0])
    pd.testing.assert_series_equal(actual, expected)


def test_setup_class_is_mutually_exclusive_and_breakout_wins() -> None:
    frame = pd.DataFrame(
        [
            {"new_20d_high": True, "rvol": 1.8, "close_location_pct": 80, "distance_below_52w": 0, "range_5d_pct": 5, "range_10d_pct": 8, "atr_pct_avg_5d": 2, "atr_pct_avg_20d": 3, "avg_volume_5d": 80, "avg_volume_20d": 100},
            {"new_20d_high": False, "rvol": 1.0, "close_location_pct": 50, "distance_below_52w": 4, "range_5d_pct": 8, "range_10d_pct": 8, "atr_pct_avg_5d": 3, "atr_pct_avg_20d": 3, "avg_volume_5d": 100, "avg_volume_20d": 100},
            {"new_20d_high": False, "rvol": 1.0, "close_location_pct": 50, "distance_below_52w": 12, "range_5d_pct": 5, "range_10d_pct": 8, "atr_pct_avg_5d": 2, "atr_pct_avg_20d": 3, "avg_volume_5d": 80, "avg_volume_20d": 100},
            {"new_20d_high": False, "rvol": 1.0, "close_location_pct": 50, "distance_below_52w": 40, "range_5d_pct": 10, "range_10d_pct": 8, "atr_pct_avg_5d": 4, "atr_pct_avg_20d": 3, "avg_volume_5d": 120, "avg_volume_20d": 100},
        ]
    )

    actual = indicators.setup_class(frame).tolist()

    assert actual == ["BREAKOUT", "PIVOT", "BASE", "NONE"]
