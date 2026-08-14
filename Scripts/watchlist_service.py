"""Persistent candidate lifecycle state."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd


TERMINAL_STATES = {"Invalidated", "Expired", "Removed", "Completed"}


def transition_candidate(previous: dict | None, current: dict) -> tuple[str, str]:
    previous_state = str((previous or {}).get("candidate_state", "Observe"))
    current_state = str(current.get("candidate_state", "Observe"))
    if previous_state in TERMINAL_STATES:
        return previous_state, f"retained terminal state {previous_state}"
    if bool(current.get("invalidated", False)) or current_state == "Invalidated":
        return "Invalidated", "invalidation condition violated"
    if bool(current.get("triggered", False)) or current_state == "Triggered":
        return "Triggered", "trigger condition confirmed"
    if current_state == "Prepare" and previous_state == "Observe":
        return "Prepare", "setup matured with valid trigger and invalidation"
    if current_state == "Prepare":
        return "Prepare", "setup remains actionable"
    return "Observe", "leadership/setup evidence remains under preparation threshold"


def _json_load(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def persist_candidate_snapshot(db_path: Path, candidate_rows: pd.DataFrame, trade_date: date) -> None:
    if candidate_rows is None or candidate_rows.empty:
        return
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with duckdb.connect(str(db_path)) as db:
        for _, row in candidate_rows.iterrows():
            symbol = str(row.get("symbol", "")).strip().upper()
            score_version = str(row.get("score_version", "focused-v1"))
            existing = db.execute(
                "SELECT * FROM watchlist_candidates WHERE symbol = ? AND score_version = ? ORDER BY updated_at DESC LIMIT 1",
                [symbol, score_version],
            ).fetchdf()
            previous = existing.iloc[0].to_dict() if not existing.empty else None
            # Prefer prior first_seen (stable identity); fall back to candidate / trade_date.
            if previous is not None and previous.get("first_seen_date") is not None and pd.notna(previous.get("first_seen_date")):
                first_seen = pd.Timestamp(previous["first_seen_date"]).date()
            elif row.get("setup_first_seen") is not None and pd.notna(row.get("setup_first_seen")):
                first_seen = pd.Timestamp(row.get("setup_first_seen")).date()
            else:
                first_seen = pd.Timestamp(trade_date).date()
            state, reason = transition_candidate(previous, row.to_dict())
            state_history = _json_load(previous.get("state_history") if previous else None)
            if not state_history or state_history[-1].get("trade_date") != str(pd.Timestamp(trade_date).date()) or state_history[-1].get("state") != state:
                state_history.append({"trade_date": str(pd.Timestamp(trade_date).date()), "state": state, "reason": reason})
            age = row.get("setup_age_sessions")
            if age is None or (isinstance(age, float) and pd.isna(age)):
                age = max(1, (pd.Timestamp(trade_date).date() - first_seen).days + 1)
            values = [
                symbol, score_version, first_seen, pd.Timestamp(trade_date).date(), state, reason,
                row.get("trigger_price"), row.get("invalidation_price"), row.get("first_resistance"),
                first_seen, age, json.dumps(state_history),
                previous.get("created_at") if previous else now, now,
            ]
            if previous:
                db.execute(
                    """
                    UPDATE watchlist_candidates SET last_seen_date=?, candidate_state=?, state_reason=?, trigger_price=?, invalidation_price=?, first_resistance=?, setup_first_seen=?, setup_age_sessions=?, state_history=?, updated_at=?
                    WHERE symbol=? AND score_version=? AND first_seen_date=?
                    """,
                    [values[3], values[4], values[5], values[6], values[7], values[8], values[9], values[10], values[11], values[13], symbol, score_version, previous["first_seen_date"]],
                )
            else:
                db.execute(
                    """INSERT INTO watchlist_candidates (symbol, score_version, first_seen_date, last_seen_date, candidate_state, state_reason, trigger_price, invalidation_price, first_resistance, setup_first_seen, setup_age_sessions, state_history, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    values,
                )


def load_watchlist(db_path: Path, states=None) -> pd.DataFrame:
    with duckdb.connect(str(db_path), read_only=True) as db:
        if states:
            placeholders = ",".join("?" for _ in states)
            return db.execute(f"SELECT * FROM watchlist_candidates WHERE candidate_state IN ({placeholders}) ORDER BY updated_at DESC", list(states)).fetchdf()
        return db.execute("SELECT * FROM watchlist_candidates ORDER BY updated_at DESC").fetchdf()
