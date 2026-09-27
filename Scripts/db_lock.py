"""Cross-process writer lock for the MarketPulse DuckDB files.

Every entry point that writes the market DB takes ``writer_lock(db_path)``. The lock is a
file next to the DB (``marketpulse.duckdb.write.lock``) created atomically with
``O_CREAT | O_EXCL`` and holding the owner's pid + timestamp. A lock whose pid is no longer
alive, or that is older than ``stale_hours``, is broken with a printed warning. The lock is
re-entrant within one thread of one process, so ``append_session -> write_database ->
materialize_decision_tables -> run_migrations`` never deadlocks on itself.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

LOCK_SUFFIX = ".write.lock"
DEFAULT_TIMEOUT_S = float(os.environ.get("MP_DB_LOCK_TIMEOUT_S", "900") or 900)
DEFAULT_STALE_HOURS = 6.0
# A lock file whose content cannot be parsed is only treated as stale once it is this old
# (its creator may simply not have written the payload yet).
_UNREADABLE_GRACE_S = 60.0

_state_guard = threading.Lock()
# resolved lock path -> [owning thread ident, depth]
_held: dict[str, list[int]] = {}


class WriterLockTimeout(RuntimeError):
    """Raised when the writer lock could not be acquired within the timeout."""


def lock_path_for(db_path: Path | str) -> Path:
    db_path = Path(db_path)
    return db_path.with_name(db_path.name + LOCK_SUFFIX)


def pid_alive(pid: int) -> bool:
    """True if a process with ``pid`` is currently running."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # Access denied means the process exists but belongs to someone else.
            return ctypes.get_last_error() == 5
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_info(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _stale_reason(path: Path, info: dict | None, stale_hours: float) -> str | None:
    now = time.time()
    if info is None:
        try:
            age = now - path.stat().st_mtime
        except OSError:
            return None  # vanished; the acquire loop simply retries
        return f"unreadable lock file {age:.0f}s old" if age > _UNREADABLE_GRACE_S else None
    pid = info.get("pid")
    try:
        created = float(info.get("created_ts"))
    except (TypeError, ValueError):
        created = None
    if created is not None and now - created > stale_hours * 3600:
        return f"lock older than {stale_hours:g}h (pid {pid}, since {info.get('created_at')})"
    if not pid_alive(pid):
        return f"owner pid {pid} is not running (since {info.get('created_at')})"
    return None


def _try_create(path: Path, owner: str) -> bool:
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    payload = {
        "pid": os.getpid(),
        "thread": threading.get_ident(),
        "host": socket.gethostname(),
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "created_ts": time.time(),
        "owner": owner or " ".join(sys.argv[:2]),
    }
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(payload))
    return True


def _release(path: Path) -> None:
    info = _read_info(path)
    if info is not None and info.get("pid") not in (None, os.getpid()):
        print(f"Warning: writer lock {path} now belongs to pid {info.get('pid')}; not removing it.")
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def is_held_here(db_path: Path | str) -> bool:
    """True if the current thread already holds the writer lock for ``db_path``."""
    key = str(lock_path_for(db_path).resolve())
    with _state_guard:
        entry = _held.get(key)
        return entry is not None and entry[0] == threading.get_ident()


@contextmanager
def writer_lock(
    db_path: Path | str,
    timeout_s: float | None = None,
    *,
    poll_s: float = 0.5,
    stale_hours: float = DEFAULT_STALE_HOURS,
    owner: str = "",
) -> Iterator[Path]:
    """Hold the exclusive writer lock for ``db_path`` for the duration of the block.

    Raises ``WriterLockTimeout`` (naming the holder and the lock file) if another live writer
    keeps it past ``timeout_s`` seconds (default ``MP_DB_LOCK_TIMEOUT_S`` or 900).
    """
    timeout_s = DEFAULT_TIMEOUT_S if timeout_s is None else float(timeout_s)
    path = lock_path_for(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = str(path.resolve())
    me = threading.get_ident()

    with _state_guard:
        entry = _held.get(key)
        reentered = entry is not None and entry[0] == me
        if reentered:
            entry[1] += 1
    if reentered:
        try:
            yield path
        finally:
            with _state_guard:
                _held[key][1] -= 1
        return

    deadline = time.monotonic() + max(0.0, timeout_s)
    announced = False
    while True:
        with _state_guard:
            busy_here = key in _held  # another thread of this process holds it
            if not busy_here and _try_create(path, owner):
                _held[key] = [me, 1]
                break
        if not busy_here:
            info = _read_info(path)
            reason = _stale_reason(path, info, stale_hours)
            if reason:
                # Re-read right before breaking so we never delete a lock someone just took.
                if _read_info(path) == info:
                    print(f"Warning: breaking stale writer lock {path}: {reason}")
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass
                    except OSError as exc:
                        print(f"Warning: could not remove stale lock {path}: {exc}")
                continue
            if not announced:
                holder = f"pid {info.get('pid')} since {info.get('created_at')}" if info else "unknown owner"
                print(f"Waiting for MarketPulse writer lock {path} (held by {holder})...")
                announced = True
        if time.monotonic() >= deadline:
            info = _read_info(path) or {}
            raise WriterLockTimeout(
                f"Timed out after {timeout_s:g}s waiting for writer lock {path} "
                f"(held by pid {info.get('pid', '?')} since {info.get('created_at', '?')}, "
                f"owner {info.get('owner', '?')!r}). If no MarketPulse writer is running, delete the lock file."
            )
        time.sleep(poll_s)

    try:
        yield path
    finally:
        with _state_guard:
            _held.pop(key, None)
            _release(path)
