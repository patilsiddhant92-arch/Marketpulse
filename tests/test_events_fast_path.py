"""Characterization tests for the pre-normalised event-risk fast path.

``_reference_event_risk`` is a verbatim port of the pre-optimisation
``event_risk_for_date`` (which re-upper-cased / re-parsed every events row per call).
Both the public DataFrame API and the prepared fast path must match it exactly.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from Scripts.events import event_risk_for_date, normalize_events, prepare_event_sessions, prepare_events

NONE = {"next_event_date": None, "days_to_next_event": None, "event_within_1_session": False, "event_within_3_sessions": False, "event_within_5_sessions": False, "event_within_10_sessions": False, "event_risk": "none"}


def _reference_event_risk(events, symbol, trade_date, sessions=None):
    if events is None or events.empty:
        return dict(NONE)
    trade_day = pd.Timestamp(trade_date).normalize()
    sym_upper = str(symbol).strip().upper()
    if "event_date" in events.columns and "symbol" in events.columns:
        filtered = events[(events["symbol"].astype(str).str.upper() == sym_upper) & (pd.to_datetime(events["event_date"], errors="coerce") >= trade_day)]
    else:
        filtered = normalize_events(events)
        filtered = filtered[(filtered["symbol"] == sym_upper) & (filtered["event_date"] >= trade_day)]
    if filtered.empty:
        return dict(NONE)
    event_day = pd.Timestamp(filtered["event_date"].min()).normalize()
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


def _events_frames():
    base = pd.DataFrame(
        [
            {"symbol": "AAA", "event_date": date(2026, 8, 5), "event_type": "financial_results", "headline": "Q1"},
            {"symbol": "aaa", "event_date": date(2026, 8, 20), "event_type": "dividend", "headline": "div"},
            {"symbol": "AAA", "event_date": date(2026, 7, 1), "event_type": "board_meeting", "headline": "old"},
            {"symbol": " BBB", "event_date": date(2026, 8, 4), "event_type": "bonus", "headline": "space-padded symbol"},
            {"symbol": "BBB", "event_date": date(2026, 9, 30), "event_type": "split", "headline": "far"},
            {"symbol": "CCC", "event_date": None, "event_type": "split", "headline": "no date"},
            {"symbol": None, "event_date": date(2026, 8, 6), "event_type": "split", "headline": "no symbol"},
            {"symbol": "DDD", "event_date": date(2026, 8, 3), "event_type": "results", "headline": "same day"},
            {"symbol": "EEE", "event_date": date(2026, 8, 10), "event_type": "results", "headline": "not a session"},
        ]
    )
    strings = base.assign(event_date=["2026-08-05", "2026-08-20", "2026-07-01", "2026-08-04", "2026-09-30", "garbage", "2026-08-06", "2026-08-03", "2026-08-10"])
    timestamps = base.assign(event_date=pd.to_datetime(base["event_date"]))
    missing_symbol_col = base.drop(columns=["symbol"]).assign(ticker=base["symbol"])  # -> normalize_events fallback
    fallback = base.rename(columns={"event_date": "date"}).assign(event_date=base["event_date"]).drop(columns=["symbol"]).assign(Symbol=base["symbol"])
    return {"dates": base, "strings": strings, "timestamps": timestamps, "no_symbol_col": missing_symbol_col, "fallback": fallback, "empty": pd.DataFrame(), "none": None}


SESSIONS = [
    None,
    pd.to_datetime(["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-20"]),
    list(pd.to_datetime(["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-20"])),
    ["2026-08-03", "2026-08-05", "not-a-date"],  # unparseable -> calendar-day fallback
    ["2026-08-04", "2026-08-05"],  # trade day missing -> calendar-day fallback
]


@pytest.mark.parametrize("frame_name", list(_events_frames()))
@pytest.mark.parametrize("session_case", range(len(SESSIONS)))
def test_public_and_prepared_paths_match_reference(frame_name, session_case):
    events = _events_frames()[frame_name]
    sessions = SESSIONS[session_case]
    prepared = prepare_events(events)
    prepared_sessions = prepare_event_sessions(sessions) if sessions is not None else None
    for symbol in ("AAA", "aaa ", "BBB", " bbb", "CCC", "DDD", "EEE", "ZZZ", None, "NONE", "nan"):
        for trade_date in (date(2026, 8, 3), date(2026, 8, 5), date(2026, 8, 21), date(2026, 10, 1)):
            expected = _reference_event_risk(events, symbol, trade_date, sessions)
            assert event_risk_for_date(events, symbol, trade_date, sessions) == expected, (frame_name, symbol, trade_date)
            assert event_risk_for_date(prepared, symbol, trade_date, sessions) == expected, (frame_name, symbol, trade_date)
            assert event_risk_for_date(prepared, symbol, trade_date, prepared_sessions) == expected, (frame_name, symbol, trade_date)


def test_prepare_events_is_idempotent_and_does_not_mutate_input():
    events = _events_frames()["strings"]
    snapshot = events.copy()
    prepared = prepare_events(events)
    assert prepare_events(prepared) is prepared
    pd.testing.assert_frame_equal(events, snapshot)


def test_score_candidates_prepares_events_once_and_matches_per_row_reference(monkeypatch):
    from Scripts import candidate_engine

    symbols = ["AAA", "BBB", "DDD", "EEE", "ZZZ"]
    indicators = pd.DataFrame(
        [
            {"symbol": s, "trade_date": d, "close_price": 100.0 + i, "high_20d": 103.0 + i, "low_10d": 94.0, "ema_20": 96.0, "high_50d": 112.0 + i,
             "rs_percentile": 50 + i, "avg_traded_value_cr_20d": 50, "atr_pct": 3, "sector": "Technology", "industry": "Software"}
            for i, s in enumerate(symbols)
            for d in (date(2026, 7, 31), date(2026, 8, 3))
        ]
    )
    breadth = pd.DataFrame([{"trade_date": date(2026, 8, 3), "breadth_state": "Broad", "advance_pct": 65, "above_50ema_pct": 70, "above_200ema_pct": 60}])
    rotations = pd.DataFrame([{"trade_date": date(2026, 8, 3), "group_name": "Technology", "level": "sector", "rotation_state": "Leading", "rotation_score": 80}])
    index_features = pd.DataFrame([{"trade_date": date(2026, 8, 3), "index_name": "Nifty 500", "trend_state": "Constructive"}])
    events = _events_frames()["dates"]

    calls = []
    real_prepare = candidate_engine.prepare_events
    monkeypatch.setattr(candidate_engine, "prepare_events", lambda ev: calls.append(1) or real_prepare(ev))
    result = candidate_engine.score_candidates(indicators, breadth, rotations, pd.DataFrame(), index_features, events, pd.DataFrame(), date(2026, 8, 3))
    assert len(calls) == 1

    sessions = pd.to_datetime(indicators["trade_date"]).drop_duplicates().sort_values().tolist()
    expected = {s: _reference_event_risk(events, s, date(2026, 8, 3), sessions)["event_risk"] for s in symbols}
    assert result.set_index("symbol")["event_risk"].to_dict() == expected
    assert set(expected.values()) >= {"high", "none"}
