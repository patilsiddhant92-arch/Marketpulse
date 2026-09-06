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
    from App.ui.market_health import render_market_health_strip
    from App.ui.widgets import (
        chart_panel,
        flow_spark,
        grouped_line_chart,
        leadership_tile,
        line_chart,
        return_heatmap,
        signal_tile,
        signal_tone,
    )
except ModuleNotFoundError:
    from market_flags import annotate  # type: ignore
    from market_status import load_market_status, non_actionable_message  # type: ignore
    from market_summary import delivery_thrust, group_tape, group_trend, movers, near_highs, stock_turnover, tape  # type: ignore
    try:
        from ui.market_health import render_market_health_strip  # type: ignore
    except ModuleNotFoundError:
        try:
            from App.ui.market_health import render_market_health_strip  # type: ignore
        except ModuleNotFoundError:
            def render_market_health_strip(db_path: Path) -> None:  # type: ignore
                pass
    from ui.widgets import (  # type: ignore
        chart_panel,
        flow_spark,
        grouped_line_chart,
        leadership_tile,
        line_chart,
        return_heatmap,
        signal_tile,
        signal_tone,
    )


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


def _pct(v, digits: int = 1, signed: bool = False) -> str:
    value = _fmt(v, digits, pct=signed)
    return "—" if value == "—" else f"{value}%"


def _count(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    try:
        return f"{int(float(v)):,}"
    except (TypeError, ValueError):
        return "—"


def _money(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    try:
        number = float(v)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(number):
        return "—"
    if abs(number) >= 1000:
        return f"₹{number / 1000:,.1f}k Cr"
    return f"₹{number:,.0f} Cr"


def _state_tone(value: object) -> str:
    state = str(value or "").lower()
    if any(word in state for word in ("improv", "broad", "lead", "strong")):
        return "good"
    if any(word in state for word in ("weak", "lag", "risk")):
        return "bad"
    if "emerg" in state:
        return "info"
    return "neutral"


def _deal_flow(db_path: Path) -> pd.DataFrame:
    """Return the existing deal read-model flow without making the Desk depend on it."""
    try:
        from App.deals_read_model import query_deals_desk_default
    except ModuleNotFoundError:
        try:
            from deals_read_model import query_deals_desk_default  # type: ignore
        except ModuleNotFoundError:
            return pd.DataFrame()
    try:
        return query_deals_desk_default(db_path, card_limit=1).flow
    except Exception:
        return pd.DataFrame()


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

    as_of = str(t.get("as_of") or "—")[:10]
    posture = str(b.get("breadth_state") or "Unclassified")

    # First viewport: Mantis-grade clickable 7-card regime strip with historical breadth modal
    with ui.element("section").classes("mp-regime-strip"):
        render_market_health_strip(db_path)
        # Fallback parity anchor: signal_tile available for legacy layout if required

    # Leadership is intentionally ranked and compact, rather than a loose list.
    try:
        sec = group_tape(db_path, "sector")
    except Exception:
        sec = pd.DataFrame()
    try:
        ind = group_tape(db_path, "industry")
    except Exception:
        ind = pd.DataFrame()
    with ui.element("section").classes("mp-leadership-strip"):
        with ui.row().classes("w-full items-center justify-between gap-3 mp-strip-heading"):
            ui.label("Leadership").classes("mp-strip-title")
            ui.label("Top groups by RS · today / 5D / flow").classes("mp-strip-caption")
        with ui.element("div").classes("mp-leadership-grid"):
            rank = 1
            for frame, group_label in ((sec, "Sector"), (ind, "Industry")):
                if frame is None or frame.empty or "grp" not in frame.columns:
                    continue
                ranked = frame.copy()
                sort_cols = [column for column in ("rs", "day_pct", "t_o_today") if column in ranked.columns]
                if sort_cols:
                    ranked = ranked.sort_values(sort_cols, ascending=[False] + [False] * (len(sort_cols) - 1), na_position="last")
                for _, row in ranked.head(2).iterrows():
                    day_pct = row.get("day_pct")
                    leadership_tile(
                        rank,
                        str(row.get("grp") or "Unclassified"),
                        group_label=group_label,
                        rs=row.get("rs"),
                        day_pct=day_pct,
                        week_pct=row.get("week_pct"),
                        flow_multiple=row.get("vs_20d"),
                        tone=signal_tone(day_pct),
                    )
                    rank += 1
            if rank == 1:
                ui.label("No sector or industry leadership data for the latest session.").classes("text-sm text-[var(--mp-muted)]")

    hist = t.get("breadth_hist", pd.DataFrame())
    sec_hist = group_trend(db_path, "sector", top_n=6, days=21)
    deal_flow = _deal_flow(db_path)

    with ui.element("div").classes("mp-chart-grid"):
        with chart_panel(
            "Participation",
            "Advance and EMA breadth · 21 sessions",
            tone=_state_tone(posture),
        ):
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
                    series_tones={"Advance": "good", "50d": "info", "200d": "cyan"},
                    area=True,
                )

        with chart_panel(
            "New highs",
            "20-day highs · participation impulse",
            tone="good",
        ):
            if hist is None or hist.empty or "new_20d_highs" not in hist.columns:
                ui.label("No new-high history yet.").classes("text-sm text-[var(--mp-muted)]")
            else:
                line_chart(
                    hist.sort_values("trade_date"),
                    date_col="trade_date",
                    series={"New 20d highs": "new_20d_highs"},
                    series_tones={"New 20d highs": "good"},
                    area=True,
                )

        with chart_panel(
            "Sector rotation",
            "Top turnover groups · daily return trend",
            tone="info",
            extra_class="span-2",
        ):
            if sec_hist.empty:
                ui.label("No sector history.").classes("text-sm text-[var(--mp-muted)]")
            else:
                grouped_line_chart(sec_hist, date_col="trade_date", group_col="grp", value_col="day_pct")

        with chart_panel(
            "Buy / sell flow",
            "Institutional deal value · latest eligible universe",
            tone="info",
            extra_class="span-2 mp-flow-panel",
        ):
            flow_spark(deal_flow)

    hist = t.get("breadth_hist", pd.DataFrame())
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

    ui.label("What moved today").classes("mp-section-title mt-4")
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
    with ui.element("div").classes("mp-movers-grid"):
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
