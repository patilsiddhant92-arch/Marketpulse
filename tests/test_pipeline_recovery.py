from __future__ import annotations

from datetime import date
from zipfile import ZipFile
from pathlib import Path
import json

import duckdb


def _write_pr_zip(path):
    with ZipFile(path, "w") as archive:
        archive.writestr("an07082026.txt", "Acme Technologies Limited ACME : General Updates : Order announced\n")
        archive.writestr("bm07082026.txt", "Acme Technologies Limited ACME : 14-AUG-2026 : Financial Results : Results meeting\n")
        archive.writestr("bc07082026.csv", "SERIES,SYMBOL,SECURITY,RECORD_DT,BC_STRT_DT,BC_END_DT,EX_DT,ND_STRT_DT,ND_END_DT,PURPOSE\nEQ,ACME,Acme Technologies Limited,2026-08-20,,,,,,DIVIDEND\n")
        archive.writestr("bh07082026.csv", "SYMBOL,SERIES,SECURITY,HIGH/LOW\nACME,EQ,Acme Technologies Limited,H\n")
        archive.writestr("hl07082026.csv", "SECURITY,NEW,PREVIOUS,NEW_STATUS\nAcme Technologies Limited,120,110,H\n")
        archive.writestr("tt07082026.csv", "SECURITY,PREV_CL_PR,CLOSE_PRIC,NET_TRDQTY,NET_TRDVAL\nAcme Technologies Limited,110,120,1000,1200000\n")


def _seed_core_db(path):
    from Scripts.migrations import run_migrations

    run_migrations(path)
    with duckdb.connect(str(path)) as db:
        db.execute("CREATE TABLE indicators_daily (symbol TEXT, trade_date DATE, close_price DOUBLE, high_20d DOUBLE, low_10d DOUBLE, ema_20 DOUBLE, high_50d DOUBLE, avg_traded_value_cr_20d DOUBLE, rs_percentile DOUBLE, rs_1y_percentile DOUBLE, rs_3m_percentile DOUBLE, trend_score DOUBLE, contraction_score DOUBLE, volume_dryup_score DOUBLE, pivot_proximity_score DOUBLE, close_location_pct DOUBLE, delivery_pct DOUBLE, avg_delivery_pct_20d DOUBLE, rvol DOUBLE, ema_stack_bullish BOOLEAN, near_52w_high BOOLEAN, sector TEXT, industry TEXT)")
        db.execute("INSERT INTO indicators_daily VALUES ('ACME', '2026-08-07', 100, 103, 94, 96, 120, 25, 90, 85, 88, 80, 70, 60, 75, 80, 55, 45, 1.4, true, true, 'Technology', 'Software')")
        db.execute("CREATE TABLE breadth_daily (trade_date DATE, breadth_state TEXT, advance_pct DOUBLE, above_50ema_pct DOUBLE, above_200ema_pct DOUBLE)")
        db.execute("INSERT INTO breadth_daily VALUES ('2026-08-07', 'Broad', 65, 70, 60)")
        db.execute("CREATE TABLE stocks_master (symbol TEXT, sector TEXT, industry TEXT, market_cap_cr DOUBLE, band DOUBLE)")
        db.execute("INSERT INTO stocks_master VALUES ('ACME', 'Technology', 'Software', 2500, 10)")
        db.execute("CREATE TABLE deals (symbol TEXT, trade_date DATE, deal_value_cr DOUBLE, side TEXT)")
        db.execute("CREATE TABLE sector_rotation (trade_date DATE, group_name TEXT, level TEXT, rotation_state TEXT, rotation_score DOUBLE)")


def test_prepare_session_manifest_records_and_validates_all_reports(tmp_path):
    from Scripts.ingestion_manifest import prepare_session_manifest, read_manifest

    session = tmp_path / "07082026"
    session.mkdir()
    report = session / "sec_bhavdata_full_07082026.csv"
    report.write_text("SYMBOL,DATE1,CLOSE_PRICE\nACME,07-Aug-2026,100\n", encoding="utf-8")
    zip_path = session / "PR070826.zip"
    _write_pr_zip(zip_path)

    manifest_path = prepare_session_manifest(session, date(2026, 8, 7), [report.name, zip_path.name])
    manifest = read_manifest(manifest_path)

    assert manifest.status == "validated"
    assert {item.filename for item in manifest.reports} == {report.name, zip_path.name}

    report.write_text("changed", encoding="utf-8")
    try:
        read_manifest(manifest_path)
    except ValueError as exc:
        assert "checksum mismatch" in str(exc)
    else:
        raise AssertionError("checksum change must invalidate the manifest")


def test_process_accepted_session_ingests_pr_and_materializes_focused_v2(tmp_path):
    from Scripts.decision_pipeline import process_accepted_session

    db_path = tmp_path / "marketpulse.duckdb"
    _seed_core_db(db_path)
    session = tmp_path / "07082026"
    session.mkdir()
    _write_pr_zip(session / "PR070826.zip")

    first = process_accepted_session(db_path, session, date(2026, 8, 7))
    second = process_accepted_session(db_path, session, date(2026, 8, 7))

    assert first["decision_rows"] == 1
    assert first["pr_counts"]["security_events"] == 2
    assert first == second
    with duckdb.connect(str(db_path), read_only=True) as db:
        assert db.execute("SELECT count(*) FROM security_events").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM candidate_daily WHERE score_version = 'focused-v2'").fetchone()[0] == 1


def test_daily_pipeline_wires_downloaded_session_to_decision_processing():
    root = Path(__file__).resolve().parents[1]
    daily_source = (root / "Scripts" / "daily_pipeline.py").read_text(encoding="utf-8")
    download_source = (root / "Scripts" / "download_nse_reports.py").read_text(encoding="utf-8")

    assert "process_accepted_session" in daily_source
    assert "prepare_session_manifest" in download_source


def test_pipeline_health_is_not_healthy_when_focused_v2_is_missing(tmp_path):
    from Scripts.pipeline_health import assess_pipeline
    from Scripts.migrations import run_migrations

    db_path = tmp_path / "marketpulse.duckdb"
    status_path = tmp_path / "status.json"
    run_migrations(db_path)
    with duckdb.connect(str(db_path)) as db:
        db.execute("CREATE TABLE prices_daily (trade_date DATE)")
        db.execute("INSERT INTO prices_daily VALUES ('2026-08-07')")
        db.execute("INSERT INTO candidate_daily (trade_date, symbol, score_version, total_score) VALUES ('2026-08-07', 'AAA', 'focused-v1', 70)")
    status_path.write_text(json.dumps({"ok": True, "steps": []}), encoding="utf-8")

    report = assess_pipeline(db_path, status_path=status_path, expected_session="2026-08-07")

    assert report.status == "Partial"
    assert "focused-v2" in report.message
