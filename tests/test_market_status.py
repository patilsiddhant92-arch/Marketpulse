from __future__ import annotations

import json
from datetime import date

import duckdb


def _db_with_snapshot(path, market_date: str, decision_date: str | None = None):
    from Scripts.migrations import run_migrations

    run_migrations(path)
    with duckdb.connect(str(path)) as db:
        db.execute("CREATE TABLE indicators_daily (trade_date DATE)")
        db.execute("INSERT INTO indicators_daily VALUES (?)", [market_date])
        if decision_date is not None:
            db.execute("INSERT INTO candidate_daily (trade_date, symbol, score_version) VALUES (?, 'AAA', 'focused-v2')", [decision_date])


def test_expected_nse_session_rolls_weekend_back_to_friday():
    from App.market_status import expected_nse_session

    assert expected_nse_session(date(2026, 8, 17)) == date(2026, 8, 17)
    assert expected_nse_session(date(2026, 8, 16)) == date(2026, 8, 14)


def test_load_market_status_marks_weekday_snapshot_stale(tmp_path):
    from App.market_status import load_market_status

    db_path = tmp_path / "marketpulse.duckdb"
    status_path = tmp_path / "status.json"
    _db_with_snapshot(db_path, "2026-08-14", "2026-08-14")
    status_path.write_text(json.dumps({"ok": True}), encoding="utf-8")

    status = load_market_status(db_path, status_path, today=date(2026, 8, 17))

    assert status.status == "Stale"
    assert status.actionable is False
    assert status.database_date == "2026-08-14"
    assert "expected session is 2026-08-17" in status.message


def test_load_market_status_is_actionable_when_market_and_decision_match(tmp_path):
    from App.market_status import load_market_status

    db_path = tmp_path / "marketpulse.duckdb"
    _db_with_snapshot(db_path, "2026-08-17", "2026-08-17")

    status = load_market_status(db_path, None, today=date(2026, 8, 17))

    assert status.status == "Healthy"
    assert status.actionable is True
