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

# Single owner: Scripts.desk_contract.DARVAS (imported — do not re-literal here).
try:
    from Scripts.desk_contract import DARVAS
except ImportError:  # script/cwd import style
    from desk_contract import DARVAS  # type: ignore

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
    "signal_date",
]


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def darvas_v2_enabled() -> bool:
    # Default ON — set MP_DARVAS_V2=0 to force legacy desk/chart paths.
    return _env_flag("MP_DARVAS_V2", default=True)


def darvas_weekly_enabled() -> bool:
    # Completed-week path stays opt-in.
    return _env_flag("MP_DARVAS_WEEKLY", default=False)


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
    sess.sort()
    s_dt = pd.to_datetime(sess)
    periods = s_dt.to_period("W-FRI")
    fridays = periods.end_time.date
    valid_mask = fridays <= as_of_d
    if not valid_mask.any():
        return []
    valid_periods = periods[valid_mask]
    valid_sessions = pd.Series(sess)[valid_mask]
    return valid_sessions.groupby(valid_periods).max().tolist()


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

    frame["_dt"] = pd.to_datetime(frame[date_col])
    frame = frame[frame["_dt"].dt.normalize() <= pd.Timestamp(as_of_d)]
    if frame.empty:
        return empty

    frame["_period"] = frame["_dt"].dt.to_period("W-FRI")
    frame["_fri"] = frame["_period"].dt.end_time.dt.date
    frame_completed = frame[frame["_fri"] <= as_of_d]
    if frame_completed.empty:
        return empty

    agg_rules = {
        date_col: "max",
        open_col: "first",
        high_col: "max",
        low_col: "min",
        close_col: "last",
    }
    if vol_col:
        agg_rules[vol_col] = "sum"

    grouped = (
        frame_completed.sort_values(date_col)
        .groupby([sym_col, "_period"], sort=False)
        .agg(agg_rules)
        .reset_index()
    )
    out = pd.DataFrame(
        {
            "symbol": grouped[sym_col],
            "trade_date": pd.to_datetime(grouped[date_col]).dt.normalize(),
            "open_price": grouped[open_col],
            "high_price": grouped[high_col],
            "low_price": grouped[low_col],
            "close_price": grouped[close_col],
            "volume": grouped[vol_col] if vol_col else np.nan,
        },
        columns=empty_cols,
    )
    return out.sort_values(["symbol", "trade_date"]).reset_index(drop=True)


