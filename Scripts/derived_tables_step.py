"""Wires the Scripts/derived tables (regime_daily, group_daily, setup_daily, deal_session_net)
into the full build and the incremental append.

Fail-soft by design: the derived tables are views over the core tables, so a failure here is
reported loudly (``WARNING: DERIVED TABLES ...``) but never blocks or undoes the price /
indicator write (which is fail-closed). Inputs are read from the DuckDB being written, so the
full build and the append feed the builders the same final tables; only the columns the
builders use are loaded.
"""
from __future__ import annotations

import time
from typing import Any

import pandas as pd

DERIVED_TABLES = ("regime_daily", "group_daily", "setup_daily", "deal_session_net")
PRICE_COLUMNS = ("symbol", "trade_date", "close_price", "volume", "turnover_cr")
# Full rebuilds parallelise setup_daily (the calling script must guard its entry point with
# `if __name__ == "__main__":` - build_database, safe_rebuild, append_database, daily_pipeline do).
FULL_SETUP_WORKERS = 3


def _package():
    import derived  # Scripts/derived; ImportError when the package is not installed

    return derived


def indicator_columns(package) -> list[str]:
    cols = ["symbol", "trade_date"]
    for mod_name in ("regime", "group_daily", "setup_daily"):
        mod = getattr(package, mod_name, None)
        for col in getattr(mod, "INDICATOR_COLUMNS", ()):
            if col not in cols:
                cols.append(col)
    if "avg_traded_value_cr_20d" not in cols:
        cols.append("avg_traded_value_cr_20d")
    return cols


def _table(con, name: str) -> pd.DataFrame | None:
    tables = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    if name not in tables:
        return None
    return con.execute(f'SELECT * FROM "{name}"').fetchdf()


def build_from_con(con, *, incremental: bool, setup_workers: int | None = None) -> dict[str, pd.DataFrame]:
    """Build every derived table from the tables in ``con``."""
    from streaming_build import read_slim

    package = _package()
    indicators = read_slim(con, "indicators_daily", indicator_columns(package))
    prices = read_slim(con, "prices_daily", PRICE_COLUMNS)
    extra: dict[str, Any] = package.incremental_setup_args(con) if incremental else {}
    workers = setup_workers if setup_workers is not None else (1 if incremental else FULL_SETUP_WORKERS)
    return package.build_derived_tables(
        prices=prices,
        indicators=indicators,
        index_daily=_table(con, "index_daily"),
        master=_table(con, "stocks_master"),
        deals=_table(con, "deals"),
        breadth=_table(con, "breadth_daily"),
        reference=_table(con, "security_reference_daily"),
        setup_workers=workers,
        **extra,
    )


def rebuild_in_place(con, *, incremental: bool, quiet: bool = False, own_transaction: bool = True) -> dict[str, int]:
    """Build and write the derived tables into ``con``; returns rows written per table
    (empty on failure). Never raises."""
    started = time.perf_counter()
    try:
        package = _package()
    except ImportError as exc:
        print(f"WARNING: DERIVED TABLES NOT REBUILT - Scripts/derived is not available ({exc}).", flush=True)
        return {}
    try:
        tables = build_from_con(con, incremental=incremental)
        if own_transaction:
            con.execute("BEGIN TRANSACTION")
        try:
            written = package.write_derived_tables(con, tables)
            if own_transaction:
                con.execute("COMMIT")
        except BaseException:
            if own_transaction:
                con.execute("ROLLBACK")
            raise
        errors = dict(getattr(package, "LAST_RUN", {}).get("errors", {}))
    except Exception as exc:  # noqa: BLE001 - fail-soft
        print(f"WARNING: DERIVED TABLES NOT REBUILT ({type(exc).__name__}: {exc}); core tables are unaffected.", flush=True)
        return {}
    for name, err in errors.items():
        print(f"WARNING: derived table {name} FAILED ({err}); the previous copy (if any) is kept.", flush=True)
    if not quiet:
        rows = ", ".join(f"{k} {v:,}" for k, v in written.items())
        print(f"Derived tables rebuilt in {time.perf_counter() - started:.0f}s ({'incremental' if incremental else 'full'}): {rows}", flush=True)
    return written
