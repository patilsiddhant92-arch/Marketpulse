"""Candidate queue and Today decision home — focused-v2 read model only."""

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


# Decision-desk default columns (≤10). Shared by Today + Candidates.
DECISION_PRESET_COLUMNS = [
    "symbol",
    "candidate_state",
    "total_score",
    "sector",
    "why_now",
    "trigger_price",
    "invalidation_price",
    "distance_to_trigger_pct",
    "reward_to_risk",
    "market_cap_cr",
]

CANDIDATES_ADVANCED_COLUMNS = [
    "industry",
    "avg_traded_value_cr_20d",
    "market_regime",
    "sector_state",
    "latest_change",
    "first_resistance",
    "initial_risk_pct",
    "event_risk",
    "eligibility_status",
    "blocking_reasons",
    "warning_reasons",
]


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


def _preset_view(frame: pd.DataFrame, columns: list[str] | None = None) -> pd.DataFrame:
    cols = columns or DECISION_PRESET_COLUMNS
    return frame[[c for c in cols if c in frame.columns]].copy()


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
        "Audited focused-v2 queue. Hard-gated at ₹1,000 Cr; blocked rows keep their reasons.",
    )
    with ui.row().classes("gap-2 flex-wrap mp-toolbar"):
        compact_kpi("Decision", snapshot.as_of or "Missing")
        compact_kpi("Version", snapshot.score_version)
        compact_kpi("Gate", snapshot.market_gate)
        compact_kpi("Eligible", len(snapshot.eligible))
        compact_kpi("Blocked", len(snapshot.blocked))
        compact_kpi("MCap out", snapshot.excluded_by_market_cap)
    if snapshot.stale:
        ui.label(f"Data health: {snapshot.diagnostic.replace('_', ' ')}").classes("mp-badge mp-warn mt-2")

    all_rows = _rows(snapshot)
    if all_rows.empty:
        ui.label("No focused-v2 decision rows are available for this session.").classes(
            "text-[var(--mp-muted)] text-sm mt-3"
        )
        return

    with ui.row().classes("gap-2 items-end flex-wrap mp-toolbar mt-3"):
        state = ui.select(
            ["All", "Prepare", "Observe", "Blocked"], value="All", label="State"
        ).classes("w-32").props("dense")
        sectors = ["All"] + sorted(
            str(value) for value in all_rows.get("sector", pd.Series(dtype=str)).dropna().unique()
        )
        sector = ui.select(sectors, value="All", label="Sector").classes("w-44").props("dense")
        min_cap = ui.number("Min MCap Cr", value=0, min=0, format="%.0f").classes("w-32").props("dense")
        show_advanced = ui.checkbox("More columns", value=False).props("dense")

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
        cols = list(DECISION_PRESET_COLUMNS)
        if show_advanced.value:
            cols = cols + [c for c in CANDIDATES_ADVANCED_COLUMNS if c not in cols]
        view = _preset_view(frame, cols)
        with host:
            ui.label(f"{len(view)} rows match").classes("text-xs text-[var(--mp-muted)] mt-2")
            table_from_df(view, "Decision queue", pagination=25, page_key="candidates")

    for control in (state, sector, min_cap, show_advanced):
        control.on_value_change(lambda _: refresh())
    refresh()


