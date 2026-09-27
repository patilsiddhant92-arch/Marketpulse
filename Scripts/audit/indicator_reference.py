"""Independent reference implementation of the MarketPulse indicators (audit 2026-09-27).

Deliberately does NOT import any production indicator / predicate code (Scripts.indicators,
build_database, darvas_squeeze, minervini_geometry, derived.*). Everything is written from the
textbook / documented definitions with plain numpy loops, so an agreement with the stored
values is independent evidence, not the same code run twice.

Inputs are adjusted OHLCV from ``prices_daily`` via ``COALESCE(adj_*, raw)`` (spec §4: all
indicators use split/bonus-adjusted prices).

Conventions reproduced (and where they differ from a textbook, the textbook variant is also
available so the audit can report the size of the convention effect):

* EMA: recursive ``y_t = a*x_t + (1-a)*y_{t-1}``, a = 2/(span+1), seeded with the FIRST close
  (``seed="first"``; pandas ``ewm(adjust=False)``), value hidden until ``span`` bars exist.
  Textbook alternative ``seed="sma"``: seed = SMA of the first ``span`` closes.
* RSI(14) Wilder: RMA of gains / losses, a = 1/14, seeded with the first 1-bar change
  (``seed="first"``) or with the SMA of the first 14 changes (``seed="sma"``, Wilder 1978).
* ATR(14) "SMA ATR": simple mean of true range over 14 bars (min 5 bars); ATR Wilder = RMA.
* ADR(20)%: mean of (high/low - 1)*100 over 20 bars (min 5).
* RVOL: volume / mean(volume of the 20 PRECEDING bars) (min 5).
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

ADJ_SELECT = """
    SELECT symbol, trade_date, series,
           COALESCE(adj_open_price, open_price)   AS o,
           COALESCE(adj_high_price, high_price)   AS h,
           COALESCE(adj_low_price, low_price)     AS l,
           COALESCE(adj_close_price, close_price) AS c,
           COALESCE(adj_prev_close, prev_close)   AS pc,
           COALESCE(adj_volume, volume)           AS v,
           COALESCE(adj_delivery_qty, delivery_qty) AS dq,
           delivery_pct AS dp, turnover_cr AS to_cr, turnover_lacs AS to_lacs, trades,
           COALESCE(adj_avg_price, avg_price) AS avgp, price_factor
    FROM prices_daily
"""


def load_adjusted(con, symbols: Iterable[str], until=None) -> pd.DataFrame:
    """Adjusted OHLCV for `symbols` (optionally truncated at `until`), ordered by symbol, date."""
    syms = sorted(set(symbols))
    con.register("_ref_syms", pd.DataFrame({"symbol": syms}))
    try:
        where = "WHERE symbol IN (SELECT symbol FROM _ref_syms)"
        params: list = []
        if until is not None:
            where += " AND trade_date <= ?"
            params.append(pd.Timestamp(until))
        df = con.execute(f"{ADJ_SELECT} {where} ORDER BY symbol, trade_date", params).fetchdf()
    finally:
        con.unregister("_ref_syms")
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df


# ------------------------------------------------------------------------------------------
# Moving averages / oscillators (numpy loops, no pandas ewm/rolling)
# ------------------------------------------------------------------------------------------
def ema(x: np.ndarray, span: int, seed: str = "first") -> np.ndarray:
    x = np.asarray(x, dtype=float)
    n = len(x)
    out = np.full(n, np.nan)
    if n == 0:
        return out
    a = 2.0 / (span + 1.0)
    if seed == "first":
        y = x[0]
        for i in range(n):
            if i > 0:
                y = a * x[i] + (1 - a) * y
            if i >= span - 1:
                out[i] = y
    elif seed == "sma":
        if n < span:
            return out
        y = float(np.mean(x[:span]))
        out[span - 1] = y
        for i in range(span, n):
            y = a * x[i] + (1 - a) * y
            out[i] = y
    else:
        raise ValueError(seed)
    return out


def sma(x: np.ndarray, window: int, min_periods: int | None = None) -> np.ndarray:
    """Mean of the last `window` non-NaN-or-NaN values; NaNs are skipped, need >= min_periods."""
    x = np.asarray(x, dtype=float)
    mp = window if min_periods is None else min_periods
    out = np.full(len(x), np.nan)
    for i in range(len(x)):
        w = x[max(0, i - window + 1): i + 1]
        w = w[np.isfinite(w)]
        if len(w) >= mp:
            out[i] = w.sum() / len(w)
    return out


def rolling_max(x: np.ndarray, window: int, min_periods: int) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    for i in range(len(x)):
        w = x[max(0, i - window + 1): i + 1]
        w = w[np.isfinite(w)]
        if len(w) >= min_periods:
            out[i] = w.max()
    return out


def rolling_min(x: np.ndarray, window: int, min_periods: int) -> np.ndarray:
    return -rolling_max(-np.asarray(x, dtype=float), window, min_periods)


def rma(x: np.ndarray, period: int, seed: str = "first") -> np.ndarray:
    """Wilder's running moving average over the finite tail of `x` (leading NaNs skipped)."""
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    finite = np.flatnonzero(np.isfinite(x))
    if len(finite) == 0:
        return out
    s = finite[0]
    a = 1.0 / period
    if seed == "first":
        y = x[s]
        for k, i in enumerate(range(s, len(x))):
            if k > 0:
                y = a * x[i] + (1 - a) * y
            if k >= period - 1:
                out[i] = y
    else:
        if len(x) - s < period:
            return out
        y = float(np.mean(x[s:s + period]))
        out[s + period - 1] = y
        for i in range(s + period, len(x)):
            y = a * x[i] + (1 - a) * y
            out[i] = y
    return out


