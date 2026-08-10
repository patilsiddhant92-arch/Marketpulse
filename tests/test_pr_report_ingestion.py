from __future__ import annotations

from datetime import date
from zipfile import ZipFile

import duckdb


def _write_fixture(path):
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "an07082026.txt",
            "Acme Technologies Limited ACME : Outcome of Board Meeting : Financial results approved\n"
            "Bad line without a symbol\n",
        )
        archive.writestr(
            "bm07082026.txt",
            "Acme Technologies Limited ACME : 14-AUG-2026 : Financial Results : Results meeting\n",
        )
        archive.writestr(
            "bc07082026.csv",
            "SERIES,SYMBOL,SECURITY,RECORD_DT,BC_STRT_DT,BC_END_DT,EX_DT,ND_STRT_DT,ND_END_DT,PURPOSE\n"
            "EQ,ACME,Acme Technologies Limited,2026-08-20,,,,,,DIVIDEND\n"
            "EQ,ACME,Acme Technologies Limited,2026-08-20,,,,2026-08-19,,BONUS ISSUE\n",
        )
        archive.writestr(
            "bh07082026.csv",
            "SYMBOL,SERIES,SECURITY,HIGH/LOW\nACME,EQ,Acme Technologies Limited,H\n",
        )
        archive.writestr(
            "hl07082026.csv",
            "SECURITY,NEW,PREVIOUS,NEW_STATUS\nAcme Technologies Limited,120,110,H\n",
        )
        archive.writestr(
            "tt07082026.csv",
            "SECURITY,PREV_CL_PR,CLOSE_PRIC,NET_TRDQTY,NET_TRDVAL\nAcme Technologies Limited,110,120,1000,1200000\n",
        )


def test_parse_pr_zip_maps_announcements_actions_and_risk_reports(tmp_path):
    from Scripts.pr_report_ingestion import parse_pr_zip

    path = tmp_path / "PR070826.zip"
    _write_fixture(path)

    bundle = parse_pr_zip(path, date(2026, 8, 7))

    assert bundle.events["symbol"].tolist() == ["ACME", "ACME"]
    assert set(bundle.events["event_type"]) == {"financial_results", "board_meeting"}
    assert set(bundle.corporate_actions["action_type"]) == {"dividend", "bonus"}
    assert bundle.risk_daily["risk_type"].tolist() == ["new_high", "new_high"]
    assert bundle.risk_daily["security_name"].tolist() == ["Acme Technologies Limited", "Acme Technologies Limited"]
    assert bundle.top_value.iloc[0]["net_trade_value_cr"] == 0.12


def test_upsert_pr_bundle_is_idempotent_and_records_source_checksum(tmp_path):
    from Scripts.migrations import run_migrations
    from Scripts.pr_report_ingestion import parse_pr_zip, upsert_pr_bundle

    zip_path = tmp_path / "PR070826.zip"
    db_path = tmp_path / "marketpulse.duckdb"
    _write_fixture(zip_path)
    run_migrations(db_path)
    bundle = parse_pr_zip(zip_path, date(2026, 8, 7))

    first = upsert_pr_bundle(db_path, bundle, "sha-test")
    second = upsert_pr_bundle(db_path, bundle, "sha-test")

    assert first == second
    with duckdb.connect(str(db_path), read_only=True) as db:
        assert db.execute("SELECT count(*) FROM security_events").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM corporate_actions").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM security_risk_daily").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM top_value_daily").fetchone()[0] == 1
        assert db.execute("SELECT DISTINCT source_checksum FROM security_events").fetchall() == [("sha-test",)]
