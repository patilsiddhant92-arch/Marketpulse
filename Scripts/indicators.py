"""Pure indicator calculations used by the EOD pipeline.

The functions in this module deliberately have no DuckDB or application
dependencies.  They are small calculation boundaries that can be golden-
tested independently from database rebuild orchestration.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(close: pd.Series, span: int) -> pd.Series:
    """Return the standard non-adjusted exponential moving average."""
    return close.ewm(span=span, adjust=False, min_periods=span).mean()


def sma(close: pd.Series, window: int) -> pd.Series:
    """Return a simple moving average. Minervini Trend Template uses SMA 50/150/200."""
    return close.rolling(window, min_periods=window).mean()


def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    """Return RSI using Wilder's RMA smoothing."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Return daily true range using the previous close for gap handling."""
    previous_close = close.shift(1)
    return pd.concat(
        [high - low, (high - previous_close).abs(), (low - previous_close).abs()],
        axis=1,
    ).max(axis=1)


def atr_sma(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Return MarketPulse's current SMA ATR definition.

    The five-row minimum is intentionally retained for compatibility with
    the production ``indicators_daily.atr_14`` column.
    """
    return true_range(high, low, close).rolling(period, min_periods=5).mean()


def atr_wilder(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Return additive Wilder ATR; this must not replace ``atr_sma``."""
    return true_range(high, low, close).ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()


def rvol(volume: pd.Series, window: int = 20) -> pd.Series:
    """Return volume relative to its rolling simple average."""
    average_volume = volume.rolling(window, min_periods=5).mean()
    return volume / average_volume


def rs_quarterly_mix(
    close: pd.Series,
    *,
    require_history: bool = True,
) -> pd.Series:
    """Return the weighted non-overlapping quarterly return mix.

    The default is leak-safe for short histories: fewer than four quarterly
    observations produces NaN rather than treating missing history as 0%.
    ``require_history=False`` is available for compatibility calculations
    while old persisted columns are being migrated.
    """
    latest_q = close / close.shift(63) - 1
    prior_q2 = close.shift(63) / close.shift(126) - 1
    prior_q3 = close.shift(126) / close.shift(189) - 1
    prior_q4 = close.shift(189) / close.shift(252) - 1
    quarters = pd.concat([latest_q, prior_q2, prior_q3, prior_q4], axis=1)
    weights = np.array([0.40, 0.20, 0.20, 0.20])
    if require_history:
        return quarters.mul(weights, axis=1).sum(axis=1, min_count=4)
    return quarters.fillna(0).mul(weights, axis=1).sum(axis=1)


def distance_below_high(close: pd.Series, high: pd.Series) -> pd.Series:
    """Return non-negative percentage distance below a reference high."""
    safe_high = high.replace(0, np.nan)
    return ((safe_high - close) / safe_high * 100).clip(lower=0)


def setup_class(frame: pd.DataFrame) -> pd.Series:
    """Assign one mutually-exclusive daily setup class, breakout first."""
    breakout = (
        frame["new_20d_high"].fillna(False).astype(bool)
        & frame["rvol"].ge(1.5)
        & frame["close_location_pct"].ge(66)
    )
    pivot = (~breakout) & frame["distance_below_52w"].le(5)
    contraction_ok = frame["range_5d_pct"].lt(frame["range_10d_pct"]) & frame["atr_pct_avg_5d"].lt(frame["atr_pct_avg_20d"])
    dryup_ok = frame["avg_volume_5d"].lt(frame["avg_volume_20d"])
    base = (~breakout) & (~pivot) & contraction_ok & dryup_ok & frame["distance_below_52w"].le(15)
    return pd.Series(
        np.select([breakout, pivot, base], ["BREAKOUT", "PIVOT", "BASE"], default="NONE"),
        index=frame.index,
        name="setup_class",
    )


__all__ = [
    "atr_sma",
    "atr_wilder",
    "distance_below_high",
    "ema",
    "rsi_wilder",
    "rvol",
    "rs_quarterly_mix",
    "setup_class",
    "sma",
    "true_range",
]
