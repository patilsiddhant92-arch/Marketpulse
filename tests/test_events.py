from datetime import date

import pandas as pd


def test_event_risk_reports_session_windows():
    from Scripts.events import event_risk_for_date

    events = pd.DataFrame(
        [{"symbol": "AAA", "event_date": date(2026, 8, 5), "event_type": "financial_results", "headline": "Q1"}]
    )
    sessions = pd.to_datetime(["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06"])

    risk = event_risk_for_date(events, "AAA", date(2026, 8, 3), sessions)

    assert risk["days_to_next_event"] == 2
    assert risk["event_within_3_sessions"] is True
    assert risk["event_risk"] == "high"


def test_normalize_events_deduplicates_schema_key():
    from Scripts.events import normalize_events

    rows = pd.DataFrame(
        [
            {"symbol": "AAA", "event_date": "2026-08-05", "event_type": "results", "source_id": "x"},
            {"symbol": "AAA", "event_date": "2026-08-05", "event_type": "financial_results", "source_id": "x"},
        ]
    )
    result = normalize_events(rows)

    assert len(result) == 1
    assert result.iloc[0]["event_type"] == "financial_results"
