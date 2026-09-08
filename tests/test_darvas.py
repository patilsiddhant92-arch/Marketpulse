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


def test_darvas_squeeze_real_examples_and_rejections():
    """Verify exact real market examples: ROSSTECH, NPST, EXPLEOSOL, CHALET must PASS; NTPC, RHIM must FAIL."""
    # 1. ROSSTECH (PASS): Squeezed 4.41%, 10EMA > 20EMA, OHLC inside [1120.37, 1172.0]
    assert is_darvas_10ema_squeeze(
        close=1148.2, top_box=1172.0, bottom_box=1057.95, ema10=1120.37,
        high=1172.0, low=1139.6, open_price=1156.3, ema20=1098.06
    )

    # 2. NPST (PASS): Squeezed 4.65%, 10EMA > 20EMA, OHLC inside [1682.82, 1764.8]
    assert is_darvas_10ema_squeeze(
        close=1740.4, top_box=1764.8, bottom_box=1561.8, ema10=1682.82,
        high=1746.8, low=1691.2, open_price=1713.8, ema20=1646.14
    )

    # 3. EXPLEOSOL (PASS): Squeezed 4.61%, 10EMA > 20EMA, OHLC inside [884.21, 926.9]
    assert is_darvas_10ema_squeeze(
        close=899.55, top_box=926.9, bottom_box=849.0, ema10=884.21,
        high=922.0, low=895.0, open_price=910.45, ema20=872.78
    )

    # 4. CHALET (PASS): Squeezed 4.93%, 10EMA > 20EMA, Low holds 10EMA (893.1 vs 893.65)
    assert is_darvas_10ema_squeeze(
        close=908.75, top_box=939.95, bottom_box=884.5, ema10=893.65,
        high=913.45, low=893.1, open_price=900.0, ema20=879.00
    )

    # 5. NTPC (FAIL): 10EMA < 20EMA (downtrend: 332.27 < 335.14), Low & Close < 10EMA
    assert not is_darvas_10ema_squeeze(
        close=332.0, top_box=344.45, bottom_box=323.5, ema10=332.27,
        high=333.8, low=330.35, open_price=332.5, ema20=335.14
    )

    # 6. RHIM (FAIL): 10EMA < 20EMA (downtrend: 372.55 < 377.45), Open & Low < 10EMA
    assert not is_darvas_10ema_squeeze(
        close=373.8, top_box=377.8, bottom_box=361.35, ema10=372.55,
        high=375.15, low=369.0, open_price=371.8, ema20=377.45
    )


