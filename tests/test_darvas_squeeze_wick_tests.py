"""Darvas Squeeze: wick pierces of TopBox / 10 EMA are valid when close holds in-zone."""
from __future__ import annotations

from Scripts.darvas_squeeze import evaluate_squeeze_bar, is_darvas_10ema_squeeze, squeeze_frame
import pandas as pd


def test_high_pierce_topbox_close_in_zone_passes():
    assert is_darvas_10ema_squeeze(
        close=588.2,
        top_box=593.0,
        bottom_box=500.0,
        ema10=571.36,
        high=597.85,
        low=578.55,
        open_price=584.95,
        ema20=555.95,
        max_squeeze_pct=5.0,
        max_candle_range_pct=4.0,
    )


def test_low_undercut_ema_close_in_zone_passes():
    state = evaluate_squeeze_bar(
        close=102.0,
        top_box=105.0,
        bottom_box=90.0,
        ema10=100.0,
        high=102.5,
        low=98.5,
        open_price=101.0,
        ema20=99.0,
        rvol=0.7,
        ema10_prev=99.5,
    )
    assert state["qualifies"] is True
    assert state["failed_low"] is True


def test_close_above_topbox_still_fails():
    assert not is_darvas_10ema_squeeze(
        close=596.0,
        top_box=593.0,
        bottom_box=500.0,
        ema10=571.0,
        high=598.0,
        low=580.0,
        open_price=585.0,
        ema20=555.0,
    )
