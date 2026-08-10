from __future__ import annotations

from pathlib import Path

import duckdb


def _seed_audit_db(path: Path) -> None:
    with duckdb.connect(str(path)) as db:
        db.execute(
            """
            CREATE TABLE candidate_daily (
                trade_date DATE,
                symbol TEXT,
                score_version TEXT,
                market_cap_cr DOUBLE,
                total_score DOUBLE
            )
            """
        )
        db.executemany(
            "INSERT INTO candidate_daily VALUES (?, ?, ?, ?, ?)",
            [
                ("2026-08-07", "BIG", "focused-v1", 1200.0, 80.0),
                ("2026-08-07", "SMALL", "focused-v1", 999.99, 79.0),
                ("2026-08-07", "UNKNOWN", "focused-v1", None, 78.0),
                ("2026-08-06", "OLD", "focused-v1", 1300.0, 70.0),
                ("2026-08-07", "NEW", "focused-v2", 1500.0, 81.0),
            ],
        )
        db.execute("CREATE TABLE portfolio_positions (symbol TEXT, status TEXT)")
        db.execute("INSERT INTO portfolio_positions VALUES ('BIG', 'OPEN')")
        db.execute("CREATE TABLE security_events (symbol TEXT)")
        db.execute("INSERT INTO security_events VALUES ('BIG')")
        db.execute("CREATE TABLE corporate_actions (symbol TEXT)")
        db.execute("INSERT INTO corporate_actions VALUES ('BIG')")


def test_audit_database_reports_latest_versions_gates_and_pr_counts(tmp_path):
    from Scripts.recovery_audit import audit_database

    path = tmp_path / "marketpulse.duckdb"
    _seed_audit_db(path)

    report = audit_database(path)

    assert report.database_date.isoformat() == "2026-08-07"
    assert report.candidate_date.isoformat() == "2026-08-07"
    assert report.score_versions == {"focused-v1": 4, "focused-v2": 1}
    assert report.latest_candidate_count == 4
    assert report.below_market_cap_count == 1
    assert report.missing_market_cap_count == 1
    assert report.portfolio_count == 1
    assert report.pr_table_counts == {
        "security_events": 1,
        "corporate_actions": 1,
        "security_risk_daily": 0,
        "top_value_daily": 0,
        "ingested_reports": 0,
    }


def test_audit_database_is_read_only_and_does_not_create_schema(tmp_path):
    from Scripts.recovery_audit import audit_database

    path = tmp_path / "marketpulse.duckdb"
    with duckdb.connect(str(path)) as db:
        db.execute("CREATE TABLE prices_daily (trade_date DATE)")
        db.execute("INSERT INTO prices_daily VALUES ('2026-08-07')")
    before = path.stat().st_mtime_ns

    audit_database(path)

    after = path.stat().st_mtime_ns
    with duckdb.connect(str(path), read_only=True) as db:
        tables = {row[0] for row in db.execute("SHOW TABLES").fetchall()}
    assert before == after
    assert tables == {"prices_daily"}
