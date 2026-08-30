"""Desk = tape. Daily/weekly/monthly summary, what moved, turnover.

Cash book only. Index levels stay out of this page.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pandas as pd
from nicegui import ui

try:
    from App.market_flags import annotate
    from App.market_status import load_market_status, non_actionable_message
    from App.market_summary import delivery_thrust, group_tape, group_trend, movers, near_highs, stock_turnover, tape
    from App.ui.widgets import grouped_line_chart, line_chart, return_heatmap
except ModuleNotFoundError:
    from market_flags import annotate  # type: ignore
    from market_status import load_market_status, non_actionable_message  # type: ignore
    from market_summary import delivery_thrust, group_tape, group_trend, movers, near_highs, stock_turnover, tape  # type: ignore
    from ui.widgets import grouped_line_chart, line_chart, return_heatmap  # type: ignore


def _fmt(v, digits=1, pct=False, money=False):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if money:
        return f"{x:,.0f}"
    if pct:
        return f"{x:+.{digits}f}%" if digits else f"{x:+.0f}%"
    return f"{x:.{digits}f}"


def _kpi(label: str, value: str, hint: str = "", hint_cls: str = "") -> None:
    with ui.column().classes("mp-kpi"):
        ui.label(label).classes("mp-kpi-label")
        ui.label(value).classes("mp-kpi-value")
        if hint:
            ui.label(hint).classes(hint_cls or "text-sm text-[var(--mp-muted)]")


def build_desk_page(
    db_path: Path,
    section_header: Callable,
    table_from_df: Callable,
    compact_kpi: Callable,
) -> None:
    db_path = Path(db_path)
    status = load_market_status(db_path, db_path.parent / "status.json")
    t = tape(db_path)
    b = t.get("breadth") or {}

    section_header("Tape", "What the cash session did. Daily / weekly / monthly. Not a candidate queue.")
    if not status.actionable:
        ui.label(non_actionable_message(status)).classes("mp-badge mp-bad w-full mt-2")

    ui.label("Daily").classes("mp-section-title mt-2")
    with ui.row().classes("gap-3 flex-wrap mp-toolbar"):
        _kpi("As of", str(t.get("as_of") or "—")[:10])
        _kpi("Advance", _fmt(b.get("advance_pct"), 1) + "%")
        _kpi("50d", _fmt(b.get("above_50ema_pct"), 1) + "%")
        _kpi("200d", _fmt(b.get("above_200ema_pct"), 1) + "%")
        _kpi(
            "Near 52w high",
            str(int(b["near_52w_highs"]))
            if b.get("near_52w_highs") is not None and pd.notna(b.get("near_52w_highs"))
            else "—",
        )
        _kpi("Session T/O Cr", _fmt(t.get("session_turnover_cr"), 0, money=True))
        if b.get("breadth_state"):
            _kpi("Regime", str(b["breadth_state"]))

    ui.label("Participation trend").classes("mp-section-title mt-3")
    hist = t.get("breadth_hist", pd.DataFrame())
    if hist is None or hist.empty:
        ui.label("No breadth history yet.").classes("text-sm text-[var(--mp-muted)]")
    else:
        recent = hist.sort_values("trade_date")
        line_chart(
            recent,
            date_col="trade_date",
            series={
                "Advance": "advance_pct",
                "50d": "above_50ema_pct",
                "200d": "above_200ema_pct",
            },
        )
        if "new_20d_highs" in recent.columns:
            ui.label("New 20-day highs").classes("mp-section-title mt-3")
            line_chart(recent, date_col="trade_date", series={"New 20d highs": "new_20d_highs"})

    ui.label("Sector return trend (top turnover groups)").classes("mp-section-title mt-3")
    sec_hist = group_trend(db_path, "sector", top_n=6, days=21)
    if sec_hist.empty:
        ui.label("No sector history.").classes("text-sm text-[var(--mp-muted)]")
    else:
        grouped_line_chart(sec_hist, date_col="trade_date", group_col="grp", value_col="day_pct")

    mv = movers(db_path)
    if mv.empty:
        ui.label("No indicators for the latest session.").classes("text-sm text-[var(--mp-muted)]")
        return
    try:
        from App.market_flags import deal_when_map, leadership_sets
    except ModuleNotFoundError:
        from market_flags import deal_when_map, leadership_sets  # type: ignore
    lead = leadership_sets(db_path)
    when = deal_when_map(db_path)
    mv = annotate(mv, db_path, flags=lead, when=when)

    ui.label("What moved today").classes("mp-section-title mt-3")
    cols_move = [
        c
        for c in [
            "symbol",
            "day_pct",
            "week_pct",
            "month_pct",
            "t_o_today",
            "rvol",
            "delivery_pct",
            "rs_percentile",
            "away_52w_high_pct",
            "deal_when",
            "sector",
            "industry",
            "market_cap_cr",
        ]
        if c in mv.columns
    ]
    with ui.row().classes("w-full gap-4 flex-wrap"):
        with ui.column().classes("flex-1 min-w-[320px]"):
            table_from_df(mv.sort_values("day_pct", ascending=False).head(15)[cols_move], "Up", pagination=15)
        with ui.column().classes("flex-1 min-w-[320px]"):
            table_from_df(mv.sort_values("day_pct", ascending=True).head(15)[cols_move], "Down", pagination=15)

    if "rvol" in mv.columns:
        table_from_df(
            mv.sort_values("rvol", ascending=False).head(20)[cols_move],
            "Volume shock (rvol)",
            pagination=20,
        )

    ui.label("Turnover — today / week / month").classes("mp-section-title mt-3")
    to = annotate(stock_turnover(db_path), db_path, flags=lead, when=when)
    to_cols = [
        c
        for c in ["symbol", "day_pct", "t_o_today", "t_o_1w", "t_o_1m", "vs_20d", "rs_percentile", "deal_when", "sector", "industry", "market_cap_cr"]
        if c in to.columns
    ]
    table_from_df(to[to_cols], "Stock turnover", pagination=25)

    ui.label("Sectors by rupees").classes("mp-section-title mt-3")
    sec = group_tape(db_path, "sector")
    if not sec.empty:
        return_heatmap(sec.head(16), name_col="grp", value_col="day_pct")
    sec_cols = [
        c
        for c in ["grp", "n", "day_pct", "week_pct", "month_pct", "advance_pct", "above_50", "rs", "rs_rank", "t_o_today", "t_o_1w", "vs_20d"]
        if c in sec.columns
    ]
    table_from_df(sec[sec_cols].head(20), "Sector tape", pagination=20, copy_symbols=False)

    highs = annotate(near_highs(db_path), db_path, flags=lead, when=when)
    ui.label("Near 52-week high (within 5%)").classes("mp-section-title mt-3")
    if highs.empty:
        ui.label("No names hugging the 52-week high in the ₹1,000 Cr universe.").classes("text-sm text-[var(--mp-muted)]")
    else:
        high_cols = [
            c
            for c in ["symbol", "day_pct", "away_52w_high_pct", "rs_percentile", "rvol", "t_o_today", "delivery_pct", "deal_when", "sector", "industry"]
            if c in highs.columns
        ]
        table_from_df(highs[high_cols], "Near highs", pagination=15)

    thrust = annotate(delivery_thrust(db_path), db_path, flags=lead, when=when)
    ui.label("Price up + delivery ≥ 50% + rvol ≥ 1.2").classes("mp-section-title mt-3")
    if thrust.empty:
        ui.label("No delivery thrust names today.").classes("text-sm text-[var(--mp-muted)]")
    else:
        th_cols = [
            c
            for c in ["symbol", "day_pct", "delivery_pct", "rvol", "t_o_today", "rs_percentile", "away_52w_high_pct", "deal_when", "sector"]
            if c in thrust.columns
        ]
        table_from_df(thrust[th_cols], "Delivery thrust", pagination=15)
