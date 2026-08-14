"""Signal ledger state and stable identity management."""

from __future__ import annotations

import hashlib
import json
from datetime import date

import pandas as pd

# Ledger membership (correctness spine): eligible Observe + Prepare + Triggered + Invalidated.
# Blocked candidates never enter the ledger.
LEDGER_STATES = frozenset({"Observe", "Prepare", "Triggered", "Invalidated"})


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


def _as_date(value) -> date | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return pd.Timestamp(value).date()


def resolve_first_seen(
    *,
    symbol: str,
    setup_type: str,
    score_version: str,
    trade_date: date,
    candidate_setup_first_seen,
    prior_records: list[dict],
) -> date:
    """Ledger owns first_seen: reuse prior open identity; never mint a new id daily.

    Scorer may leave setup_first_seen null. If scorer stamps as_of, ignore it when
    a prior ledger/watchlist row exists for the continuity key.
    """
    trade_date = pd.Timestamp(trade_date).date()
    prior_matches = [
        value
        for value in prior_records
        if value.get("symbol") == symbol
        and value.get("setup_type", "focused_setup") == setup_type
        and value.get("score_version") == score_version
    ]
    if prior_matches:
        # Prefer earliest prior first_seen among matching open identity rows.
        dates = []
        for row in prior_matches:
            fs = _as_date(row.get("first_seen_date") or row.get("setup_first_seen"))
            if fs is not None:
                dates.append(fs)
        if dates:
            return min(dates)

    explicit = _as_date(candidate_setup_first_seen)
    # Treat explicit equal to trade_date as "scorer default as_of" — still OK for first ever sighting.
    if explicit is not None:
        return explicit
    return trade_date


def session_age(first_seen: date, trade_date: date, session_dates: list[date] | None = None) -> int:
    """Count trading sessions from first_seen to trade_date inclusive when calendar known."""
    first_seen = pd.Timestamp(first_seen).date()
    trade_date = pd.Timestamp(trade_date).date()
    if trade_date < first_seen:
        return 1
    if session_dates:
        sessions = sorted({pd.Timestamp(d).date() for d in session_dates})
        in_range = [d for d in sessions if first_seen <= d <= trade_date]
        return max(1, len(in_range))
    return max(1, (trade_date - first_seen).days + 1)


def apply_stable_identity(
    candidate_rows: pd.DataFrame,
    existing_ledger: pd.DataFrame | None,
    trade_date: date,
    *,
    session_dates: list[date] | None = None,
    existing_watchlist: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Rewrite setup_first_seen / setup_age_sessions using ledger-owned identity."""
    if candidate_rows is None or candidate_rows.empty:
        return candidate_rows
    prior: list[dict] = []
    if existing_ledger is not None and not existing_ledger.empty:
        prior.extend(existing_ledger.to_dict("records"))
    if existing_watchlist is not None and not existing_watchlist.empty:
        # Map watchlist rows into prior-records shape.
        for row in existing_watchlist.to_dict("records"):
            prior.append(
                {
                    "symbol": row.get("symbol"),
                    "setup_type": row.get("setup_type", "focused_setup"),
                    "score_version": row.get("score_version"),
                    "first_seen_date": row.get("first_seen_date") or row.get("setup_first_seen"),
                }
            )
    out = candidate_rows.copy()
    trade_date = pd.Timestamp(trade_date).date()
    first_seens = []
    ages = []
    for _, candidate in out.iterrows():
        symbol = str(candidate.get("symbol", "")).strip().upper()
        setup_type = str(candidate.get("setup_type", "focused_setup") or "focused_setup")
        version = str(candidate.get("score_version", "focused-v2"))
        first_seen = resolve_first_seen(
            symbol=symbol,
            setup_type=setup_type,
            score_version=version,
            trade_date=trade_date,
            candidate_setup_first_seen=candidate.get("setup_first_seen"),
            prior_records=prior,
        )
        first_seens.append(first_seen)
        ages.append(session_age(first_seen, trade_date, session_dates))
    out["setup_first_seen"] = first_seens
    out["setup_age_sessions"] = ages
    return out


def update_signal_ledger(existing: pd.DataFrame, candidate_rows: pd.DataFrame, trade_date: date) -> pd.DataFrame:
    records = {row["signal_id"]: row.to_dict() for _, row in existing.iterrows()} if existing is not None and not existing.empty else {}
    prior_list = list(records.values())
    for _, candidate in candidate_rows.iterrows():
        state = str(candidate.get("candidate_state", "Observe"))
        if state not in LEDGER_STATES:
            continue
        # Blocked-like eligibility must not enter ledger even if state mis-set.
        eligibility = str(candidate.get("eligibility_status", "") or "").lower()
        if eligibility == "blocked":
            continue
        symbol = str(candidate.get("symbol", "")).strip().upper()
        setup_type = str(candidate.get("setup_type", "focused_setup") or "focused_setup")
        version = str(candidate.get("score_version", "focused-v1"))
        first_seen = resolve_first_seen(
            symbol=symbol,
            setup_type=setup_type,
            score_version=version,
            trade_date=trade_date,
            candidate_setup_first_seen=candidate.get("setup_first_seen"),
            prior_records=prior_list,
        )
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
            "peak_score": max(float(previous.get("peak_score", candidate.get("total_score") or 0) or 0), float(candidate.get("total_score") or 0)),
            "trigger_price": candidate.get("trigger_price"),
            "invalidation_price": candidate.get("invalidation_price"),
            "market_regime": candidate.get("market_regime"),
            "sector_state": candidate.get("sector_state"),
            "industry_state": candidate.get("industry_state"),
            "feature_snapshot": json.dumps(
                {
                    key: candidate.get(key)
                    for key in (
                        "total_score",
                        "leadership_score",
                        "setup_score",
                        "participation_score",
                        "context_score",
                        "risk_score",
                        "event_risk",
                    )
                },
                default=str,
            ),
            "state_history": json.dumps(history, default=str),
        }
        prior_list = list(records.values())
    return pd.DataFrame(records.values())
