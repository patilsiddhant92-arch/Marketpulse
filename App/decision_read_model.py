"""Read-only contract for the candidate queue shown by the UI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd


FOCUSED_SCORE_VERSION = "focused-v2"
MIN_MARKET_CAP_CR = 1000.0


@dataclass(frozen=True)
class DecisionSnapshot:
    as_of: date | None
    score_version: str
    market_gate: str
    eligible: pd.DataFrame
    blocked: pd.DataFrame
    excluded_by_market_cap: int
    stale: bool
    diagnostic: str = "ok"


def _empty() -> pd.DataFrame:
    return pd.DataFrame()


def _diagnostic(as_of: date | None, expected_date: date | None, *, missing: bool = False) -> tuple[bool, str]:
    if missing or as_of is None:
        return True, "decision_snapshot_missing"
    if expected_date is not None and as_of != expected_date:
        return True, "decision_snapshot_stale"
    return False, "ok"


def load_decision_snapshot(db_path: Path, expected_date: date | None = None) -> DecisionSnapshot:
    """Load the latest focused-v2 partition without falling back to older scores."""
    expected = pd.Timestamp(expected_date).date() if expected_date is not None else None
    try:
        with duckdb.connect(str(db_path), read_only=True) as db:
            table = db.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'candidate_daily'"
            ).fetchone()[0]
            if not table:
                stale, diagnostic = _diagnostic(None, expected, missing=True)
                return DecisionSnapshot(None, FOCUSED_SCORE_VERSION, "Unknown", _empty(), _empty(), 0, stale, diagnostic)
            latest_row = db.execute(
                "SELECT max(trade_date) FROM candidate_daily WHERE score_version = ?",
                [FOCUSED_SCORE_VERSION],
            ).fetchone()
            latest = latest_row[0] if latest_row else None
            if latest is None:
                stale, diagnostic = _diagnostic(None, expected, missing=True)
                return DecisionSnapshot(None, FOCUSED_SCORE_VERSION, "Unknown", _empty(), _empty(), 0, stale, diagnostic)
            frame = db.execute(
                "SELECT * FROM candidate_daily WHERE trade_date = ? AND score_version = ?",
                [latest, FOCUSED_SCORE_VERSION],
            ).fetchdf()
    except (duckdb.Error, OSError):
        stale, diagnostic = _diagnostic(None, expected, missing=True)
        return DecisionSnapshot(None, FOCUSED_SCORE_VERSION, "Unknown", _empty(), _empty(), 0, stale, diagnostic)

    as_of = pd.Timestamp(latest).date()
    stale, diagnostic = _diagnostic(as_of, expected)
    if frame.empty:
        return DecisionSnapshot(as_of, FOCUSED_SCORE_VERSION, "Unknown", frame, frame.copy(), 0, stale, diagnostic)

    cap = pd.to_numeric(frame.get("market_cap_cr"), errors="coerce")
    cap_excluded = cap.isna() | (cap < MIN_MARKET_CAP_CR)
    eligible_mask = (
        frame.get("eligibility_status", pd.Series(index=frame.index, dtype=object)).astype(str).str.lower().eq("eligible")
        & cap.notna()
        & (cap >= MIN_MARKET_CAP_CR)
    )
    eligible = frame.loc[eligible_mask].copy()
    blocked = frame.loc[~eligible_mask].copy()
    sort_cols = [column for column in ("total_score", "symbol") if column in frame.columns]
    if sort_cols:
        eligible = eligible.sort_values(sort_cols, ascending=[False, True][: len(sort_cols)], na_position="last")
        blocked = blocked.sort_values(sort_cols, ascending=[False, True][: len(sort_cols)], na_position="last")
    market_gate = "Unknown"
    if "market_regime" in frame.columns:
        regimes = frame["market_regime"].dropna().astype(str)
        if not regimes.empty:
            market_gate = regimes.iloc[0]
    return DecisionSnapshot(as_of, FOCUSED_SCORE_VERSION, market_gate, eligible.reset_index(drop=True), blocked.reset_index(drop=True), int(cap_excluded.sum()), stale, diagnostic)


__all__ = ["DecisionSnapshot", "FOCUSED_SCORE_VERSION", "MIN_MARKET_CAP_CR", "load_decision_snapshot"]
