"""Manas Focus — EOD focus-list chips for Action Desk primary #3.

Hard gates (Screener Desk + Siddhant):
- ema_shakeout on signal bar
- raw ret_63d >= +30% (fail closed if hist short; no rs_3m_percentile soft gate)
- purple density: >=3 days in 63d with |ret|>=5% and volume>=1M
  (500k is a documented soft alt only — do not loosen v1 silently)
- close_price >= 30
- ema_10 rising is SOFT rank only (not a hard exclude)

Universe merge with setup_pool enforces mcap/band/ADV.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

MANAS = dict(
    purple_lookback=63,
    purple_abs_ret=0.05,
    purple_min_volume=1_000_000,  # AD primary default; soft alt 500_000 later only
    purple_min_volume_soft_alt=500_000,
    purple_min_count=3,
    min_ret_3m=0.30,
    ret_3m_sessions=63,
    min_avg_volume_20d=200_000,
    min_close_price=30.0,
)


def _pick_col(df: pd.DataFrame, *names: str) -> str | None:
    for name in names:
        if name in df.columns:
            return name
    return None


def purple_density(
    volume: np.ndarray,
    close: np.ndarray,
    *,
    lookback: int = 63,
    abs_ret: float = 0.05,
    min_volume: float = 1_000_000,
) -> int:
    if close is None or len(close) < 2:
        return 0
    n = len(close)
    start = max(1, n - int(lookback))
    count = 0
    for i in range(start, n):
        prev = close[i - 1]
        if not (np.isfinite(prev) and prev > 0 and np.isfinite(close[i])):
            continue
        ret = abs(float(close[i]) / float(prev) - 1.0)
        vol = volume[i] if volume is not None and i < len(volume) else np.nan
        if ret >= abs_ret and np.isfinite(vol) and float(vol) >= min_volume:
            count += 1
    return int(count)


def ret_3m_pct(close: np.ndarray, sessions: int = 63) -> float:
    """Raw 63-session return in percent. NaN if hist too short (fail closed)."""
    if close is None or len(close) <= sessions:
        return float("nan")
    a = float(close[-1])
    b = float(close[-(sessions + 1)])
    if not (np.isfinite(a) and np.isfinite(b) and b > 0):
        return float("nan")
    return (a / b - 1.0) * 100.0


def classify_manas_focus_frame(
    daily: pd.DataFrame,
    *,
    cfg: dict[str, Any] | None = None,
) -> pd.DataFrame:
    params = dict(MANAS)
    if cfg:
        params.update(cfg)
    cols = [
        "symbol",
        "purple_n",
        "ret_3m_pct",
        "close_location_pct",
        "ema_rising",
        "avg_volume_20d",
        "ema_shakeout",
        "qualifies",
    ]
    empty = pd.DataFrame(columns=cols)
    if daily is None or daily.empty:
        return empty

    frame = daily.copy()
    sym_col = _pick_col(frame, "symbol")
    date_col = _pick_col(frame, "trade_date", "date")
    close_col = _pick_col(frame, "close_price", "close")
    vol_col = _pick_col(frame, "volume")
    shake_col = _pick_col(frame, "ema_shakeout")
    cl_col = _pick_col(frame, "close_location_pct")
    ema10_col = _pick_col(frame, "ema_10", "ema10")
    avgvol_col = _pick_col(frame, "avg_volume_20d")
    if not all([sym_col, date_col, close_col, vol_col]):
        return empty
    if shake_col is None:
        return empty

    rows: list[dict[str, Any]] = []
    lb = int(params["purple_lookback"])
    min_close = float(params["min_close_price"])
    for sym, group in frame.groupby(sym_col, sort=False):
        g = group.sort_values(date_col)
        if len(g) < max(10, int(params["ret_3m_sessions"]) + 1):
            continue
        closes = g[close_col].to_numpy(dtype=float)
        volumes = g[vol_col].to_numpy(dtype=float)
        last = g.iloc[-1]
        last_close = float(last[close_col])
        if not (np.isfinite(last_close) and last_close >= min_close):
            continue
        if not bool(last[shake_col]):
            continue

        r3 = ret_3m_pct(closes, sessions=int(params["ret_3m_sessions"]))
        if not (np.isfinite(r3) and r3 >= float(params["min_ret_3m"]) * 100.0):
            continue

        purple_n = purple_density(
            volumes,
            closes,
            lookback=lb,
            abs_ret=float(params["purple_abs_ret"]),
            min_volume=float(params["purple_min_volume"]),
        )
        if purple_n < int(params["purple_min_count"]):
            continue

        avg_vol = float(last[avgvol_col]) if avgvol_col is not None and pd.notna(last[avgvol_col]) else np.nan
        if np.isfinite(avg_vol) and avg_vol < float(params["min_avg_volume_20d"]):
            continue

        ema_rising = False
        if ema10_col is not None and len(g) >= 2:
            e0 = float(g[ema10_col].iloc[-1])
            e1 = float(g[ema10_col].iloc[-2])
            ema_rising = bool(np.isfinite(e0) and np.isfinite(e1) and e0 > e1)

        cl = float(last[cl_col]) if cl_col is not None and pd.notna(last[cl_col]) else np.nan
        rows.append(
            {
                "symbol": sym,
                "purple_n": purple_n,
                "ret_3m_pct": round(float(r3), 2),
                "close_location_pct": round(cl, 1) if np.isfinite(cl) else np.nan,
                "ema_rising": ema_rising,
                "avg_volume_20d": round(avg_vol, 0) if np.isfinite(avg_vol) else np.nan,
                "ema_shakeout": True,
                "qualifies": True,
            }
        )

    if not rows:
        return empty
    out = pd.DataFrame(rows, columns=cols)
    # Soft rank: rising 10 EMA first, then purple, then 3M force
    out = out.sort_values(
        ["ema_rising", "purple_n", "ret_3m_pct"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    return out
