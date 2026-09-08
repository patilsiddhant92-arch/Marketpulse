"""Nicolas Darvas Box and 10/20 EMA Squeeze — canonical daily + completed-week implementation.

Box construction matches the TradingView Pine `ta.valuewhen` definition.
Squeeze membership follows the §8.3 truth table (open-floor dropped, failed-low cap).
Weekly bars use as_of >= calendar Friday of the W-FRI period — never as_of >= week_end_session.

Pine:
    boxp = 5
    LL = ta.lowest(low, boxp)
    k1 = ta.highest(high, boxp)
    k2 = ta.highest(high, boxp - 1)
    k3 = ta.highest(high, boxp - 2)
    NH = ta.valuewhen(high > k1[1], high, 0)
    box1 = k3 < k2
    TopBox = ta.valuewhen(ta.barssince(high > k1[1]) == boxp - 2 and box1, NH, 0)
    BottomBox = ta.valuewhen(ta.barssince(high > k1[1]) == boxp - 2 and box1, LL, 0)
"""
from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any, Literal

import numpy as np
import pandas as pd

# Duplicated until PR 7 owns desk_contract.DARVAS.
DARVAS: dict[str, float | int] = dict(
    max_squeeze_pct=5.0,
    max_range_pct=4.0,
    ceiling_tol=1.002,
    wick_floor_tol=0.995,
    close_floor_tol=0.998,
    undercut_cap_tol=0.985,
    ema_stack_tol=0.004,
    ema_trend_tol=0.995,
    box_lookback_sessions=252,
    display_window=40,
)

SQUEEZE_COLUMNS = [
    "symbol",
    "darvas_top",
    "darvas_bottom",
    "squeeze_pct",
    "squeeze_pct_5d_ago",
    "squeeze_pct_5w_ago",
    "tightening",
    "squeeze_age",
    "failed_low",
    "ema_floor",
    "candle_range_pct",
    "box_age_sessions",
    "qualifies",
]


def darvas_v2_enabled() -> bool:
    return os.environ.get("MP_DARVAS_V2", "").strip().lower() in {"1", "true", "yes", "on"}


def darvas_weekly_enabled() -> bool:
    return os.environ.get("MP_DARVAS_WEEKLY", "").strip().lower() in {"1", "true", "yes", "on"}


WEEKLY_LOOKBACK_SESSIONS = 400


def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        ts = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(ts):
        return None
    return ts.date()


def calendar_friday(d: Any) -> date:
    """pandas W-FRI period end is that week's Friday calendar date, holiday or not."""
    day = _to_date(d)
    if day is None:
        raise ValueError("calendar_friday requires a date")
    return pd.Period(day, freq="W-FRI").end_time.date()


def week_complete(period: Any, as_of: Any) -> bool:
    """True iff as_of >= calendar Friday of the W-FRI period.

    Do not use as_of >= week_end_session — that false-completes Mon–Thu when the
    frame is truncated at as_of (desk path).
    """
    as_of_d = _to_date(as_of)
    if as_of_d is None:
        return False
    if isinstance(period, pd.Period):
        fri = period.asfreq("W-FRI").end_time.date()
    else:
        fri = calendar_friday(period)
    return as_of_d >= fri


def week_end_session(period: Any, sessions: Any) -> date | None:
    """Last session in `sessions` belonging to the W-FRI period (Thu on holiday Friday)."""
    if isinstance(period, pd.Period):
        p = period.asfreq("W-FRI")
    else:
        day = _to_date(period)
        if day is None:
            return None
        p = pd.Period(day, freq="W-FRI")
    in_period: list[date] = []
    for s in sessions:
        sd = _to_date(s)
        if sd is None:
            continue
        if pd.Period(sd, freq="W-FRI") == p:
            in_period.append(sd)
    return max(in_period) if in_period else None


