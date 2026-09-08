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


def test_session_lag_is_grouped_session_shift_not_calendar_days() -> None:
    values = pd.Series([10.0, 20.0, 30.0, 40.0, 1.0, 2.0, 3.0])
    group = pd.Series(["AAA", "AAA", "AAA", "AAA", "BBB", "BBB", "BBB"])

    actual = indicators.session_lag(values, group, 2)

    expected = pd.Series([np.nan, np.nan, 10.0, 20.0, np.nan, np.nan, 1.0])
    pd.testing.assert_series_equal(actual, expected)


def _indicator_price_frame(
    symbol: str,
    n: int,
    *,
    start_price: float,
    drift: float,
    start: str = "2024-01-02",
) -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=n)
    close = start_price + np.arange(n) * drift
    return pd.DataFrame(
        {
            "symbol": symbol,
            "trade_date": dates,
            "open_price": close,
            "high_price": close + 1.0,
            "low_price": close - 1.0,
            "close_price": close,
            "volume": 1_000.0,
            "turnover_cr": 1.0,
            "delivery_qty": 500.0,
            "delivery_pct": 50.0,
            "prev_close": np.concatenate([[np.nan], close[:-1]]),
        }
    )


def test_calc_indicators_persists_adr_and_rs_side_columns() -> None:
    from Scripts.build_database import calc_indicators
    from Scripts.indicators import adr_pct

    mature_a = _indicator_price_frame("AAA", 320, start_price=100.0, drift=0.30)
    mature_b = _indicator_price_frame("BBB", 320, start_price=100.0, drift=0.10)
    prices = pd.concat([mature_a, mature_b], ignore_index=True)
    enrichment = pd.DataFrame(
        {"symbol": ["AAA", "BBB"], "high_52w": [200.0, 200.0], "low_52w": [50.0, 50.0]}
    )

    result = calc_indicators(prices, enrichment)
    aaa = result[result["symbol"] == "AAA"].sort_values("trade_date")

    for column in (
        "adr_20_pct",
        "rs_score_adaptive",
        "rs_percentile_ipo",
        "rs_rank_t5",
        "rs_rank_t15",
        "rs_rank_t30",
    ):
        assert column in result.columns
    assert "wema_20" in result.columns
    assert "rs_rank_t0" not in result.columns

    expected_adr = adr_pct(aaa["high_price"], aaa["low_price"], window=20)
    pd.testing.assert_series_equal(
        aaa["adr_20_pct"].reset_index(drop=True),
        expected_adr.reset_index(drop=True),
        check_names=False,
    )
    rs = aaa["rs_percentile"].reset_index(drop=True)
    pd.testing.assert_series_equal(
        aaa["rs_rank_t5"].reset_index(drop=True),
        rs.shift(5),
        check_names=False,
    )
    pd.testing.assert_series_equal(
        aaa["rs_rank_t15"].reset_index(drop=True),
        rs.shift(15),
        check_names=False,
    )
    pd.testing.assert_series_equal(
        aaa["rs_rank_t30"].reset_index(drop=True),
        rs.shift(30),
        check_names=False,
    )
    first_rs = int(rs.first_valid_index())
    assert pd.notna(aaa["rs_rank_t5"].iloc[first_rs + 5])
    assert pd.isna(aaa["rs_rank_t5"].iloc[first_rs + 4])


def test_adaptive_mixer_never_writes_rs_percentile_and_mature_ranks_ignore_ipos() -> None:
    from Scripts.build_database import calc_indicators

    mature_a = _indicator_price_frame("AAA", 320, start_price=100.0, drift=0.30)
    mature_b = _indicator_price_frame("BBB", 320, start_price=100.0, drift=0.10)
    mature_c = _indicator_price_frame("CCC", 320, start_price=100.0, drift=-0.05)
    last_date = mature_a["trade_date"].iloc[-1]
    ipo_start = (last_date - pd.tseries.offsets.BDay(39)).strftime("%Y-%m-%d")
    ipo = _indicator_price_frame("IPO1", 40, start_price=50.0, drift=2.0, start=ipo_start)

    enrichment = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC", "IPO1"],
            "high_52w": [200.0, 200.0, 200.0, 200.0],
            "low_52w": [50.0, 50.0, 50.0, 50.0],
        }
    )
    with_ipo = calc_indicators(pd.concat([mature_a, mature_b, mature_c, ipo], ignore_index=True), enrichment)
    without_ipo = calc_indicators(pd.concat([mature_a, mature_b, mature_c], ignore_index=True), enrichment)

    as_of = with_ipo["trade_date"].max()
    latest_with = with_ipo[with_ipo["trade_date"] == as_of].set_index("symbol")
    latest_without = without_ipo[without_ipo["trade_date"] == as_of].set_index("symbol")

    ipo_row = latest_with.loc["IPO1"]
    assert pd.isna(ipo_row["rs_percentile"])
    assert pd.isna(ipo_row["rs_percentile_primary"])
    assert pd.notna(ipo_row["rs_score_adaptive"])
    assert pd.notna(ipo_row["rs_percentile_ipo"])

    for symbol in ("AAA", "BBB", "CCC"):
        pd.testing.assert_series_equal(
            with_ipo.loc[with_ipo["symbol"] == symbol, "rs_percentile"].reset_index(drop=True),
            without_ipo.loc[without_ipo["symbol"] == symbol, "rs_percentile"].reset_index(drop=True),
            check_names=False,
        )
        assert pd.notna(latest_with.loc[symbol, "rs_percentile"])
        assert pd.notna(latest_with.loc[symbol, "rs_score_adaptive"])
        assert latest_with.loc[symbol, "rs_percentile"] == latest_without.loc[symbol, "rs_percentile"]