def monthly_ohlc(daily: pd.DataFrame, *, as_of: Any = None) -> pd.DataFrame:
    """Monthly OHLC aggregation. Resamples daily bars into calendar months for monthly Darvas boxes."""
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

    frame["_dt"] = pd.to_datetime(frame[date_col])
    frame = frame[frame["_dt"].dt.normalize() <= pd.Timestamp(as_of_d)]
    if frame.empty:
        return empty

    frame["_period"] = frame["_dt"].dt.to_period("M")

    agg_rules = {
        date_col: "max",
        open_col: "first",
        high_col: "max",
        low_col: "min",
        close_col: "last",
    }
    if vol_col:
        agg_rules[vol_col] = "sum"

    grouped = (
        frame.sort_values(date_col)
        .groupby([sym_col, "_period"], sort=False)
        .agg(agg_rules)
        .reset_index()
    )
    out = pd.DataFrame(
        {
            "symbol": grouped[sym_col],
            "trade_date": pd.to_datetime(grouped[date_col]).dt.normalize(),
            "open_price": grouped[open_col],
            "high_price": grouped[high_col],
            "low_price": grouped[low_col],
            "close_price": grouped[close_col],
            "volume": grouped[vol_col] if vol_col else np.nan,
        },
        columns=empty_cols,
    )
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
    rvol: float | None = None,
    ema10_prev: float | None = None,
    max_squeeze_pct: float | None = None,
    max_candle_range_pct: float | None = None,
    require_ohlc_inside: bool = True,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Truth-table evaluation of one bar. Close must sit in the squeeze zone; wicks may test outside.

    bottom_box is accepted for call-site compatibility with the Pine pair; v2 does
    not gate on the red line. Wick pierces of TopBox / 10 EMA are valid tests when close holds in-zone.
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

    # Close must finish inside the squeeze zone (10 EMA ↔ TopBox).
    # Wicks may test outside: high can pierce TopBox, low can undercut 10/20 EMA —
    # those are valid range tests when the close reclaims the zone.
    close_ok = (c >= e10 * close_floor_tol) and (c <= top * ceiling_tol)
    wick_undercut = l < ema_floor * wick_floor_tol
    failed_low = bool(wick_undercut and close_ok)  # informational: tested support, closed in zone
    _ = undercut_cap_tol  # retained in DARVAS for charts; no longer a hard reject
    _ = o  # open may also poke; close_ok is the membership gate

    qualifies = trend_ok and (0.0 <= squeeze_pct <= max_sq)
    dist_to_green = ((top - c) / top) * 100.0
    qualifies = qualifies and (-0.2 <= dist_to_green <= max_sq)

    if require_ohlc_inside:
        range_ok = (not np.isfinite(candle_range_pct)) or (candle_range_pct <= max_range)
        qualifies = qualifies and close_ok and range_ok

    # Approach A hard gates (optional args keep pure-geometry unit tests working).
    e10_prev = _f(ema10_prev)
    if np.isfinite(e10_prev):
        qualifies = qualifies and (e10 > e10_prev)

    if rvol is not None:
        max_rvol = float(params.get("max_rvol", DARVAS.get("max_rvol", 1.0)))
        rv = _f(rvol)
        qualifies = qualifies and np.isfinite(rv) and (rv <= max_rvol)

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
    timeframe: Literal["D", "W", "M"] = "D",
    as_of: Any = None,
    cfg: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """One row per symbol with Darvas squeeze metrics on the as-of bar.

    `daily` needs symbol, trade_date, OHLC (open_price/high_price/low_price/close_price
    or open/high/low/close), and optionally ema_10 / ema_20.
    timeframe="W" resamples completed weeks only.
    timeframe="M" resamples completed months.
    """
    if timeframe not in ("D", "W", "M"):
        raise ValueError(f"timeframe must be 'D', 'W', or 'M', got {timeframe!r}")

    params = dict(DARVAS)
    if cfg:
        params.update(cfg)

    empty = pd.DataFrame(columns=SQUEEZE_COLUMNS)
    if daily is None or daily.empty:
        return empty

    frame = daily.copy()
    is_resampled = timeframe in ("W", "M")
    if is_resampled:
        if timeframe == "W":
            frame = weekly_ohlc(frame, as_of=as_of)
        else:
            frame = monthly_ohlc(frame, as_of=as_of)
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
        if is_resampled:
            ema10 = pd.Series(closes).ewm(span=10, adjust=False, min_periods=min(len(closes), 10)).mean().to_numpy()
            ema20 = pd.Series(closes).ewm(span=20, adjust=False, min_periods=min(len(closes), 20)).mean().to_numpy()
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

        rvol_col = _pick_col(g, "rvol", "rel_volume")
        rvols = g[rvol_col].to_numpy(dtype=float) if rvol_col else np.full(len(g), np.nan)

        def _bar_rvol(i: int) -> float | None:
            if rvol_col is None:
                return None
            rv = rvols[i] if i < len(rvols) else np.nan
            return float(rv) if np.isfinite(rv) else None

        cur_max_range = (
            float(params.get("max_range_pct_weekly", 8.0))
            if timeframe == "W"
            else (float(params.get("max_range_pct_monthly", 12.0)) if timeframe == "M" else None)
        )
        last_state = evaluate_squeeze_bar(
            closes[-1],
            top_box[-1],
            bottom_box[-1],
            ema10[-1],
            high=highs[-1],
            low=lows[-1],
            open_price=opens[-1],
            ema20=ema20[-1],
            rvol=_bar_rvol(len(g) - 1),
            ema10_prev=float(ema10[-2]) if len(ema10) >= 2 else None,
            max_candle_range_pct=cur_max_range,
            cfg=params,
        )
        sq_now = last_state["squeeze_pct"]
        lookback = 6 if timeframe == "D" else (3 if timeframe == "W" else 2)
        sq_prior = _squeeze_pct_at(top_box[-lookback], ema10[-lookback]) if len(g) >= lookback else np.nan
        # Daily: 5 sessions. Weekly: completed weeks. Monthly: completed months.
        sq_5d = sq_prior if timeframe == "D" else np.nan
        sq_5w = sq_prior if timeframe == "W" else np.nan
        persist_n = int(params.get("persist_sessions", 5))
        persist_max_rvol = float(params.get("persist_max_rvol", 1.5))
        persist_max_range = float(params.get("persist_max_range_pct", 6.0))
        close_floor_tol = float(params.get("close_floor_tol", DARVAS["close_floor_tol"]))
        ceiling_tol = float(params.get("ceiling_tol", DARVAS["ceiling_tol"]))
        signal_i = len(g) - 1  # weekly/monthly keep the as-of bar; daily may rewind to persist hit
        if timeframe == "D":
            tightening = bool(np.isfinite(sq_now) and np.isfinite(sq_prior) and sq_now < sq_prior)
            last_ok = bool(last_state["qualifies"])
            persist_hit = False
            start_p = max(0, len(g) - persist_n)
            for pi in range(start_p, len(g)):
                e20_p = ema20[pi] if pi < len(ema20) else np.nan
                e10_prev_p = float(ema10[pi - 1]) if pi >= 1 else None
                if evaluate_squeeze_bar(
                    closes[pi],
                    top_box[pi],
                    bottom_box[pi],
                    ema10[pi],
                    high=highs[pi],
                    low=lows[pi],
                    open_price=opens[pi],
                    ema20=e20_p,
                    rvol=_bar_rvol(pi),
                    ema10_prev=e10_prev_p,
                    max_candle_range_pct=cur_max_range,
                    cfg=params,
                )["qualifies"]:
                    persist_hit = True
                    signal_i = pi
            last_rv = _bar_rvol(len(g) - 1)
            last_range = last_state["candle_range_pct"]
            still_in = (
                np.isfinite(closes[-1])
                and np.isfinite(ema10[-1])
                and np.isfinite(top_box[-1])
                and top_box[-1] > 0
                and closes[-1] >= ema10[-1] * close_floor_tol
                and closes[-1] <= top_box[-1] * ceiling_tol
            )
            persist_ok = persist_hit and still_in
            if np.isfinite(last_range):
                persist_ok = persist_ok and last_range <= persist_max_range
            if last_rv is not None:
                persist_ok = persist_ok and last_rv <= persist_max_rvol
            qualifies = last_ok or persist_ok
            if last_ok:
                signal_i = len(g) - 1
        else:
            if np.isfinite(sq_now) and np.isfinite(sq_prior) and sq_prior > 0:
                tightening = bool(sq_now <= sq_prior + 0.2)
            else:
                tightening = bool(np.isfinite(sq_now))
            qualifies = bool(last_state["qualifies"])
            if np.isfinite(sq_prior) and sq_prior > 0:
                qualifies = qualifies and tightening
        # Dry-vol gate applies only when rvol is present (evaluate_squeeze_bar).
        # Action Desk hist query must SELECT rvol so production never skips it.

        squeeze_age = 0
        for i in range(len(g) - 1, -1, -1):
            e20_i = ema20[i] if i < len(ema20) else np.nan
            e10_prev_i = float(ema10[i - 1]) if i >= 1 else None
            bar_ok = evaluate_squeeze_bar(
                closes[i],
                top_box[i],
                bottom_box[i],
                ema10[i],
                high=highs[i],
                low=lows[i],
                open_price=opens[i],
                ema20=e20_i,
                rvol=_bar_rvol(i),
                ema10_prev=e10_prev_i,
                max_candle_range_pct=cur_max_range,
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
                "qualifies": bool(qualifies),
                "signal_date": pd.Timestamp(g[date_col].iloc[signal_i]).date() if qualifies else None,
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
    sort_cols = []
    ascending = []
    if "squeeze_pct" in out.columns:
        sort_cols.append("squeeze_pct")
        ascending.append(True)
    sort_cols.append("_boost")
    ascending.append(False)
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


def _bar_tags_ema10(
    open_: float,
    high: float,
    low: float,
    close: float,
    ema10: float,
    *,
    above_tol: float = 0.04,
    undercut_tol: float = 0.015,
) -> bool:
    """True when this bar's OHLC tests the 10 EMA (wick or body)."""
    vals = (open_, high, low, close, ema10)
    if not all(np.isfinite(v) and v > 0 for v in (close, ema10, low, high)):
        return False
    tagged_low = (low <= ema10 * (1.0 + above_tol)) and (low >= ema10 * (1.0 - undercut_tol))
    body_lo = min(open_, close) if np.isfinite(open_) else close
    body_hi = max(open_, close) if np.isfinite(open_) else close
    tagged_body = body_lo <= ema10 * (1.0 + above_tol) and body_hi >= ema10 * 0.998
    return bool(tagged_low or tagged_body)


def classify_darvas_10ema_frame(
    daily: pd.DataFrame,
    *,
    timeframe: Literal["D", "W", "M"] = "D",
    as_of: Any = None,
    cfg: dict[str, Any] | None = None,
    thrust_lookback: int = 10,
    min_thrust_pct: float = 3.0,
    min_thrust_rvol: float = 1.5,
    max_away_ema_pct: float = 3.5,
    catchup_high_tol_pct: float = 5.0,
    structure_lookback: int = 5,
    tag_lookback: int = 8,
    catchup_max_away_pct: float = 12.0,
    catchup_max_rvol: float = 2.2,
    traceback_max_away_pct: float = 18.0,
) -> pd.DataFrame:
    """Classify rising-10-EMA setups: Pullback | Trace-back | Catch-up.

    Pullback: latest OHLC is still on the 10 EMA.
    Trace-back: OHLC tagged 10 EMA in `tag_lookback` sessions, then price moved.
    Catch-up: 10 EMA rising into held highs (price already extended).

    Latest close must finish above a rising 10 EMA. Wicks may undercut.
    """
    if timeframe not in ("D", "W", "M"):
        raise ValueError(f"timeframe must be 'D', 'W', or 'M', got {timeframe!r}")

    params = dict(DARVAS)
    if cfg:
        params.update(cfg)
    max_rvol = float(params.get("max_rvol", 1.0))
    cols = [
        "symbol",
        "flavor",
        "ema_10",
        "away_10ema_pct",
        "rvol",
        "thrust_pct",
        "qualifies",
        "signal_date",
    ]
    empty = pd.DataFrame(columns=cols)
    if daily is None or daily.empty:
        return empty

    frame = daily.copy()
    is_resampled = timeframe in ("W", "M")
    if is_resampled:
        if timeframe == "W":
            frame = weekly_ohlc(frame, as_of=as_of)
        else:
            frame = monthly_ohlc(frame, as_of=as_of)
        if frame.empty:
            return empty
        sym_col = "symbol"
        date_col = "trade_date"
        open_col = "open_price"
        high_col = "high_price"
        low_col = "low_price"
        close_col = "close_price"
        vol_col = "volume" if "volume" in frame.columns else None
        ema10_col = None
        rvol_col = None
        # On weekly/monthly, 6 bars is a strong multi-month lookback
        thrust_lookback = min(thrust_lookback, 8)
        structure_lookback = min(structure_lookback, 4)
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
        vol_col = _pick_col(frame, "volume")
        ema10_col = _pick_col(frame, "ema_10", "ema10")
        rvol_col = _pick_col(frame, "rvol", "rel_volume")

    rows: list[dict[str, Any]] = []
    for sym, group in frame.groupby(sym_col, sort=False):
        g = group.sort_values(date_col)
        if len(g) < max(5, thrust_lookback):
            continue
        opens = g[open_col].to_numpy(dtype=float)
        highs = g[high_col].to_numpy(dtype=float)
        lows = g[low_col].to_numpy(dtype=float)
        closes = g[close_col].to_numpy(dtype=float)

        if is_resampled or ema10_col is None:
            ema10 = pd.Series(closes).ewm(span=10, adjust=False, min_periods=min(len(closes), 10)).mean().to_numpy()
        else:
            ema10 = g[ema10_col].to_numpy(dtype=float)

        if is_resampled or rvol_col is None:
            if vol_col is not None and vol_col in g.columns:
                vols = g[vol_col].to_numpy(dtype=float)
                v_avg = pd.Series(vols).rolling(10, min_periods=1).mean().to_numpy()
                rvols = np.where(v_avg > 0, vols / v_avg, 1.0)
            else:
                rvols = np.ones(len(closes))
        else:
            rvols = g[rvol_col].to_numpy(dtype=float)
        i = len(g) - 1
        e10 = float(ema10[i])
        e10_prev = float(ema10[i - 1])
        c = float(closes[i])
        h = float(highs[i])
        o = float(opens[i])
        rv = float(rvols[i])
        if not (np.isfinite(e10) and np.isfinite(e10_prev) and np.isfinite(c)):
            continue
        if e10 <= e10_prev:
            continue
        if not (c > e10 and h >= e10):
            continue

        look_n = min(int(tag_lookback), 4) if is_resampled else int(tag_lookback)
        tag_idxs = [
            j
            for j in range(max(0, i - look_n + 1), i + 1)
            if _bar_tags_ema10(float(opens[j]), float(highs[j]), float(lows[j]), float(closes[j]), float(ema10[j]))
        ]
        last_tags = bool(tag_idxs and tag_idxs[-1] == i)
        tag_i = tag_idxs[-1] if tag_idxs else None

        start_i = max(0, i - int(thrust_lookback))
        thrust_pct = 0.0
        thrust_idx: int | None = None
        for j in range(start_i, i):
            prev_c = closes[j - 1] if j > 0 else np.nan
            if not np.isfinite(prev_c) or prev_c <= 0:
                continue
            day_pct = (closes[j] / prev_c - 1.0) * 100.0
            prior_high = highs[j - 1] if j > 0 else np.nan
            rvol_j = rvols[j]
            thrust_day = (day_pct >= min_thrust_pct) or (
                np.isfinite(rvol_j)
                and rvol_j >= min_thrust_rvol
                and np.isfinite(prior_high)
                and closes[j] > prior_high
            )
            if thrust_day:
                thrust_idx = j
                thrust_pct = max(thrust_pct, float(day_pct))

        post_tag_holds = True
        if tag_i is not None:
            for j in range(tag_i, i + 1):
                if not (np.isfinite(closes[j]) and np.isfinite(ema10[j]) and closes[j] >= ema10[j] * 0.998):
                    post_tag_holds = False
                    break

        top_box, _bot = calculate_darvas_box(highs, lows, boxp=5)
        top_now = float(top_box[i]) if np.isfinite(top_box[i]) else np.nan
        if np.isfinite(top_now) and top_now > 0 and c < top_now:
            sq_now = ((top_now - e10) / top_now) * 100.0
            sq_prior = (
                ((float(top_box[i - 5]) - float(ema10[i - 5])) / float(top_box[i - 5])) * 100.0
                if i >= 5 and np.isfinite(top_box[i - 5]) and float(top_box[i - 5]) > 0
                else np.nan
            )
            tightening = bool(np.isfinite(sq_now) and np.isfinite(sq_prior) and sq_now < sq_prior)
            if tightening and 0.0 <= sq_now <= 8.0:
                continue

        away = ((c / e10) - 1.0) * 100.0
        recent_closes = closes[max(0, i - 4) : i + 1]
        max_close_5 = float(np.nanmax(recent_closes)) if len(recent_closes) else np.nan
        near_held_highs = (
            np.isfinite(max_close_5)
            and max_close_5 > 0
            and ((max_close_5 - c) / max_close_5) * 100.0 <= catchup_high_tol_pct
        )
        away_prior = ((closes[i - 3] / ema10[i - 3]) - 1.0) * 100.0 if i >= 3 and ema10[i - 3] > 0 else np.nan
        ema_catching = (np.isfinite(away_prior) and away < away_prior) or (
            i >= 5 and ema10[i - 5] > 0 and (e10 / ema10[i - 5] - 1.0) >= 0.005
        )
        flavor: str | None = None
        signal_i = i
        dry_enough = (not np.isfinite(rv)) or rv <= max_rvol
        catchup_vol_ok = (not np.isfinite(rv)) or rv <= catchup_max_rvol

        traceback_i = None
        for ti in reversed(tag_idxs):
            if ti < i and np.isfinite(closes[ti]) and closes[ti] > 0 and c > closes[ti] * 1.003:
                holds = True
                for j in range(ti, i + 1):
                    if not (np.isfinite(closes[j]) and np.isfinite(ema10[j]) and closes[j] >= ema10[j] * 0.998):
                        holds = False
                        break
                if holds:
                    traceback_i = ti
                    break

        if last_tags and abs(away) <= max_away_ema_pct and dry_enough:
            flavor = "Pullback"
        elif traceback_i is not None and 0.3 <= away <= traceback_max_away_pct:
            flavor = "Trace-back"
            signal_i = traceback_i
        elif abs(away) <= max_away_ema_pct and dry_enough and (last_tags or (tag_i is not None and i - tag_i <= 2)):
            flavor = "Pullback"
            if tag_i is not None:
                signal_i = tag_i
        elif (
            near_held_highs
            and 1.5 <= away <= catchup_max_away_pct
            and catchup_vol_ok
            and ema_catching
        ):
            flavor = "Catch-up"
        if flavor is None:
            continue

        signal_date = pd.Timestamp(g[date_col].iloc[signal_i]).date()
        rows.append(
            {
                "symbol": sym,
                "flavor": flavor,
                "ema_10": e10,
                "away_10ema_pct": round(away, 2),
                "rvol": round(rv, 3) if np.isfinite(rv) else np.nan,
                "thrust_pct": round(thrust_pct, 2),
                "qualifies": True,
                "signal_date": signal_date,
            }
        )

    if not rows:
        return empty
    return pd.DataFrame(rows, columns=cols)