def completed_weeks(sessions: Any, as_of: Any) -> list[date]:
    """Unique week_end_session for each W-FRI period in sessions that is week_complete."""
    as_of_d = _to_date(as_of)
    if as_of_d is None:
        return []
    sess: list[date] = []
    seen: set[date] = set()
    for s in sessions:
        sd = _to_date(s)
        if sd is None or sd in seen or sd > as_of_d:
            continue
        seen.add(sd)
        sess.append(sd)
    if not sess:
        return []
    seen_p: set[pd.Period] = set()
    ends: list[date] = []
    for s in sess:
        p = pd.Period(s, freq="W-FRI")
        if p in seen_p:
            continue
        seen_p.add(p)
        if week_complete(p, as_of_d):
            end = week_end_session(p, sess)
            if end is not None:
                ends.append(end)
    return ends


def last_completed_week(sessions: Any, as_of: Any) -> date | None:
    weeks = completed_weeks(sessions, as_of)
    return max(weeks) if weeks else None


def weekly_ohlc(daily: pd.DataFrame, *, as_of: Any = None) -> pd.DataFrame:
    """Completed-week OHLC only. Index date is week_end_session, not calendar Friday.

    Completeness is as_of >= calendar_friday(period). Never as_of >= week_end_session.
    """
    empty_cols = [
        "symbol",
        "trade_date",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
    ]
    empty = pd.DataFrame(columns=empty_cols)
    if daily is None or daily.empty:
        return empty

    frame = daily.copy()
    sym_col = _pick_col(frame, "symbol")
    date_col = _pick_col(frame, "trade_date", "date")
    open_col = _pick_col(frame, "open_price", "open")
    high_col = _pick_col(frame, "high_price", "high")
    low_col = _pick_col(frame, "low_price", "low")
    close_col = _pick_col(frame, "close_price", "close")
    vol_col = _pick_col(frame, "volume")
    if not all([sym_col, date_col, open_col, high_col, low_col, close_col]):
        return empty

    if as_of is None:
        as_of = frame[date_col].max()
    as_of_d = _to_date(as_of)
    if as_of_d is None:
        return empty
    frame = frame[pd.to_datetime(frame[date_col]).dt.normalize() <= pd.Timestamp(as_of_d)]
    if frame.empty:
        return empty

    rows: list[dict[str, Any]] = []
    for sym, group in frame.groupby(sym_col, sort=False):
        g = group.sort_values(date_col)
        sessions = pd.to_datetime(g[date_col]).dt.date.tolist()
        week_ends = completed_weeks(sessions, as_of_d)
        if not week_ends:
            continue
        periods = pd.to_datetime(g[date_col]).dt.to_period("W-FRI")
        for week_end in week_ends:
            p = pd.Period(week_end, freq="W-FRI")
            bars = g.loc[periods == p]
            if bars.empty:
                continue
            row: dict[str, Any] = {
                "symbol": sym,
                "trade_date": pd.Timestamp(week_end),
                "open_price": bars[open_col].iloc[0],
                "high_price": bars[high_col].max(),
                "low_price": bars[low_col].min(),
                "close_price": bars[close_col].iloc[-1],
                "volume": bars[vol_col].sum() if vol_col is not None else np.nan,
            }
            rows.append(row)

    if not rows:
        return empty
    out = pd.DataFrame(rows, columns=empty_cols)
    return out.sort_values(["symbol", "trade_date"]).reset_index(drop=True)


def calculate_darvas_box(
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    boxp: int = 5,
) -> tuple[np.ndarray, np.ndarray]:
    """TopBox (Green Line) and BottomBox (Red Line) matching TradingView Pine."""
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    n = len(h)

    if n < boxp:
        return np.full(n, np.nan), np.full(n, np.nan)

    ll = pd.Series(l).rolling(boxp).min().values
    k1 = pd.Series(h).rolling(boxp).max().values
    k2 = pd.Series(h).rolling(boxp - 1).max().values
    k3 = pd.Series(h).rolling(boxp - 2).max().values

    top_box = np.full(n, np.nan)
    bottom_box = np.full(n, np.nan)

    current_top = np.nan
    current_bottom = np.nan
    nh = np.nan
    bars_since_nh = 999

    for i in range(1, n):
        bars_since_nh += 1
        if i >= boxp and h[i] > k1[i - 1]:
            nh = h[i]
            bars_since_nh = 0

        box1 = (k3[i] < k2[i]) if i >= boxp else False
        if bars_since_nh == (boxp - 2) and box1:
            current_top = nh
            current_bottom = ll[i]

        top_box[i] = current_top
        bottom_box[i] = current_bottom

    return top_box, bottom_box


