"""Minervini Trend Template (SMA) and successive T (contraction) geometry.

Live helpers so the UI can show SMA 50/150/200 and 1T–4T without waiting
for a full indicators rebuild. Pipeline calc_indicators also writes SMA
columns on the next EOD run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

try:
    from indicators import sma
except ModuleNotFoundError:
    from Scripts.indicators import sma  # type: ignore


TEMPLATE_CHECKS = (
    ("price_gt_150_200", "Price > 150 SMA and 200 SMA"),
    ("sma_150_gt_200", "150 SMA > 200 SMA"),
    ("sma_200_rising", "200 SMA rising 1 month"),
    ("sma_50_stack", "50 SMA > 150 SMA and 200 SMA"),
    ("price_gt_50", "Price > 50 SMA"),
    ("off_52w_low", "≥30% above 52-week low"),
    ("near_52w_high", "Within 25% of 52-week high"),
    ("rs_70", "RS ≥ 70"),
)


@dataclass
class Contraction:
    label: str
    start_date: Any
    trough_date: Any
    end_date: Any
    peak: float
    trough: float
    depth_pct: float
    bars: int
    volume_ratio: float


@dataclass
class TSequence:
    contractions: list[Contraction] = field(default_factory=list)
    pivot: float | None = None
    stop: float | None = None
    weeks: int | None = None
    footprint: str = "—"


def load_ohlcv(db_path: Path, symbol: str, lookback: int = 400) -> pd.DataFrame:
    sym = str(symbol).strip().upper()
    with duckdb.connect(str(db_path), read_only=True) as db:
        frame = db.execute(
            """
            SELECT trade_date, open_price, high_price, low_price, close_price, volume
            FROM prices_daily
            WHERE symbol = ?
            ORDER BY trade_date
            """,
            [sym],
        ).fetchdf()
    if frame.empty:
        return frame
    return frame.tail(lookback).reset_index(drop=True)


def load_template_context(db_path: Path, symbol: str) -> dict[str, Any]:
    """Latest close, RS, 52w distance from indicators_daily (live SMA from prices)."""
    ohlcv = load_ohlcv(db_path, symbol, lookback=260)
    ctx: dict[str, Any] = {"symbol": str(symbol).strip().upper()}
    if ohlcv.empty:
        return ctx
    close = pd.to_numeric(ohlcv["close_price"], errors="coerce")
    ctx["close"] = float(close.iloc[-1])
    ctx["sma_50"] = float(sma(close, 50).iloc[-1]) if len(close) >= 50 else None
    ctx["sma_150"] = float(sma(close, 150).iloc[-1]) if len(close) >= 150 else None
    ctx["sma_200"] = float(sma(close, 200).iloc[-1]) if len(close) >= 200 else None
    sma200 = sma(close, 200)
    ctx["sma_200_rising"] = bool(sma200.iloc[-1] > sma200.iloc[-21]) if len(sma200.dropna()) > 21 else False
    with duckdb.connect(str(db_path), read_only=True) as db:
        row = db.execute(
            """
            SELECT rs_percentile, away_52w_low_pct, distance_below_52w, ema_10, ema_20, ema_50, ema_100, ema_200,
                   ema_stack_bullish, close_price
            FROM indicators_daily
            WHERE symbol = ?
            ORDER BY trade_date DESC
            LIMIT 1
            """,
            [ctx["symbol"]],
        ).fetchone()
        cols = [
            "rs_percentile",
            "away_52w_low_pct",
            "distance_below_52w",
            "ema_10",
            "ema_20",
            "ema_50",
            "ema_100",
            "ema_200",
            "ema_stack_bullish",
            "close_price",
        ]
        if row:
            ctx.update({k: row[i] for i, k in enumerate(cols)})
    return ctx


def evaluate_trend_template(ctx: dict[str, Any]) -> dict[str, Any]:
    close = ctx.get("close") or ctx.get("close_price")
    sma50, sma150, sma200 = ctx.get("sma_50"), ctx.get("sma_150"), ctx.get("sma_200")
    checks = {
        "price_gt_150_200": bool(close and sma150 and sma200 and close > sma150 and close > sma200),
        "sma_150_gt_200": bool(sma150 and sma200 and sma150 > sma200),
        "sma_200_rising": bool(ctx.get("sma_200_rising")),
        "sma_50_stack": bool(sma50 and sma150 and sma200 and sma50 > sma150 and sma50 > sma200),
        "price_gt_50": bool(close and sma50 and close > sma50),
        "off_52w_low": bool(pd.notna(ctx.get("away_52w_low_pct")) and float(ctx["away_52w_low_pct"]) >= 30),
        "near_52w_high": bool(pd.notna(ctx.get("distance_below_52w")) and float(ctx["distance_below_52w"]) <= 25),
        "rs_70": bool(pd.notna(ctx.get("rs_percentile")) and float(ctx["rs_percentile"]) >= 70),
    }
    n = sum(1 for v in checks.values() if v)
    return {
        "checks": checks,
        "pass_n": n,
        "pass_all": n == 8,
        "label": f"{n}/8",
        "rows": [(key, label, checks[key]) for key, label in TEMPLATE_CHECKS],
    }


def _fractal_indices(series: pd.Series, *, kind: str, left: int = 2, right: int = 2) -> list[int]:
    idx: list[int] = []
    values = series.to_numpy()
    n = len(values)
    for i in range(left, n - right):
        window = values[i - left : i + right + 1]
        if kind == "high" and values[i] >= window.max() and (window == values[i]).sum() == 1:
            idx.append(i)
        if kind == "low" and values[i] <= window.min() and (window == values[i]).sum() == 1:
            idx.append(i)
    return idx


def detect_contractions(ohlcv: pd.DataFrame, *, min_bars: int = 8, min_depth: float = 3.0) -> TSequence:
    """Named Ts after the last ≥20% advance. Expanding swing ends the sequence."""
    result = TSequence()
    if ohlcv is None or len(ohlcv) < 30:
        return result
    high = pd.to_numeric(ohlcv["high_price"], errors="coerce")
    low = pd.to_numeric(ohlcv["low_price"], errors="coerce")
    vol = pd.to_numeric(ohlcv["volume"], errors="coerce") if "volume" in ohlcv.columns else pd.Series(1.0, index=ohlcv.index)
    dates = ohlcv["trade_date"]
    peaks = _fractal_indices(high, kind="high")
    troughs = _fractal_indices(low, kind="low")
    if len(peaks) < 2 or len(troughs) < 1:
        return result

    # Last ≥20% rally: peak whose high is ≥20% above a prior trough.
    base_peak_i = None
    for p in reversed(peaks):
        prior = [t for t in troughs if t < p]
        if not prior:
            continue
        t = prior[-1]
        if high.iloc[t] and (high.iloc[p] / low.iloc[t] - 1) >= 0.20:
            base_peak_i = p
            break
    if base_peak_i is None:
        base_peak_i = peaks[-1]

    # Walk peaks after the base-start peak; each peak-to-next-trough-to-next-peak is a T.
    later_peaks = [p for p in peaks if p >= base_peak_i]
    contractions: list[Contraction] = []
    prev_depth = 999.0
    for i, p in enumerate(later_peaks[:-1]):
        next_p = later_peaks[i + 1]
        mid_troughs = [t for t in troughs if p < t < next_p]
        if not mid_troughs:
            continue
        t = min(mid_troughs, key=lambda j: low.iloc[j])
        bars = int(next_p - p)
        if bars < min_bars:
            continue
        peak_px = float(high.iloc[p])
        trough_px = float(low.iloc[t])
        if peak_px <= 0:
            continue
        depth = (peak_px - trough_px) / peak_px * 100
        if depth < min_depth:
            continue
        if depth >= prev_depth:
            break
        avg_base = float(vol.iloc[max(0, p - 20) : p + 1].mean() or 1)
        avg_t = float(vol.iloc[p : next_p + 1].mean() or 1)
        contractions.append(
            Contraction(
                label=f"{len(contractions) + 1}T",
                start_date=dates.iloc[p],
                trough_date=dates.iloc[t],
                end_date=dates.iloc[next_p],
                peak=peak_px,
                trough=trough_px,
                depth_pct=depth,
                bars=bars,
                volume_ratio=avg_t / avg_base if avg_base else 1.0,
            )
        )
        prev_depth = depth
        if len(contractions) >= 4:
            break

    result.contractions = contractions
    if contractions:
        last = contractions[-1]
        result.pivot = last.peak
        result.stop = last.trough
        first = contractions[0]
        result.weeks = max(1, int(round(sum(c.bars for c in contractions) / 5)))
        result.footprint = f"{result.weeks}W {first.depth_pct:.0f}/{last.depth_pct:.0f} {len(contractions)}T"
    return result


def ema_stack_label(ctx: dict[str, Any]) -> str:
    e10, e20, e50, e100, e200 = (ctx.get(k) for k in ("ema_10", "ema_20", "ema_50", "ema_100", "ema_200"))
    if ctx.get("ema_stack_bullish"):
        return "10>20>50>100>200"
    parts = []
    seq = [("10", e10), ("20", e20), ("50", e50), ("100", e100), ("200", e200)]
    for (a, av), (b, bv) in zip(seq, seq[1:]):
        if av is None or bv is None or pd.isna(av) or pd.isna(bv):
            continue
        parts.append(f"{a}>" if av > bv else f"{a}<")
    return "".join(parts) + "200" if parts else "—"


def t_graph_svg(seq: TSequence, *, width: int = 520, height: int = 220) -> str:
    """Schematic 1T–4T path. Empty sequence still draws the axis and a note."""
    gold = "#c9a227"
    ink = "#12151c"
    fail = "#c0392b"
    muted = "#5c5648"
    ts = seq.contractions[:4]
    n = len(ts)
    if not ts:
        return f"""<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img" aria-label="No VCP Ts">
  <text x="24" y="110" font-size="13" fill="{muted}" font-family="IBM Plex Sans,sans-serif">No named Ts yet. Need 2+ decreasing pullbacks after a 20%+ Stage-2 advance.</text>
