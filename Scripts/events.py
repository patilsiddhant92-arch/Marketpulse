"""Event normalization and point-in-time event-risk helpers."""

from __future__ import annotations

import hashlib
from datetime import date

import pandas as pd


EVENT_TYPES = {
    "results": "financial_results",
    "financial result": "financial_results",
    "financial_results": "financial_results",
    "board": "board_meeting",
    "board meeting": "board_meeting",
    "board_meeting": "board_meeting",
    "dividend": "dividend",
    "bonus": "bonus",
    "split": "split",
    "rights": "rights_issue",
    "rights issue": "rights_issue",
    "merger": "merger_demerger",
    "demerger": "merger_demerger",
    "insider": "material_corporate_announcement",
}


def normalize_events(rows: pd.DataFrame) -> pd.DataFrame:
    columns = ["symbol", "event_date", "event_type", "headline", "source_id", "source_checksum"]
    if rows is None or rows.empty:
        return pd.DataFrame(columns=columns)
    result = rows.copy()
    for col in columns:
        if col not in result.columns:
            result[col] = ""
    result["symbol"] = result["symbol"].astype(str).str.strip().str.upper()
    result["event_date"] = pd.to_datetime(result["event_date"], errors="coerce").dt.normalize()
    result["event_type"] = result["event_type"].astype(str).str.strip().str.lower().map(lambda value: EVENT_TYPES.get(value, value))
    result["headline"] = result["headline"].fillna("").astype(str)
    result["source_id"] = result["source_id"].fillna("").astype(str)
    missing = result["source_checksum"].isna() | (result["source_checksum"].astype(str).str.len() == 0)
    result.loc[missing, "source_checksum"] = result.loc[missing].apply(
        lambda row: hashlib.sha256(f"{row.symbol}|{row.event_date}|{row.event_type}|{row.source_id}|{row.headline}".encode()).hexdigest(), axis=1
    )
    result = result[result["symbol"].ne("") & result["event_date"].notna() & result["event_type"].ne("")]
    return result.drop_duplicates(["symbol", "event_date", "event_type", "source_id"], keep="last")[columns].reset_index(drop=True)


def event_risk_for_date(events: pd.DataFrame, symbol: str, trade_date: date, sessions=None) -> dict:
    if events is None or events.empty:
        return {"next_event_date": None, "days_to_next_event": None, "event_within_1_session": False, "event_within_3_sessions": False, "event_within_5_sessions": False, "event_within_10_sessions": False, "event_risk": "none"}
    trade_day = pd.Timestamp(trade_date).normalize()
    sym_upper = str(symbol).strip().upper()
    if "event_date" in events.columns and "symbol" in events.columns:
        filtered = events[(events["symbol"].astype(str).str.upper() == sym_upper) & (pd.to_datetime(events["event_date"], errors="coerce") >= trade_day)]
    else:
        filtered = normalize_events(events)
        filtered = filtered[(filtered["symbol"] == sym_upper) & (filtered["event_date"] >= trade_day)]
    if filtered.empty:
        return {"next_event_date": None, "days_to_next_event": None, "event_within_1_session": False, "event_within_3_sessions": False, "event_within_5_sessions": False, "event_within_10_sessions": False, "event_risk": "none"}

    event_day = pd.Timestamp(filtered["event_date"].min()).normalize()
    session_index = None
    if sessions is not None:
        try:
            session_values = [pd.Timestamp(s).normalize() for s in (sessions if isinstance(sessions, (list, tuple, pd.Index, pd.Series)) else list(sessions))]
            session_index = session_values.index(trade_day)
            event_index = session_values.index(event_day)
            distance = max(0, event_index - session_index)
        except (ValueError, IndexError):
            distance = int((event_day - trade_day).days)
    else:
        distance = int((event_day - trade_day).days)

    return {
        "next_event_date": event_day.date(),
        "days_to_next_event": distance,

        "event_within_1_session": distance <= 1,
        "event_within_3_sessions": distance <= 3,
        "event_within_5_sessions": distance <= 5,
        "event_within_10_sessions": distance <= 10,
        "event_risk": "high" if distance <= 3 else "warn" if distance <= 10 else "none",
    }
