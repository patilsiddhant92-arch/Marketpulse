"""
Nicolas Darvas Box indicator & Darvas 10 EMA Squeeze pattern detection.
Mathematically matches TradingView Pine Script definition.

Pine Script formula:
    boxp = 5
    LL = ta.lowest(low, boxp)
    k1 = ta.highest(high, boxp)
    k2 = ta.highest(high, boxp - 1)
    k3 = ta.highest(high, boxp - 2)
    NH = ta.valuewhen(high > k1[1], high, 0)
    box1 = k3 < k2
    TopBox = ta.valuewhen(ta.barssince(high > k1[1]) == boxp - 2 and box1, NH, 0)
    BottomBox = ta.valuewhen(ta.barssince(high > k1[1]) == boxp - 2 and box1, LL, 0)
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_darvas_box(
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    boxp: int = 5,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Calculate TopBox (Green Line) and BottomBox (Red Line) matching TradingView Pine Script.
    
    Returns:
        tuple of (top_box, bottom_box) as numpy float64 arrays with same length as input.
    """
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    n = len(h)
    
    if n < boxp:
        return np.full(n, np.nan), np.full(n, np.nan)
        
    ll = pd.Series(l).rolling(boxp).min().values
    k1 = pd.Series(h).rolling(boxp).max().values
    k2 = pd.Series(h).rolling(boxp - 1).max().values
    k3 = pd.Series(h).rolling(boxp - 2).max().values
    
    top_box = np.full(n, np.nan)
    bottom_box = np.full(n, np.nan)
    
    current_top = np.nan
    current_bottom = np.nan
    nh = np.nan
    bars_since_nh = 999
    
    for i in range(1, n):
        bars_since_nh += 1
        # Today made a new boxp-period high relative to yesterday's highest
        if i >= boxp and h[i] > k1[i - 1]:
            nh = h[i]
            bars_since_nh = 0
            
        box1 = (k3[i] < k2[i]) if i >= boxp else False
        if bars_since_nh == (boxp - 2) and box1:
            current_top = nh
            current_bottom = ll[i]
            
        top_box[i] = current_top
        bottom_box[i] = current_bottom
        
    return top_box, bottom_box


def compute_darvas_metrics(
    close: np.ndarray | pd.Series,
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    boxp: int = 5,
    ema_span: int = 10,
) -> dict[str, np.ndarray]:
    """Compute Darvas top, bottom, 10 EMA, and squeeze percentage series."""
    c = np.asarray(close, dtype=float)
    top_box, bottom_box = calculate_darvas_box(high, low, boxp=boxp)
    ema10 = pd.Series(c).ewm(span=ema_span, adjust=False).mean().values
    
    with np.errstate(divide="ignore", invalid="ignore"):
        squeeze_pct = np.where(top_box > 0, ((top_box - ema10) / top_box) * 100.0, np.nan)
        dist_to_green = np.where(top_box > 0, ((top_box - c) / top_box) * 100.0, np.nan)
        dist_to_ema10 = np.where(ema10 > 0, ((c - ema10) / ema10) * 100.0, np.nan)
        
    return {
        "top_box": top_box,
        "bottom_box": bottom_box,
        "ema10": ema10,
        "squeeze_pct": squeeze_pct,
        "dist_to_green_pct": dist_to_green,
        "dist_to_ema10_pct": dist_to_ema10,
    }


def is_darvas_10ema_squeeze(
    close: float,
    top_box: float,
    bottom_box: float,
    ema10: float,
    high: float | None = None,
    low: float | None = None,
    open_price: float | None = None,
    max_squeeze_pct: float = 5.0,
    max_candle_range_pct: float = 3.5,
    require_ohlc_inside: bool = True,
    ema20: float | None = None,
) -> bool:
    """
    Check if a candle meets the Darvas Green Line + 10 EMA / 20 EMA Squeeze criteria:
    1. TopBox and 10 EMA (or 20 EMA) are active and valid.
    2. Squeeze spread between TopBox and EMA is tight (0 to max_squeeze_pct, e.g. 5.0%).
    3. Price is coiled below or testing Green Line (within -0.2% to 4.0% of Green Line).
    4. Price is holding above / near 10 EMA or 20 EMA (within -2.0% to +3.5% of EMA).
    5. When require_ohlc_inside is True:
       - Entire OHLC (Open, High, Low, Close) is strictly contained inside the box:
         * High <= top_box * 1.002 (does not pierce above ceiling; hasn't broken out yet)
         * Low >= bottom_box * 0.998 (does not break below floor)
         * Low >= support_ema * 0.98 (holds dynamic EMA support)
         * Open and Close are inside [support_ema * 0.98, top_box * 1.002]
       - In Near Range: candle range (High - Low) / Close <= max_candle_range_pct (e.g. 3.5%).
    """
    if np.isnan(top_box) or top_box <= 0:
        return False

    # Support either 10 EMA or 20 EMA
    emas_to_check = [e for e in [ema10, ema20] if e is not None and not np.isnan(e) and e > 0]
    if not emas_to_check:
        return False

    qualified = False
    for cur_ema in emas_to_check:
        squeeze_pct = ((top_box - cur_ema) / top_box) * 100.0
        dist_to_green = ((top_box - close) / top_box) * 100.0
        dist_to_ema = ((close - cur_ema) / cur_ema) * 100.0

        if not (0.0 <= squeeze_pct <= max_squeeze_pct):
            continue

        if not (-2.0 <= dist_to_ema <= 3.5 and -0.2 <= dist_to_green <= 4.0):
            continue

        if require_ohlc_inside:
            h = high if high is not None else close
            l = low if low is not None else close
            o = open_price if open_price is not None else close

            if h > top_box * 1.002:
                continue
            if l < bottom_box * 0.998:
                continue
            if l < cur_ema * 0.98:
                continue
            if o > top_box * 1.002 or o < cur_ema * 0.98:
                continue
            if close > top_box * 1.002 or close < cur_ema * 0.98:
                continue
            if close > 0:
                candle_range_pct = ((h - l) / close) * 100.0
                if candle_range_pct > max_candle_range_pct:
                    continue

        qualified = True
        break

    return qualified
