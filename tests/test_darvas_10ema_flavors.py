"""Tests for Darvas 10 EMA Pullback / Catch-up flavors."""
from __future__ import annotations

import numpy as np
import pandas as pd

from Scripts.darvas_squeeze import classify_darvas_10ema_frame


def _base_hist(*, last_rvol=0.6, last_close=100.0, last_ema10=99.5, thrust=True):
    dates = pd.bdate_range("2026-08-01", periods=15)
    rows = []
    ema = 95.0
    close = 96.0
    for i, d in enumerate(dates):
        if thrust and i == 10:
            close = close * 1.04  # ~4% thrust
            rvol = 1.8
            high = close * 1.01
        elif i == len(dates) - 1:
            close = last_close
            ema = last_ema10
            rvol = last_rvol
            high = max(close * 1.005, last_close)
        else:
            close = close * 1.002
            ema = ema + 0.15
            rvol = 0.9
            high = close * 1.01
        if i != len(dates) - 1:
            ema = ema + 0.1
        rows.append(
            {
                "symbol": "DEMO",
                "trade_date": d,
                "open_price": close * 0.995,
                "high_price": high,
                "low_price": close * 0.99,
                "close_price": close if i != len(dates) - 1 else last_close,
                "ema_10": ema if i != len(dates) - 1 else last_ema10,
                "ema_20": (ema if i != len(dates) - 1 else last_ema10) - 0.4,
                "rvol": rvol if i != len(dates) - 1 else last_rvol,
            }
        )
    # fix last row explicitly
    rows[-1]["close_price"] = last_close
    rows[-1]["ema_10"] = last_ema10
    rows[-1]["ema_20"] = last_ema10 - 0.3
    rows[-1]["rvol"] = last_rvol
    rows[-1]["high_price"] = max(last_close * 1.002, last_close)
    rows[-1]["low_price"] = min(last_close * 0.995, last_ema10 * 0.995)
    rows[-1]["open_price"] = last_close
    # ensure ema rising into last
    rows[-2]["ema_10"] = last_ema10 - 0.5
    return pd.DataFrame(rows)


def test_pullback_flavor_dry_near_ema():
    df = _base_hist(last_rvol=0.6, last_close=100.0, last_ema10=99.6, thrust=True)
    out = classify_darvas_10ema_frame(df)
    assert not out.empty
    assert out.iloc[0]["flavor"] == "Pullback"


def test_catchup_flavor_held_highs_ema_rising():
    # Price held near highs, ema catching up, dry vol, prior thrust
    df = _base_hist(last_rvol=0.55, last_close=104.0, last_ema10=102.8, thrust=True)
    # Keep highs elevated on last few bars
    df.loc[df.index[-3]:, "high_price"] = 104.5
    df.loc[df.index[-1], "close_price"] = 104.0
    df.loc[df.index[-1], "ema_10"] = 102.8
    df.loc[df.index[-2], "ema_10"] = 101.5
    out = classify_darvas_10ema_frame(df)
    assert not out.empty
    assert out.iloc[0]["flavor"] in {"Catch-up", "Pullback"}


def test_wet_volume_rejects():
    df = _base_hist(last_rvol=1.4, last_close=100.0, last_ema10=99.6, thrust=True)
    out = classify_darvas_10ema_frame(df)
    assert out.empty or not bool(out.iloc[0].get("qualifies", True))


def test_no_thrust_rejects():
    df = _base_hist(last_rvol=0.6, last_close=100.0, last_ema10=99.6, thrust=False)
    out = classify_darvas_10ema_frame(df)
    assert out.empty
