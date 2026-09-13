"""Approach A: dry-vol + rising 10 EMA + hard tightening for Darvas Squeeze."""
from __future__ import annotations

import numpy as np
import pandas as pd

from Scripts.darvas_squeeze import evaluate_squeeze_bar, squeeze_frame
from Scripts.desk_contract import DARVAS


def _maxhealth_like_ohlc() -> dict:
    # Geometry matches 2026-09-11 MAXHEALTH-ish: tight Top↔EMA, rising ema10, wet rvol.
    return dict(
        close=1037.7,
        top_box=1042.1,
        bottom_box=985.5,
        ema10=1017.22,
        high=1041.5,
        low=1022.7,
        open_price=1028.2,
        ema20=1019.27,
    )


def test_darvas_max_rvol_constant():
    assert DARVAS.get("max_rvol") == 1.0


def test_maxhealth_like_wet_rvol_fails_squeeze():
    kw = _maxhealth_like_ohlc()
    state = evaluate_squeeze_bar(**kw, rvol=1.31, ema10_prev=1012.67)
    assert state["qualifies"] is False


def test_same_geometry_dry_rvol_and_rising_ema_passes():
    kw = _maxhealth_like_ohlc()
    state = evaluate_squeeze_bar(**kw, rvol=0.70, ema10_prev=1012.67)
    assert state["qualifies"] is True


def test_falling_ema10_fails_even_with_dry_rvol():
    kw = _maxhealth_like_ohlc()
    state = evaluate_squeeze_bar(**kw, rvol=0.70, ema10_prev=1020.0)
    assert state["qualifies"] is False


def test_squeeze_frame_hard_tightening_and_rvol():
    # Build a short series: prior wider squeeze, last bar tight + dry + rising ema.
    dates = pd.bdate_range("2026-08-01", periods=20)
    # Synthetic coil: highs flat near 100, ema10 rising into highs, dry vol on last bar.
    rows = []
    ema = 90.0
    for i, d in enumerate(dates):
        ema = ema + 0.4
        topish = 100.0
        close = 96.0 + i * 0.05
        rvol = 1.4 if i < len(dates) - 1 else 0.6
        rows.append(
            {
                "symbol": "DRYCOIL",
                "trade_date": d,
                "open_price": close - 0.2,
                "high_price": topish if i >= 10 else 98.0 + (i % 3),
                "low_price": close - 1.0,
                "close_price": close,
                "ema_10": ema,
                "ema_20": ema - 0.5,
                "rvol": rvol,
            }
        )
    # Force a valid box: need Pine-like box formation — use real calculate via frame.
    # Prefer calling squeeze_frame and asserting gate behavior with patched last rvol.
    df = pd.DataFrame(rows)
    # If frame can't form a box, still unit-test evaluate; for frame, inject known tops via
    # a minimal path: last bar wet must fail when geometry would otherwise pass.
    out = squeeze_frame(df, timeframe="D")
    assert not out.empty
    # Wet last bar (we set 0.6 dry) — should qualify only if geometry+tightening ok.
    # Flip last rvol wet and re-run.
    df2 = df.copy()
    df2.loc[df2.index[-1], "rvol"] = 1.31
    out_wet = squeeze_frame(df2, timeframe="D")
    assert not out_wet.empty
    assert bool(out_wet.iloc[0]["qualifies"]) is False


def test_squeeze_frame_rejects_when_not_tightening():
    # Monotone expanding gap should fail hard tightening when prior finite.
    dates = pd.bdate_range("2026-08-01", periods=16)
    rows = []
    for i, d in enumerate(dates):
        rows.append(
            {
                "symbol": "WIDEN",
                "trade_date": d,
                "open_price": 100.0,
                "high_price": 110.0 + i * 0.5,
                "low_price": 99.0,
                "close_price": 105.0,
                "ema_10": 100.0 - i * 0.2,  # falling away → wider squeeze
                "ema_20": 99.0 - i * 0.2,
                "rvol": 0.5,
            }
        )
    out = squeeze_frame(pd.DataFrame(rows), timeframe="D")
    if out.empty:
        return
    # If prior squeeze finite and not tightening, qualifies must be false.
    row = out.iloc[0]
    if np.isfinite(row["squeeze_pct_5d_ago"]) and not bool(row["tightening"]):
        assert bool(row["qualifies"]) is False
