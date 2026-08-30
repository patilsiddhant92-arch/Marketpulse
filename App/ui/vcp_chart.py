"""OHLC VCP chart: candles + SMA 50/150/200 + contraction regions + pivot/stop."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
from nicegui import ui

try:
    from Scripts.indicators import sma
    from Scripts.minervini_geometry import detect_contractions, load_ohlcv, load_template_context
except ModuleNotFoundError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "Scripts"))
    from indicators import sma  # type: ignore
    from minervini_geometry import detect_contractions, load_ohlcv, load_template_context  # type: ignore


def render_vcp_ohlc(db_path: Path, symbol: str, *, bars: int = 180) -> None:
    """Draw a real candlestick VCP, not a schematic."""
    ohlcv = load_ohlcv(db_path, symbol, lookback=max(bars, 220))
    if ohlcv.empty or len(ohlcv) < 30:
        ui.label(f"Not enough OHLC for {symbol}.").classes("text-sm text-[var(--mp-muted)]")
        return
    frame = ohlcv.tail(bars).reset_index(drop=True)
    close = pd.to_numeric(frame["close_price"], errors="coerce")
    high = pd.to_numeric(frame["high_price"], errors="coerce")
    low = pd.to_numeric(frame["low_price"], errors="coerce")
    op = pd.to_numeric(frame["open_price"], errors="coerce")
    dates = pd.to_datetime(frame["trade_date"]).dt.strftime("%Y-%m-%d").tolist()
    candles = [
        [None if pd.isna(o) else float(o), None if pd.isna(c) else float(c), None if pd.isna(l) else float(l), None if pd.isna(h) else float(h)]
        for o, c, l, h in zip(op, close, low, high)
    ]
    seq = detect_contractions(ohlcv)
    def _line(series: pd.Series) -> list:
        return [None if pd.isna(v) else float(round(float(v), 2)) for v in series]

    s50 = _line(sma(close, 50))
    s150 = _line(sma(close, 150)) if len(close) >= 150 else [None] * len(close)
    s200 = _line(sma(close, 200)) if len(close) >= 200 else [None] * len(close)

    date_set = set(dates)
    mark_areas = []
    palette = ["rgba(201,162,39,0.16)", "rgba(31,138,76,0.12)", "rgba(88,166,255,0.12)", "rgba(192,57,43,0.10)"]
    for i, c in enumerate(seq.contractions[:4]):
        a = str(pd.Timestamp(c.start_date).date())
        b = str(pd.Timestamp(c.end_date).date())
        if a not in date_set:
            a = min(dates, key=lambda d: abs(pd.Timestamp(d) - pd.Timestamp(c.start_date)))
        if b not in date_set:
            b = min(dates, key=lambda d: abs(pd.Timestamp(d) - pd.Timestamp(c.end_date)))
        mark_areas.append(
            [
                {"xAxis": a, "itemStyle": {"color": palette[i % 4]}, "name": c.label},
                {"xAxis": b},
            ]
        )
    mark_lines = []
    if seq.pivot:
        mark_lines.append({"yAxis": round(seq.pivot, 2), "name": "Pivot", "label": {"formatter": "Pivot"}, "lineStyle": {"color": "#c9a227", "type": "dashed", "width": 1.5}})
    if seq.stop:
        mark_lines.append({"yAxis": round(seq.stop, 2), "name": "Stop", "label": {"formatter": "Stop"}, "lineStyle": {"color": "#c0392b", "type": "dashed", "width": 1.5}})

    ui.echart(
        {
            "backgroundColor": "transparent",
            "animation": False,
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "cross"}},
            "legend": {
                "top": 0,
                "textStyle": {"color": "#d8d0c0", "fontSize": 13},
                "data": ["OHLC", "SMA 50", "SMA 150", "SMA 200"],
            },
            "grid": {"left": 56, "right": 16, "top": 28, "bottom": 28},
            "xAxis": {
                "type": "category",
                "data": dates,
                "axisLabel": {"color": "#d8d0c0", "fontSize": 12, "hideOverlap": True},
                "axisLine": {"lineStyle": {"color": "#2a261c"}},
            },
            "yAxis": {
                "scale": True,
                "axisLabel": {"color": "#d8d0c0", "fontSize": 12},
                "splitLine": {"lineStyle": {"color": "#2a261c"}},
            },
            "dataZoom": [{"type": "inside"}, {"type": "slider", "height": 16, "bottom": 4}],
            "series": [
                {
                    "name": "OHLC",
                    "type": "candlestick",
                    "data": candles,
                    "itemStyle": {
                        "color": "#1f8a4c",
                        "color0": "#c0392b",
                        "borderColor": "#1f8a4c",
                        "borderColor0": "#c0392b",
                    },
                    "markArea": {"silent": True, "data": mark_areas} if mark_areas else None,
                    "markLine": {"symbol": "none", "data": mark_lines} if mark_lines else None,
                },
                {"name": "SMA 50", "type": "line", "data": s50, "showSymbol": False, "lineStyle": {"width": 1.2, "color": "#58a6ff"}},
                {"name": "SMA 150", "type": "line", "data": s150, "showSymbol": False, "lineStyle": {"width": 1.2, "color": "#c9a227"}},
                {"name": "SMA 200", "type": "line", "data": s200, "showSymbol": False, "lineStyle": {"width": 1.6, "color": "#e6edf3"}},
            ],
        }
    ).classes("w-full h-[440px]")
    labels = [f"{c.label} {c.depth_pct:.1f}%" for c in seq.contractions]
    ui.label(
        f"{seq.footprint}  ·  " + (" → ".join(labels) if labels else "no named Ts yet")
    ).classes("text-xs text-[var(--mp-muted)] mt-1")
    _render_rs_vs_nifty(db_path, dates, close)


def _nifty_closes(db_path: Path) -> pd.DataFrame:
    with duckdb.connect(str(db_path), read_only=True) as db:
        return db.execute(
            """
            SELECT trade_date, close_price
            FROM index_daily
            WHERE lower(index_name) IN ('nifty 50', 'nifty50')
               OR lower(index_name) LIKE 'nifty 50%'
            ORDER BY trade_date
            """
        ).fetchdf()


def _render_rs_vs_nifty(db_path: Path, dates: list[str], close: pd.Series) -> None:
    nifty = _nifty_closes(db_path)
    if nifty.empty or close.empty:
        ui.label("No Nifty 50 series for RS line.").classes("text-xs text-[var(--mp-muted)]")
        return
    nifty["trade_date"] = pd.to_datetime(nifty["trade_date"]).dt.strftime("%Y-%m-%d")
    aligned = pd.DataFrame({"trade_date": dates, "stock": pd.to_numeric(close, errors="coerce")})
    aligned = aligned.merge(nifty.rename(columns={"close_price": "nifty"}), on="trade_date", how="inner")
    aligned = aligned.dropna()
    if len(aligned) < 10:
        ui.label("Not enough overlapping Nifty bars for RS line.").classes("text-xs text-[var(--mp-muted)]")
        return
    base_stock = float(aligned["stock"].iloc[0])
    base_nifty = float(aligned["nifty"].iloc[0])
    if base_stock <= 0 or base_nifty <= 0:
        return
    ratio = (aligned["stock"] / aligned["nifty"]) / (base_stock / base_nifty) * 100
    ui.label("RS vs Nifty 50 (100 = start of window)").classes("mp-section-title mt-3")
    ui.echart(
        {
            "backgroundColor": "transparent",
            "animation": False,
            "tooltip": {"trigger": "axis"},
            "grid": {"left": 48, "right": 16, "top": 12, "bottom": 24},
            "xAxis": {
                "type": "category",
                "data": aligned["trade_date"].tolist(),
                "axisLabel": {"color": "#d8d0c0", "fontSize": 12, "hideOverlap": True},
            },
            "yAxis": {
                "scale": True,
                "axisLabel": {"color": "#d8d0c0", "fontSize": 12},
                "splitLine": {"lineStyle": {"color": "#2a261c"}},
            },
            "series": [
                {
                    "name": "RS vs Nifty",
                    "type": "line",
                    "showSymbol": False,
                    "data": [round(float(v), 2) for v in ratio],
                    "lineStyle": {"width": 1.6, "color": "#c9a227"},
                    "markLine": {
                        "symbol": "none",
                        "data": [{"yAxis": 100, "lineStyle": {"color": "#a89f8e", "type": "dotted"}}],
                    },
                }
            ],
        }
    ).classes("w-full h-[180px]")
