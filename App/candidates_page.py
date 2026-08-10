"""Candidate queue built from the same focused-v2 read model as Today."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Callable

import duckdb
import pandas as pd
from nicegui import ui

try:
    from .decision_read_model import DecisionSnapshot, load_decision_snapshot
except ImportError:  # app.py is executed as a script with App/ on sys.path.
    from decision_read_model import DecisionSnapshot, load_decision_snapshot


def _market_date(db_path: Path) -> date | None:
    try:
        with duckdb.connect(str(db_path), read_only=True) as db:
            value = db.execute("SELECT max(trade_date) FROM indicators_daily").fetchone()[0]
        return pd.Timestamp(value).date() if value is not None else None
    except Exception:
        return None


def _rows(snapshot: DecisionSnapshot) -> pd.DataFrame:
    frames = []
    for frame in (snapshot.eligible, snapshot.blocked):
        if frame is not None and not frame.empty:
            frames.append(frame.copy())
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    if "candidate_state" not in combined:
        combined["candidate_state"] = "Blocked"
    return combined


def build_candidates_page(
    db_path: Path,
    section_header: Callable,
    table_from_df: Callable,
    compact_kpi: Callable,
) -> None:
    market_date = _market_date(db_path)
    snapshot = load_decision_snapshot(db_path, expected_date=market_date)
    section_header(
        "Candidates",
        "The audited focused-v2 queue. Eligibility is hard-gated at ₹1,000 Cr market cap; blocked rows stay visible with reasons.",
    )
    with ui.row().classes("gap-2 flex-wrap mp-toolbar"):
        compact_kpi("Decision", snapshot.as_of or "Missing")
        compact_kpi("Version", snapshot.score_version)
        compact_kpi("Market gate", snapshot.market_gate)
        compact_kpi("Eligible", len(snapshot.eligible))
        compact_kpi("Blocked", len(snapshot.blocked))
        compact_kpi("MCap excluded", snapshot.excluded_by_market_cap)
    if snapshot.stale:
        ui.label(f"Data health: {snapshot.diagnostic.replace('_', ' ')}").classes("mp-badge mp-warn mt-2")

    all_rows = _rows(snapshot)
    if all_rows.empty:
        ui.label("No focused-v2 decision rows are available for this session.").classes("text-[var(--mp-muted)] text-sm mt-3")
        return

    with ui.row().classes("gap-2 items-end flex-wrap mp-toolbar mt-3"):
        state = ui.select(["All", "Prepare", "Observe", "Blocked"], value="All", label="State").classes("w-32").props("dense")
        sectors = ["All"] + sorted(str(value) for value in all_rows.get("sector", pd.Series(dtype=str)).dropna().unique())
        sector = ui.select(sectors, value="All", label="Sector").classes("w-44").props("dense")
        min_cap = ui.number("Min MCap Cr", value=0, min=0, format="%.0f").classes("w-32").props("dense")
        max_trigger = ui.number("Max trigger %", value=5, min=-100, format="%.1f").classes("w-32").props("dense")
        min_rr = ui.number("Min R:R", value=1.5, min=0, format="%.1f").classes("w-28").props("dense")

    host = ui.column().classes("w-full")

    def refresh() -> None:
        host.clear()
        frame = all_rows.copy()
        if state.value and state.value != "All":
            frame = frame[frame["candidate_state"].astype(str) == str(state.value)]
        if sector.value and sector.value != "All" and "sector" in frame.columns:
            frame = frame[frame["sector"].astype(str) == str(sector.value)]
        cap = pd.to_numeric(frame.get("market_cap_cr"), errors="coerce")
        frame = frame[cap.fillna(-1) >= float(min_cap.value or 0)]
        trigger = pd.to_numeric(frame.get("distance_to_trigger_pct"), errors="coerce")
        frame = frame[trigger.isna() | (trigger <= float(max_trigger.value or 0))]
        rr = pd.to_numeric(frame.get("reward_to_risk"), errors="coerce")
        frame = frame[rr.isna() | (rr >= float(min_rr.value or 0))]
        columns = [
            "symbol", "candidate_state", "total_score", "market_cap_cr", "avg_traded_value_cr_20d",
            "sector", "industry", "market_regime", "sector_state", "why_now", "latest_change",
            "trigger_price", "invalidation_price", "first_resistance", "distance_to_trigger_pct",
            "initial_risk_pct", "reward_to_risk", "event_risk", "eligibility_status",
            "blocking_reasons", "warning_reasons",
        ]
        view = frame[[column for column in columns if column in frame.columns]].copy()
        with host:
            ui.label(f"{len(view)} rows match the current filters").classes("text-xs text-[var(--mp-muted)] mt-2")
            table_from_df(view, "Decision queue", pagination=25, page_key="candidates")

    for control in (state, sector, min_cap, max_trigger, min_rr):
        control.on_value_change(lambda _: refresh())
    refresh()


def build_today_decision_panel(db_path: Path, table_from_df: Callable, compact_kpi: Callable) -> None:
    """Compact canonical queue inserted above the legacy Today research cards."""
    market_date = _market_date(db_path)
    snapshot = load_decision_snapshot(db_path, expected_date=market_date)
    ui.label("Audited decision queue · focused-v2").classes("mp-section-title mt-2")
    with ui.row().classes("gap-2 flex-wrap mp-toolbar"):
        compact_kpi("As of", snapshot.as_of or "Missing")
        compact_kpi("Gate", snapshot.market_gate)
        compact_kpi("Prepare/Observe", len(snapshot.eligible))
        compact_kpi("Blocked", len(snapshot.blocked))
        compact_kpi("MCap excluded", snapshot.excluded_by_market_cap)
    if snapshot.stale:
        ui.label(f"Decision data is not current: {snapshot.diagnostic.replace('_', ' ')}").classes("mp-badge mp-warn mt-1")
    if snapshot.eligible.empty:
        ui.label("No eligible focused-v2 rows. Open Candidates for the blocked diagnostic queue.").classes("text-[var(--mp-muted)] text-sm mt-2")
        return
    columns = [
        "symbol", "candidate_state", "total_score", "market_cap_cr", "sector", "why_now",
        "trigger_price", "invalidation_price", "distance_to_trigger_pct", "initial_risk_pct",
        "reward_to_risk", "event_risk", "warning_reasons",
    ]
    view = snapshot.eligible.head(10)[[column for column in columns if column in snapshot.eligible.columns]].copy()
    table_from_df(view, "Prepare and observe · all rows pass ₹1,000 Cr", pagination=10, page_key="today-decision")


__all__ = ["build_candidates_page", "build_today_decision_panel"]
