"""Unit tests for sector-index RS helpers."""
from __future__ import annotations

import numpy as np
import pandas as pd

from Scripts.sector_index_rs import attach_sector_index_rs, compute_index_bench_rs
from Scripts.true_rs import BENCH_MIDSML400, BENCH_NIFTY50


def _bdates(n):
    return pd.bdate_range("2025-01-02", periods=n)


def test_attach_sector_index_rs_known():
    dates = _bdates(70)
    membership = pd.DataFrame(
        {
            "index_name": ["NIFTY IT"] * 1,
            "mp_index_name": ["Nifty IT"],
            "symbol": ["AAA"],
            "as_of_date": ["2026-09-14"],
            "category": ["Sectoral"],
            "clean_name": ["NIFTY IT"],
        }
    )
    stock = pd.DataFrame(
        {
            "symbol": ["AAA"] * 70,
            "trade_date": dates,
            "close_price": np.linspace(100, 140, 70),
        }
    )
    idx_it = pd.DataFrame(
        {
            "trade_date": dates,
            "index_name": "Nifty IT",
            "close_price": np.linspace(100, 120, 70),
        }
    )
    idx_n50 = pd.DataFrame(
        {
            "trade_date": dates,
            "index_name": BENCH_NIFTY50,
            "close_price": np.linspace(100, 110, 70),
        }
    )
    index_daily = pd.concat([idx_it, idx_n50], ignore_index=True)
    out = attach_sector_index_rs(stock, index_daily, membership)
    assert out["sector_index_name"].iloc[-1] == "Nifty IT"
    assert out["rs_vs_sector_index_63d"].notna().sum() >= 1


def test_compute_index_bench_rs():
    dates = _bdates(70)
    frames = []
    for name, end in [("Nifty IT", 120), (BENCH_NIFTY50, 110), (BENCH_MIDSML400, 115)]:
        frames.append(
            pd.DataFrame(
                {
                    "trade_date": dates,
                    "index_name": name,
                    "close_price": np.linspace(100, end, 70),
                }
            )
        )
    index_daily = pd.concat(frames, ignore_index=True)
    out = compute_index_bench_rs(index_daily, index_names=["Nifty IT"])
    assert "rs_vs_midsml400_63d" in out.columns
    assert out["rs_vs_midsml400_63d"].notna().sum() >= 1
