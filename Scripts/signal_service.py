"""Signal ledger state and stable identity management."""

from __future__ import annotations

import hashlib
import json
from datetime import date

import pandas as pd


def _signal_id(symbol: str, setup_type: str, score_version: str, first_seen: date) -> str:
    key = f"{symbol}|{setup_type}|{score_version}|{first_seen.isoformat()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def _history(value) -> list:
    if isinstance(value, list):
        return value
    try:
        return json.loads(value) if value else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def update_signal_ledger(existing: pd.DataFrame, candidate_rows: pd.DataFrame, trade_date: date) -> pd.DataFrame:
    records = {row["signal_id"]: row.to_dict() for _, row in existing.iterrows()} if existing is not None and not existing.empty else {}
    for _, candidate in candidate_rows.iterrows():
        state = str(candidate.get("candidate_state", "Observe"))
        if state not in {"Prepare", "Triggered", "Invalidated"}:
            continue
        symbol = str(candidate.get("symbol", "")).strip().upper()
        setup_type = str(candidate.get("setup_type", "focused_setup"))
        version = str(candidate.get("score_version", "focused-v1"))
        prior_matches = [value for value in records.values() if value.get("symbol") == symbol and value.get("setup_type", "focused_setup") == setup_type and value.get("score_version") == version]
        explicit_first_seen = candidate.get("setup_first_seen")
        first_seen = pd.Timestamp(explicit_first_seen if explicit_first_seen is not None and pd.notna(explicit_first_seen) else (prior_matches[0].get("first_seen_date") if prior_matches else trade_date)).date()
        signal_id = _signal_id(symbol, setup_type, version, first_seen)
        previous = records.get(signal_id, {})
        history = _history(previous.get("state_history"))
        if not history or history[-1].get("date") != str(pd.Timestamp(trade_date).date()) or history[-1].get("state") != state:
            history.append({"date": str(pd.Timestamp(trade_date).date()), "state": state, "score": candidate.get("total_score")})
        trigger_date = previous.get("trigger_date")
        if state == "Triggered" and (trigger_date is None or pd.isna(trigger_date)):
            trigger_date = pd.Timestamp(trade_date).date()
        invalidation_date = previous.get("invalidation_date")
        if state == "Invalidated" and (invalidation_date is None or pd.isna(invalidation_date)):
            invalidation_date = pd.Timestamp(trade_date).date()
        records[signal_id] = {
            **previous,
            "signal_id": signal_id,
            "symbol": symbol,
            "setup_type": setup_type,
            "score_version": version,
            "first_seen_date": first_seen,
            "last_seen_date": pd.Timestamp(trade_date).date(),
            "trigger_date": trigger_date,
            "invalidation_date": invalidation_date,
            "expiry_date": previous.get("expiry_date"),
            "status": state.lower(),
            "initial_score": previous.get("initial_score", candidate.get("total_score")),
            "peak_score": max(float(previous.get("peak_score", candidate.get("total_score") or 0)), float(candidate.get("total_score") or 0)),
            "trigger_price": candidate.get("trigger_price"),
            "invalidation_price": candidate.get("invalidation_price"),
            "market_regime": candidate.get("market_regime"),
            "sector_state": candidate.get("sector_state"),
            "industry_state": candidate.get("industry_state"),
            "feature_snapshot": json.dumps({key: candidate.get(key) for key in ("total_score", "leadership_score", "setup_score", "participation_score", "context_score", "risk_score", "event_risk")}, default=str),
            "state_history": json.dumps(history, default=str),
        }
    return pd.DataFrame(records.values())
