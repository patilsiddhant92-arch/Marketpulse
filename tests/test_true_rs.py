"""Unit tests for excess_vs_index / true RS columns."""
from __future__ import annotations

import numpy as np
import pandas as pd

from Scripts.true_rs import (
    BENCH_MIDSML400,
    BENCH_NIFTY50,
    TRUE_RS_COLUMNS,
    attach_true_rs_columns,
    excess_vs_index,
)


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2026-01-02", periods=n)


def test_excess_vs_index_known_series():
    # 4 sessions; measure excess over 3 sessions on last bar
    dates = _dates(4)
    # stock: 100 -> 110 over 3 steps from idx0 to idx3 = +10%
    stock = pd.DataFrame(
        {
            "symbol": ["AAA"] * 4,
            "trade_date": dates,
            "close_price": [100.0, 102.0, 105.0, 110.0],
        }
    )
    # index: 100 -> 104 over same = +4%
    index = pd.DataFrame(
        {
            "trade_date": dates,
            "close_price": [100.0, 101.0, 102.0, 104.0],
        }
    )
    excess = excess_vs_index(stock, index, sessions=3)
    # only last row has 3 prior sessions
    assert np.isnan(excess.iloc[0])
    assert np.isnan(excess.iloc[1])
    assert np.isnan(excess.iloc[2])
    assert abs(float(excess.iloc[3]) - 6.0) < 1e-9


def test_excess_fail_closed_when_index_missing_day():
    dates = _dates(5)
    stock = pd.DataFrame(
        {
            "symbol": ["AAA"] * 5,
            "trade_date": dates,
            "close_price": [100, 101, 102, 103, 110],
        }
    )
    # drop middle index day so lag alignment breaks on some rows
    index = pd.DataFrame(
        {
            "trade_date": dates.delete(2),
            "close_price": [100, 101, 103, 104],
        }
    )
    excess = excess_vs_index(stock, index, sessions=2)
    # rows whose trade_date not in index map → nan for index_ret
    assert np.isnan(excess.iloc[2])


def test_attach_true_rs_columns_adds_four():
    dates = _dates(70)
    stock = pd.DataFrame(
        {
            "symbol": ["AAA"] * 70,
            "trade_date": dates,
            "close_price": np.linspace(100, 130, 70),
        }
    )
    idx50 = pd.DataFrame(
        {
            "trade_date": dates,
            "index_name": BENCH_NIFTY50,
            "close_price": np.linspace(100, 110, 70),
        }
    )
    idx_ms = pd.DataFrame(
        {
            "trade_date": dates,
            "index_name": BENCH_MIDSML400,
            "close_price": np.linspace(100, 120, 70),
        }
    )
    index_daily = pd.concat([idx50, idx_ms], ignore_index=True)
    out = attach_true_rs_columns(stock.assign(rs_percentile=50.0), index_daily)
    for col in TRUE_RS_COLUMNS:
        assert col in out.columns
    assert out["rs_vs_nifty50_63d"].notna().sum() >= 1
