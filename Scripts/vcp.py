"""Manas Arora Volatility Contraction Pattern (VCP) Engine.

Implements Manas Arora's swing trading VCP methodology (adapted from Mark Minervini SEPA):
1. Stage 2 Technical Template: Price > 200 EMA, within 25% of 52-week high, prior uptrend (+20%+ in 3M).
2. Progressive Contraction Waves: Successive pullbacks contracting in depth (T1 > T2 > T3 / T4).
3. Volume Dry-Up (VDU): Supply exhaustion where 3-day volume shrinks relative to 20-day average (VDU ratio <= 0.80).
4. Pivot & Stop Loss: Trigger entry at pivot breakout (or tight coil cheat entry near 10/20 EMA); Stop Loss at the low of the final contraction wave (strictly controlling risk to 3-5%).
5. Trailing: 10 EMA (fast momentum) or 20 EMA (wider swing).

Universe merge with setup_pool enforces market cap, band, and ADV liquidity.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

VCP = dict(
    min_ret_3m=0.20,  # Prior 3-month momentum requirement (+20%)
    ret_3m_sessions=63,
    max_away_52w_high_pct=-25.0,  # Within 25% of 52W high
    min_avg_volume_20d=100_000,
    min_close_price=30.0,
    vdu_threshold=0.80,  # Volume Dry-Up ratio (3D vol / 20D vol)
    super_vdu_threshold=0.60,
    purple_lookback=63,
    purple_abs_ret=0.05,
    purple_min_volume=1_000_000,
    purple_min_volume_soft_alt=500_000,
    purple_min_count=0,  # Soft ranking factor in Manas VCP
    require_shakeout=False,  # Shakeout is an optional confirmation, not a hard barrier
    require_min_ret_3m=False,  # Prior force preferred, soft fallback if history short
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


def analyze_manas_vcp(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
) -> dict[str, Any]:
    """Detect Manas Arora (Minervini SEPA) Volatility Contraction Pattern geometry.

    Identifies:
    - Progressive contraction stages (T1 -> T2 -> T3) with decreasing depth %
    - Volume Dry-Up (VDU) in final contraction (supply exhaustion)
    - Pivot resistance level, breakout proximity, and contraction stop-loss level
    """
    n = len(closes)
    if n < 15:
        return {
            "vcp_stage": "Developing",
            "contractions": [],
            "contractions_depth": "—",
            "vdu_active": False,
            "vdu_ratio": 1.0,
            "pivot_price": float(np.nanmax(highs[-15:])) if n > 0 else 0.0,
            "stop_price": float(np.nanmin(lows[-15:])) if n > 0 else 0.0,
            "pivot_distance_pct": 0.0,
            "vcp_score": 0.0,
        }

    lookback = min(n, 50)
    w_highs = highs[-lookback:]
    w_lows = lows[-lookback:]
    w_closes = closes[-lookback:]
    w_volumes = volumes[-lookback:]

    # Detect discrete swing highs and swing lows (2-bar local extrema)
    pivots_high: list[tuple[int, float]] = []
    pivots_low: list[tuple[int, float]] = []
    for i in range(2, lookback - 2):
        if (
            w_highs[i] >= w_highs[i - 1]
            and w_highs[i] >= w_highs[i - 2]
            and w_highs[i] >= w_highs[i + 1]
            and w_highs[i] >= w_highs[i + 2]
        ):
            pivots_high.append((i, float(w_highs[i])))
        if (
            w_lows[i] <= w_lows[i - 1]
            and w_lows[i] <= w_lows[i - 2]
            and w_lows[i] <= w_lows[i + 1]
            and w_lows[i] <= w_lows[i + 2]
        ):
            pivots_low.append((i, float(w_lows[i])))

    contractions: list[float] = []
    last_swing_low = float(np.nanmin(w_lows[-10:])) if len(w_lows) >= 10 else float(np.nanmin(w_lows))

    if len(pivots_high) >= 2 and len(pivots_low) >= 2:
        for ph, pl in zip(pivots_high[-4:], pivots_low[-4:]):
            if ph[1] > 0 and pl[1] <= ph[1]:
                depth = round(((ph[1] - pl[1]) / ph[1]) * 100.0, 1)
                if 1.0 <= depth <= 35.0:
                    contractions.append(depth)
        if pivots_low:
            last_swing_low = pivots_low[-1][1]

    # Fallback to 3-segment progressive window analysis if fewer than 2 discrete pivot pairs
    if len(contractions) < 2:
        step = lookback // 3
        if step >= 4:
            seg1_h = float(np.nanmax(w_highs[:step]))
            seg1_l = float(np.nanmin(w_lows[:step]))
            d1 = round(((seg1_h - seg1_l) / seg1_h) * 100.0, 1) if seg1_h > 0 else 0.0

            seg2_h = float(np.nanmax(w_highs[step : 2 * step]))
            seg2_l = float(np.nanmin(w_lows[step : 2 * step]))
            d2 = round(((seg2_h - seg2_l) / seg2_h) * 100.0, 1) if seg2_h > 0 else 0.0

            seg3_h = float(np.nanmax(w_highs[2 * step :]))
            seg3_l = float(np.nanmin(w_lows[2 * step :]))
            d3 = round(((seg3_h - seg3_l) / seg3_h) * 100.0, 1) if seg3_h > 0 else 0.0

            if d1 > 0 and d2 > 0 and d3 > 0:
                contractions = [d1, d2, d3]
                last_swing_low = seg3_l

    vcp_stage = "Consolidating"
    if len(contractions) >= 3 and contractions[0] > contractions[1] > contractions[2]:
        vcp_stage = "3T VCP"
    elif len(contractions) >= 2 and contractions[-2] > contractions[-1]:
        vcp_stage = "2T VCP"
    elif len(contractions) >= 1 and contractions[-1] <= 6.0:
        vcp_stage = "Tight Coil"

    depth_str = " → ".join(f"{d:.1f}%" for d in contractions) if contractions else "—"

    # Volume Dry-Up (VDU) in right side of base
    v20 = float(np.nanmean(w_volumes[-20:])) if len(w_volumes) >= 20 else float(np.nanmean(w_volumes))
    v3 = float(np.nanmean(w_volumes[-3:])) if len(w_volumes) >= 3 else v20
    vdu_ratio = round(float(v3 / v20), 2) if np.isfinite(v20) and v20 > 0 else 1.0
    vdu_active = bool(vdu_ratio <= 0.80)
    vdu_super_dry = bool(vdu_ratio <= 0.60)

    # Pivot level & distance
    pivot_price = round(float(np.nanmax(w_highs)), 2)
    curr_close = float(closes[-1])
    pivot_dist_pct = round(((curr_close / pivot_price) - 1.0) * 100.0, 1) if pivot_price > 0 else 0.0
    stop_price = round(float(last_swing_low), 2)

    # Composite Manas VCP Score (0 to 100)
    score = 35.0
    if vcp_stage == "3T VCP":
        score += 35.0
    elif vcp_stage == "2T VCP":
        score += 25.0
    elif vcp_stage == "Tight Coil":
        score += 18.0

    if vdu_super_dry:
        score += 20.0
    elif vdu_active:
        score += 15.0

    # Near pivot bonus (-4.0% to +1.0%)
    if -4.0 <= pivot_dist_pct <= 1.0:
        score += 15.0

    # Extra tightness in final contraction
    if contractions and contractions[-1] <= 5.0:
        score += 5.0

    return {
        "vcp_stage": vcp_stage,
        "contractions": contractions,
        "contractions_depth": depth_str,
        "vdu_active": vdu_active,
        "vdu_ratio": vdu_ratio,
        "pivot_price": pivot_price,
        "stop_price": stop_price,
        "pivot_distance_pct": pivot_dist_pct,
        "vcp_score": round(min(score, 100.0), 1),
    }


def classify_vcp_frame(
    daily: pd.DataFrame,
    *,
    cfg: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Classify candidate symbols under the Manas Arora VCP framework.

    Evaluates:
    - Stage 2 template compliance (Price > 200 EMA, within 25% of 52W high)
    - Progressive contraction stages (T1 > T2 > T3)
    - Volume Dry-Up (VDU <= 0.80)
    - Pivot resistance level, breakout proximity, and contraction stop loss
    """
    params = dict(VCP)
    if cfg:
        params.update(cfg)

    cols = [
        "symbol",
        "vcp_stage",
        "contractions_depth",
        "vdu_active",
        "vdu_ratio",
        "pivot_price",
        "stop_price",
        "pivot_distance_pct",
        "vcp_score",
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
    high_col = _pick_col(frame, "high_price", "high")
    low_col = _pick_col(frame, "low_price", "low")
    vol_col = _pick_col(frame, "volume")
    shake_col = _pick_col(frame, "ema_shakeout")
    cl_col = _pick_col(frame, "close_location_pct")
    ema10_col = _pick_col(frame, "ema_10", "ema10")
    ema200_col = _pick_col(frame, "ema_200", "ema200")
    away_52w_col = _pick_col(frame, "away_52w_high_pct")
    avgvol_col = _pick_col(frame, "avg_volume_20d")

    if not all([sym_col, date_col, close_col, vol_col]):
        return empty

    rows: list[dict[str, Any]] = []
    lb = int(params["purple_lookback"])
    min_close = float(params["min_close_price"])
    req_shakeout = bool(params.get("require_shakeout", False))
    req_min_r3 = bool(params.get("require_min_ret_3m", False))
    min_purple = int(params.get("purple_min_count", 0))

    for sym, group in frame.groupby(sym_col, sort=False):
        g = group.sort_values(date_col)
        if len(g) < 15:
            continue
        closes = g[close_col].to_numpy(dtype=float)
        highs = g[high_col].to_numpy(dtype=float) if high_col else closes
        lows = g[low_col].to_numpy(dtype=float) if low_col else closes
        volumes = g[vol_col].to_numpy(dtype=float)
        last = g.iloc[-1]
        last_close = float(last[close_col])

        # Minimum absolute price filter
        if not (np.isfinite(last_close) and last_close >= min_close):
            continue

        # Invariant: Stage 2 template — Stock must trade ABOVE 200 EMA
        if ema200_col is not None and pd.notna(last[ema200_col]):
            e200 = float(last[ema200_col])
            if np.isfinite(e200) and last_close < e200:
                continue

        # Invariant: Stage 2 template — Stock must be within 25% of 52-week high
        if away_52w_col is not None and pd.notna(last[away_52w_col]):
            a52 = float(last[away_52w_col])
            if np.isfinite(a52) and a52 < float(params["max_away_52w_high_pct"]):
                continue

        # Optional shakeout gate (legacy / testing switch)
        shake_val = bool(last[shake_col]) if shake_col and pd.notna(last[shake_col]) else False
        if req_shakeout and not shake_val:
            continue

        # Prior 3-month momentum
        r3 = ret_3m_pct(closes, sessions=int(params["ret_3m_sessions"]))
        if req_min_r3 and (np.isnan(r3) or r3 < float(params["min_ret_3m"]) * 100.0):
            continue

        # Purple candle density (soft ranking factor)
        purple_n = purple_density(
            volumes,
            closes,
            lookback=lb,
            abs_ret=float(params["purple_abs_ret"]),
            min_volume=float(params["purple_min_volume"]),
        )
        if purple_n < min_purple:
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

        # Full Manas Arora VCP geometry analysis
        manas_metrics = analyze_manas_vcp(highs, lows, closes, volumes)

        rows.append(
            {
                "symbol": sym,
                "vcp_stage": manas_metrics["vcp_stage"],
                "contractions_depth": manas_metrics["contractions_depth"],
                "vdu_active": manas_metrics["vdu_active"],
                "vdu_ratio": manas_metrics["vdu_ratio"],
                "pivot_price": manas_metrics["pivot_price"],
                "stop_price": manas_metrics["stop_price"],
                "pivot_distance_pct": manas_metrics["pivot_distance_pct"],
                "vcp_score": manas_metrics["vcp_score"],
                "purple_n": purple_n,
                "ret_3m_pct": round(float(r3), 2) if np.isfinite(r3) else np.nan,
                "close_location_pct": round(cl, 1) if np.isfinite(cl) else np.nan,
                "ema_rising": ema_rising,
                "avg_volume_20d": round(avg_vol, 0) if np.isfinite(avg_vol) else np.nan,
                "ema_shakeout": shake_val,
                "qualifies": True,
            }
        )

    if not rows:
        return empty
    out = pd.DataFrame(rows, columns=cols)
    # Rank: highest VCP score (progressive contractions + VDU) first, then pivot proximity, rising EMA, 3M return
    out = out.sort_values(
        ["vcp_score", "pivot_distance_pct", "ema_rising", "ret_3m_pct"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)
    return out
