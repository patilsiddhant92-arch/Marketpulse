"""RSI(14) divergence engine: 8 types (Strong / Medium / Weak / Hidden x bull / bear).

Canonical module (pure: pandas + numpy, no DB). The EOD pipeline (Scripts/build_database.py)
and the API (App/services/divergence.py via App/indicators/rsi_divergence.py) both call it,
so a flag in indicators_daily and a row on the chart always agree.

Rules (HarkPro/12-sprint2-plan.md "Divergence API contract", prototype
HarkPro/tools/divergence/detect_prototype.py):

* Pivots: 3-bar pivots on the LOW (bull) / HIGH (bear): bar i is a pivot when its low (high) is
  the min (max) of bars i-3 .. i+3. A pivot is CONFIRMED on bar i+3 (its close) - nothing is
  known about it earlier, so a divergence exists only from its ``confirm`` bar on (no look-ahead).
* Pairs: two consecutive pivots of the same side, 5-60 bars apart.
* "Equal": price within 0.5 x ATR(14, Wilder, at the 2nd pivot); RSI within 2 points.
* Types (bull; bear mirrors every inequality):
    Strong  price lower low,  RSI higher low
    Medium  price equal low,  RSI higher low
    Weak    price lower low,  RSI equal low
    Hidden  price higher low, RSI lower low
* Zone filter (regular = Strong/Medium/Weak): bull needs an RSI pivot < 40 and RSI never > 60
  between the pivots (inclusive); bear needs an RSI pivot > 60 and RSI never < 40 between.
* Hidden trend filter: bull needs close > EMA50 and RSI < 50 at the 2nd pivot; bear needs
  close < EMA50 and RSI > 50.
* Trigger: bull = the highest high between the two lows (inclusive); bear = the lowest low
  between the two highs. Stop: bull = the 2nd pivot's low; bear = the 2nd pivot's high.
* Status as of a date: walking the closes after the 2nd pivot up to the date, the first close
  beyond the trigger -> "triggered", the first close beyond the stop -> "failed"; neither ->
  "watching". Both are terminal. (Closes, as in the prototype; a close cannot beat the stop
  before the confirm bar because the pivot is the window extreme.)

Works on any bar series: daily, or W/M bars resampled from adjusted daily prices.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

try:
    from Scripts.indicators import atr_wilder, ema, rsi_wilder
except (ModuleNotFoundError, ImportError):  # Scripts/ on sys.path (pipeline entry points)
    from indicators import atr_wilder, ema, rsi_wilder  # type: ignore

PIVOT_K = 3
MIN_GAP = 5
MAX_GAP = 60
PRICE_TOL_ATR = 0.5
RSI_TOL = 2.0
RSI_LOW = 40.0
RSI_HIGH = 60.0
HIDDEN_RSI = 50.0
RSI_PERIOD = 14
ATR_PERIOD = 14
TREND_EMA = 50

SIDES = ("bull", "bear")
TYPES = ("Strong", "Medium", "Weak", "Hidden")
REGULAR = ("Strong", "Medium", "Weak")
STATUSES = ("watching", "triggered", "failed")


@dataclass(frozen=True)
class Divergence:
    side: str            # bull | bear
    type: str            # Strong | Medium | Weak | Hidden
    p1: int              # bar index of the 1st pivot
    p2: int              # bar index of the 2nd pivot
    confirm: int         # bar index on which the divergence becomes known (p2 + 3)
    p1_price: float      # low (bull) / high (bear) at the pivots
    p2_price: float
    p1_rsi: float
    p2_rsi: float
    trigger_price: float
    stop_price: float

    @property
    def regular(self) -> bool:
        return self.type in REGULAR


# ------------------------------------------------------------------------------------- inputs
def indicator_inputs(high: pd.Series, low: pd.Series, close: pd.Series) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """RSI(14) Wilder on close, ATR(14) Wilder, EMA50 on close - the same functions as the
    pipeline's rsi_14 / atr_14_wilder / ema_50 columns."""
    high = pd.Series(np.asarray(high, dtype=float))
    low = pd.Series(np.asarray(low, dtype=float))
    close = pd.Series(np.asarray(close, dtype=float))
    rsi = rsi_wilder(close, RSI_PERIOD).to_numpy(dtype=float)
    atr = atr_wilder(high, low, close, ATR_PERIOD).to_numpy(dtype=float)
    trend = ema(close, TREND_EMA).to_numpy(dtype=float)
    return rsi, atr, trend


