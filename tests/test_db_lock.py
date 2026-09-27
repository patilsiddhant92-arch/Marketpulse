import json
import os
import subprocess
import sys
import threading
import time

import pytest

import db_lock
from db_lock import WriterLockTimeout, lock_path_for, writer_lock


def _dead_pid() -> int:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def test_lock_file_created_and_removed(tmp_path):
    db = tmp_path / "marketpulse.duckdb"
    lock = lock_path_for(db)
    assert lock.name == "marketpulse.duckdb.write.lock"
    with writer_lock(db):
        assert lock.exists()
        info = json.loads(lock.read_text(encoding="utf-8"))
        assert info["pid"] == os.getpid()
        assert "created_at" in info
    assert not lock.exists()


def test_reentrant_in_same_thread(tmp_path):
    db = tmp_path / "x.duckdb"
    with writer_lock(db, timeout_s=0.5):
        with writer_lock(db, timeout_s=0.5):
            assert lock_path_for(db).exists()
        # inner exit must not release the outer hold
        assert lock_path_for(db).exists()
    assert not lock_path_for(db).exists()


def test_released_on_exception(tmp_path):
    db = tmp_path / "x.duckdb"
    with pytest.raises(ValueError):
        with writer_lock(db):
            raise ValueError("boom")
    assert not lock_path_for(db).exists()


def test_times_out_when_held_by_live_process(tmp_path):
    db = tmp_path / "x.duckdb"
    lock = lock_path_for(db)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        lock.write_text(json.dumps({"pid": child.pid, "created_at": "now", "created_ts": time.time()}), encoding="utf-8")
        started = time.monotonic()
        with pytest.raises(WriterLockTimeout) as exc:
            with writer_lock(db, timeout_s=0.6, poll_s=0.1):
                pass
        assert time.monotonic() - started >= 0.5
        assert str(child.pid) in str(exc.value)
        assert str(lock) in str(exc.value)
        assert lock.exists()  # a live holder's lock is never broken
    finally:
        child.kill()
        child.wait()


def test_breaks_lock_of_dead_pid(tmp_path, capsys):
    db = tmp_path / "x.duckdb"
    lock = lock_path_for(db)
    lock.write_text(json.dumps({"pid": _dead_pid(), "created_at": "then", "created_ts": time.time()}), encoding="utf-8")
    with writer_lock(db, timeout_s=2, poll_s=0.05):
        info = json.loads(lock.read_text(encoding="utf-8"))
        assert info["pid"] == os.getpid()
    assert "stale" in capsys.readouterr().out.lower()


def test_breaks_lock_older_than_stale_hours(tmp_path, capsys):
    db = tmp_path / "x.duckdb"
    lock = lock_path_for(db)
    lock.write_text(json.dumps({"pid": os.getppid(), "created_at": "old", "created_ts": time.time() - 7 * 3600}), encoding="utf-8")
    with writer_lock(db, timeout_s=2, poll_s=0.05, stale_hours=6):
        pass
    assert "stale" in capsys.readouterr().out.lower()


def test_other_thread_waits_for_release(tmp_path):
    db = tmp_path / "x.duckdb"
    order = []
    entered = threading.Event()

    def holder():
        with writer_lock(db):
            entered.set()
            time.sleep(0.4)
            order.append("holder_done")

    t = threading.Thread(target=holder)
    t.start()
    entered.wait(2)
    with writer_lock(db, timeout_s=5, poll_s=0.05):
        order.append("waiter_in")
    t.join()
    assert order == ["holder_done", "waiter_in"]


def test_pid_alive_helper():
    assert db_lock.pid_alive(os.getpid())
    assert not db_lock.pid_alive(_dead_pid())
