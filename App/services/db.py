"""Database access for API v2.

- Market DB is always opened read-only, with external file access disabled
  (defence in depth against `COPY ... TO` style writes).
- A DuckDB lock held by another process (the EOD writer) surfaces as
  `DBUnavailable`, which the v2 router turns into 503 + Retry-After.
- `fingerprint()` is a cheap stat-based key of the market DB file; the
  response cache (`cached`) is keyed on it so a new EOD session invalidates
  everything automatically.
- Paths are resolved from the environment on every call (MP_DB_PATH,
  MP_USER_DB_PATH, MP_STATUS_PATH) so tests can point at fixture DBs.
"""
from __future__ import annotations

import math
import os
import threading
from collections import OrderedDict
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterator

import duckdb

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB_DIR = ROOT_DIR / "Database"
RETRY_AFTER_SECONDS = 15


class DBUnavailable(Exception):
    """Database missing or locked by a writer; maps to HTTP 503."""

    def __init__(self, reason: str, retry_after: int = RETRY_AFTER_SECONDS):
        super().__init__(reason)
        self.reason = reason
        self.retry_after = retry_after


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
def market_db_path() -> Path:
    env = os.environ.get("MP_DB_PATH", "").strip()
    return Path(env) if env else DEFAULT_DB_DIR / "marketpulse.duckdb"


def user_db_path() -> Path:
    env = os.environ.get("MP_USER_DB_PATH", "").strip()
    return Path(env) if env else market_db_path().parent / "marketpulse_user.duckdb"


def status_path() -> Path:
    env = os.environ.get("MP_STATUS_PATH", "").strip()
    return Path(env) if env else market_db_path().parent / "status.json"


def holidays_path() -> Path:
    env = os.environ.get("MP_HOLIDAYS_PATH", "").strip()
    if env:
        return Path(env)
    rel = Path("Input") / "reference" / "nse_holidays.json"
    # Prefer the calendar next to the DB's project (worktrees don't carry untracked Input/).
    for base in (market_db_path().resolve().parent.parent, ROOT_DIR):
        if (base / rel).exists():
            return base / rel
    return ROOT_DIR / rel


# --------------------------------------------------------------------------
# Connections
# --------------------------------------------------------------------------
_LOCK_MARKERS = ("could not set lock", "lock on file", "being used by another process", "conflicting lock")


def _is_lock_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in _LOCK_MARKERS)


@contextmanager
def market_conn() -> Iterator[duckdb.DuckDBPyConnection]:
    """Read-only connection to the market DB; raises DBUnavailable on lock/missing."""
    path = market_db_path()
    if not path.exists():
        raise DBUnavailable(f"market database not found ({path.name})")
    try:
        con = duckdb.connect(str(path), read_only=True)
    except duckdb.Error as exc:  # IOException on writer lock
        if _is_lock_error(exc):
            raise DBUnavailable("market database is locked by a writer (EOD run in progress)") from exc
        raise DBUnavailable(f"market database cannot be opened: {type(exc).__name__}") from exc
    try:
        try:
            con.execute("SET enable_external_access = false")
        except duckdb.Error:
            pass
        yield con
    finally:
        con.close()


@contextmanager
def user_conn(read_only: bool = False) -> Iterator[duckdb.DuckDBPyConnection]:
    """Connection to the user DB (watchlist, notes). Created on first write."""
    path = user_db_path()
    if read_only and not path.exists():
        raise DBUnavailable("user database not found")
    try:
        con = duckdb.connect(str(path), read_only=read_only)
    except duckdb.Error as exc:
        if _is_lock_error(exc):
            raise DBUnavailable("user database is locked by another process") from exc
        raise DBUnavailable(f"user database cannot be opened: {type(exc).__name__}") from exc
    try:
        yield con
    finally:
        con.close()


# --------------------------------------------------------------------------
# Introspection helpers
# --------------------------------------------------------------------------
def table_exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    row = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'main' AND table_name = ?",
        [name],
    ).fetchone()
    return bool(row and row[0])


