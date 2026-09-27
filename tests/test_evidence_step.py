from __future__ import annotations

import duckdb

import evidence_step


def test_failure_is_soft_and_leaves_db_usable(tmp_path, capsys):
    db = tmp_path / "m.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE prices_daily AS SELECT 1 AS x")
    assert evidence_step.rebuild_in_place(con, db, quiet=True) == {}
    assert "EVIDENCE TABLES NOT REBUILT" in capsys.readouterr().out
    assert con.execute("SELECT x FROM prices_daily").fetchone() == (1,)
    con.close()


def test_skip_flag(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("MP_SKIP_EVIDENCE", "1")
    called = []
    monkeypatch.setattr(evidence_step.subprocess, "run", lambda *a, **k: called.append(a))
    assert evidence_step.run_isolated(tmp_path / "m.duckdb") == 0
    assert called == []
    assert "skipped" in capsys.readouterr().out
