"""Metric dictionary (spec §6.2): Scripts/data/metric_dictionary.yaml, cached by file mtime."""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import yaml

from App.services.db import ROOT_DIR

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"mtime": None, "entries": []}


def dictionary_path() -> Path:
    env = os.environ.get("MP_METRIC_DICTIONARY", "").strip()
    return Path(env) if env else ROOT_DIR / "Scripts" / "data" / "metric_dictionary.yaml"


def load() -> list[dict[str, Any]]:
    path = dictionary_path()
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return []
    with _LOCK:
        if _STATE["mtime"] == mtime:
            return _STATE["entries"]
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = data.get("metrics", []) if isinstance(data, dict) else []
    entries = [e for e in entries if isinstance(e, dict) and e.get("key")]
    with _LOCK:
        _STATE.update(mtime=mtime, entries=entries)
    return entries


def by_key() -> dict[str, dict[str, Any]]:
    return {e["key"]: e for e in load()}


def entries(keys: list[str] | None = None) -> list[dict[str, Any]]:
    all_entries = load()
    if not keys:
        return all_entries
    wanted = set(keys)
    return [e for e in all_entries if e["key"] in wanted]
