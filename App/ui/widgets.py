"""Reusable desk widgets (PR-UI-KIT-B / PR-DEALS)."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

import pandas as pd
from nicegui import ui


def signal_tone(value: Any, *, midpoint: float = 0.0) -> str:
    """Map a numeric value to a restrained semantic tone for a data tile."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "neutral"
    if pd.isna(number):
        return "neutral"
    if number > midpoint:
        return "good"
    if number < midpoint:
        return "bad"
    return "neutral"


def signal_tile(
    label: str,
    value: Any,
    *,
    tone: str = "neutral",
    delta: str = "",
    context: str = "",
) -> None:
    """Compact regime/KPI tile with a semantic background and readable hierarchy."""
    safe_tone = tone if tone in {"good", "bad", "warn", "info", "neutral"} else "neutral"
    with ui.element("article").classes(f"mp-signal-tile tone-{safe_tone}"):
        with ui.row().classes("w-full items-center justify-between gap-2 mp-signal-topline"):
            ui.label(label).classes("mp-signal-label")
            if delta:
                ui.label(delta).classes("mp-signal-delta")
        ui.label(str(value)).classes("mp-signal-value")
        if context:
            ui.label(context).classes("mp-signal-context")


def leadership_tile(
    rank: int,
    name: str,
    *,
    group_label: str,
    rs: Any = None,
    day_pct: Any = None,
    week_pct: Any = None,
    flow_multiple: Any = None,
    tone: str = "good",
) -> None:
    """Ranked sector/industry tile used by the Desk leadership strip."""
    safe_tone = tone if tone in {"good", "bad", "warn", "info", "neutral"} else "neutral"

    def _value(value: Any, suffix: str = "", digits: int = 1) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "—"
        if pd.isna(number):
            return "—"
        return f"{number:+.{digits}f}{suffix}" if suffix else f"{number:.{digits}f}"

    with ui.element("article").classes(f"mp-leadership-tile tone-{safe_tone}"):
        with ui.row().classes("w-full items-center justify-between gap-2"):
            ui.label(f"#{int(rank)}").classes("mp-leadership-rank")
            ui.label(str(group_label).upper()).classes("mp-leadership-kicker")
        ui.label(str(name)).classes("mp-leadership-name")
        with ui.row().classes("w-full items-center gap-3 mp-leadership-stats"):
            with ui.column().classes("gap-0"):
                ui.label("RS").classes("mp-leadership-stat-label")
                ui.label(_value(rs, digits=0)).classes("mp-leadership-stat-value")
            with ui.column().classes("gap-0"):
                ui.label("TODAY").classes("mp-leadership-stat-label")
                ui.label(_value(day_pct, "%")).classes("mp-leadership-stat-value")
            with ui.column().classes("gap-0"):
                ui.label("FLOW").classes("mp-leadership-stat-label")
                ui.label(_value(flow_multiple, "x")).classes("mp-leadership-stat-value")
        if week_pct is not None:
            ui.label(f"5D {_value(week_pct, '%')}").classes("mp-leadership-context")


@contextmanager
def chart_panel(
    title: str,
    subtitle: str = "",
    *,
    tone: str = "neutral",
    extra_class: str = "",
):
    """Bounded chart surface with consistent title, subtitle, and spacing."""
    safe_tone = tone if tone in {"good", "bad", "warn", "info", "neutral"} else "neutral"
    classes = f"mp-chart-panel tone-{safe_tone} {extra_class}".strip()
    with ui.element("section").classes(classes):
        with ui.row().classes("w-full items-start justify-between gap-3 mp-chart-panel-heading"):
            ui.label(title).classes("mp-chart-title")
            ui.label("DESK").classes("mp-chart-kicker")
        if subtitle:
            ui.label(subtitle).classes("mp-chart-subtitle")
        yield


def action_button(label: str, on_click: Callable[[], None], *, primary: bool = True) -> None:
    cls = "mp-primary" if primary else "mp-button"
    ui.button(label, on_click=on_click).classes(cls).props("dense")


def symbol_chip_strip(symbols: list[str], *, preview: int = 24) -> None:
    """Show a compact chip strip; does not truncate the copy source."""
    shown = symbols[:preview]
    with ui.element("div").classes("mp-chip-strip mt-2"):
        for sym in shown:
            ui.label(sym).classes("mp-symbol-chip")
        if len(symbols) > preview:
            ui.label(f"+{len(symbols) - preview} more in copy").classes("text-xs text-[var(--mp-muted)] self-center")