def build_today_page(
    db_path: Path,
    table_from_df: Callable,
    compact_kpi: Callable,
    *,
    copy_text: Callable[[str, str], None] | None = None,
) -> DecisionSnapshot:
    """Premium Today: one focused-v2 queue, snapshot-once, state chips, ≤10 cols.

    Does not run prep_score / near-entry / deals-hot SQL.
    Returns the snapshot so callers can attach lazy Market context without reloading decisions.
    """
    market_date = _market_date(db_path)
    snapshot = load_decision_snapshot(db_path, expected_date=market_date)

    try:
        from App.ui.shell import page_shell
    except ModuleNotFoundError:
        try:
            from ui.shell import page_shell  # type: ignore
        except ModuleNotFoundError:
            page_shell = None

    if page_shell:
        page_shell(
            "Today",
            f"Audited queue · {snapshot.score_version} · session {snapshot.as_of or '—'}",
            eyebrow="Decision desk",
        )
    else:
        ui.label("Today").classes("mp-page-title")
        ui.label(f"Audited queue · {snapshot.score_version}").classes("mp-page-subtitle")

    with ui.row().classes("gap-2 flex-wrap mp-toolbar"):
        compact_kpi("As of", snapshot.as_of or "Missing")
        compact_kpi("Gate", snapshot.market_gate)
        compact_kpi("Prepare", int((snapshot.eligible.get("candidate_state") == "Prepare").sum()) if not snapshot.eligible.empty and "candidate_state" in snapshot.eligible else 0)
        compact_kpi("Observe", int((snapshot.eligible.get("candidate_state") == "Observe").sum()) if not snapshot.eligible.empty and "candidate_state" in snapshot.eligible else len(snapshot.eligible))
        compact_kpi("Blocked", len(snapshot.blocked))
        compact_kpi("MCap out", snapshot.excluded_by_market_cap)

    if snapshot.stale:
        ui.label(
            f"Decision data is not current: {snapshot.diagnostic.replace('_', ' ')}"
        ).classes("mp-badge mp-warn mt-1")

    eligible = snapshot.eligible.copy() if snapshot.eligible is not None else pd.DataFrame()
    if eligible.empty:
        ui.label(
            "No eligible focused-v2 rows. Open Candidates for the blocked diagnostic queue."
        ).classes("text-[var(--mp-muted)] text-sm mt-2")
        return snapshot

    # State chips — filter in memory; re-render table host only
    prep_n = int((eligible["candidate_state"].astype(str) == "Prepare").sum()) if "candidate_state" in eligible else 0
    obs_n = int((eligible["candidate_state"].astype(str) == "Observe").sum()) if "candidate_state" in eligible else len(eligible)
    chip_state = {"value": "All"}

    with ui.row().classes("gap-2 flex-wrap items-center mt-3 mp-desk-action"):
        ui.label("Show").classes("text-xs text-[var(--mp-muted)]")
        chip_all = ui.button(f"All ({len(eligible)})", on_click=lambda: _set_chip("All")).props(
            "dense outline" if chip_state["value"] != "All" else "dense"
        ).classes("mp-button")
        chip_prep = ui.button(f"Prepare ({prep_n})", on_click=lambda: _set_chip("Prepare")).props(
            "dense outline"
        ).classes("mp-button")
        chip_obs = ui.button(f"Observe ({obs_n})", on_click=lambda: _set_chip("Observe")).props(
            "dense outline"
        ).classes("mp-button")
        if copy_text is not None:
            def _copy_visible() -> None:
                frame = _filtered()
                syms = (
                    frame["symbol"].dropna().astype(str).str.upper().drop_duplicates().tolist()
                    if not frame.empty and "symbol" in frame.columns
                    else []
                )
                text = ",".join(f"NSE:{s.replace('-', '_')}" for s in syms)
                copy_text("Today queue", text)

            ui.button("Copy symbols", on_click=_copy_visible).classes("mp-primary").props("dense")

    table_host = ui.column().classes("w-full")

    def _filtered() -> pd.DataFrame:
        frame = eligible
        if chip_state["value"] in {"Prepare", "Observe"} and "candidate_state" in frame.columns:
            frame = frame[frame["candidate_state"].astype(str) == chip_state["value"]]
        return frame

    def _paint() -> None:
        table_host.clear()
        frame = _filtered()
        view = _preset_view(frame.head(25))
        with table_host:
            if view.empty:
                ui.label("No names in this state.").classes("text-sm text-[var(--mp-muted)]")
            else:
                table_from_df(
                    view,
                    f"Queue · {chip_state['value']} · {len(frame)} eligible",
                    pagination=10,
                    page_key=None,  # no Hide/Save prefs chrome on decision home
                )

    def _set_chip(value: str) -> None:
        chip_state["value"] = value
        # Restyle: primary for active is approximate via re-prop
        for btn, name in ((chip_all, "All"), (chip_prep, "Prepare"), (chip_obs, "Observe")):
            if name == value:
                btn.props(remove="outline")
            else:
                btn.props("outline")
        _paint()

    _paint()
    return snapshot


def build_today_decision_panel(db_path: Path, table_from_df: Callable, compact_kpi: Callable) -> None:
    """Backward-compatible alias — prefer build_today_page."""
    build_today_page(db_path, table_from_df, compact_kpi)


__all__ = [
    "DECISION_PRESET_COLUMNS",
    "build_candidates_page",
    "build_today_decision_panel",
    "build_today_page",
]
