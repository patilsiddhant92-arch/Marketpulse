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
    df = _hist(last_rvol=0.55, last_close=108.0, last_ema10=100.0, thrust=True)
    for n, j in enumerate(df.index[-8:]):
        ema = 94.0 + n * 0.75
        close = 107.5
        df.loc[j, "ema_10"] = ema
        df.loc[j, "close_price"] = close
        df.loc[j, "open_price"] = close
        df.loc[j, "high_price"] = close * 1.008
        df.loc[j, "low_price"] = close * 0.997  # well above 10 EMA — no tag
        df.loc[j, "rvol"] = 0.55
    df.loc[df.index[-1], "close_price"] = 108.0
    df.loc[df.index[-1], "ema_10"] = 100.0
    df.loc[df.index[-2], "ema_10"] = 98.8
    out = classify_darvas_10ema_frame(df)
    assert not out.empty
    assert out.iloc[0]["flavor"] == "Catch-up"


def test_wet_volume_rejects():
    df = _hist(last_rvol=1.4, last_close=100.0, last_ema10=99.6, thrust=True)
    for j in df.index[:-1]:
        ema = float(df.loc[j, "ema_10"])
        df.loc[j, "low_price"] = ema * 1.06
        df.loc[j, "open_price"] = ema * 1.05
        df.loc[j, "close_price"] = max(float(df.loc[j, "close_price"]), ema * 1.04)
        df.loc[j, "high_price"] = max(float(df.loc[j, "high_price"]), float(df.loc[j, "close_price"]))
    out = classify_darvas_10ema_frame(df)
    assert out.empty


def test_no_tag_and_not_near_highs_rejects():
    df = _hist(last_rvol=0.6, last_close=110.0, last_ema10=99.6, thrust=False)
    for j in df.index:
        ema = float(df.loc[j, "ema_10"])
        df.loc[j, "low_price"] = ema * 1.06
        df.loc[j, "open_price"] = ema * 1.07
        df.loc[j, "close_price"] = 120.0
        df.loc[j, "high_price"] = 121.0
    df.loc[df.index[-1], "close_price"] = 110.0
    df.loc[df.index[-1], "high_price"] = 111.0
    df.loc[df.index[-1], "low_price"] = 109.0
    df.loc[df.index[-1], "ema_10"] = 99.6
    df.loc[df.index[-2], "ema_10"] = 99.0
    out = classify_darvas_10ema_frame(df)
    assert out.empty


def test_close_under_ema_after_thrust_rejects():
    df = _hist(last_rvol=0.6, last_close=100.0, last_ema10=99.6, thrust=True, keep_closes_above_ema=True)
    ema = float(df.loc[df.index[-1], "ema_10"])
    df.loc[df.index[-1], "close_price"] = ema * 0.99
    df.loc[df.index[-1], "open_price"] = ema * 0.99
    df.loc[df.index[-1], "high_price"] = ema * 0.995
    df.loc[df.index[-1], "low_price"] = ema * 0.98
    out = classify_darvas_10ema_frame(df)
    assert out.empty


def test_open_under_ema_with_wick_tag_is_pullback():
    df = _hist(last_rvol=0.6, last_close=100.0, last_ema10=99.6, thrust=True, keep_closes_above_ema=True)
    ema = float(df.loc[df.index[-1], "ema_10"])
    df.loc[df.index[-1], "open_price"] = ema * 0.98
    df.loc[df.index[-1], "low_price"] = ema * 0.99
    df.loc[df.index[-1], "close_price"] = ema * 1.004
    df.loc[df.index[-1], "high_price"] = ema * 1.01
    out = classify_darvas_10ema_frame(df)
    assert not out.empty
    assert out.iloc[0]["flavor"] == "Pullback"


def test_traceback_tag_two_days_ago_then_move():
    """PINELABS-style: OHLC tags 10 EMA two sessions back, then price leaves."""
    df = _hist(last_rvol=0.5, last_close=106.0, last_ema10=100.0, thrust=True)
    ema_seq = [96.0, 97.0, 98.0, 99.0, 100.0]
    close_seq = [97.0, 98.2, 99.0, 102.5, 106.0]
    for offset, (ema, close) in enumerate(zip(ema_seq, close_seq)):
        j = df.index[-5 + offset]
        df.loc[j, "ema_10"] = ema
        df.loc[j, "close_price"] = close
        df.loc[j, "open_price"] = close
        df.loc[j, "high_price"] = close * 1.01
        df.loc[j, "low_price"] = close * 0.995
        df.loc[j, "rvol"] = 0.5
    tag = df.index[-3]
    df.loc[tag, "low_price"] = 98.0 * 0.999
    df.loc[tag, "ema_10"] = 98.0
    df.loc[tag, "close_price"] = 99.0
    df.loc[tag, "open_price"] = 99.0
    out = classify_darvas_10ema_frame(df)
    assert not out.empty
    assert out.iloc[0]["flavor"] == "Trace-back"


def test_weekly_and_monthly_darvas_10ema_resampling():
    # Construct 120 daily bars spanning multiple months
    dates = pd.bdate_range("2026-01-01", periods=120)
    rows = []
    c = 100.0
    for i, d in enumerate(dates):
        if i == 80:
            c = c * 1.15  # major thrust
        elif i > 80:
            c = c * 1.002
        else:
            c = c * 1.001
        rows.append({
            "symbol": "MULTI",
            "trade_date": d,
            "open_price": c * 0.999,
            "high_price": c * 1.01,
            "low_price": c * 0.995,
            "close_price": c,
            "volume": 500_000.0,
        })
    df = pd.DataFrame(rows)

    # Weekly classification
    out_w = classify_darvas_10ema_frame(df, timeframe="W")
    assert isinstance(out_w, pd.DataFrame)
    assert "flavor" in out_w.columns
    assert "away_10ema_pct" in out_w.columns

    # Monthly classification
    out_m = classify_darvas_10ema_frame(df, timeframe="M")
    assert isinstance(out_m, pd.DataFrame)
    assert "flavor" in out_m.columns

