"""
In-memory session snapshot cache for MarketPulse.
Provides sub-millisecond query result caching for immutable EOD trading sessions.
"""
from __future__ import annotations

import functools
import time
from pathlib import Path
from typing import Any, Callable

# Global in-memory cache: (cache_key) -> (timestamp, data)
_CACHE: dict[str, tuple[float, Any]] = {}
CACHE_TTL_SECONDS = 3600.0  # 1 hour default TTL for EOD data


def cache_key(db_path: Path | str, session_date: str | None, tag: str, *args: Any) -> str:
    """Generate a unique cache key for a dataset.

    If session_date is omitted or 'latest', the database file's modification time
    is incorporated so cached datasets automatically refresh when a new session
    is written to the database.
    """
    db_name = Path(db_path).name if db_path else "default"
    if session_date is not None and str(session_date).strip().lower() != "latest":
        d_str = str(session_date)
    else:
        try:
            p = Path(db_path)
            d_str = f"mtime_{p.stat().st_mtime_ns}" if p.exists() else "latest"
        except Exception:
            d_str = "latest"
    args_str = "_".join(str(a) for a in args)
    return f"{db_name}:{d_str}:{tag}:{args_str}"


def get_cached(key: str) -> Any | None:
    """Retrieve data from cache if present and not expired."""
    entry = _CACHE.get(key)
    if entry is None:
        return None
    ts, val = entry
    if (time.time() - ts) > CACHE_TTL_SECONDS:
        del _CACHE[key]
        return None
    return val


def set_cached(key: str, val: Any) -> Any:
    """Store data in cache."""
    _CACHE[key] = (time.time(), val)
    return val


def invalidate_cache(tag_prefix: str | None = None) -> int:
    """Clear all or matching cached entries."""
    global _CACHE
    if tag_prefix is None:
        count = len(_CACHE)
        _CACHE.clear()
        return count
    keys_to_del = [k for k in _CACHE if tag_prefix in k]
    for k in keys_to_del:
        del _CACHE[k]
    return len(keys_to_del)


# Convenient alias for clearing cache
clear_cache = invalidate_cache


def cached_query(tag: str):
    """Decorator to cache function results by first argument (db_path) and date."""
    def decorator(fn: Callable):
        @functools.wraps(fn)
        def wrapper(db_path: Path | str, *args, **kwargs):
            key = cache_key(db_path, kwargs.get("trade_date"), tag, *args, sorted(kwargs.items()))
            hit = get_cached(key)
            if hit is not None:
                return hit
            result = fn(db_path, *args, **kwargs)
            set_cached(key, result)
            return result
        return wrapper
    return decorator
