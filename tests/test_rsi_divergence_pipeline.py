"""indicators_daily RSI divergence columns come from the causal engine (no shift(-1) look-ahead)."""
from __future__ import annotations

import numpy as np
import pandas as pd

import build_database as bd
from App.indicators import rsi_divergence as rd


def _symbol_frame(seed: int = 3, n: int = 520) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-05-06", periods=n)
    ret = rng.normal(0, 0.018, n) + 0.004 * np.sin(np.arange(n) / 25)
    close = 100 * np.exp(np.cumsum(ret))
    spread = np.abs(rng.normal(0, 0.012, n)) * close
    high = close + spread
    low = close - spread
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(high, open_)
    low = np.minimum(low, open_)
    vol = rng.integers(100_000, 1_000_000, n).astype(float)
    return pd.DataFrame({
        "symbol": "TEST", "series": "EQ", "trade_date": dates,
        "open_price": open_, "high_price": high, "low_price": low, "close_price": close,
        "volume": vol, "turnover_cr": vol * close / 1e7, "delivery_qty": vol * 0.4, "delivery_pct": 40.0,
    })


def test_daily_flags_match_engine_and_type_column():
    g = bd._calc_single_symbol_indicators(_symbol_frame())
    divs = rd.detect(g.high_price, g.low_price, g.close_price)
    bull = np.zeros(len(g), bool)
    bear = np.zeros(len(g), bool)
    for d in divs:
        if d.regular:
            (bull if d.side == "bull" else bear)[d.confirm] = True
    assert np.array_equal(g.bullish_rsi_divergence.to_numpy(bool), bull)
    assert np.array_equal(g.bearish_rsi_divergence.to_numpy(bool), bear)
    assert bull.any() and bear.any()
    labels = g.rsi_divergence_type.dropna()
    assert len(labels) == len({d.confirm for d in divs})
    assert all(any(t in x for t in rd.TYPES) for x in labels)


def test_divergence_columns_are_causal():
    full_in = _symbol_frame()
    full = bd._calc_single_symbol_indicators(full_in)
    cols = ["bullish_rsi_divergence", "bearish_rsi_divergence", "rsi_divergence_type"]
    for t in (200, 333, 470):
        part = bd._calc_single_symbol_indicators(full_in.iloc[: t + 1])
        a = full.iloc[: t + 1][cols].reset_index(drop=True)
        b = part[cols].reset_index(drop=True)
        pd.testing.assert_frame_equal(a, b, check_dtype=False)
        # weekly / monthly: rows mapped to completed W/M bars do not change either
        last_fri = part.trade_date.iloc[-1] - pd.Timedelta(days=(part.trade_date.iloc[-1].weekday() - 4) % 7 or 7)
        wk = part.trade_date <= last_fri
        for c in ("bullish_rsi_divergence_w", "bearish_rsi_divergence_w"):
            assert np.array_equal(full.iloc[: t + 1][c].to_numpy(bool)[wk.to_numpy()], part[c].to_numpy(bool)[wk.to_numpy()])
