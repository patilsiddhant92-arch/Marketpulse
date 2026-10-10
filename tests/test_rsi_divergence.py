"""RSI divergence engine (Scripts/rsi_divergence.py): 8 types, filters, trigger/stop, status, no look-ahead."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from App.indicators import rsi_divergence as rd


# ----------------------------------------------------------------------------- crafted series
def _bull_lows(p2_low: float = 85.0) -> np.ndarray:
    """Strictly monotone legs: only bars 10 and 20 are low pivots (90 then p2_low)."""
    lows = np.empty(31)
    for i in range(31):
        if i <= 10:
            lows[i] = 90 + (10 - i)
        elif i <= 15:
            lows[i] = 90 + (i - 10) * 1.4  # up to 97
        elif i <= 20:
            lows[i] = 97 - (i - 15) * (97 - p2_low) / 5  # down to p2_low
        else:
            lows[i] = p2_low + (i - 20) * 1.5
    return lows


def _bull_case(p2_low: float = 85.0, r1: float = 30.0, r2: float = 35.0, mid_rsi: float = 45.0,
               trend: float = 200.0, close_off: float = 2.0):
    lows = _bull_lows(p2_low)
    highs = lows + 3
    highs[15] = 108.0
    closes = lows + close_off
    rsi = np.full(len(lows), mid_rsi)
    rsi[10], rsi[20] = r1, r2
    atr = np.full(len(lows), 2.0)
    tr = np.full(len(lows), trend)
    return highs, lows, closes, rsi, atr, tr


def _mirror(highs, lows, closes, rsi, atr, tr):
    """Bull case -> the bear case (price reflected around 100, RSI around 50)."""
    return 200 - lows, 200 - highs, 200 - closes, 100 - rsi, atr, 200 - tr


def _only(divs, side):
    out = [d for d in divs if d.side == side]
    assert len(out) == 1, divs
    return out[0]


# ----------------------------------------------------------------------------- classify (8 types)
@pytest.mark.parametrize("dp,dr,side,want", [
    (-1.0, 5.0, "bull", "Strong"), (0.2, 5.0, "bull", "Medium"), (-1.0, 1.0, "bull", "Weak"), (1.0, -5.0, "bull", "Hidden"),
    (1.0, -5.0, "bear", "Strong"), (-0.2, -5.0, "bear", "Medium"), (1.0, -1.0, "bear", "Weak"), (-1.0, 5.0, "bear", "Hidden"),
    (0.5, 2.1, "bull", "Medium"),   # 0.5 ATR is still "equal"
    (-0.51, 2.0, "bull", "Weak"),   # 2 RSI points is still "equal"
    (0.0, 0.0, "bull", None), (-1.0, -5.0, "bull", None), (1.0, 5.0, "bear", None), (1.0, 1.0, "bull", None),
])
def test_classify(dp, dr, side, want):
    assert rd.classify(dp, dr, side) == want


def test_find_pivots_three_bar_window_and_confirm_bar():
    v = np.array([5, 4, 3, 2, 3, 4, 5, 6, 5, 4, 1, 4, 5], dtype=float)
    assert rd.find_pivots(v, "bull").tolist() == [3]  # bar 10 has no 3 bars after it -> not confirmed yet
    assert rd.find_pivots(np.append(v, [6, 7]), "bull").tolist() == [3, 10]
    assert rd.find_pivots(v, "bear").tolist() == [7]


# ----------------------------------------------------------------------------- detect: regular
def test_strong_bull_trigger_stop_confirm():
    h, lo, c, rsi, atr, tr = _bull_case()
    d = _only(rd.detect(h, lo, c, rsi=rsi, atr=atr, trend=tr), "bull")
    assert (d.type, d.p1, d.p2, d.confirm) == ("Strong", 10, 20, 23)
    assert d.trigger_price == 108.0 and d.stop_price == 85.0
    assert (d.p1_price, d.p2_price, d.p1_rsi, d.p2_rsi) == (90.0, 85.0, 30.0, 35.0)
    assert d.regular


def test_strong_bear_is_the_mirror():
    h, lo, c, rsi, atr, tr = _mirror(*_bull_case())
    d = _only(rd.detect(h, lo, c, rsi=rsi, atr=atr, trend=tr), "bear")
    assert (d.type, d.p1, d.p2, d.confirm) == ("Strong", 10, 20, 23)
    assert d.trigger_price == 92.0 and d.stop_price == 115.0


@pytest.mark.parametrize("p2_low,r2,want", [(89.5, 35.0, "Medium"), (85.0, 31.0, "Weak")])
def test_medium_and_weak(p2_low, r2, want):
    for mirror in (False, True):
        case = _bull_case(p2_low=p2_low, r2=r2)
        if mirror:
            case = _mirror(*case)
        side = "bear" if mirror else "bull"
        assert _only(rd.detect(case[0], case[1], case[2], rsi=case[3], atr=case[4], trend=case[5]), side).type == want


def test_regular_zone_filters():
    # no RSI pivot below 40 -> no regular bull
    h, lo, c, rsi, atr, tr = _bull_case(r1=41.0, r2=46.0, mid_rsi=50.0)
    assert not [d for d in rd.detect(h, lo, c, rsi=rsi, atr=atr, trend=tr) if d.side == "bull"]
    # RSI above 60 between the lows -> no regular bull
    h, lo, c, rsi, atr, tr = _bull_case()
    rsi[15] = 61.0
    assert not [d for d in rd.detect(h, lo, c, rsi=rsi, atr=atr, trend=tr) if d.side == "bull"]
    rsi[15] = 60.0  # touching 60 is allowed
    assert _only(rd.detect(h, lo, c, rsi=rsi, atr=atr, trend=tr), "bull").type == "Strong"
    # bear mirror: RSI below 40 between the highs
    h, lo, c, rsi, atr, tr = _mirror(*_bull_case())
    rsi[15] = 39.0
    assert not [d for d in rd.detect(h, lo, c, rsi=rsi, atr=atr, trend=tr) if d.side == "bear"]


def test_pivot_gap_bounds():
    # gap 10 passes; stretch the series so the two lows are 4 or 61 bars apart -> nothing
    def series(gap):
        n = gap + 20
        lows = np.empty(n)
        a, b = 8, 8 + gap
        mid = (a + b) // 2
        for i in range(n):
            if i <= a:
                lows[i] = 90 + (a - i)
            elif i <= mid:
                lows[i] = 90 + (i - a) * (7 / max(1, mid - a))
            elif i <= b:
                lows[i] = 97 - (i - mid) * (12 / max(1, b - mid))
            else:
                lows[i] = 85 + (i - b)
        highs = lows + 3
        rsi = np.full(n, 45.0)
        rsi[a], rsi[b] = 30.0, 35.0
        return highs, lows, lows + 1, rsi, np.full(n, 2.0), np.full(n, 200.0)
    for gap, found in [(4, False), (5, True), (60, True), (61, False)]:
        h, lo, c, rsi, atr, tr = series(gap)
        bulls = [d for d in rd.detect(h, lo, c, rsi=rsi, atr=atr, trend=tr) if d.side == "bull"]
        assert bool(bulls) == found, gap


# ----------------------------------------------------------------------------- detect: hidden
def test_hidden_bull_needs_uptrend_and_rsi_below_50():
    # price higher low (90 -> 93), RSI lower low (45 -> 40), close above EMA50
    h, lo, c, rsi, atr, tr = _bull_case(p2_low=93.0, r1=45.0, r2=40.0, mid_rsi=55.0, trend=50.0)
    d = _only(rd.detect(h, lo, c, rsi=rsi, atr=atr, trend=tr), "bull")
    assert d.type == "Hidden" and not d.regular
    # below the EMA -> no hidden bull
    h, lo, c, rsi, atr, tr = _bull_case(p2_low=93.0, r1=45.0, r2=40.0, mid_rsi=55.0, trend=150.0)
    assert not [d for d in rd.detect(h, lo, c, rsi=rsi, atr=atr, trend=tr) if d.side == "bull"]
    # RSI at the 2nd low not below 50 -> no hidden bull
    h, lo, c, rsi, atr, tr = _bull_case(p2_low=93.0, r1=58.0, r2=52.0, mid_rsi=55.0, trend=50.0)
    assert not [d for d in rd.detect(h, lo, c, rsi=rsi, atr=atr, trend=tr) if d.side == "bull"]


def test_hidden_bear_mirror():
    h, lo, c, rsi, atr, tr = _mirror(*_bull_case(p2_low=93.0, r1=45.0, r2=40.0, mid_rsi=55.0, trend=50.0))
    assert _only(rd.detect(h, lo, c, rsi=rsi, atr=atr, trend=tr), "bear").type == "Hidden"


# ----------------------------------------------------------------------------- status
def test_status_watching_triggered_failed():
    h, lo, c, rsi, atr, tr = _bull_case()
    d = _only(rd.detect(h, lo, c, rsi=rsi, atr=atr, trend=tr), "bull")
    assert rd.status_as_of(d, c) == ("watching", None)  # closes never cross 108 or 85
    up = c.copy(); up[27] = 109.0
    assert rd.status_as_of(d, up) == ("triggered", 27)
    assert rd.status_as_of(d, up, end=27) == ("watching", None)  # as of the bar before
    down = c.copy(); down[25] = 84.0; down[27] = 109.0
    assert rd.status_as_of(d, down) == ("failed", 25)  # first event wins, terminal


def test_status_bear_mirror():
    h, lo, c, rsi, atr, tr = _mirror(*_bull_case())
    d = _only(rd.detect(h, lo, c, rsi=rsi, atr=atr, trend=tr), "bear")
    dn = c.copy(); dn[26] = 91.0
    assert rd.status_as_of(d, dn) == ("triggered", 26)
    up = c.copy(); up[26] = 116.0
    assert rd.status_as_of(d, up) == ("failed", 26)


def test_to_rows_contract_fields():
    h, lo, c, rsi, atr, tr = _bull_case()
    dates = list(pd.bdate_range("2026-01-01", periods=len(c)).date)
    rows = rd.to_rows([_only(rd.detect(h, lo, c, rsi=rsi, atr=atr, trend=tr), "bull")], dates, closes=c)
    r = rows[0]
    for k in ("side", "type", "p1_date", "p2_date", "p1_price", "p2_price", "p1_rsi", "p2_rsi", "confirm_date",
              "trigger_price", "stop_price", "status"):
        assert k in r
    assert r["confirm_date"] == dates[23] and r["status"] in rd.STATUSES


# ----------------------------------------------------------------------------- no look-ahead
def _random_bars(seed: int, n: int = 700) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ret = rng.normal(0, 0.018, n) + 0.004 * np.sin(np.arange(n) / 25)  # swings so all types show up
    close = 100 * np.exp(np.cumsum(ret))
    spread = np.abs(rng.normal(0, 0.012, n)) * close
    high = np.maximum(close, close * (1 + rng.normal(0, 0.004, n))) + spread
    low = np.minimum(close, close * (1 - rng.normal(0, 0.004, n))) - spread
    return pd.DataFrame({"high": high, "low": low, "close": close})


def _key(d: rd.Divergence):
    return (d.side, d.type, d.p1, d.p2, d.confirm, round(d.trigger_price, 9), round(d.stop_price, 9),
            round(d.p1_rsi, 9), round(d.p2_rsi, 9))


@pytest.mark.parametrize("seed", [1, 7, 42])
def test_no_look_ahead_appending_bars_never_changes_the_past(seed):
    bars = _random_bars(seed)
    full = rd.detect(bars.high, bars.low, bars.close)
    assert full, "fixture should produce divergences"
    bull_f, bear_f, typ_f = rd.confirm_flags(bars.high, bars.low, bars.close)
    for t in (60, 150, 299, 300, 301, 450, 601, len(bars) - 2):
        cut = bars.iloc[: t + 1]
        part = rd.detect(cut.high, cut.low, cut.close)
        # 1. results known on date T are exactly the full-history results confirmed by T
        assert [_key(d) for d in part] == [_key(d) for d in full if d.confirm <= t]
        # 2. nothing is ever "known" before its confirm bar = 2nd pivot + 3 bars
        assert all(d.confirm == d.p2 + rd.PIVOT_K and d.confirm <= t for d in part)
        # 3. per-bar pipeline flags for bars <= T are unchanged by later bars
        b, s, ty = rd.confirm_flags(cut.high, cut.low, cut.close)
        assert np.array_equal(b, bull_f[: t + 1]) and np.array_equal(s, bear_f[: t + 1])
        assert list(ty) == list(typ_f[: t + 1])
        # 4. status as of T uses only closes <= T
        for d in part:
            assert rd.status_as_of(d, cut.close.to_numpy()) == rd.status_as_of(d, bars.close.to_numpy(), end=t + 1)


def test_random_series_covers_all_eight_types():
    seen = set()
    for seed in range(1, 30):
        bars = _random_bars(seed)
        seen |= {(d.side, d.type) for d in rd.detect(bars.high, bars.low, bars.close)}
    assert seen == {(s, t) for s in rd.SIDES for t in rd.TYPES}


def test_short_series_is_empty():
    assert rd.detect([1, 2, 3], [0, 1, 2], [1, 2, 3]) == []
    b, s, t = rd.confirm_flags([1, 2, 3], [0, 1, 2], [1, 2, 3])
    assert not b.any() and not s.any() and all(x is None for x in t)
