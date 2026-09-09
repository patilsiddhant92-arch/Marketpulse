"""OHLC VCP chart: candles + SMA 50/150/200 + contraction regions + pivot/stop."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
from nicegui import ui

try:
    from App.ui.widgets import chart_theme
except ModuleNotFoundError:
    from ui.widgets import chart_theme  # type: ignore

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
    theme = chart_theme()

    date_set = set(dates)
    mark_areas = []
    palette = ["rgba(216,172,61,0.16)", "rgba(69,212,131,0.12)", "rgba(116,169,255,0.12)", "rgba(242,124,132,0.10)"]
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
        mark_lines.append({"yAxis": round(seq.pivot, 2), "name": "Pivot", "label": {"formatter": "Pivot"}, "lineStyle": {"color": theme["series"][0], "type": "dashed", "width": 1.5}})
    if seq.stop:
        mark_lines.append({"yAxis": round(seq.stop, 2), "name": "Stop", "label": {"formatter": "Stop"}, "lineStyle": {"color": theme["bad"], "type": "dashed", "width": 1.5}})

    ui.echart(
        {
            "backgroundColor": "transparent",
            "animation": False,
            "tooltip": {
                "trigger": "axis",
                "axisPointer": {"type": "cross"},
                "backgroundColor": theme.get("tooltip_bg", "rgba(15, 23, 42, 0.95)"),
                "borderColor": theme.get("tooltip_border", "#334155"),
                "borderWidth": 1,
                "textStyle": {"color": "#F1F4F8", "fontFamily": "IBM Plex Mono", "fontSize": 11},
            },
            "legend": {
                "top": 0,
                "textStyle": {"color": theme["text"], "fontSize": 12, "fontFamily": "IBM Plex Sans"},
                "data": ["OHLC", "SMA 50", "SMA 150", "SMA 200"],
            },
            "grid": {"left": 56, "right": 16, "top": 28, "bottom": 28},
            "xAxis": {
                "type": "category",
                "data": dates,
                "axisLabel": {"color": theme["text"], "fontSize": 11, "hideOverlap": True},
                "axisLine": {"lineStyle": {"color": theme["grid"]}},
            },
            "yAxis": {
                "scale": True,
                "axisLabel": {"color": theme["text"], "fontSize": 11},
                "splitLine": {"lineStyle": {"color": theme["grid"]}},
            },
            "dataZoom": [{"type": "inside"}, {"type": "slider", "height": 16, "bottom": 4}],
            "series": [
                {
                    "name": "OHLC",
                    "type": "candlestick",
                    "data": candles,
                    "itemStyle": {
                        "color": theme["good"],
                        "color0": theme["bad"],
                        "borderColor": theme["good"],
                        "borderColor0": theme["bad"],
                    },
                    "markArea": {"silent": True, "data": mark_areas} if mark_areas else None,
                    "markLine": {"symbol": "none", "data": mark_lines} if mark_lines else None,
                },
                {"name": "SMA 50", "type": "line", "data": s50, "showSymbol": False, "lineStyle": {"width": 1.2, "color": theme["series"][1]}},
                {"name": "SMA 150", "type": "line", "data": s150, "showSymbol": False, "lineStyle": {"width": 1.2, "color": theme["series"][0]}},
                {"name": "SMA 200", "type": "line", "data": s200, "showSymbol": False, "lineStyle": {"width": 1.6, "color": theme["text"]}},
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
    theme = chart_theme()
    ui.label("RS vs Nifty 50 (100 = start of window)").classes("mp-section-title mt-3")
    ui.echart(
        {
            "backgroundColor": "transparent",
            "animation": False,
            "tooltip": {
                "trigger": "axis",
                "axisPointer": {"type": "line"},
                "backgroundColor": theme.get("tooltip_bg", "rgba(15, 23, 42, 0.95)"),
                "borderColor": theme.get("tooltip_border", "#334155"),
                "borderWidth": 1,
                "textStyle": {"color": "#F1F4F8", "fontFamily": "IBM Plex Mono", "fontSize": 11},
            },
            "grid": {"left": 48, "right": 16, "top": 12, "bottom": 24},
            "xAxis": {
                "type": "category",
                "data": aligned["trade_date"].tolist(),
                "axisLabel": {"color": theme["text"], "fontSize": 11, "hideOverlap": True},
                "axisLine": {"lineStyle": {"color": theme["grid"]}},
            },
            "yAxis": {
                "scale": True,
                "axisLabel": {"color": theme["text"], "fontSize": 11},
                "splitLine": {"lineStyle": {"color": theme["grid"]}},
            },
            "series": [
                {
                    "name": "RS vs Nifty",
                    "type": "line",
                    "showSymbol": False,
                    "data": [round(float(v), 2) for v in ratio],
                    "lineStyle": {"width": 1.6, "color": theme["series"][0]},
                    "markLine": {
                        "symbol": "none",
                        "data": [{"yAxis": 100, "lineStyle": {"color": theme["faint"], "type": "dotted"}}],
                    },
                }
            ],
        }
    ).classes("w-full h-[180px]")
