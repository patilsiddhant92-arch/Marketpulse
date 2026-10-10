"""Pure helpers for the Setups tab (HarkPro/06-tab2-setups.md, locked spec 2026-10-09).

No database access here, so every rule is unit-testable. The calculations are ported from the
locked mockup builder (HarkPro/tools/setups_mockup/extract.py); the screener maths itself stays in
setup_daily / Scripts.darvas_squeeze / App.services.momentum (unchanged).
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

import numpy as np

# Spec: Pulse -> Setups group state (Industry level, all stocks). Pulse owns the rule: App/services/group_state.py.
from App.services.group_state import CAUTION, FAVOUR, NEUTRAL, STATE_ORDER  # noqa: E402,F401
from App.services.group_state import rule as group_state  # noqa: E402,F401

QUEUE_TAG = {"darvas_squeeze": "SQZ", "darvas_10ema": "10E", "vcp": "VCP"}
QUEUE_NAME = {"darvas_squeeze": "Darvas Squeeze", "darvas_10ema": "Darvas 10 EMA", "vcp": "VCP", "momentum": "Momentum"}
SCREENERS = ("darvas_squeeze", "darvas_10ema", "vcp", "momentum")


def fnum(x: Any, nd: int | None = None) -> float | None:
    """Finite float (rounded) or None. NULL stays NULL."""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, nd) if nd is not None else f


# --------------------------------------------------------------------------- stock derivations
def delivery_streak(dp: Sequence[Any], dp20: Sequence[Any]) -> int:
    """Consecutive latest sessions with delivery % above the stock's own 20D average."""
    n = 0
    for a, b in zip(reversed(list(dp)), reversed(list(dp20))):
        a, b = fnum(a), fnum(b)
        if a is None or b is None or a <= b:
            break
        n += 1
    return n


def turnover_multiples(tov: Sequence[Any]) -> dict[str, float | None]:
    """Turnover 1D / 1W (5D avg) / 1M (21D avg) as a multiple of the stock's own 3M (63D) average."""
    vals = [fnum(v) for v in tov]
    w63 = [v for v in vals[-63:] if v is not None]
    base = sum(w63) / len(w63) if len(w63) >= 20 else None

    def mult(k: int) -> float | None:
        w = [v for v in vals[-k:] if v is not None]
        if not base or len(w) < k:
            return None
        return round(sum(w) / len(w) / base, 2)

    return {"1d": mult(1), "1w": mult(5), "1m": mult(21)}


def ten_ema_tag(flavor: str | None, low: Any, ema10: Any) -> tuple[str, str, int | None]:
    """Darvas 10 EMA case + tier. Retrace = Pullback + Trace-back, Catch-up = Catch-up.
    T1 = whole bar above the 10 EMA (low >= 10 EMA); T2 = the wick undercuts it."""
    case = "Catch-up" if (flavor or "").lower().startswith("catch") else "Retrace"
    lo, e = fnum(low), fnum(ema10)
    tier = None if lo is None or e is None else (1 if lo >= e else 2)
    return case, f"10E {case} T{tier}" if tier else f"10E {case}", tier


def risk_pct(trigger: Any, stop: Any) -> float | None:
    t, s = fnum(trigger), fnum(stop)
    if not t or s is None or s >= t:
        return None
    return round((t - s) / t * 100, 1)


def room_to_run(trigger: Any, high_52w: Any) -> tuple[float | None, bool]:
    """Distance from trigger to overhead supply (prototype: the 52W high). (pct, blue_sky)."""
    t, h = fnum(trigger), fnum(high_52w)
    if not t or not h:
        return None, False
    if t >= h * 0.995:
        return None, True
    return round((h / t - 1) * 100, 1), False


def box_character(top: np.ndarray, close: np.ndarray, window: int = 126) -> tuple[int, int]:
    """The stock's own Darvas box breakouts in the last `window` sessions.
    Held = +5% within 10 sessions. Failed = back below the box top within 5 sessions."""
    held = failed = 0
    n = len(close)
    for i in range(max(1, n - window), n - 5):
        t = top[i - 1]
        if np.isfinite(t) and close[i] > t >= close[i - 1]:
            fwd10 = close[i + 1:i + 11]
            fwd5 = close[i + 1:i + 6]
            if len(fwd10) and np.nanmax(fwd10) >= close[i] * 1.05:
                held += 1
            elif len(fwd5) and np.nanmin(fwd5) < t:
                failed += 1
    return held, failed


def weekly_check(weekly_closes: Sequence[float]) -> dict[str, bool | float | None]:
    """Weekly close vs 10-week line, and last 3 weekly closes within 2%."""
    w = [float(x) for x in weekly_closes if fnum(x) is not None]
    above = bool(w[-1] > sum(w[-10:]) / 10) if len(w) >= 10 else None
    spread = round((max(w[-3:]) / min(w[-3:]) - 1) * 100, 1) if len(w) >= 3 and min(w[-3:]) > 0 else None
    return {"above_10w": above, "tight": None if spread is None else spread <= 2.0, "spread_3w_pct": spread}


