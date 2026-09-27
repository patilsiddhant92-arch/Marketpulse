"""Historical setups: same predicates as the Desk, point-in-time (spec §5 study hygiene)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from Scripts.darvas_squeeze import calculate_darvas_box, evaluate_squeeze_bar
from Scripts.evidence.setups import (_SymbolArrays, contractions_window, darvas_squeeze_flags,
                                     historical_setups_from_indicators)
from Scripts.minervini_geometry import detect_contractions


def _walk(n: int, seed: int, symbol: str = "AAA") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.02, n)))
    high = close * (1 + rng.uniform(0, 0.03, n))
    low = close * (1 - rng.uniform(0, 0.03, n))
    opn = low + (high - low) * rng.uniform(0, 1, n)
    vol = rng.uniform(1e5, 1e6, n)
    vol[rng.uniform(0, 1, n) < 0.02] = np.nan
    df = pd.DataFrame({"symbol": symbol, "series": "EQ", "trade_date": pd.bdate_range("2023-01-02", periods=n),
                       "open_price": opn, "high_price": high, "low_price": low, "close_price": close, "volume": vol})
    c = df["close_price"]
    df["ema_10"] = c.ewm(span=10, adjust=False).mean()
    df["ema_20"] = c.ewm(span=20, adjust=False).mean()
    df["ema_200"] = c.ewm(span=200, adjust=False).mean()
    df["rvol"] = df["volume"] / df["volume"].rolling(20, min_periods=1).mean()
    df["avg_volume_20d"] = df["volume"].rolling(20, min_periods=1).mean()
    df["avg_traded_value_cr_20d"] = 10.0
    df["turnover_cr"] = 10.0
    df["mcap_cr"] = 5000.0
    df["trend_template_pass"] = True
    df["rs_percentile"] = 80.0
    df["away_52w_high_pct"] = (c / c.cummax() - 1) * 100
    return df


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_vcp_kernel_matches_detect_contractions(seed):
    df = _walk(400, seed)
    arr = _SymbolArrays(df["high_price"].to_numpy(), df["low_price"].to_numpy(), df["volume"].to_numpy())
    for r in range(40, 400, 7):
        lo = max(0, r - 251)
        ref = detect_contractions(df.iloc[lo:r + 1][["trade_date", "open_price", "high_price", "low_price", "close_price", "volume"]])
        got = contractions_window(arr, lo, r)
        assert len(got) == len(ref.contractions), r
        for g, c in zip(got, ref.contractions):
            assert g[3] == pytest.approx(c.peak) and g[4] == pytest.approx(c.trough)
            assert g[5] == pytest.approx(c.depth_pct) and g[6] == c.bars
            assert g[7] == pytest.approx(c.volume_ratio, nan_ok=True)
        if ref.contractions:
            assert got[-1][3] == pytest.approx(ref.pivot) and got[-1][4] == pytest.approx(ref.stop)


def test_darvas_bar_flags_match_desk_truth_table():
    df = _walk(300, 7)
    f = darvas_squeeze_flags(df)
    top, bottom = calculate_darvas_box(df["high_price"], df["low_price"], boxp=5)
    e10 = df["ema_10"].to_numpy()
    for i in range(1, len(df)):
        ref = evaluate_squeeze_bar(df["close_price"].iat[i], top[i], bottom[i], e10[i], high=df["high_price"].iat[i],
                                   low=df["low_price"].iat[i], open_price=df["open_price"].iat[i],
                                   ema20=df["ema_20"].iat[i], rvol=df["rvol"].iat[i] if np.isfinite(df["rvol"].iat[i]) else None,
                                   ema10_prev=e10[i - 1])
        if np.isfinite(df["rvol"].iat[i]):
            assert bool(f["bar_ok"].iat[i]) == ref["qualifies"], i


def test_historical_setups_are_point_in_time():
    df = pd.concat([_walk(420, 11, "AAA"), _walk(420, 12, "BBB")], ignore_index=True)
    full = historical_setups_from_indicators(df)
    cut = df["trade_date"].iloc[300]
    part = historical_setups_from_indicators(df.loc[df["trade_date"] <= cut])
    a = full.loc[full["trade_date"] <= cut, ["queue", "symbol", "trade_date", "trigger_price", "stop_price"]].reset_index(drop=True)
    b = part[["queue", "symbol", "trade_date", "trigger_price", "stop_price"]].reset_index(drop=True)
    assert len(a) > 0
    pd.testing.assert_frame_equal(a, b)
    assert set(full["queue"]) <= {"darvas_squeeze", "vcp", "momentum"}
    assert full["setup_id"].str.count(":").eq(2).all()