def rsi_wilder(close: np.ndarray, period: int = 14, seed: str = "first") -> np.ndarray:
    c = np.asarray(close, dtype=float)
    d = np.r_[np.nan, np.diff(c)]
    gain = np.where(np.isfinite(d), np.maximum(d, 0.0), np.nan)
    loss = np.where(np.isfinite(d), np.maximum(-d, 0.0), np.nan)
    ag, al = rma(gain, period, seed), rma(loss, period, seed)
    out = np.full(len(c), np.nan)
    ok = np.isfinite(ag) & np.isfinite(al)
    with np.errstate(divide="ignore", invalid="ignore"):
        out[ok] = 100.0 - 100.0 / (1.0 + ag[ok] / al[ok])
    out[ok & (al == 0)] = 100.0
    out[ok & (ag == 0) & (al > 0)] = 0.0
    return out


def true_range(h: np.ndarray, l: np.ndarray, c: np.ndarray) -> np.ndarray:
    pc = np.r_[np.nan, np.asarray(c, dtype=float)[:-1]]
    tr = np.asarray(h, dtype=float) - np.asarray(l, dtype=float)
    with np.errstate(invalid="ignore"):
        tr = np.fmax(tr, np.abs(h - pc))
        tr = np.fmax(tr, np.abs(l - pc))
    return tr


def adr_pct(h: np.ndarray, l: np.ndarray, window: int = 20) -> np.ndarray:
    l = np.where(np.asarray(l, dtype=float) == 0, np.nan, l)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.maximum((np.asarray(h, dtype=float) / l - 1.0) * 100.0, 0.0)
    return sma(r, window, 5)


def rvol(v: np.ndarray, window: int = 20) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    prior = sma(np.r_[np.nan, v[:-1]], window, 5)
    with np.errstate(invalid="ignore", divide="ignore"):
        return v / prior


def pct_return(c: np.ndarray, n: int) -> np.ndarray:
    c = np.asarray(c, dtype=float)
    out = np.full(len(c), np.nan)
    if len(c) > n:
        out[n:] = (c[n:] / c[:-n] - 1.0) * 100.0
    return out