def _compact_deal_when(text: str) -> tuple[int, str]:
    parts = [p.strip() for p in str(text).split("·") if p.strip()]
    n = len(parts)
    if n == 0:
        return 0, ""
    head = " · ".join(parts[:3])
    if n > 3:
        head = f"{head} +{n - 3}"
    return n, head


def deal_flow_card(
    symbol: str,
    buy_cr: float,
    *,
    sell_cr: float | None = None,
    net_cr: float | None = None,
    clients: int | None = None,
    rs: float | None = None,
    away_52w: float | None = None,
    inst_names: str | None = None,
    cost_basis_pct: float | None = None,
    deal_when: str | None = None,
    on_tv: Callable[[], None] | None = None,
    on_copy: Callable[[], None] | None = None,
    on_click: Callable[[], None] | None = None,
) -> None:
    sessions, when_short = _compact_deal_when(deal_when or "")
    loved = (clients or 0) >= 3 or sessions >= 3
    sell_v = float(sell_cr or 0) if sell_cr is not None and pd.notna(sell_cr) else 0.0
    net_v = float(net_cr) if net_cr is not None and pd.notna(net_cr) else buy_cr - sell_v
    card_el = ui.element("div").classes("mp-deal-card cursor-pointer hover:shadow-md transition-all")
    with card_el:
        with ui.row().classes("w-full items-center justify-between gap-2"):
            with ui.row().classes("items-center gap-2"):
                sym_lbl = ui.label(symbol).classes("sym hover:underline cursor-pointer")
                if on_tv:
                    sym_lbl.on("click", lambda _: on_tv())
                if loved:
                    ui.label("Inst love").classes("mp-mini-badge mp-deal-badge")
            ui.label(f"+{buy_cr:,.0f} Cr").classes("mp-up")
        with ui.element("div").classes("mp-deal-grid"):
            ui.label("Buy Cr").classes("k")
            ui.label(f"{buy_cr:,.0f}").classes("v mp-up")
            ui.label("Sell Cr").classes("k")
            ui.label(f"{sell_v:,.0f}").classes("v mp-down" if sell_v else "v")
            ui.label("Net Cr").classes("k")
            ui.label(f"{net_v:+,.0f}").classes("v mp-up" if net_v >= 0 else "v mp-down")
            ui.label("RS %").classes("k")
            ui.label("—" if rs is None or pd.isna(rs) else f"{float(rs):.0f}").classes("v")
            ui.label("52W %").classes("k")
            ui.label("—" if away_52w is None or pd.isna(away_52w) else f"{float(away_52w):.1f}%").classes("v")
            ui.label("vs Entry %").classes("k")
            ui.label(
                "—" if cost_basis_pct is None or pd.isna(cost_basis_pct) else f"{float(cost_basis_pct):.1f}%"
            ).classes("v")
        bits = []
        if clients is not None:
            bits.append(f"{int(clients)} inst")
        if sessions:
            bits.append(f"{sessions} sessions")
        if bits:
            ui.label(" · ".join(bits)).classes("meta mt-1")
        if when_short:
            ui.label(when_short).classes("meta")
        if inst_names:
            ui.label(inst_names).classes("inst-line mt-1")
        with ui.row().classes("gap-2 mt-2"):
            if on_click:
                ui.button("360°", on_click=on_click).props("dense flat").classes("mp-button text-xs font-semibold")
            if on_tv:
                ui.button("TV", on_click=on_tv).props("dense flat").classes("mp-button text-xs")
            if on_copy:
                ui.button("Copy", on_click=on_copy).props("dense flat").classes("mp-button text-xs")



