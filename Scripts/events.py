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


def _no_event() -> dict:
    return {"next_event_date": None, "days_to_next_event": None, "event_within_1_session": False, "event_within_3_sessions": False, "event_within_5_sessions": False, "event_within_10_sessions": False, "event_risk": "none"}


class PreparedEvents:
    """Events pre-normalised once for many ``event_risk_for_date`` lookups.

    Holds, per upper-cased symbol key, the parsed event dates (used for the ``>= trade
    day`` filter) and the original ``event_date`` values (whose min is reported), so a
    lookup touches only that symbol's rows instead of re-upper-casing and re-parsing the
    whole table. Keys/parsing are computed with exactly the expressions the per-call
    path used over the full table, so results are identical.
    """

    __slots__ = ("empty", "_parsed", "_original", "_positions", "_on_or_after")

    def __init__(self, events: pd.DataFrame | None):
        self._positions: dict = {}
        self._on_or_after: dict = {}
        self._parsed = self._original = None
        self.empty = events is None or events.empty
        if self.empty:
            return
        if "event_date" in events.columns and "symbol" in events.columns:
            keys = events["symbol"].astype(str).str.upper()
            self._parsed = pd.to_datetime(events["event_date"], errors="coerce")
            self._original = events["event_date"]
        else:
            normalized = normalize_events(events)
            keys = normalized["symbol"]
            self._parsed = normalized["event_date"]
            self._original = normalized["event_date"]
        self._positions = dict(keys.groupby(keys.to_numpy(), sort=False).indices)

    def next_event_day(self, sym_upper: str, trade_day: pd.Timestamp):
        """Earliest event day on/after ``trade_day`` (normalised Timestamp) or None."""
        # Full-table ``parsed >= trade_day`` (same expression as the per-call path),
        # computed once per distinct trade day and before the symbol lookup.
        on_or_after = self._on_or_after.get(trade_day)
        if on_or_after is None:
            on_or_after = (self._parsed >= trade_day).to_numpy()
            if len(self._on_or_after) >= 64:
                self._on_or_after.clear()
            self._on_or_after[trade_day] = on_or_after
        positions = self._positions.get(sym_upper)
        if positions is None:
            return None
        selected = positions[on_or_after[positions]]
        if not len(selected):
            return None
        return pd.Timestamp(self._original.iloc[selected].min()).normalize()


def prepare_events(events) -> PreparedEvents:
    """Normalise an events frame once for repeated ``event_risk_for_date`` calls."""
    if isinstance(events, PreparedEvents):
        return events
    return PreparedEvents(events)


class PreparedSessions:
    """Session calendar converted once: normalised Timestamp -> first position."""

    __slots__ = ("_positions", "_error")

    def __init__(self, sessions):
        self._positions: dict | None = None
        self._error: BaseException | None = None
        try:
            values = [pd.Timestamp(s).normalize() for s in (sessions if isinstance(sessions, (list, tuple, pd.Index, pd.Series)) else list(sessions))]
        except (ValueError, IndexError):
            return  # unusable calendar -> calendar-day distance (as before)
        except Exception as exc:  # surfaced lazily, exactly where the per-call path raised
            self._error = exc
            return
        positions: dict = {}
        for i, value in enumerate(values):
            positions.setdefault(value, i)
        self._positions = positions

    def distance(self, trade_day: pd.Timestamp, event_day: pd.Timestamp) -> int:
        if self._error is not None:
            raise self._error
        if self._positions is not None and trade_day in self._positions and event_day in self._positions:
            return max(0, self._positions[event_day] - self._positions[trade_day])
        return int((event_day - trade_day).days)


def prepare_event_sessions(sessions) -> PreparedSessions:
    if isinstance(sessions, PreparedSessions):
        return sessions
    return PreparedSessions(sessions)


def event_risk_for_date(events: pd.DataFrame | PreparedEvents, symbol: str, trade_date: date, sessions=None) -> dict:
    """Next-event risk for one symbol/day.

    ``events`` may be a raw events DataFrame or a :func:`prepare_events` result and
    ``sessions`` a session sequence or a :func:`prepare_event_sessions` result; the
    prepared forms are the fast path for scoring many symbols against the same inputs.
    """
    prepared = prepare_events(events)
    if prepared.empty:
        return _no_event()
    trade_day = pd.Timestamp(trade_date).normalize()
    sym_upper = str(symbol).strip().upper()
    event_day = prepared.next_event_day(sym_upper, trade_day)
    if event_day is None:
        return _no_event()

    if sessions is not None:
        distance = prepare_event_sessions(sessions).distance(trade_day, event_day)
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
