from datetime import datetime, timedelta

import duckdb
import pytest

import db_backup


def _make_db(path, rows=3):
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE TABLE t AS SELECT range AS x FROM range(?)", [rows])


def test_backup_is_dated_readable_and_in_backups_dir(tmp_path):
    db = tmp_path / "marketpulse.duckdb"
    _make_db(db, 5)
    out = db_backup.backup_database(db, now=datetime(2026, 9, 27, 20, 1, 2))
    assert out == tmp_path / "backups" / "marketpulse_20260927_200102.duckdb"
    with duckdb.connect(str(out), read_only=True) as con:
        assert con.execute("SELECT count(*) FROM t").fetchone()[0] == 5
    assert not list((tmp_path / "backups").glob("*.part"))


def test_backup_prunes_to_keep_newest(tmp_path):
    db = tmp_path / "marketpulse.duckdb"
    _make_db(db)
    start = datetime(2026, 9, 1, 20, 0, 0)
    made = [db_backup.backup_database(db, keep=5, now=start + timedelta(days=i)) for i in range(7)]
    left = sorted(p.name for p in (tmp_path / "backups").glob("marketpulse_*.duckdb"))
    assert left == sorted(p.name for p in made[-5:])


def test_prune_ignores_other_prefixes(tmp_path):
    db = tmp_path / "marketpulse.duckdb"
    _make_db(db)
    backups = tmp_path / "backups"
    backups.mkdir()
    other = backups / "marketpulse_user_20200101_000000.duckdb"
    other.write_bytes(b"x")
    for i in range(3):
        db_backup.backup_database(db, keep=1, now=datetime(2026, 9, 1 + i))
    assert other.exists()
    assert len(list(backups.glob("marketpulse_2*.duckdb"))) == 1


def test_same_second_backups_do_not_collide(tmp_path):
    db = tmp_path / "marketpulse.duckdb"
    _make_db(db)
    when = datetime(2026, 9, 27, 20, 0, 0)
    a = db_backup.backup_database(db, now=when)
    b = db_backup.backup_database(db, now=when)
    assert a != b and a.exists() and b.exists()


def test_refuses_when_disk_too_small(tmp_path, monkeypatch):
    db = tmp_path / "marketpulse.duckdb"
    _make_db(db)

    class Usage:
        total = used = 0
        free = 10

    monkeypatch.setattr(db_backup.shutil, "disk_usage", lambda p: Usage)
    with pytest.raises(db_backup.BackupError, match="free"):
        db_backup.backup_database(db)
    assert not list((tmp_path / "backups").glob("*.duckdb"))


def test_missing_db_returns_none(tmp_path):
    assert db_backup.backup_database(tmp_path / "nope.duckdb") is None


def test_user_db_backup_keeps_seven(tmp_path):
    user = tmp_path / "marketpulse_user.duckdb"
    _make_db(user)
    for i in range(9):
        db_backup.backup_user_db(user, now=datetime(2026, 9, 1 + i, 21))
    left = list((tmp_path / "backups").glob("marketpulse_user_*.duckdb"))
    assert len(left) == 7
