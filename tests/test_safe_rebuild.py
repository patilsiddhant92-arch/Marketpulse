"""safe_rebuild: full build into a temp DB, validate against the live DB, then swap safely."""
from __future__ import annotations

import hashlib

import duckdb
import pandas as pd
import pytest

import build_database as bd
import safe_rebuild as sr
from db_lock import lock_path_for


@pytest.fixture(autouse=True)
def _no_external_inputs(monkeypatch):
    monkeypatch.setattr(bd, "load_all_index_history", lambda root: pd.DataFrame())
    monkeypatch.setattr(bd, "load_reference_history", lambda root: pd.DataFrame())
    monkeypatch.setattr(sr, "_materialize", lambda db_path: None)


def _frames(last_day="2026-09-25", n=3):
    dates = pd.bdate_range(end=last_day, periods=n)
    prices = pd.DataFrame({"symbol": "AAA", "series": "EQ", "trade_date": dates, "close_price": 10.0})
    return {
        "prices": prices,
        "master": pd.DataFrame({"symbol": ["AAA"], "is_active": [True]}),
        "enrichment": pd.DataFrame({"symbol": ["AAA"]}),
        "indicators": prices[["symbol", "trade_date", "close_price"]],
        "deals": pd.DataFrame({"symbol": pd.Series([], dtype=str), "trade_date": pd.Series([], dtype="datetime64[ns]")}),
        "breadth_daily": pd.DataFrame({"trade_date": dates}),
        "sector_rotation": pd.DataFrame({"level": ["s"], "group_name": ["g"], "trade_date": [dates[-1]]}),
        "screener_results": pd.DataFrame({"screener_name": ["x"], "symbol": ["AAA"]}),
        "sector_metrics_daily": None,
        "reference_history": None,
        "price_adjustments": None,
    }


def _live(path, last_day="2026-09-24"):
    with duckdb.connect(str(path)) as con:
        con.execute(f"CREATE TABLE prices_daily AS SELECT 'OLD' AS symbol, DATE '{last_day}' AS trade_date, 1.0 AS close_price")
        con.execute("CREATE TABLE trade_journal AS SELECT range AS id FROM range(3)")
        con.execute("CREATE TABLE signal_ledger AS SELECT 'a' AS signal_id")


def _digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_rebuild_swaps_after_validation(tmp_path, monkeypatch, capsys):
    db = tmp_path / "marketpulse.duckdb"
    _live(db)
    monkeypatch.setattr(sr, "compute_full_build", lambda quiet=False, **kw: _frames())
    assert sr.main(["--db", str(db)]) == 0
    with duckdb.connect(str(db), read_only=True) as con:
        assert con.execute("SELECT max(trade_date) FROM prices_daily").fetchone()[0].isoformat()[:10] == "2026-09-25"
        assert con.execute("SELECT count(*) FROM trade_journal").fetchone()[0] == 3
    assert list((tmp_path / "backups").glob("marketpulse_*.duckdb"))
    out = capsys.readouterr().out
    assert "prices_daily" in out and "2026-09-25" in out and "trade_journal" in out
    assert not lock_path_for(db).exists()
    assert not bd.temp_db_path(db).exists()


def test_dry_run_never_touches_target(tmp_path, monkeypatch, capsys):
    db = tmp_path / "marketpulse.duckdb"
    _live(db)
    before = _digest(db)
    monkeypatch.setattr(sr, "compute_full_build", lambda quiet=False, **kw: _frames())
    assert sr.main(["--db", str(db), "--dry-run"]) == 0
    assert _digest(db) == before
    assert not bd.temp_db_path(db).exists()
    assert not (tmp_path / "backups").exists()
    assert "dry run" in capsys.readouterr().out.lower()


def test_dry_run_keep_temp(tmp_path, monkeypatch):
    db = tmp_path / "marketpulse.duckdb"
    _live(db)
    monkeypatch.setattr(sr, "compute_full_build", lambda quiet=False, **kw: _frames())
    assert sr.main(["--db", str(db), "--dry-run", "--keep-temp"]) == 0
    assert bd.temp_db_path(db).exists()


def test_validation_failure_blocks_swap(tmp_path, monkeypatch, capsys):
    db = tmp_path / "marketpulse.duckdb"
    _live(db, last_day="2026-09-30")  # live is AHEAD of the rebuild
    before = _digest(db)
    monkeypatch.setattr(sr, "compute_full_build", lambda quiet=False, **kw: _frames("2026-09-25"))
    assert sr.main(["--db", str(db)]) == 2
    assert _digest(db) == before
    out = capsys.readouterr().out
    assert "max date" in out.lower()
    assert bd.temp_db_path(db).exists()  # kept for inspection


def test_validate_checks_empty_prices_and_preserved_counts(tmp_path):
    live, temp = tmp_path / "live.duckdb", tmp_path / "temp.duckdb"
    with duckdb.connect(str(live)) as con:
        con.execute("CREATE TABLE prices_daily AS SELECT 'A' AS symbol, DATE '2026-09-01' AS trade_date")
        con.execute("CREATE TABLE trade_journal AS SELECT range AS id FROM range(5)")
        con.execute("CREATE TABLE signal_ledger AS SELECT 'a' AS signal_id")
    with duckdb.connect(str(temp)) as con:
        con.execute("CREATE TABLE prices_daily (symbol TEXT, trade_date DATE)")
        con.execute("CREATE TABLE trade_journal AS SELECT range AS id FROM range(4)")
    problems = sr.validate_temp(temp, live)
    text = " | ".join(problems)
    assert "prices_daily is empty" in text
    assert "trade_journal" in text and "signal_ledger" in text


def test_fresh_target_without_live_db(tmp_path, monkeypatch):
    db = tmp_path / "new" / "marketpulse.duckdb"
    db.parent.mkdir()
    monkeypatch.setattr(sr, "compute_full_build", lambda quiet=False, **kw: _frames())
    assert sr.main(["--db", str(db)]) == 0
    assert db.exists()


def test_rebuild_forces_bhavcopy_universe():
    import inspect

    src = inspect.getsource(bd.compute_full_build)
    assert "build_prices(None)" in src
