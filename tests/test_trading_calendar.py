from __future__ import annotations

from datetime import date, datetime

from trading_calendar import build_calendar, expected_latest_session, observed_sessions, parse_holiday_payload

PAYLOAD = {"CM": [{"tradingDate": "26-Jan-2026", "weekDay": "Monday", "description": "Republic Day"},
                  {"tradingDate": "02-Oct-2026", "weekDay": "Friday", "description": "Gandhi Jayanti"}],
           "CBM": [{"tradingDate": "15-Jan-2026"}]}


def test_parse_holidays_prefers_cm_segment():
    assert parse_holiday_payload(PAYLOAD) == [date(2026, 1, 26), date(2026, 10, 2)]
    assert parse_holiday_payload({"XX": [{"tradingDate": "01-May-2026"}]}) == [date(2026, 5, 1)]


def test_observed_sessions_from_manifest_and_files(tmp_path):
    (tmp_path / "sec_bhavdata_full_25092026.csv").write_text("x")
    manifest = {("2026-09-24", "bhav"): {"status": "ok"}, ("2026-09-23", "bhav"): {"status": "error"},
                ("2026-09-22", "index"): {"status": "ok"}}
    assert observed_sessions(manifest, [tmp_path]) == {date(2026, 9, 24), date(2026, 9, 25)}


def test_build_calendar_reasons():
    sessions = {date(2026, 11, 6), date(2026, 11, 8)}  # Fri + Sunday Muhurat
    holidays = {date(2026, 11, 10)}
    cal = build_calendar(date(2026, 11, 6), date(2026, 11, 10), sessions, holidays).set_index("trade_date")
    assert cal.loc[date(2026, 11, 6), "reason"] == "session"
    assert cal.loc[date(2026, 11, 7), "reason"] == "weekend"
    assert cal.loc[date(2026, 11, 8), "reason"] == "special_session"
    assert cal.loc[date(2026, 11, 9), "reason"] == "unknown"
    assert cal.loc[date(2026, 11, 10), "reason"] == "holiday"
    assert bool(cal.loc[date(2026, 11, 8), "is_session"]) is True


def test_expected_latest_session_skips_weekend_and_holiday():
    holidays = {date(2026, 10, 2)}
    # Saturday 3-Oct evening → Thursday 1-Oct (Fri 2-Oct is a holiday)
    assert expected_latest_session(datetime(2026, 10, 3, 20, 0), set(), holidays) == date(2026, 10, 1)
    # Monday 5-Oct morning (before close) → still Thursday 1-Oct
    assert expected_latest_session(datetime(2026, 10, 5, 9, 0), set(), holidays) == date(2026, 10, 1)
    # Monday evening → Monday
    assert expected_latest_session(datetime(2026, 10, 5, 19, 0), set(), holidays) == date(2026, 10, 5)
    # Sunday Muhurat session already observed → that Sunday
    assert expected_latest_session(datetime(2026, 11, 8, 20, 0), {date(2026, 11, 8)}, set()) == date(2026, 11, 8)