def find_pivots(values: np.ndarray, side: str, k: int = PIVOT_K) -> np.ndarray:
    """Indices i (k <= i < n-k) whose value is the min (bull) / max (bear) of i-k .. i+k.
    Only pivots whose confirm bar i+k exists in ``values`` are returned."""
    v = np.asarray(values, dtype=float)
    n = len(v)
    if n < 2 * k + 1:
        return np.empty(0, dtype=int)
    windows = np.lib.stride_tricks.sliding_window_view(v, 2 * k + 1)  # window j is centred on j+k
    centre = v[k:n - k]
    ext = np.nanmin(windows, axis=1) if side == "bull" else np.nanmax(windows, axis=1)
    ok = (centre == ext) & ~np.isnan(centre)
    return np.flatnonzero(ok) + k


def classify(dp_atr: float, dr: float, side: str) -> str | None:
    """dp_atr = (price2 - price1) / ATR; dr = rsi2 - rsi1. Returns the type or None."""
    p_eq = abs(dp_atr) <= PRICE_TOL_ATR
    r_eq = abs(dr) <= RSI_TOL
    if side == "bull":
        if dp_atr < -PRICE_TOL_ATR and dr > RSI_TOL:
            return "Strong"
        if p_eq and dr > RSI_TOL:
            return "Medium"
        if dp_atr < -PRICE_TOL_ATR and r_eq:
            return "Weak"
        if dp_atr > PRICE_TOL_ATR and dr < -RSI_TOL:
            return "Hidden"
    else:
        if dp_atr > PRICE_TOL_ATR and dr < -RSI_TOL:
            return "Strong"
        if p_eq and dr < -RSI_TOL:
            return "Medium"
        if dp_atr > PRICE_TOL_ATR and r_eq:
            return "Weak"
        if dp_atr < -PRICE_TOL_ATR and dr > RSI_TOL:
            return "Hidden"
    return None


# ------------------------------------------------------------------------------------- detect
def detect(high: Sequence[float], low: Sequence[float], close: Sequence[float], *,
           rsi: np.ndarray | None = None, atr: np.ndarray | None = None,
           trend: np.ndarray | None = None) -> list[Divergence]:
    """Every divergence whose confirm bar lies inside the series, oldest confirm first.

    Causal by construction: the type, trigger and stop of a divergence use bars <= its 2nd
    pivot, and the pivot itself needs bars <= confirm. Appending bars never changes or removes
    a divergence already returned (the indicators are recursive, so their past values are
    fixed). Precomputed ``rsi`` / ``atr`` / ``trend`` (EMA50) arrays may be passed.
    """
    h = np.asarray(high, dtype=float)
    lo = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)
    n = len(c)
    if n < 2 * PIVOT_K + 1 + MIN_GAP:
        return []
    if rsi is None or atr is None or trend is None:
        r0, a0, t0 = indicator_inputs(pd.Series(h), pd.Series(lo), pd.Series(c))
        rsi = r0 if rsi is None else np.asarray(rsi, dtype=float)
        atr = a0 if atr is None else np.asarray(atr, dtype=float)
        trend = t0 if trend is None else np.asarray(trend, dtype=float)
    else:
        rsi, atr, trend = (np.asarray(x, dtype=float) for x in (rsi, atr, trend))

    out: list[Divergence] = []
    for side in SIDES:
        src = lo if side == "bull" else h
        piv = find_pivots(src, side)
        for a, b in zip(piv[:-1], piv[1:]):
            gap = int(b - a)
            if gap < MIN_GAP or gap > MAX_GAP:
                continue
            r1, r2, atr_b = rsi[a], rsi[b], atr[b]
            if not (np.isfinite(r1) and np.isfinite(r2) and np.isfinite(atr_b)) or atr_b <= 0:
                continue
            kind = classify((src[b] - src[a]) / atr_b, r2 - r1, side)
            if kind is None:
                continue
            if kind != "Hidden":
                mid = rsi[a:b + 1]
                if np.isnan(mid).any():
                    continue
                if side == "bull" and (min(r1, r2) >= RSI_LOW or mid.max() > RSI_HIGH):
                    continue
                if side == "bear" and (max(r1, r2) <= RSI_HIGH or mid.min() < RSI_LOW):
                    continue
            else:
                ema_b = trend[b]
                if not np.isfinite(ema_b):
                    continue
                if side == "bull" and not (c[b] > ema_b and r2 < HIDDEN_RSI):
                    continue
                if side == "bear" and not (c[b] < ema_b and r2 > HIDDEN_RSI):
                    continue
            trig = float(np.nanmax(h[a:b + 1])) if side == "bull" else float(np.nanmin(lo[a:b + 1]))
            out.append(Divergence(
                side=side, type=kind, p1=int(a), p2=int(b), confirm=int(b + PIVOT_K),
                p1_price=float(src[a]), p2_price=float(src[b]), p1_rsi=float(r1), p2_rsi=float(r2),
                trigger_price=trig, stop_price=float(src[b]),
            ))
    out.sort(key=lambda d: (d.confirm, d.p2, d.side, TYPES.index(d.type)))
    return out


