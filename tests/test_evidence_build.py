"""End to end: build_evidence_tables on a fixture DB, write to a separate DB, serve through the v2 services."""
from __future__ import annotations

import hashlib
import shutil

import duckdb
import pytest

from Scripts.evidence import TABLES, build_evidence_tables, write_evidence_tables
from Scripts.evidence import run as cli
from tests import evidence_fixture as fx


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("evidence")
    market = fx.build_db(tmp / "market.duckdb")
    con = duckdb.connect(str(market), read_only=True)
    try:
        tables = build_evidence_tables(con)
    finally:
        con.close()
    serve = tmp / "serve.duckdb"
    shutil.copy(market, serve)
    out = duckdb.connect(str(serve))
    try:
        counts = write_evidence_tables(out, tables)
    finally:
        out.close()
    return market, serve, tables, counts


def test_all_tables_built_and_written(served):
    _market, serve, tables, counts = served
    assert set(TABLES) <= set(counts)
    con = duckdb.connect(str(serve), read_only=True)
    try:
        for t in TABLES:
            assert con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] == counts[t]
        # rewrite is idempotent (CREATE OR REPLACE)
    finally:
        con.close()
    so = tables["setup_outcomes"]
    assert {"queue", "setup_id", "signal_date", "r_multiple", "hit_2r", "environment_state", "group_quadrant"} <= set(so.columns)
    assert set(so["queue"]) <= {"darvas_squeeze", "vcp", "momentum"}
    assert (so["environment_state"].dropna().isin(["Favourable", "Constructive", "Mixed", "Weak", "Danger"])).all()
    meta = dict(zip(tables["evidence_meta"]["key"], tables["evidence_meta"]["value"]))
    assert '"regime_daily.verdict"' == meta["env_source"]


def test_services_read_evidence_tables(served, monkeypatch, tmp_path):
    _market, serve, tables, _ = served
    monkeypatch.setenv("MP_DB_PATH", str(serve))
    monkeypatch.setenv("MP_HOLIDAYS_PATH", str(tmp_path / "none.json"))
    from App.services import db, evidence, research, stock

    db.clear_cache()
    ev = evidence.evidence(None, "momentum")
    assert ev.status == "ok" and ev.rows and ev.rows[0]["bucket"] == "all"
    assert all(("n" in r) and (r["insufficient_sample"] == (r["n"] < 30)) for r in ev.rows)
    an = research.analogs(None)
    assert an.status == "ok" and len(an.rows) == 10 and an.extra["k"] == 10
    assert {"analog_date", "distance", "fwd_midsml400_20d_pct"} <= set(an.rows[0])
    bm = research.big_moves(None)
    assert bm.status == "ok" and bm.rows and "lift" in bm.extra and "feature_path" in bm.extra
    assert {"broad_sector", "sector", "broad_industry", "industry", "path_pct", "verdict_then"} <= set(bm.rows[0])
    one = research.big_move(None, bm.rows[0]["event_id"])
    assert one.rows and one.extra["features"] and {"feature", "offset", "mover_value"} <= set(one.extra["features"][0])
    assert research.group_studies(None, "industry").rows
    # time travel: an event is hidden before it was confirmed; its 60-session outcome is nulled while open
    first = min(tables["big_move_events"]["confirmed_date"])
    early = research.big_moves(first.date())
    assert all(r["confirmed_date"] <= first.date() for r in early.rows)
    assert all(r["move_pct"] is None for r in early.rows)
    sa = stock.analogs(None, "JUMPA")
    assert sa.status == "ok" and "distribution" in sa.extra


def test_cli_never_writes_the_market_db(tmp_path):
    market = fx.build_db(tmp_path / "market.duckdb")
    before = hashlib.sha256(market.read_bytes()).hexdigest()
    with pytest.raises(SystemExit):
        cli.main(["--db", str(market), "--out", str(market)])
    out = tmp_path / "evidence.duckdb"
    assert cli.main(["--db", str(market), "--out", str(out), "--pr-dir", "none"]) == 0
    assert hashlib.sha256(market.read_bytes()).hexdigest() == before
    con = duckdb.connect(str(out), read_only=True)
    try:
        names = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    finally:
        con.close()
    assert set(TABLES) <= names
