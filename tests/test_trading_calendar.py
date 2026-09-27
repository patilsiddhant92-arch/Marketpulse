from __future__ import annotations

from datetime import date, datetime, timezone

from trading_calendar import build_calendar, expected_latest_session, observed_sessions, parse_holiday_payload

PAYLOAD = {"CM": [{"tradingDate": "26-Jan-2026", "weekDay": "Monday", "description": "Republic Day"},
                  {"tradingDate": "02-Oct-2026", "weekDay": "Friday", "description": "Gandhi Jayanti"}],
           "CBM": [{"tradingDate": "15-Jan-2026"}]}


def test_parse_holidays_prefers_cm_segment():
    assert parse_holiday_payload(PAYLOAD) == [date(2026, 1, 26), date(2026, 10, 2)]
    assert parse_holiday_payload({"XX": [{"tradingDate": "01-May-2026"}]}) == [date(2026, 5, 1)]


_BHAV_HEADER = "SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER\n"


def _bhav_csv(date1_str: str) -> str:
    return _BHAV_HEADER + f"20MICRONS, EQ, {date1_str}, 35.20, 36.00, 36.80, 35.25, 35.65, 35.80, 35.96, 49077, 17.65, 370, 36031, 73.42\n"


def test_observed_sessions_uses_internal_date1_not_filename(tmp_path):
    # NSE served a duplicate copy of Friday's bhavcopy under a Sunday-dated filename;
    # the file's internal DATE1 (not the filename) says which day was actually traded.
    (tmp_path / "sec_bhavdata_full_05012020.csv").write_text(_bhav_csv("03-Jan-2020"))
    manifest = {("2020-01-05", "bhav"): {"status": "ok"}}
    sessions = observed_sessions(manifest, [tmp_path])
    assert date(2020, 1, 5) not in sessions
    assert date(2020, 1, 3) in sessions


def test_observed_sessions_muhurat_date1(tmp_path):
    # sec_bhavdata_full_05112021.csv is named for Friday 5-Nov-2021 but its DATE1 holds
    # the Thursday 4-Nov-2021 Diwali Muhurat session.
    (tmp_path / "sec_bhavdata_full_05112021.csv").write_text(_bhav_csv("04-Nov-2021"))
    manifest = {("2021-11-05", "bhav"): {"status": "ok"}}
    sessions = observed_sessions(manifest, [tmp_path])
    assert date(2021, 11, 4) in sessions


def test_observed_sessions_manifest_ok_without_file_is_ignored(tmp_path):
    manifest = {("2026-09-24", "bhav"): {"status": "ok"}}
    assert observed_sessions(manifest, [tmp_path]) == set()


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


def test_expected_latest_session_respects_special_sessions():
    # Repro: Monday 9-Nov with holiday, Sunday 8-Nov is Muhurat session
    # Should return Sunday Muhurat session, not skip it as a weekend
    assert expected_latest_session(datetime(2026, 11, 9, 20, 0), {date(2026, 11, 8)}, {date(2026, 11, 9)}) == date(2026, 11, 8)


def test_expected_latest_session_with_timezone_aware():
    # Monday 5-Oct 13:00 UTC = 18:30 IST (after close, current day)
    assert expected_latest_session(datetime(2026, 10, 5, 13, 0, tzinfo=timezone.utc), set(), set()) == date(2026, 10, 5)
    # Monday 5-Oct 11:00 UTC = 16:30 IST (before close, previous day)
    assert expected_latest_session(datetime(2026, 10, 5, 11, 0, tzinfo=timezone.utc), set(), set()) == date(2026, 10, 2)