def status_as_of(div: Divergence, closes: Sequence[float], start: int | None = None, end: int | None = None) -> tuple[str, int | None]:
    """(status, bar index of the deciding close) walking ``closes[start:end]``.

    By default the walk covers the bars after the 2nd pivot of the same series up to its end;
    pass another close series (e.g. daily closes for a W/M divergence) with ``start`` / ``end``
    set to the bars after the 2nd pivot's period and up to the as-of date.
    """
    cl = np.asarray(closes, dtype=float)
    s = div.p2 + 1 if start is None else int(start)
    e = len(cl) if end is None else int(end)
    seg = cl[s:e]
    if seg.size == 0:
        return "watching", None
    if div.side == "bull":
        hit_t = seg > div.trigger_price
        hit_f = seg < div.stop_price
    else:
        hit_t = seg < div.trigger_price
        hit_f = seg > div.stop_price
    it = int(np.argmax(hit_t)) if hit_t.any() else None
    jf = int(np.argmax(hit_f)) if hit_f.any() else None
    if it is None and jf is None:
        return "watching", None
    if jf is None or (it is not None and it <= jf):
        return "triggered", s + it  # type: ignore[operator]
    return "failed", s + jf


# ------------------------------------------------------------------------------------- pipeline flags
def type_label(div: Divergence) -> str:
    return f"{div.type} {div.side}"


def confirm_flags(high: Sequence[float], low: Sequence[float], close: Sequence[float], *,
                  rsi: np.ndarray | None = None, atr: np.ndarray | None = None,
                  trend: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per bar: (regular bull confirmed on this bar, regular bear confirmed on this bar,
    type label of every divergence - incl. Hidden - confirmed on this bar, ', '-joined, else None).
    Causal: bar t's values depend only on bars <= t."""
    n = len(close)
    bull = np.zeros(n, dtype=bool)
    bear = np.zeros(n, dtype=bool)
    labels: list[list[str]] = [[] for _ in range(n)]
    for d in detect(high, low, close, rsi=rsi, atr=atr, trend=trend):
        if d.regular:
            (bull if d.side == "bull" else bear)[d.confirm] = True
        labels[d.confirm].append(type_label(d))
    typ = np.array([", ".join(x) if x else None for x in labels], dtype=object)
    return bull, bear, typ


# ------------------------------------------------------------------------------------- API rows
def to_rows(divs: Iterable[Divergence], dates: Sequence[Any], *, closes: Sequence[float] | None = None,
            status_closes: Sequence[float] | None = None, status_dates: Sequence[Any] | None = None,
            ndigits: int = 2) -> list[dict[str, Any]]:
    """Contract rows. Status walks ``closes`` (the bar series) unless ``status_closes`` /
    ``status_dates`` (e.g. daily closes for W/M bars) are given: then the walk starts on the
    first status bar after the 2nd pivot's bar date."""
    dates = list(dates)
    out = []
    sd = None
    if status_closes is not None and status_dates is not None:
        sd = pd.DatetimeIndex(pd.to_datetime(list(status_dates)))
        status_closes = np.asarray(status_closes, dtype=float)
    for d in divs:
        if sd is not None:
            start = int(sd.searchsorted(pd.Timestamp(dates[d.p2]), side="right"))
            st, at = status_as_of(d, status_closes, start=start)  # type: ignore[arg-type]
            st_date = status_dates[at] if at is not None else None
        else:
            st, at = status_as_of(d, closes if closes is not None else [])
            st_date = dates[at] if at is not None else None
        out.append({
            "side": d.side, "type": d.type,
            "p1_date": dates[d.p1], "p2_date": dates[d.p2],
            "p1_price": round(d.p1_price, ndigits), "p2_price": round(d.p2_price, ndigits),
            "p1_rsi": round(d.p1_rsi, 1), "p2_rsi": round(d.p2_rsi, 1),
            "confirm_date": dates[d.confirm],
            "trigger_price": round(d.trigger_price, ndigits), "stop_price": round(d.stop_price, ndigits),
            "status": st, "status_date": st_date, "bars_apart": d.p2 - d.p1,
        })
    return out


__all__ = [
    "Divergence", "PIVOT_K", "MIN_GAP", "MAX_GAP", "PRICE_TOL_ATR", "RSI_TOL", "RSI_LOW", "RSI_HIGH",
    "HIDDEN_RSI", "SIDES", "TYPES", "REGULAR", "STATUSES", "indicator_inputs", "find_pivots", "classify",
    "detect", "status_as_of", "type_label", "confirm_flags", "to_rows", "asdict",
]
