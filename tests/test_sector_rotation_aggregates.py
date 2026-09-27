from __future__ import annotations

import numpy as np
import pandas as pd

import build_database
import index_constituents


def _indicators() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2026-09-25"] * 3),
            "symbol": ["AAA", "BBB", "CCC"],
            "return_5d_pct": [1.0, np.nan, 3.0],
            "return_1m_pct": [2.0, 4.0, np.nan],
            "return_3m_pct": [np.nan, np.nan, np.nan],
            "rs_percentile": [90.0, 60.0, 30.0],
            "close_price": [110.0, 90.0, 100.0],
            "prev_close": [100.0, 95.0, np.nan],
            "ema_10": [100.0, 100.0, np.nan],
            "ema_50": [100.0, 80.0, 90.0],
            "ema_200": [np.nan, np.nan, np.nan],
            "near_52w_high": [True, False, True],
            "is_vcp": [False, False, True],
            "turnover_cr": [1.5, np.nan, 2.5],
        }
    )


def test_group_aggregates_skip_nan_and_count_nan_ema_as_not_above():
    master = pd.DataFrame(
        {"symbol": ["AAA", "BBB", "CCC"], "broad_sector": ["X"] * 3, "sector": ["X"] * 3,
         "broad_industry": ["X"] * 3, "industry": ["X"] * 3}
    )
    out = build_database.build_sector_rotation(_indicators(), master)
    row = out[out["level"] == "Sector"].iloc[0]

    assert row["stocks"] == 3.0
    assert row["return_5d_pct"] == 2.0
    assert row["return_1m_pct"] == 3.0
    assert np.isnan(row["return_3m_pct"])
    assert row["rs_percentile"] == 60.0
    assert np.isclose(row["above_10ema_pct"], 100 / 3)
    assert np.isclose(row["above_50ema_pct"], 100.0)
    assert row["above_200ema_pct"] == 0.0
    assert row["near_52w_highs"] == 2.0
    assert row["vcp_candidates"] == 1.0
    assert row["turnover_cr"] == 4.0
    assert np.isclose(row["adv_pct"], 100 / 3)
    for col in ("stocks", "near_52w_highs", "vcp_candidates", "adv_pct"):
        assert out[col].dtype == np.float64


def test_sector_index_resolved_once_per_symbol(monkeypatch):
    calls: list[str] = []
    real = index_constituents.resolve_sector_index

    def spy(sym, membership, master_row=None, soft_map=None):
        calls.append(sym)
        return real(sym, membership, master_row, soft_map)

    monkeypatch.setattr(index_constituents, "resolve_sector_index", spy)
    membership = pd.DataFrame(
        {"symbol": ["AAA"], "mp_index_name": ["NIFTY IT"], "category": ["Sectoral"], "clean_name": ["NIFTY IT"]}
    )
    symbols = pd.Series(["AAA", "BBB", "AAA", "aaa ", "BBB"], index=[10, 11, 12, 13, 14])

    out = index_constituents.map_symbols_to_indices(symbols, membership)

    assert sorted(calls) == ["AAA", "BBB"]
    assert list(out.index) == [10, 11, 12, 13, 14]
    assert list(out) == ["NIFTY IT", None, "NIFTY IT", "NIFTY IT", None]
