"""Every market-DB writer entry point waits for / respects the shared writer lock."""
from __future__ import annotations

import json
import subprocess
import sys
import time

import duckdb
import pandas as pd
import pytest

import db_lock
from db_lock import WriterLockTimeout, lock_path_for


@pytest.fixture
def foreign_lock(tmp_path, monkeypatch):
    """The DB's writer lock held by another live process; lock waits time out fast."""
    db = tmp_path / "marketpulse.duckdb"
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    lock_path_for(db).write_text(json.dumps({"pid": child.pid, "created_at": "now", "created_ts": time.time()}), encoding="utf-8")
    monkeypatch.setattr(db_lock, "DEFAULT_TIMEOUT_S", 0.3)
    yield db
    child.kill()
    child.wait()


def test_run_migrations_respects_lock(foreign_lock):
    from migrations import run_migrations

    with pytest.raises(WriterLockTimeout):
        run_migrations(foreign_lock)
    assert not foreign_lock.exists()


def test_materialize_respects_lock(foreign_lock):
    from materialize_decision_tables import materialize_decision_tables

    with pytest.raises(WriterLockTimeout):
        materialize_decision_tables(foreign_lock)


def test_refresh_52w_respects_lock(foreign_lock, monkeypatch):
    import refresh_52w_asof as r52

    with duckdb.connect(str(foreign_lock)) as con:
        con.execute("CREATE TABLE indicators_daily AS SELECT 'AAA' AS symbol, DATE '2026-08-03' AS trade_date, "
                    "100.0 AS close_price, 110.0 AS high_252d, 80.0 AS low_252d")
    before = foreign_lock.read_bytes()
    monkeypatch.setattr(r52, "DB_PATH", foreign_lock)
    monkeypatch.setattr(r52, "load_reference_history", lambda root: pd.DataFrame({
        "symbol": ["AAA"], "effective_date": pd.to_datetime(["2026-08-03"]), "high_52w": [120.0], "low_52w": [70.0]}))
    with pytest.raises(WriterLockTimeout):
        r52.main()
    assert foreign_lock.read_bytes() == before


def test_append_session_respects_lock(foreign_lock, monkeypatch):
    import append_database

    monkeypatch.setattr(append_database, "DB_PATH", foreign_lock)
    with pytest.raises(WriterLockTimeout):
        append_database.append_session(notify_telegram=False)


def test_refresh_deals_respects_lock(foreign_lock, monkeypatch):
    import refresh_deals

    foreign_lock.write_bytes(b"")  # exists; content irrelevant, the lock is checked first
    monkeypatch.setattr(refresh_deals, "DB_PATH", foreign_lock)
    with pytest.raises(WriterLockTimeout):
        refresh_deals.refresh_deals(clean=False, fetch=False)


def test_nested_writers_do_not_deadlock(tmp_path):
    """append -> write_database -> materialize -> run_migrations all take the same lock."""
    from db_lock import writer_lock
    from migrations import run_migrations

    db = tmp_path / "marketpulse.duckdb"
    with writer_lock(db, timeout_s=0.2):
        run_migrations(db)
    assert not lock_path_for(db).exists()