</svg>"""
    path = ["M 24 70 L 70 36"]
    labels = []
    x = 70
    y = 36
    depths = [c.depth_pct for c in ts]
    max_d = max(depths)
    for i, depth in enumerate(depths[:4]):
        drop = 18 + 70 * (depth / max_d)
        rise = drop * 0.62
        x2 = x + 70
        y2 = y + drop
        x3 = x2 + 48
        y3 = y2 - rise
        path.append(f"L {x2:.1f} {y2:.1f} L {x3:.1f} {y3:.1f}")
        labels.append((x2 + 4, y2 + 14, f"{i+1}T {depth:.0f}%"))
        x, y = x3, y3
    pivot_y = y
    stop_y = min(height - 40, y + 22)
    vol_x0 = 90
    vol_html = []
    for i, c in enumerate(ts or [None, None, None]):
        h = 36 - i * 8
        vx = vol_x0 + i * 88
        fill = gold if i >= max(0, n - 2) else ink
        vol_html.append(f'<rect x="{vx}" y="{height-28-h}" width="16" height="{h}" fill="{fill}" opacity="0.55"/>')
    label_html = "".join(
        f'<text x="{lx}" y="{ly}" font-size="11" font-weight="700" fill="{ink}" font-family="IBM Plex Mono,monospace">{txt}</text>'
        for lx, ly, txt in labels
    )
    note = seq.footprint if seq.contractions else "No named Ts yet — need 2+ decreasing pullbacks after a 20%+ advance"
    return f"""<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img" aria-label="VCP 1T 2T 3T 4T graph">
  <path d="{' '.join(path)}" fill="none" stroke="{ink}" stroke-width="2.4" stroke-linejoin="round"/>
  <line x1="{x}" y1="{pivot_y}" x2="{width-16}" y2="{pivot_y}" stroke="{gold}" stroke-width="1.3" stroke-dasharray="5 4"/>
  <line x1="{x-40}" y1="{stop_y}" x2="{width-16}" y2="{stop_y}" stroke="{fail}" stroke-width="1.3" stroke-dasharray="4 3"/>
  <text x="{width-70}" y="{pivot_y-6}" font-size="10" fill="{gold}" font-family="IBM Plex Mono,monospace">PIVOT</text>
  <text x="{width-70}" y="{stop_y+12}" font-size="10" fill="{fail}" font-family="IBM Plex Mono,monospace">STOP</text>
  {label_html}
  {''.join(vol_html)}
  <text x="8" y="{height-8}" font-size="10" fill="{muted}" font-family="IBM Plex Mono,monospace">{note}</text>
</svg>"""