def flow_spark(flow: pd.DataFrame) -> None:
    """Compact buy vs sell bars for lookback window."""
    if flow is None or flow.empty:
        ui.label("No deal flow in window.").classes("text-sm text-[var(--mp-muted)]")
        return
    rows = flow.copy()
    rows["trade_date"] = pd.to_datetime(rows["trade_date"], errors="coerce").dt.strftime("%d-%b")
    x = rows["trade_date"].tolist()
    buy = pd.to_numeric(rows.get("buy_cr"), errors="coerce").fillna(0).round(1).tolist()
    sell = pd.to_numeric(rows.get("sell_cr"), errors="coerce").fillna(0).round(1).tolist()
    theme = chart_theme()
    ui.echart(
        {
            "backgroundColor": "transparent",
            "animation": False,
            "tooltip": {
                "trigger": "axis",
                "axisPointer": {"type": "shadow"},
                "backgroundColor": theme.get("tooltip_bg", "rgba(15, 23, 42, 0.95)"),
                "borderColor": theme.get("tooltip_border", "#334155"),
                "borderWidth": 1,
                "textStyle": {"color": theme["text_strong"], "fontFamily": "IBM Plex Mono", "fontSize": 11},
            },
            "grid": {"left": 40, "right": 12, "top": 16, "bottom": 28},
            "legend": {"show": True, "top": 0, "right": 0, "textStyle": {"fontSize": 12, "color": theme["text"]}},
            "xAxis": {"type": "category", "data": x, "axisLabel": {"fontSize": 11, "color": theme["text"]}, "axisLine": {"lineStyle": {"color": theme["grid"]}}},
            "yAxis": {"type": "value", "axisLabel": {"fontSize": 11, "color": theme["text"]}, "splitLine": {"lineStyle": {"color": theme["grid"]}}},
            "series": [
                {"name": "BUY Cr", "type": "bar", "data": buy, "itemStyle": {"color": theme["good"]}},
                {"name": "SELL Cr", "type": "bar", "data": sell, "itemStyle": {"color": theme["bad"]}},
            ],
        }
    ).classes("mp-flow-spark w-full")


def return_heatmap(frame: pd.DataFrame, *, name_col: str, value_col: str = "day_pct") -> None:
    """Tile heatmap of signed returns. Color is P&L of the cell, not of every % in the app."""
    if frame is None or frame.empty or name_col not in frame.columns or value_col not in frame.columns:
        return
    rows = frame.dropna(subset=[name_col]).head(24)
    if rows.empty:
        return
    with ui.element("div").classes("mp-heat-grid"):
        for _, row in rows.iterrows():
            try:
                value = float(row[value_col])
            except (TypeError, ValueError):
                continue
            if value >= 2:
                tone = "mp-heat-up-2"
            elif value > 0:
                tone = "mp-heat-up-1"
            elif value <= -2:
                tone = "mp-heat-down-2"
            elif value < 0:
                tone = "mp-heat-down-1"
            else:
                tone = "mp-heat-flat"
            week = row["week_pct"] if "week_pct" in row.index and pd.notna(row["week_pct"]) else None
            month = row["month_pct"] if "month_pct" in row.index and pd.notna(row["month_pct"]) else None
            turnover = row["t_o_today"] if "t_o_today" in row.index and pd.notna(row["t_o_today"]) else None
            extra = []
            if week is not None:
                extra.append(f"W {float(week):+.1f}%")
            if month is not None:
                extra.append(f"M {float(month):+.1f}%")
            if turnover is not None:
                extra.append(f"₹{float(turnover):,.0f} Cr")
            with ui.element("div").classes(f"mp-heat-tile {tone}"):
                ui.label(str(row[name_col])).classes("name")
                ui.label(f"{value:+.1f}%").classes("val")
                if extra:
                    ui.label(" · ".join(extra)).classes("meta")


def chart_theme() -> dict[str, Any]:
    """Return stable ECharts colors for the Institutional Midnight theme."""
    return {
        "text": "#98A7BA",
        "text_strong": "#F1F4F8",
        "faint": "#6E7E93",
        "grid": "#263447",
        "tooltip_bg": "rgba(15, 23, 42, 0.95)",
        "tooltip_border": "#334155",
        "series": ["#D8AC3D", "#74A9FF", "#45D483", "#F27C84", "#5AD3D0", "#F0BE58"],
        "primary": "#D8AC3D",
        "info": "#74A9FF",
        "good": "#45D483",
        "bad": "#F27C84",
        "warn": "#F0BE58",
        "cyan": "#5AD3D0",
    }


def _series_color(theme: dict[str, Any], tone: str | None, index: int) -> str:
    tone_colors = {
        "primary": theme["primary"],
        "info": theme["info"],
        "good": theme["good"],
        "bad": theme["bad"],
        "warn": theme["warn"],
        "cyan": theme["cyan"],
        "neutral": theme["series"][index % len(theme["series"])],
    }
    return tone_colors.get(str(tone or "neutral"), tone_colors["neutral"])


