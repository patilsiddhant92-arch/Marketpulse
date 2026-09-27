"""write_database: preservation failure aborts, dated backup, os.replace swap, clear swap errors."""
import hashlib

import duckdb
import pandas as pd
import pytest

import build_database as bd
from db_lock import lock_path_for


def _frames(n_days=3, symbol="AAA"):
    dates = pd.date_range("2026-09-01", periods=n_days, freq="B")
    prices = pd.DataFrame({"symbol": symbol, "series": "EQ", "trade_date": dates, "close_price": [10.0 + i for i in range(n_days)]})
    master = pd.DataFrame({"symbol": [symbol], "security_name": ["A Ltd"]})
    indicators = prices[["symbol", "trade_date", "close_price"]].copy()
    deals = pd.DataFrame({"symbol": pd.Series([], dtype=str), "trade_date": pd.Series([], dtype="datetime64[ns]")})
    breadth = pd.DataFrame({"trade_date": dates, "advances": 1})
    rotation = pd.DataFrame({"level": ["sector"], "group_name": ["X"], "trade_date": [dates[-1]]})
    screener = pd.DataFrame({"screener_name": ["S"], "symbol": [symbol]})
    return dict(prices=prices, master=master, enrichment=master.copy(), indicators=indicators, deals=deals,
                breadth_daily=breadth, sector_rotation=rotation, screener_results=screener)


@pytest.fixture(autouse=True)
def _no_external_inputs(monkeypatch):
    monkeypatch.setattr(bd, "load_all_index_history", lambda root: pd.DataFrame())
    monkeypatch.setattr(bd, "load_reference_history", lambda root: pd.DataFrame())


def _live_db(path):
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE TABLE prices_daily AS SELECT 'OLD' AS symbol, DATE '2026-08-01' AS trade_date, 1.0 AS close_price")
        con.execute("CREATE TABLE trade_journal AS SELECT range AS id, 'note' AS txt FROM range(4)")
        con.execute("CREATE TABLE signal_ledger AS SELECT 'sig' || range AS signal_id FROM range(2)")
        con.execute("CREATE TABLE watchlist_candidates AS SELECT 'W' AS symbol")


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(db, **extra):
    f = _frames()
    return bd.write_database(f["prices"], f["master"], f["enrichment"], f["indicators"], f["deals"],
                             f["breadth_daily"], f["sector_rotation"], f["screener_results"],
                             db_path=db, materialize=False, **extra)


def test_success_preserves_tables_backs_up_and_swaps(tmp_path):
    db = tmp_path / "marketpulse.duckdb"
    _live_db(db)
    backup = _write(db)
    with duckdb.connect(str(db), read_only=True) as con:
        assert con.execute("SELECT count(*) FROM trade_journal").fetchone()[0] == 4
        assert con.execute("SELECT count(*) FROM signal_ledger").fetchone()[0] == 2
        assert con.execute("SELECT count(*) FROM watchlist_candidates").fetchone()[0] == 1
        assert con.execute("SELECT count(*) FROM prices_daily").fetchone()[0] == 3
    assert backup is not None and backup.parent == tmp_path / "backups"
    with duckdb.connect(str(backup), read_only=True) as con:
        assert con.execute("SELECT symbol FROM prices_daily").fetchone()[0] == "OLD"
    assert not (tmp_path / "marketpulse.tmp.duckdb").exists()
    assert not (tmp_path / "marketpulse.backup.duckdb").exists()
    assert not (tmp_path / "marketpulse.duckdb.wal").exists()
    assert not lock_path_for(db).exists()


def test_fresh_db_without_live_file(tmp_path):
    db = tmp_path / "marketpulse.duckdb"
    assert _write(db) is None
    with duckdb.connect(str(db), read_only=True) as con:
        assert con.execute("SELECT count(*) FROM prices_daily").fetchone()[0] == 3


def test_preservation_failure_aborts_and_leaves_live_untouched(tmp_path, monkeypatch):
    db = tmp_path / "marketpulse.duckdb"
    _live_db(db)
    before = _digest(db)
    real = bd._copy_preserved_table

    def flaky(con, old_con, table, reference_history):
        if table == "signal_ledger":
            raise RuntimeError("disk hiccup")
        return real(con, old_con, table, reference_history)

    monkeypatch.setattr(bd, "_copy_preserved_table", flaky)
    with pytest.raises(bd.PreservationError, match="signal_ledger"):
        _write(db)
    assert _digest(db) == before
    assert not (tmp_path / "marketpulse.tmp.duckdb").exists()
    assert not (tmp_path / "backups").exists() or not list((tmp_path / "backups").iterdir())
    assert not lock_path_for(db).exists()
    # the read-only handle on the live DB was closed: a write connection opens fine
    with duckdb.connect(str(db)) as con:
        assert con.execute("SELECT count(*) FROM signal_ledger").fetchone()[0] == 2


def test_row_count_mismatch_is_a_preservation_failure(tmp_path, monkeypatch):
    db = tmp_path / "marketpulse.duckdb"
    _live_db(db)
    before = _digest(db)
    real = bd._copy_preserved_table

    def lossy(con, old_con, table, reference_history):
        n = real(con, old_con, table, reference_history)
        if table == "trade_journal":
            con.execute("DELETE FROM trade_journal WHERE id = 0")
        return n

    monkeypatch.setattr(bd, "_copy_preserved_table", lossy)
    with pytest.raises(bd.PreservationError, match="trade_journal"):
        _write(db)
    assert _digest(db) == before


def test_swap_blocked_by_reader_keeps_live_and_temp(tmp_path, monkeypatch):
    db = tmp_path / "marketpulse.duckdb"
    _live_db(db)
    before = _digest(db)
    calls = []

    def locked(src, dst):
        calls.append((src, dst))
        raise PermissionError(32, "The process cannot access the file because it is being used by another process")

    monkeypatch.setattr(bd, "_os_replace", locked)
    monkeypatch.setattr(bd, "SWAP_RETRY_WAIT_S", 0.01)
    with pytest.raises(bd.DatabaseSwapError) as exc:
        _write(db)
    temp = tmp_path / "marketpulse.tmp.duckdb"
    assert str(temp) in str(exc.value)
    assert len([c for c in calls if str(c[1]) == str(db)]) == bd.SWAP_RETRIES
    assert _digest(db) == before
    assert temp.exists()
    with duckdb.connect(str(temp), read_only=True) as con:
        assert con.execute("SELECT count(*) FROM trade_journal").fetchone()[0] == 4
    assert not lock_path_for(db).exists()


def test_backup_failure_aborts_swap(tmp_path, monkeypatch):
    db = tmp_path / "marketpulse.duckdb"
    _live_db(db)
    before = _digest(db)
    import db_backup

    def no_space(*a, **k):
        raise db_backup.BackupError("Not enough free disk space")

    monkeypatch.setattr(db_backup, "backup_database", no_space)
    with pytest.raises(bd.DatabaseSwapError, match="backup"):
        _write(db)
    assert _digest(db) == before
    assert (tmp_path / "marketpulse.tmp.duckdb").exists()