def table_columns(con: duckdb.DuckDBPyConnection, name: str) -> list[str]:
    rows = con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'main' AND table_name = ? "
        "ORDER BY ordinal_position",
        [name],
    ).fetchall()
    return [str(r[0]) for r in rows]


def quote_ident(name: str) -> str:
    """Quote an identifier from information_schema or a whitelist (never raw request input)."""
    return '"' + str(name).replace('"', '""') + '"'


def table_has_rows(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    if not table_exists(con, name):
        return False
    return bool(con.execute(f"SELECT EXISTS (SELECT 1 FROM {quote_ident(name)})").fetchone()[0])


# --------------------------------------------------------------------------
# Sessions / as_of
# --------------------------------------------------------------------------
def to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        import pandas as pd

        if pd.isna(value):
            return None
        return pd.Timestamp(value).date()
    except Exception:
        return None


def latest_session(con: duckdb.DuckDBPyConnection) -> date | None:
    if not table_exists(con, "indicators_daily"):
        return None
    return to_date(con.execute("SELECT max(trade_date) FROM indicators_daily").fetchone()[0])


def resolve_as_of(con: duckdb.DuckDBPyConnection, as_of: date | None) -> date | None:
    """Latest indicators session on or before `as_of` (or the latest overall)."""
    if not table_exists(con, "indicators_daily"):
        return None
    if as_of is None:
        return latest_session(con)
    row = con.execute("SELECT max(trade_date) FROM indicators_daily WHERE trade_date <= ?", [as_of]).fetchone()
    return to_date(row[0]) if row else None


def recent_sessions(con: duckdb.DuckDBPyConnection, as_of: date, n: int) -> list[date]:
    """Up to `n` distinct sessions <= as_of, newest first."""
    rows = con.execute(
        """
        SELECT trade_date FROM (
            SELECT DISTINCT trade_date FROM indicators_daily WHERE trade_date <= ?
        ) ORDER BY trade_date DESC LIMIT ?
        """,
        [as_of, int(n)],
    ).fetchall()
    return [to_date(r[0]) for r in rows]


def session_back(con: duckdb.DuckDBPyConnection, as_of: date, n: int) -> date | None:
    """Trade date `n` sessions before `as_of` (n=0 -> as_of); None if history is too short."""
    sessions = recent_sessions(con, as_of, n + 1)
    return sessions[n] if len(sessions) > n else None


# --------------------------------------------------------------------------
# Value hygiene: NULL stays NULL
# --------------------------------------------------------------------------
def num(value: Any, ndigits: int | None = None) -> float | None:
    """Finite float or None. Never substitutes a default."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, ndigits) if ndigits is not None else f


def integer(value: Any) -> int | None:
    f = num(value)
    return int(round(f)) if f is not None else None


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    try:
        import pandas as pd

        if value is pd.NaT or value is pd.NA:
            return True
    except Exception:
        pass
    return False


def text(value: Any) -> str | None:
    if _is_missing(value):
        return None
    s = str(value).strip()
    return s or None


def boolean(value: Any) -> bool | None:
    if _is_missing(value):
        return None
    return bool(value)


def records(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


# --------------------------------------------------------------------------
# Fingerprint-keyed response cache
# --------------------------------------------------------------------------
def fingerprint() -> str:
    """Cheap key that changes whenever the market DB file is rewritten."""
    path = market_db_path()
    try:
        st = path.stat()
    except OSError:
        return "missing"
    wal_part = ""
    try:
        wst = path.with_name(path.name + ".wal").stat()
        wal_part = f":{wst.st_mtime_ns}:{wst.st_size}"
    except OSError:
        pass
    return f"{path}:{st.st_mtime_ns}:{st.st_size}{wal_part}"


_CACHE: "OrderedDict[tuple, Any]" = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 256


def cached(tag: str, key: tuple, compute: Callable[[], Any]) -> Any:
    full = (fingerprint(), tag, key)
    with _CACHE_LOCK:
        if full in _CACHE:
            _CACHE.move_to_end(full)
            return _CACHE[full]
    value = compute()
    with _CACHE_LOCK:
        _CACHE[full] = value
        _CACHE.move_to_end(full)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return value


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