def line_chart(
    frame: pd.DataFrame,
    *,
    date_col: str,
    series: dict[str, str],
    height_class: str = "mp-trend-chart",
    series_tones: dict[str, str] | None = None,
    area: bool = False,
) -> None:
    """Wide-frame line chart. series maps legend label → column name."""
    if frame is None or frame.empty or date_col not in frame.columns:
        ui.label("No trend history.").classes("text-sm text-[var(--mp-text)]")
        return
    rows = frame.dropna(subset=[date_col]).copy()
    rows[date_col] = pd.to_datetime(rows[date_col], errors="coerce")
    rows = rows.dropna(subset=[date_col]).sort_values(date_col)
    if rows.empty:
        return
    x = rows[date_col].dt.strftime("%d %b").tolist()
    theme = chart_theme()
    e_series = []
    for i, (label, col) in enumerate(series.items()):
        if col not in rows.columns:
            continue
        data = [None if pd.isna(v) else round(float(v), 2) for v in pd.to_numeric(rows[col], errors="coerce")]
        color = _series_color(theme, (series_tones or {}).get(label), i)
        item = {
            "name": label,
            "type": "line",
            "showSymbol": False,
            "smooth": False,
            "data": data,
            "lineStyle": {"width": 2, "color": color},
            "itemStyle": {"color": color},
        }
        if area:
            item["areaStyle"] = {"color": color, "opacity": 0.10}
        e_series.append(
            item
        )
    if not e_series:
        return
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
                "textStyle": {"color": theme["text_strong"], "fontFamily": "IBM Plex Mono", "fontSize": 11},
            },
            "legend": {
                "top": 0,
                "textStyle": {"color": theme["text"], "fontSize": 12, "fontFamily": "IBM Plex Sans"},
            },
            "grid": {"left": 48, "right": 16, "top": 36, "bottom": 28},
            "xAxis": {
                "type": "category",
                "data": x,
                "axisLabel": {"color": theme["text"], "fontSize": 11, "hideOverlap": True},
                "axisLine": {"lineStyle": {"color": theme["grid"]}},
            },
            "yAxis": {
                "scale": True,
                "axisLabel": {"color": theme["text"], "fontSize": 11},
                "splitLine": {"lineStyle": {"color": theme["grid"]}},
            },
            "series": e_series,
        }
    ).classes(height_class)


def grouped_line_chart(
    frame: pd.DataFrame,
    *,
    date_col: str,
    group_col: str,
    value_col: str,
    height_class: str = "mp-trend-chart",
) -> None:
    """Long-frame line chart, one line per group."""
    if frame is None or frame.empty:
        return
    needed = {date_col, group_col, value_col}
    if not needed.issubset(frame.columns):
        return
    rows = frame.dropna(subset=[date_col, group_col]).copy()
    rows[date_col] = pd.to_datetime(rows[date_col], errors="coerce")
    rows = rows.dropna(subset=[date_col])
    if rows.empty:
        return
    dates = sorted(rows[date_col].unique())
    x = [pd.Timestamp(d).strftime("%d %b") for d in dates]
    series = {}
    for grp, chunk in rows.groupby(group_col):
        aligned = chunk.set_index(date_col)[value_col].reindex(dates)
        series[str(grp)] = [None if pd.isna(v) else round(float(v), 2) for v in aligned]
    if not series:
        return
    theme = chart_theme()
    e_series = []
    for i, (label, data) in enumerate(series.items()):
        e_series.append(
            {
                "name": label,
                "type": "line",
                "showSymbol": False,
                "smooth": False,
                "data": data,
                "lineStyle": {"width": 2, "color": theme["series"][i % len(theme["series"])]},
                "itemStyle": {"color": theme["series"][i % len(theme["series"])]},
            }
        )
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
                "textStyle": {"color": theme["text_strong"], "fontFamily": "IBM Plex Mono", "fontSize": 11},
            },
            "legend": {
                "top": 0,
                "type": "scroll",
                "textStyle": {"color": theme["text"], "fontSize": 12, "fontFamily": "IBM Plex Sans"},
            },
            "grid": {"left": 48, "right": 16, "top": 36, "bottom": 28},
            "xAxis": {
                "type": "category",
                "data": x,
                "axisLabel": {"color": theme["text"], "fontSize": 11, "hideOverlap": True},
                "axisLine": {"lineStyle": {"color": theme["grid"]}},
            },
            "yAxis": {
                "scale": True,
                "axisLabel": {"color": theme["text"], "fontSize": 11, "formatter": "{value}%"},
                "splitLine": {"lineStyle": {"color": theme["grid"]}},
            },
            "series": e_series,
        }
    ).classes(height_class)


def compact_kpi_row(items: list[tuple[str, Any]]) -> None:
    with ui.row().classes("gap-4 flex-wrap mp-desk-action"):
        for label, value in items:
            with ui.element("span").classes("mp-kpi-compact"):
                ui.label(label).classes("label")
                ui.label(str(value)).classes("value")