def compute_darvas_metrics(
    close: np.ndarray | pd.Series,
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    boxp: int = 5,
    ema_span: int = 10,
) -> dict[str, np.ndarray]:
    """Compute Darvas top, bottom, 10 EMA, and squeeze percentage series."""
    c = np.asarray(close, dtype=float)
    top_box, bottom_box = calculate_darvas_box(high, low, boxp=boxp)
    ema10 = pd.Series(c).ewm(span=ema_span, adjust=False).mean().values

    with np.errstate(divide="ignore", invalid="ignore"):
        squeeze_pct = np.where(top_box > 0, ((top_box - ema10) / top_box) * 100.0, np.nan)
        dist_to_green = np.where(top_box > 0, ((top_box - c) / top_box) * 100.0, np.nan)
        dist_to_ema10 = np.where(ema10 > 0, ((c - ema10) / ema10) * 100.0, np.nan)

    return {
        "top_box": top_box,
        "bottom_box": bottom_box,
        "ema10": ema10,
        "squeeze_pct": squeeze_pct,
        "dist_to_green_pct": dist_to_green,
        "dist_to_ema10_pct": dist_to_ema10,
    }


def _finite_pos(x: Any) -> bool:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return False
    return np.isfinite(v) and v > 0


def _f(x: Any, default: float = np.nan) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if np.isfinite(v) else default


def _cfg_val(cfg: dict[str, Any], key: str) -> float:
    return float(cfg.get(key, DARVAS[key]))


