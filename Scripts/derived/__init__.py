"""Derived tables (spec §4.5): regime_daily, group_daily, setup_daily, deal_session_net.

Entry points for the EOD build:

    from Scripts.derived import build_derived_tables, write_derived_tables
    tables = build_derived_tables(prices=..., indicators=..., index_daily=..., master=..., deals=...,
                                  breadth=..., reference=...)
    write_derived_tables(con, tables)

On a daily append pass **incremental_setup_args(con) (recomputes the last 5 stored sessions of
setup_daily and keeps older rows); on a full rebuild omit it.

Each builder runs in isolation: a failing builder is logged and left out of the result; the others
are still returned. Timings/errors of the last run are in LAST_RUN. Column docs: SCHEMA.md.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

import pandas as pd

from .deal_session_net import build_deal_session_net
from .group_daily import build_group_daily
from .regime import build_regime_daily
from .setup_daily import build_setup_daily

log = logging.getLogger(__name__)

TABLES = ("regime_daily", "group_daily", "setup_daily", "deal_session_net")

INDEXES: dict[str, list[tuple[str, str]]] = {
    "regime_daily": [("idx_regime_daily_date", "trade_date")],
    "group_daily": [("idx_group_daily_date_level_floor", "trade_date, level, floor"),
                    ("idx_group_daily_level_group", "level, group_name")],
    "setup_daily": [("idx_setup_daily_date_queue", "trade_date, queue"), ("idx_setup_daily_symbol", "symbol")],
    "deal_session_net": [("idx_deal_session_net_date", "trade_date"), ("idx_deal_session_net_symbol", "symbol")],
}

LAST_RUN: dict[str, Any] = {"timings_s": {}, "errors": {}, "rows": {}}

__all__ = [
    "TABLES", "LAST_RUN", "build_derived_tables", "write_derived_tables", "incremental_setup_args",
    "build_regime_daily", "build_group_daily", "build_setup_daily", "build_deal_session_net",
]


def build_derived_tables(
    *,
    prices: pd.DataFrame | None,
    indicators: pd.DataFrame,
    index_daily: pd.DataFrame | None,
    master: pd.DataFrame | None,
    deals: pd.DataFrame | None,
    breadth: pd.DataFrame | None = None,
    reference: pd.DataFrame | None = None,
    setup_since: Any = None,
    setup_previous: pd.DataFrame | None = None,
    setup_workers: int = 1,
) -> dict[str, pd.DataFrame]:
    """Build every derived table. `setup_since`/`setup_previous` make setup_daily incremental
    (recompute sessions >= setup_since, keep the stored rows before it); omit both for a full build.
    `setup_workers` > 1 parallelises setup_daily's per-window predicates (use on full rebuilds; the calling
    script must have an `if __name__ == "__main__":` guard because Windows spawns workers by re-importing it)."""
    jobs: dict[str, Callable[[], pd.DataFrame]] = {
        "regime_daily": lambda: build_regime_daily(index_daily, indicators, breadth=breadth, reference=reference),
        "group_daily": lambda: build_group_daily(indicators, master, index_daily, deals=deals, reference=reference),
        "setup_daily": lambda: build_setup_daily(indicators, prices, master=master, reference=reference,
                                                 since=setup_since, previous=setup_previous,
                                                 workers=setup_workers),
        "deal_session_net": lambda: build_deal_session_net(deals, prices, indicators),
    }
    LAST_RUN.update({"timings_s": {}, "errors": {}, "rows": {}})
    out: dict[str, pd.DataFrame] = {}
    for name, job in jobs.items():
        t0 = time.perf_counter()
        try:
            frame = job()
        except Exception as exc:  # isolation: one failing builder never blocks the others
            log.exception("derived table %s failed", name)
            LAST_RUN["errors"][name] = f"{type(exc).__name__}: {exc}"
            continue
        finally:
            LAST_RUN["timings_s"][name] = round(time.perf_counter() - t0, 2)
        out[name] = frame
        LAST_RUN["rows"][name] = int(len(frame))
        log.info("derived table %s: %d rows in %.1fs", name, len(frame), LAST_RUN["timings_s"][name])
    return out


def incremental_setup_args(con, *, lookback_sessions: int = 5) -> dict[str, Any]:
    """Arguments for an incremental setup_daily run on a daily append: recompute the last
    `lookback_sessions` stored sessions plus anything newer, keep older stored rows.
    Returns {} (=> full build) when setup_daily does not exist yet or is empty."""
    try:
        dates = con.execute(
            "SELECT DISTINCT trade_date FROM setup_daily ORDER BY trade_date DESC LIMIT ?", [int(lookback_sessions)]
        ).fetchall()
    except Exception:  # table missing
        return {}
    if not dates:
        return {}
    since = pd.Timestamp(min(d[0] for d in dates))
    previous = con.execute("SELECT * FROM setup_daily WHERE trade_date < ?", [since.to_pydatetime()]).df()
    return {"setup_since": since, "setup_previous": previous}


def write_derived_tables(con, tables: dict[str, pd.DataFrame]) -> dict[str, int]:
    """CREATE OR REPLACE each table from its frame (+ indexes). Returns rows written per table."""
    written: dict[str, int] = {}
    for name, frame in tables.items():
        if name not in TABLES or frame is None:
            continue
        view = f"_derived_{name}_src"
        con.register(view, frame)
        try:
            con.execute(f'CREATE OR REPLACE TABLE "{name}" AS SELECT * FROM "{view}"')
        finally:
            con.unregister(view)
        for idx_name, cols in INDEXES.get(name, []):
            con.execute(f'CREATE INDEX IF NOT EXISTS "{idx_name}" ON "{name}" ({cols})')
        written[name] = int(len(frame))
    return written
