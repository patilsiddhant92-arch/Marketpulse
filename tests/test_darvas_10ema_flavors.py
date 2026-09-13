"""Tests for Darvas 10 EMA Pullback / Catch-up flavors (structure-above-10EMA)."""
from __future__ import annotations

import pandas as pd

from Scripts.darvas_squeeze import classify_darvas_10ema_frame


def _hist(
    *,
    last_rvol=0.6,
    last_close=100.0,
    last_ema10=99.5,
    thrust=True,
    keep_closes_above_ema=True,
):
    dates = pd.bdate_range("2026-08-01", periods=15)
    rows = []
    ema = 95.0
    close = 96.0
    for i, d in enumerate(dates):
        if thrust and i == 10:
            close = close * 1.04
            rvol = 1.8
            high = close * 1.01
            ema = ema + 0.2
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
        rows.append(
            {
                "symbol": "DEMO",
                "trade_date": d,
                "open_price": close * 1.001 if keep_closes_above_ema else close * 0.99,
                "high_price": high,
                "low_price": close * 0.99,
                "close_price": close,
                "ema_10": ema,
                "ema_20": ema - 0.4,
                "rvol": rvol,
            }
        )
    rows[-1]["close_price"] = last_close
    rows[-1]["ema_10"] = last_ema10
    rows[-1]["ema_20"] = last_ema10 - 0.3
    rows[-1]["rvol"] = last_rvol
    rows[-1]["high_price"] = max(last_close * 1.01, last_close)
    rows[-1]["low_price"] = min(last_close * 0.995, last_ema10 * 0.99)
    rows[-1]["open_price"] = max(last_close, last_ema10 * 1.001)
    rows[-2]["ema_10"] = last_ema10 - 0.5
    # Ensure post-thrust closes stay above ema when requested
    if keep_closes_above_ema:
        for j in range(10, len(rows)):
            rows[j]["close_price"] = max(rows[j]["close_price"], rows[j]["ema_10"] * 1.002)
            rows[j]["high_price"] = max(rows[j]["high_price"], rows[j]["close_price"])
            rows[j]["open_price"] = max(rows[j]["open_price"], rows[j]["ema_10"] * 1.001)
        rows[-1]["close_price"] = max(last_close, last_ema10 * 1.002)
        rows[-1]["ema_10"] = last_ema10
    else:
        # Force a post-thrust close under ema (should reject)
        rows[-2]["close_price"] = rows[-2]["ema_10"] * 0.98
        rows[-2]["open_price"] = rows[-2]["close_price"]
    return pd.DataFrame(rows)


def test_pullback_flavor_dry_near_ema():
    df = _hist(last_rvol=0.6, last_close=100.0, last_ema10=99.6, thrust=True)
    out = classify_darvas_10ema_frame(df)
    assert not out.empty
    assert out.iloc[0]["flavor"] == "Pullback"


def test_catchup_flavor_held_highs_ema_rising():
    df = _hist(last_rvol=0.55, last_close=104.0, last_ema10=102.8, thrust=True)
    df.loc[df.index[-3]:, "high_price"] = 104.5
    df.loc[df.index[-1], "close_price"] = 104.0
    df.loc[df.index[-1], "ema_10"] = 102.8
    df.loc[df.index[-2], "ema_10"] = 101.5
    # keep structure closes above ema
    for j in df.index[-5:]:
        df.loc[j, "close_price"] = max(float(df.loc[j, "close_price"]), float(df.loc[j, "ema_10"]) * 1.002)
        df.loc[j, "high_price"] = max(float(df.loc[j, "high_price"]), float(df.loc[j, "close_price"]))
    out = classify_darvas_10ema_frame(df)
    assert not out.empty
    assert out.iloc[0]["flavor"] in {"Catch-up", "Pullback"}


def test_wet_volume_rejects():
    df = _hist(last_rvol=1.4, last_close=100.0, last_ema10=99.6, thrust=True)
    out = classify_darvas_10ema_frame(df)
    assert out.empty


def test_no_thrust_rejects():
    df = _hist(last_rvol=0.6, last_close=100.0, last_ema10=99.6, thrust=False)
    out = classify_darvas_10ema_frame(df)
    assert out.empty


def test_close_under_ema_after_thrust_rejects():
    df = _hist(last_rvol=0.6, last_close=100.0, last_ema10=99.6, thrust=True, keep_closes_above_ema=False)
    out = classify_darvas_10ema_frame(df)
    assert out.empty


def test_open_under_ema_after_thrust_rejects():
    df = _hist(last_rvol=0.6, last_close=100.0, last_ema10=99.6, thrust=True, keep_closes_above_ema=True)
    df.loc[df.index[-1], "open_price"] = float(df.loc[df.index[-1], "ema_10"]) * 0.98
    out = classify_darvas_10ema_frame(df)
    assert out.empty