def squeeze_gate_failures(*, close: float, high: float, low: float, ema10: float, ema10_prev: float | None,
                          ema20: float | None, top: float, rvol: float | None, darvas: dict[str, float]) -> list[str]:
    """Strict Squeeze gates (desk_contract.DARVAS) that a close-in-zone candidate fails, each with its value."""
    sq = (top - ema10) / top * 100
    dt = (top - close) / top * 100
    rng = (high - low) / close * 100
    out = []
    if sq > darvas["max_squeeze_pct"]:
        out.append(f"Squeeze {sq:.1f}% (needs ≤ {darvas['max_squeeze_pct']:g}%)")
    if dt > darvas["max_squeeze_pct"]:
        out.append(f"{dt:.1f}% below box top (needs ≤ {darvas['max_squeeze_pct']:g}%)")
    if rng > darvas["max_range_pct"]:
        out.append(f"Day range {rng:.1f}% (needs ≤ {darvas['max_range_pct']:g}%)")
    if rvol is not None and rvol > darvas["max_rvol"]:
        out.append(f"RVOL {rvol:.2f} (needs ≤ {darvas['max_rvol']:g})")
    if ema10_prev is not None and ema10 <= ema10_prev:
        out.append("10 EMA not rising")
    if ema20 is not None and ema10 < ema20 * darvas["ema_trend_tol"]:
        out.append("10 EMA below 20 EMA")
    return out


def drop_reason(*, has_bar: bool, in_pool: bool, close: float | None, low: float | None, ema10: float | None,
                trigger: float | None, stop: float | None) -> tuple[str, str]:
    """Why a stock left a setup queue since the previous session: (code, sentence)."""
    if not has_bar or close is None:
        return "no_bar", "No bar on this session."
    if not in_pool:
        return "left_pool", "Left the pool (turnover, market cap, band or below 200 EMA)."
    if trigger and close > trigger:
        return "broke_out", f"Broke out: closed {close:.1f} above trigger {trigger:.1f}."
    if stop and low is not None and low < stop:
        return "hit_stop", f"Hit the stop: low {low:.1f} under stop {stop:.1f}."
    if ema10 and close < ema10:
        return "below_10ema", f"Closed below 10 EMA ({(close / ema10 - 1) * 100:+.1f}%)."
    return "rule_failed", "A rule no longer holds (volume, range or squeeze width)."


def percentile_of(history: Iterable[Any], value: Any) -> float | None:
    """Share of history readings at or below `value`, 0-100."""
    v = fnum(value)
    h = [x for x in (fnum(y) for y in history) if x is not None]
    if v is None or not h:
        return None
    return round(sum(1 for x in h if x <= v) / len(h) * 100, 0)


def median(values: Iterable[Any]) -> float | None:
    h = sorted(x for x in (fnum(y) for y in values) if x is not None)
    if not h:
        return None
    m = len(h) // 2
    return float(h[m]) if len(h) % 2 else (h[m - 1] + h[m]) / 2


def sort_key(row: dict[str, Any]) -> tuple:
    """Default board order: screeners passed, then group state, RS, delivery streak, risk."""
    rsp = row.get("rs_percentile")
    risk = row.get("risk_pct")
    return (-len(row.get("screeners") or []), STATE_ORDER.get(row.get("group_state") or NEUTRAL, 1),
            -(rsp if rsp is not None else -1), -(row.get("delivery_streak") or 0),
            risk if risk is not None else 999.0, row.get("symbol") or "")


# --------------------------------------------------------------------------- read-out (04-writing-style.md)
def readout(*, counts: dict[str, dict[str, Any]], split: dict[str, int], total: int, confluence: int,
            base: dict[str, dict[str, Any]], session_gap_days: int | None,
            results_known: bool = False) -> dict[str, Any]:
    """Plain-English read-out: short active sentences, a number behind each claim, then What to do."""
    lines: list[str] = []
    todo: list[str] = []
    if session_gap_days and session_gap_days > 7:
        lines.append(f"The previous session is {session_gap_days} days earlier. 1D moves and New tags are not reliable.")
        todo.append("Check the data gap before you act on New tags")
    lines.append(f"{total} stocks pass at least one screener. {confluence} pass two or more.")
    for q in SCREENERS:
        c = counts.get(q) or {}
        n, med, pct = c.get("today"), c.get("median_20"), c.get("percentile")
        if n is None:
            continue
        name = QUEUE_NAME[q]
        if med is None:
            lines.append(f"{name}: {n} stocks. No stored history to compare.")
            continue
        word = "above" if n > med else "below" if n < med else "at"
        tail = f" Archive percentile {pct:.0f}." if pct is not None else ""
        lines.append(f"{name}: {n} stocks, {word} its 20-session median of {med:.0f}.{tail}")
    fav, neu, cau = split.get(FAVOUR, 0), split.get(NEUTRAL, 0), split.get(CAUTION, 0)
    lines.append(f"Group state: {fav} in Favour groups, {neu} Neutral, {cau} in Caution groups.")
    sq_f, sq_c = base.get(f"darvas_squeeze|{FAVOUR}"), base.get(f"darvas_squeeze|{CAUTION}")
    if sq_f and sq_c and sq_f.get("win") is not None and sq_c.get("win") is not None:
        lines.append(f"Past new squeezes in Favour groups rose after 20 sessions {sq_f['win']:.0f}% of the time "
                     f"(n {sq_f['n']}). In Caution groups: {sq_c['win']:.0f}% (n {sq_c['n']}).")
    sqz = counts.get("darvas_squeeze") or {}
    if sqz.get("percentile") is not None and sqz["percentile"] >= 80:
        todo.append("Review the Squeeze list first, because coils are building")
    if cau > fav:
        todo.append("Prefer setups in Favour groups. Skip Caution rows unless the chart is clean")
    else:
        todo.append("Start with the confluence rows in Favour groups")
    if results_known:
        todo.append("Check the highlighted rows for results dates before you plan an entry")
    else:
        todo.append("Check results dates on the exchange site, because the app has no results data yet")
    return {"lines": lines, "what_to_do": todo[:3]}