def shift(x: np.ndarray, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    if n < len(x):
        out[n:] = x[:len(x) - n]
    return out


# ------------------------------------------------------------------------------------------
# Patterns
# ------------------------------------------------------------------------------------------
def nr7_textbook(h: np.ndarray, l: np.ndarray) -> np.ndarray:
    """Today's range is the narrowest (<=) of the last 7 bars, zero-range bars included."""
    r = np.asarray(h, dtype=float) - np.asarray(l, dtype=float)
    out = np.zeros(len(r), dtype=bool)
    for i in range(6, len(r)):
        out[i] = r[i] <= np.min(r[i - 6:i + 1])
    return out


def nr7_zero_range_excluded(h: np.ndarray, l: np.ndarray) -> np.ndarray:
    """Documented production convention: zero-range (locked) bars are 'no range', so a window
    holding one is not evaluated and a zero-range bar is never NR7."""
    r = np.asarray(h, dtype=float) - np.asarray(l, dtype=float)
    r = np.where(r == 0, np.nan, r)
    out = np.zeros(len(r), dtype=bool)
    for i in range(6, len(r)):
        w = r[i - 6:i + 1]
        if np.all(np.isfinite(w)):
            out[i] = r[i] == np.min(w)
    return out


def inside_bar(h: np.ndarray, l: np.ndarray) -> np.ndarray:
    h = np.asarray(h, dtype=float)
    l = np.asarray(l, dtype=float)
    out = np.zeros(len(h), dtype=bool)
    out[1:] = (h[1:] < h[:-1]) & (l[1:] > l[:-1])
    return out


def darvas_box_pine(high: np.ndarray, low: np.ndarray, boxp: int = 5) -> tuple[np.ndarray, np.ndarray]:
    """TradingView Pine Darvas box, transcribed literally with explicit bar-by-bar series.

        LL = lowest(low, boxp); k1 = highest(high, boxp); k2 = highest(high, boxp-1)
        k3 = highest(high, boxp-2); NH = valuewhen(high > k1[1], high, 0); box1 = k3 < k2
        cond = barssince(high > k1[1]) == boxp-2 and box1
        TopBox = valuewhen(cond, NH, 0); BottomBox = valuewhen(cond, LL, 0)

    `na` comparisons are false (Pine semantics); barssince is na until the first event.
    """
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    n = len(h)

    def highest(x, k, i):
        return np.max(x[i - k + 1:i + 1]) if i >= k - 1 else np.nan

    top = np.full(n, np.nan)
    bot = np.full(n, np.nan)
    nh = np.nan
    last_event = None
    cur_t = cur_b = np.nan
    for i in range(n):
        k1_prev = highest(h, boxp, i - 1) if i >= 1 else np.nan
        event = bool(np.isfinite(k1_prev) and h[i] > k1_prev)
        if event:
            nh = h[i]
            last_event = i
        barssince = (i - last_event) if last_event is not None else None
        k2 = highest(h, boxp - 1, i)
        k3 = highest(h, boxp - 2, i)
        box1 = bool(np.isfinite(k2) and np.isfinite(k3) and k3 < k2)
        if barssince == boxp - 2 and box1:
            cur_t = nh
            ll = np.min(l[i - boxp + 1:i + 1]) if i >= boxp - 1 else np.nan
            cur_b = ll
        top[i], bot[i] = cur_t, cur_b
    return top, bot


# ------------------------------------------------------------------------------------------
# Higher timeframe
# ------------------------------------------------------------------------------------------
def weekly_rsi_on_days(dates: pd.Series, close: np.ndarray, period: int = 14) -> np.ndarray:
    """Weekly RSI (weeks ending Friday, last close of the week) visible on each daily row:
    the latest week whose Friday label is <= the row date (a week counts once its Friday is
    reached; Mon-Thu rows see the previous week)."""
    d = pd.to_datetime(pd.Series(dates)).reset_index(drop=True)
    friday = d + pd.to_timedelta((4 - d.dt.weekday) % 7, unit="D")
    wk = pd.DataFrame({"friday": friday, "c": np.asarray(close, dtype=float)})
    last = wk.groupby("friday", sort=True)["c"].last()
    w_rsi = rsi_wilder(last.to_numpy(), period, "first")
    fridays = last.index.to_numpy()
    pos = np.searchsorted(fridays, d.to_numpy(), side="right") - 1
    out = np.full(len(d), np.nan)
    ok = pos >= 0
    out[ok] = w_rsi[pos[ok]]
    return out


# ------------------------------------------------------------------------------------------
# One symbol: every reference column
# ------------------------------------------------------------------------------------------
def compute_symbol(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("trade_date").reset_index(drop=True)
    o, h, l, c, v = (g[k].to_numpy(dtype=float) for k in ("o", "h", "l", "c", "v"))
    out = pd.DataFrame({"symbol": g["symbol"], "trade_date": g["trade_date"]})
    for span in (10, 20, 50, 200):
        out[f"ema_{span}"] = ema(c, span, "first")
        out[f"ema_{span}_smaseed"] = ema(c, span, "sma")
    out["ema_100"] = ema(c, 100, "first")
    out["ema_150"] = ema(c, 150, "first")
    for w in (50, 150, 200):
        out[f"sma_{w}"] = sma(c, w)
    out["sma_200_rising"] = out["sma_200"].to_numpy() > shift(out["sma_200"].to_numpy(), 20)
    out["rsi_14"] = rsi_wilder(c, 14, "first")
    out["rsi_14_textbook"] = rsi_wilder(c, 14, "sma")
    tr = true_range(h, l, c)
    out["true_range"] = tr
    out["atr_14"] = sma(tr, 14, 5)
    out["atr_14_wilder"] = rma(tr, 14, "first")
    with np.errstate(invalid="ignore", divide="ignore"):
        out["atr_pct"] = out["atr_14"].to_numpy() / c * 100
    out["adr_20_pct"] = adr_pct(h, l, 20)
    out["change_1d_pct"] = pct_return(c, 1)
    out["return_5d_pct"] = pct_return(c, 5)
    out["return_1m_pct"] = pct_return(c, 21)
    out["return_3m_pct"] = pct_return(c, 63)
    out["return_6m_pct"] = pct_return(c, 126)
    out["rvol"] = rvol(v, 20)
    out["avg_volume_20d"] = sma(v, 20, 5)
    out["avg_delivery_pct_20d"] = sma(g["dp"].to_numpy(dtype=float), 20, 5)
    dq = g["dq"].to_numpy(dtype=float)
    out["avg_delivery_qty_20d"] = sma(dq, 20, 5)
    with np.errstate(invalid="ignore"):
        out["delivery_spike"] = dq > 2 * out["avg_delivery_qty_20d"].to_numpy()
        out["price_up_delivery_up"] = (c > shift(c, 1)) & (dq > out["avg_delivery_qty_20d"].to_numpy())
    out["avg_traded_value_cr_20d"] = sma(g["to_cr"].to_numpy(dtype=float), 20, 5)
    out["turnover_cr_from_lacs"] = g["to_lacs"].to_numpy(dtype=float) / 100.0
    out["high_252d"] = rolling_max(h, 252, 3)
    out["low_252d"] = rolling_min(l, 252, 3)
    out["high_20d"] = rolling_max(h, 20, 3)
    out["new_20d_high"] = c >= shift(out["high_20d"].to_numpy(), 1)
    out["nr7_textbook"] = nr7_textbook(h, l)
    out["nr7"] = nr7_zero_range_excluded(h, l)
    out["inside_bar"] = inside_bar(h, l)
    out["rsi_14_w"] = weekly_rsi_on_days(g["trade_date"], c, 14)
    with np.errstate(invalid="ignore", divide="ignore"):
        out["away_10ema_pct"] = (c / out["ema_10"].to_numpy() - 1) * 100
    top, bot = darvas_box_pine(h, l, 5)
    out["darvas_top"] = top
    out["darvas_bottom"] = bot
    out["close"] = c
    out["high"] = h
    out["low"] = l
    out["open"] = o
    out["volume"] = v
    return out


def average_rank_pct(values: np.ndarray) -> np.ndarray:
    """Percentile rank = average 1-based rank among finite values / count * 100 (ties averaged)."""
    x = np.asarray(values, dtype=float)
    out = np.full(len(x), np.nan)
    idx = np.flatnonzero(np.isfinite(x))
    if len(idx) == 0:
        return out
    vals = x[idx]
    order = np.argsort(vals, kind="mergesort")
    sorted_vals = vals[order]
    ranks = np.empty(len(vals))
    i = 0
    while i < len(vals):
        j = i
        while j + 1 < len(vals) and sorted_vals[j + 1] == sorted_vals[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    out[idx] = ranks / len(vals) * 100.0
    return out


RS_SCORE_SQL = """
    WITH p AS (
        SELECT symbol, trade_date, COALESCE(adj_close_price, close_price) AS c
        FROM prices_daily
    ), l AS (
        SELECT symbol, trade_date, c,
               lag(c, 63)  OVER w AS c63, lag(c, 126) OVER w AS c126,
               lag(c, 189) OVER w AS c189, lag(c, 252) OVER w AS c252
        FROM p WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
    )
    SELECT symbol, trade_date,
           0.40 * (c / c63 - 1) + 0.20 * (c63 / c126 - 1) + 0.20 * (c126 / c189 - 1) + 0.20 * (c189 / c252 - 1)
               AS rs_score
    FROM l WHERE trade_date IN (SELECT d FROM _rs_dates)
"""


def rs_percentile_for_dates(con, dates: Iterable) -> pd.DataFrame:
    """Documented RS: 40/20/20/20 weighted non-overlapping quarterly (63-session) returns over the
    symbol's own sessions, NULL without 252 prior sessions, ranked 0-100 across every symbol with
    a score that day (average rank / count)."""
    con.register("_rs_dates", pd.DataFrame({"d": pd.to_datetime(list(dates))}))
    try:
        df = con.execute(RS_SCORE_SQL).fetchdf()
    finally:
        con.unregister("_rs_dates")
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["rs_percentile_ref"] = np.nan
    for d, idx in df.groupby("trade_date").groups.items():
        df.loc[idx, "rs_percentile_ref"] = average_rank_pct(df.loc[idx, "rs_score"].to_numpy())
    return df


def trend_template(close, sma50, sma150, sma200, sma200_rising, away_52w_low_pct, dist_below_52w_high, rs) -> tuple:
    """Minervini 8 criteria (count, all-pass). NaN inputs fail their criterion."""
    with np.errstate(invalid="ignore"):
        checks = [
            (close > sma150) & (close > sma200),
            sma150 > sma200,
            np.asarray(sma200_rising, dtype=bool),
            (sma50 > sma150) & (sma50 > sma200),
            close > sma50,
            away_52w_low_pct >= 30,
            dist_below_52w_high <= 25,
            rs >= 70,
        ]
    n = np.sum([np.asarray(ch, dtype=bool) for ch in checks], axis=0)
    return n, n == 8


def detect_contractions_ref(high: np.ndarray, low: np.ndarray, min_bars: int = 8, min_depth: float = 3.0):
    """Independent transcription of the documented VCP 'successive T' rule (desk docstring /
    minervini_geometry doc): swing highs/lows are strict 2-left/2-right fractals; the base starts
    at the last swing high that is >= 20% above the preceding swing low (else the last swing
    high); each swing-high -> deepest swing-low -> next swing-high leg of >= min_bars bars and
    >= min_depth % depth is a T; depths must strictly shrink (an expanding T ends the sequence);
    at most 4 Ts. Returns (depths, pivot, stop)."""
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    n = len(h)
    if n < 30:
        return [], None, None

    def fractal(x, kind):
        idx = []
        for i in range(2, n - 2):
            w = x[i - 2:i + 3]
            ext = w.max() if kind == "high" else w.min()
            if x[i] == ext and np.sum(w == x[i]) == 1:
                idx.append(i)
        return idx

    peaks, troughs = fractal(h, "high"), fractal(l, "low")
    if len(peaks) < 2 or len(troughs) < 1:
        return [], None, None
    base = None
    for p in reversed(peaks):
        prior = [t for t in troughs if t < p]
        if prior and h[p] / l[prior[-1]] - 1 >= 0.20:
            base = p
            break
    if base is None:
        base = peaks[-1]
    later = [p for p in peaks if p >= base]
    depths, last = [], None
    prev = np.inf
    for a, b in zip(later[:-1], later[1:]):
        mids = [t for t in troughs if a < t < b]
        if not mids or b - a < min_bars:
            continue
        t = min(mids, key=lambda j: l[j])
        if h[a] <= 0:
            continue
        dep = (h[a] - l[t]) / h[a] * 100
        if dep < min_depth:
            continue
        if dep >= prev:
            break
        depths.append(dep)
        last = (h[a], l[t])
        prev = dep
        if len(depths) >= 4:
            break
    if not depths:
        return [], None, None
    return depths, last[0], last[1]