def evaluate_squeeze_bar(
    close: float,
    top_box: float,
    bottom_box: float,
    ema10: float,
    high: float | None = None,
    low: float | None = None,
    open_price: float | None = None,
    ema20: float | None = None,
    *,
    max_squeeze_pct: float | None = None,
    max_candle_range_pct: float | None = None,
    require_ohlc_inside: bool = True,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Truth-table evaluation of one bar. Open is not tested against the floor.

    bottom_box is accepted for call-site compatibility with the Pine pair; v2 does
    not gate on the red line (§8.3 discovery gates are spread, green-line, ceiling,
    floor_ok, trend, range).
    """
    _ = bottom_box  # red-line floor is intentionally gone in v2
    params = dict(DARVAS)
    if cfg:
        params.update(cfg)
    max_sq = float(max_squeeze_pct) if max_squeeze_pct is not None else _cfg_val(params, "max_squeeze_pct")
    max_range = float(max_candle_range_pct) if max_candle_range_pct is not None else _cfg_val(params, "max_range_pct")
    ceiling_tol = _cfg_val(params, "ceiling_tol")
    wick_floor_tol = _cfg_val(params, "wick_floor_tol")
    close_floor_tol = _cfg_val(params, "close_floor_tol")
    undercut_cap_tol = _cfg_val(params, "undercut_cap_tol")
    ema_stack_tol = _cfg_val(params, "ema_stack_tol")
    ema_trend_tol = _cfg_val(params, "ema_trend_tol")

    empty = {
        "qualifies": False,
        "failed_low": False,
        "ema_floor": np.nan,
        "squeeze_pct": np.nan,
        "candle_range_pct": np.nan,
        "stacked": False,
    }
    if not _finite_pos(top_box) or not _finite_pos(ema10) or not _finite_pos(close):
        return empty

    c = float(close)
    top = float(top_box)
    e10 = float(ema10)
    e20 = _f(ema20)
    h = _f(high, c) if high is not None else c
    l = _f(low, c) if low is not None else c
    o = _f(open_price, c) if open_price is not None else c

    squeeze_pct = ((top - e10) / top) * 100.0
    candle_range_pct = ((h - l) / c) * 100.0 if c > 0 else np.nan

    stacked = (
        np.isfinite(e20)
        and e20 > 0
        and e10 > 0
        and (abs(e10 - e20) / e10) <= ema_stack_tol
        and e10 >= e20 * ema_trend_tol
    )
    ema_floor = min(e10, e20) if stacked else e10

    trend_ok = True
    if np.isfinite(e20) and e20 > 0:
        trend_ok = e10 >= e20 * ema_trend_tol

    close_ok = (c >= e10 * close_floor_tol) and (c <= top * ceiling_tol)
    wick_strict = l >= ema_floor * wick_floor_tol
    failed_low = (
        (l < ema_floor * wick_floor_tol)
        and (l >= ema_floor * undercut_cap_tol)
        and close_ok
    )
    floor_ok = wick_strict or failed_low

    qualifies = trend_ok and (0.0 <= squeeze_pct <= max_sq)
    dist_to_green = ((top - c) / top) * 100.0
    qualifies = qualifies and (-0.2 <= dist_to_green <= max_sq)

    if require_ohlc_inside:
        ceiling_ok = (h <= top * ceiling_tol) and (o <= top * ceiling_tol) and (c <= top * ceiling_tol)
        range_ok = (not np.isfinite(candle_range_pct)) or (candle_range_pct <= max_range)
        qualifies = qualifies and ceiling_ok and close_ok and floor_ok and range_ok

    return {
        "qualifies": bool(qualifies),
        "failed_low": bool(failed_low),
        "ema_floor": float(ema_floor),
        "squeeze_pct": float(squeeze_pct),
        "candle_range_pct": float(candle_range_pct) if np.isfinite(candle_range_pct) else np.nan,
        "stacked": bool(stacked),
    }


def is_darvas_10ema_squeeze(
    close: float,
    top_box: float,
    bottom_box: float,
    ema10: float,
    high: float | None = None,
    low: float | None = None,
    open_price: float | None = None,
    max_squeeze_pct: float | None = None,
    max_candle_range_pct: float | None = None,
    require_ohlc_inside: bool = True,
    ema20: float | None = None,
    cfg: dict[str, Any] | None = None,
) -> bool:
    """Daily squeeze membership (v2 truth table). Open is not tested against the floor.

    Numeric caps default to DARVAS / cfg when left as None (do not hard-code 5.0/4.0 here).
    """
    state = evaluate_squeeze_bar(
        close,
        top_box,
        bottom_box,
        ema10,
        high=high,
        low=low,
        open_price=open_price,
        ema20=ema20,
        max_squeeze_pct=max_squeeze_pct,
        max_candle_range_pct=max_candle_range_pct,
        require_ohlc_inside=require_ohlc_inside,
        cfg=cfg,
    )
    return bool(state["qualifies"])


def is_darvas_10ema_squeeze_legacy(
    close: float,
    top_box: float,
    bottom_box: float,
    ema10: float,
    high: float | None = None,
    low: float | None = None,
    open_price: float | None = None,
    max_squeeze_pct: float = 5.0,
    max_candle_range_pct: float = 4.0,
    require_ohlc_inside: bool = True,
    ema20: float | None = None,
) -> bool:
    """Pre-v2 predicate: open-floor required, wick vs 10 EMA only, no stacked floor."""
    if np.isnan(top_box) or top_box <= 0 or np.isnan(ema10) or ema10 <= 0 or np.isnan(close) or close <= 0:
        return False

    if ema20 is not None and not np.isnan(ema20) and ema20 > 0:
        if ema10 < ema20 * 0.995:
            return False

    squeeze_pct = ((top_box - ema10) / top_box) * 100.0
    if not (0.0 <= squeeze_pct <= max_squeeze_pct):
        return False

    dist_to_green = ((top_box - close) / top_box) * 100.0
    if not (-0.2 <= dist_to_green <= max_squeeze_pct):
        return False

    if require_ohlc_inside:
        h = high if high is not None else close
        l = low if low is not None else close
        o = open_price if open_price is not None else close

        if h > top_box * 1.002 or o > top_box * 1.002 or close > top_box * 1.002:
            return False

        if l < ema10 * 0.995 or o < ema10 * 0.995 or close < ema10 * 0.998:
            return False

        if not np.isnan(bottom_box) and bottom_box > 0:
            if l < bottom_box * 0.998:
                return False

        if close > 0:
            candle_range_pct = ((h - l) / close) * 100.0
            if candle_range_pct > max_candle_range_pct:
                return False

    return True


def _pick_col(df: pd.DataFrame, *names: str) -> str | None:
    for name in names:
        if name in df.columns:
            return name
    return None


def _box_age_sessions(top_box: np.ndarray) -> int:
    if len(top_box) == 0 or not np.isfinite(top_box[-1]):
        return 0
    last = float(top_box[-1])
    age = 0
    for v in top_box[::-1]:
        if not np.isfinite(v) or float(v) != last:
            break
        age += 1
    return age


def _squeeze_pct_at(top: float, ema10: float) -> float:
    if not _finite_pos(top) or not np.isfinite(ema10):
        return np.nan
    return ((float(top) - float(ema10)) / float(top)) * 100.0


def squeeze_frame(
    daily: pd.DataFrame,
    *,
    timeframe: Literal["D", "W"] = "D",
    as_of: Any = None,
    cfg: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """One row per symbol with Darvas squeeze metrics on the as-of bar.

    `daily` needs symbol, trade_date, OHLC (open_price/high_price/low_price/close_price
    or open/high/low/close), and optionally ema_10 / ema_20.
    timeframe="W" resamples completed weeks only and evaluates the last completed week
    with weekly 10 EMA (stacked 20 if present). Daily ema_* columns are not reused.
    """
    if timeframe not in ("D", "W"):
        raise ValueError(f"timeframe must be 'D' or 'W', got {timeframe!r}")

    params = dict(DARVAS)
    if cfg:
        params.update(cfg)

    empty = pd.DataFrame(columns=SQUEEZE_COLUMNS)
    if daily is None or daily.empty:
        return empty

    frame = daily.copy()
    weekly = timeframe == "W"
    if weekly:
        frame = weekly_ohlc(frame, as_of=as_of)
        if frame.empty:
            return empty
        sym_col = "symbol"
        date_col = "trade_date"
        open_col = "open_price"
        high_col = "high_price"
        low_col = "low_price"
        close_col = "close_price"
        ema10_col = None
        ema20_col = None
    else:
        sym_col = _pick_col(frame, "symbol")
        date_col = _pick_col(frame, "trade_date", "date")
        open_col = _pick_col(frame, "open_price", "open")
        high_col = _pick_col(frame, "high_price", "high")
        low_col = _pick_col(frame, "low_price", "low")
        close_col = _pick_col(frame, "close_price", "close")
        if not all([sym_col, date_col, open_col, high_col, low_col, close_col]):
            return empty
        if as_of is not None:
            frame = frame[pd.to_datetime(frame[date_col]) <= pd.Timestamp(as_of)]
            if frame.empty:
                return empty
        ema10_col = _pick_col(frame, "ema_10", "ema10")
        ema20_col = _pick_col(frame, "ema_20", "ema20")

    rows: list[dict[str, Any]] = []
    for sym, group in frame.groupby(sym_col, sort=False):
        g = group.sort_values(date_col)
        if len(g) < 5:
            continue
        highs = g[high_col].to_numpy(dtype=float)
        lows = g[low_col].to_numpy(dtype=float)
        closes = g[close_col].to_numpy(dtype=float)
        opens = g[open_col].to_numpy(dtype=float)
        top_box, bottom_box = calculate_darvas_box(highs, lows, boxp=5)
        if weekly:
            ema10 = pd.Series(closes).ewm(span=10, adjust=False, min_periods=10).mean().to_numpy()
            ema20 = pd.Series(closes).ewm(span=20, adjust=False, min_periods=20).mean().to_numpy()
        elif ema10_col is not None:
            ema10 = g[ema10_col].to_numpy(dtype=float)
            if ema20_col is not None:
                ema20 = g[ema20_col].to_numpy(dtype=float)
            else:
                ema20 = pd.Series(closes).ewm(span=20, adjust=False).mean().to_numpy()
        else:
            ema10 = pd.Series(closes).ewm(span=10, adjust=False).mean().to_numpy()
            if ema20_col is not None:
                ema20 = g[ema20_col].to_numpy(dtype=float)
            else:
                ema20 = pd.Series(closes).ewm(span=20, adjust=False).mean().to_numpy()

        last_state = evaluate_squeeze_bar(
            closes[-1],
            top_box[-1],
            bottom_box[-1],
            ema10[-1],
            high=highs[-1],
            low=lows[-1],
            open_price=opens[-1],
            ema20=ema20[-1],
            cfg=params,
        )
        sq_now = last_state["squeeze_pct"]
        sq_prior = _squeeze_pct_at(top_box[-6], ema10[-6]) if len(g) >= 6 else np.nan
        # Daily: 5 sessions. Weekly: 5 completed weeks — do not store that analog in *_5d_ago.
        sq_5d = np.nan if weekly else sq_prior
        sq_5w = sq_prior if weekly else np.nan
        tightening = bool(np.isfinite(sq_now) and np.isfinite(sq_prior) and sq_now < sq_prior)

        squeeze_age = 0
        for i in range(len(g) - 1, -1, -1):
            e20_i = ema20[i] if i < len(ema20) else np.nan
            bar_ok = evaluate_squeeze_bar(
                closes[i],
                top_box[i],
                bottom_box[i],
                ema10[i],
                high=highs[i],
                low=lows[i],
                open_price=opens[i],
                ema20=e20_i,
                cfg=params,
            )["qualifies"]
            if not bar_ok:
                break
            squeeze_age += 1

        rows.append(
            {
                "symbol": sym,
                "darvas_top": float(top_box[-1]) if np.isfinite(top_box[-1]) else np.nan,
                "darvas_bottom": float(bottom_box[-1]) if np.isfinite(bottom_box[-1]) else np.nan,
                "squeeze_pct": sq_now,
                "squeeze_pct_5d_ago": sq_5d,
                "squeeze_pct_5w_ago": sq_5w,
                "tightening": tightening,
                "squeeze_age": int(squeeze_age),
                "failed_low": bool(last_state["failed_low"]),
                "ema_floor": last_state["ema_floor"],
                "candle_range_pct": last_state["candle_range_pct"],
                "box_age_sessions": _box_age_sessions(top_box),
                "qualifies": bool(last_state["qualifies"]),
            }
        )

    if not rows:
        return empty
    return pd.DataFrame(rows, columns=SQUEEZE_COLUMNS)


def sort_qualifying_squeezes(df: pd.DataFrame) -> pd.DataFrame:
    """Soft rank: tightening + squeeze_age >= 2 first, then tightest spread/range."""
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame(columns=SQUEEZE_COLUMNS)
    out = df.copy()
    tightening = out["tightening"] if "tightening" in out.columns else False
    age = out["squeeze_age"] if "squeeze_age" in out.columns else 0
    boost = tightening.fillna(False).astype(bool) & (pd.to_numeric(age, errors="coerce").fillna(0).astype(int) >= 2)
    out = out.assign(_boost=boost.astype(int))
    sort_cols = ["_boost"]
    ascending = [False]
    if "squeeze_pct" in out.columns:
        sort_cols.append("squeeze_pct")
        ascending.append(True)
    if "candle_range_pct" in out.columns:
        sort_cols.append("candle_range_pct")
        ascending.append(True)
    out = out.sort_values(sort_cols, ascending=ascending, kind="mergesort").drop(columns=["_boost"])
    return out.reset_index(drop=True)


def apply_display_window(
    df: pd.DataFrame, window: int | None = None
) -> tuple[pd.DataFrame, int]:
    """Rank, then split unclipped count from the matrix window.

    Count is taken *before* head(window). TV/matrix callers must use the returned frame.
    """
    if df is None or df.empty:
        empty = df if df is not None else pd.DataFrame(columns=SQUEEZE_COLUMNS)
        return empty, 0
    ranked = sort_qualifying_squeezes(df)
    n = int(len(ranked))
    w = int(window if window is not None else DARVAS["display_window"])
    return ranked.head(w).reset_index(drop=True), n
