from __future__ import annotations

import duckdb


def test_outcome_summary_reports_hit_rate_mfe_and_mae_by_horizon(tmp_path):
    from App.evidence_read_model import summarize_signal_outcomes

    db_path = tmp_path / "marketpulse.duckdb"
    with duckdb.connect(str(db_path)) as db:
        db.execute("CREATE TABLE signal_ledger (signal_id TEXT, score_version TEXT, market_regime TEXT, sector_state TEXT, setup_type TEXT)")
        db.execute("CREATE TABLE signal_outcomes (signal_id TEXT, horizon_sessions INTEGER, as_of_date DATE, forward_return_pct DOUBLE, max_favourable_excursion_pct DOUBLE, max_adverse_excursion_pct DOUBLE, resolved BOOLEAN)")
        db.executemany(
            "INSERT INTO signal_ledger VALUES (?, 'focused-v2', ?, ?, ?)",
            [("S1", "Constructive", "Leading", "BASE"), ("S2", "Constructive", "Leading", "BASE")],
        )
        db.executemany(
            "INSERT INTO signal_outcomes VALUES (?, 10, '2026-08-17', ?, ?, ?, TRUE)",
            [("S1", 8.0, 12.0, -3.0), ("S2", -2.0, 5.0, -7.0)],
        )
        db.execute("INSERT INTO signal_ledger VALUES ('S3', 'focused-v2', 'Constructive', 'Leading', 'BASE')")
        db.execute("INSERT INTO signal_outcomes VALUES ('S3', 10, '2026-08-17', -100, 0, -100, FALSE)")

    result = summarize_signal_outcomes(db_path, score_version="focused-v2")

    row = result.iloc[0]
    assert row["horizon_sessions"] == 10
    assert row["resolved_count"] == 2
    assert row["hit_rate_pct"] == 50.0
    assert row["avg_mfe_pct"] == 8.5
    assert row["avg_mae_pct"] == -5.0


def test_outcome_summary_preserves_regime_sector_and_setup_breakdown(tmp_path):
    from App.evidence_read_model import summarize_signal_outcomes

    db_path = tmp_path / "marketpulse.duckdb"
    with duckdb.connect(str(db_path)) as db:
        db.execute("CREATE TABLE signal_ledger (signal_id TEXT, score_version TEXT, market_regime TEXT, sector_state TEXT, setup_type TEXT)")
        db.execute("CREATE TABLE signal_outcomes (signal_id TEXT, horizon_sessions INTEGER, as_of_date DATE, forward_return_pct DOUBLE, max_favourable_excursion_pct DOUBLE, max_adverse_excursion_pct DOUBLE, resolved BOOLEAN)")
        db.execute("INSERT INTO signal_ledger VALUES ('S1', 'focused-v2', 'Constructive', 'Leading', 'BASE')")
        db.execute("INSERT INTO signal_ledger VALUES ('S2', 'focused-v2', 'Risk-Off', 'Lagging', 'BREAKOUT')")
        db.execute("INSERT INTO signal_outcomes VALUES ('S1', 10, '2026-08-17', 8, 12, -3, TRUE)")
        db.execute("INSERT INTO signal_outcomes VALUES ('S2', 10, '2026-08-17', -2, 5, -7, TRUE)")

    result = summarize_signal_outcomes(db_path, score_version="focused-v2")

    assert len(result) == 2
    assert set(result["market_regime"]) == {"Constructive", "Risk-Off"}


def test_outcome_summary_returns_empty_frame_when_contract_is_missing(tmp_path):
    from App.evidence_read_model import summarize_signal_outcomes

    result = summarize_signal_outcomes(tmp_path / "missing.duckdb")

    assert result.empty


def test_outcome_summary_omits_groups_with_no_resolved_outcomes(tmp_path):
    from App.evidence_read_model import summarize_signal_outcomes

    db_path = tmp_path / "marketpulse.duckdb"
    with duckdb.connect(str(db_path)) as db:
        db.execute("CREATE TABLE signal_ledger (signal_id TEXT, score_version TEXT, market_regime TEXT, sector_state TEXT, setup_type TEXT)")
        db.execute("CREATE TABLE signal_outcomes (signal_id TEXT, horizon_sessions INTEGER, as_of_date DATE, forward_return_pct DOUBLE, max_favourable_excursion_pct DOUBLE, max_adverse_excursion_pct DOUBLE, resolved BOOLEAN)")
        db.execute("INSERT INTO signal_ledger VALUES ('S1', 'focused-v2', 'Risk-Off', 'Lagging', 'BASE')")
        db.execute("INSERT INTO signal_outcomes VALUES ('S1', 20, '2026-08-17', NULL, NULL, NULL, FALSE)")

    result = summarize_signal_outcomes(db_path, score_version="focused-v2")

    assert result.empty
