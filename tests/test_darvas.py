"""Unit tests for Darvas Box indicator and 10 EMA squeeze logic."""
import numpy as np
import pytest
from App.indicators.darvas import calculate_darvas_box, compute_darvas_metrics, is_darvas_10ema_squeeze


def test_darvas_box_minimum_bars():
    highs = np.array([10, 11, 12])
    lows = np.array([9, 10, 11])
    top, bot = calculate_darvas_box(highs, lows, boxp=5)
    assert len(top) == 3
    assert np.all(np.isnan(top))
    assert np.all(np.isnan(bot))


def test_darvas_box_trigger_confirmation():
    # Bar 5 makes high=20, then 3 bars stay below 20
    highs = np.array([10, 12, 11, 13, 14, 20, 18, 17, 16, 15])
    lows = np.array([8, 10, 9, 11, 12, 16, 15, 14, 13, 12])
    top, bot = calculate_darvas_box(highs, lows, boxp=5)
    
    # After bar index 5 (which made new high of 20),
    # 3 bars later (index 8), top box confirms at 20.0
    assert top[8] == 20.0
    assert top[9] == 20.0
    # Bottom box should be lowest low of the last 5 bars (lows[4:9] -> min is 12)
    assert bot[8] == 12.0


def test_darvas_10ema_squeeze_criteria():
    # Squeezed & full OHLC inside box: top=100, ema10=98, O=98.5, H=99.5, L=98.2, C=99.0
    # Range = (99.5 - 98.2)/99.0 = 1.31% (near range)
    assert is_darvas_10ema_squeeze(
        close=99.0, top_box=100.0, bottom_box=92.0, ema10=98.0,
        high=99.5, low=98.2, open_price=98.5,
        max_squeeze_pct=3.5, max_candle_range_pct=3.5, require_ohlc_inside=True
    )

    # Rejection: High exceeds TopBox (pierced ceiling, not inside box)
    assert not is_darvas_10ema_squeeze(
        close=99.0, top_box=100.0, bottom_box=92.0, ema10=98.0,
        high=102.5, low=98.2, open_price=98.5,
        max_squeeze_pct=3.5, require_ohlc_inside=True
    )

    # Rejection: Candle range too wide (> 3.5%, not near range)
    assert not is_darvas_10ema_squeeze(
        close=99.0, top_box=100.0, bottom_box=92.0, ema10=98.0,
        high=100.0, low=95.0, open_price=98.0,
        max_squeeze_pct=3.5, max_candle_range_pct=3.5, require_ohlc_inside=True
    )

    # Rejection: Low breaks below 10 EMA support
    assert not is_darvas_10ema_squeeze(
        close=99.0, top_box=100.0, bottom_box=92.0, ema10=98.0,
        high=99.5, low=94.0, open_price=98.5,
        max_squeeze_pct=3.5, require_ohlc_inside=True
    )

    # Rejection: Spread too wide (top=100, ema10=90 -> 10% spread)
    assert not is_darvas_10ema_squeeze(
        close=95.0, top_box=100.0, bottom_box=85.0, ema10=90.0,
        max_squeeze_pct=3.5
    )

