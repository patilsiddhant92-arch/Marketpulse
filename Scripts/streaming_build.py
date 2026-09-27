"""Memory-bounded indicator computation for the full build and the incremental append.

The old full build held the whole price history AND the ~170-column indicators frame in pandas
(plus several full copies made by the RS / sector steps): ~2.3 GB for the indicators frame alone
at 594 sessions, i.e. well over 6 GB at five years. Here the work is split so that nothing of
size "rows x indicator columns" is ever held for the whole table:

* cross-sectional RS ranks are computed once from a slim (symbol, trade_date, close) frame;
* every other indicator column depends only on the symbol's own history (or is row-wise), so
  it is computed in symbol batches (process pool, bounded number of batches in flight) and each
  batch is INSERTed straight into DuckDB;
* downstream tables read back only the columns they use (``read_slim``).

Each batch runs exactly the same code as the in-memory ``calc_indicators`` (steps 5a-5d), so the
values are identical; only the batching changes.
"""
from __future__ import annotations

import concurrent.futures
import gc
import os
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import duckdb
import numpy as np
import pandas as pd

try:
    from price_adjustment import PRICE_COLS
except ModuleNotFoundError:  # pragma: no cover
    from Scripts.price_adjustment import PRICE_COLS  # type: ignore

# Batch sizing: rows per symbol batch and batches in flight. A batch of 40k rows peaks at
# roughly 0.3 GB inside a worker (the per-symbol pass + the RS/sector copies); with 6 workers
# and 8 batches in flight the pool stays well under 3 GB.
DEFAULT_BATCH_ROWS = int(os.environ.get("MP_BUILD_BATCH_ROWS", "40000") or 40000)
DEFAULT_WORKERS = int(os.environ.get("MP_BUILD_WORKERS", "6") or 6)
# DuckDB's own buffer pool (default: 80% of RAM) is capped for the build connections.
DUCKDB_MEMORY_LIMIT = os.environ.get("MP_BUILD_DUCKDB_MEMORY", "2GB") or "2GB"

# Columns each downstream builder reads from indicators_daily.
BREADTH_COLUMNS = (
    "symbol", "trade_date", "close_price", "prev_close", "volume", "ema_10", "ema_20", "ema_50",
    "ema_100", "ema_200", "new_20d_high", "new_50d_high", "new_100d_high", "near_52w_high", "is_vcp",
)
ROTATION_COLUMNS = (
    "symbol", "trade_date", "close_price", "prev_close", "ema_10", "ema_50", "ema_200",
    "near_52w_high", "is_vcp", "turnover_cr", "return_5d_pct", "return_1m_pct", "return_3m_pct",
    "rs_percentile",
)
METRICS_COLUMNS = (
    "symbol", "trade_date", "close_price", "ema_50", "ema_200", "avg_traded_value_cr_20d",
    "turnover_cr", "distance_below_52w", "away_52w_high_pct", "setup_class",
)
DEAL_PRICE_COLUMNS = ("symbol", "trade_date", "close_price", "volume", "turnover_cr")
DEAL_INDICATOR_COLUMNS = (
    "symbol", "trade_date", "rs_percentile", "vcp_score", "vcp_state", "is_vcp", "near_52w_high",
    "near_database_high", "ema_stack_bullish", "away_10ema_pct", "away_52w_high_pct",
)
# indicator_input() replaces these with their adj_ counterparts.
INDICATOR_SWAP_COLUMNS = (*PRICE_COLS, "prev_close", "volume", "delivery_qty")


@dataclass
class StagedTable:
    """A table already written into a staging DuckDB file (instead of a pandas frame).

    ``build_temp_database`` adopts the staging file as its temp DB, so the table is never
    re-materialised in memory or copied.
    """

    path: Path
    table: str
    rows: int = 0
    info: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return int(self.rows)


def stage_db_path(db_path: Path) -> Path:
    return Path(db_path).with_suffix(".stage.duckdb")


def remove_db_file(path: Path) -> None:
    for leftover in (Path(path), Path(str(path) + ".wal")):
        try:
            leftover.unlink()
        except FileNotFoundError:
            pass


def connect_build_db(path: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(path))
    try:
        con.execute(f"SET memory_limit = '{DUCKDB_MEMORY_LIMIT}'")
        con.execute("SET preserve_insertion_order = true")
    except duckdb.Error:  # pragma: no cover - settings are best effort
        pass
    return con


def _q(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def table_columns(con: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    return [str(r[1]) for r in con.execute(f"PRAGMA table_info({_q(table)})").fetchall()]


def indicator_input_select(price_columns: Iterable[str]) -> str:
    """SELECT list that turns a prices_daily row into `price_adjustment.indicator_input` output:
    same columns in the same order, adj_* values swapped in (as DOUBLE) and adj_* dropped."""
    cols = list(price_columns)
    present = set(cols)
    parts = []
    for col in cols:
        if col.startswith("adj_"):
            continue
        if col in INDICATOR_SWAP_COLUMNS and f"adj_{col}" in present:
            parts.append(f"CAST({_q('adj_' + col)} AS DOUBLE) AS {_q(col)}")
        else:
            parts.append(_q(col))
    return ", ".join(parts)


def match_datetime_units(frame: pd.DataFrame, unit_dtype) -> pd.DataFrame:
    """Cast every datetime64 column of a DuckDB result to ``unit_dtype`` (the unit the in-memory
    build used), so frames read back behave - and are written back - exactly like the originals."""
    if unit_dtype is None:
        return frame
    for col in frame.columns:
        dtype = frame[col].dtype
        if pd.api.types.is_datetime64_any_dtype(dtype) and getattr(dtype, "tz", None) is None and dtype != unit_dtype:
            frame[col] = frame[col].astype(unit_dtype)
    return frame


def read_slim(
    con: duckdb.DuckDBPyConnection,
    table: str,
    columns: Iterable[str],
    *,
    where: str = "",
    params: list | None = None,
    order: str = "symbol, trade_date",
    date_dtype=None,
) -> pd.DataFrame:
    """Only ``columns`` of ``table`` (those that exist), rows in (symbol, trade_date) order - the
    row order of the in-memory indicators frame, so groupby sums add up in the same order."""
    have = set(table_columns(con, table))
    cols = [c for c in columns if c in have]
    sql = f"SELECT {', '.join(_q(c) for c in cols)} FROM {_q(table)}"
    if where:
        sql += f" WHERE {where}"
    if order:
        sql += f" ORDER BY {order}"
    frame = con.execute(sql, params or []).fetchdf()
    return match_datetime_units(frame, date_dtype)


# --------------------------------------------------------------------------------------------
# DuckDB schema for streamed batches
# --------------------------------------------------------------------------------------------

def duckdb_type_for(series: pd.Series) -> str:
    """The DuckDB type the old whole-frame ``CREATE TABLE AS SELECT * FROM df`` gives a column.

    Datetimes are always TIMESTAMP (microseconds) - the build's trade dates are midnight values
    parsed at microsecond resolution; a batch whose optional date column happens to be all-NaT
    must not turn the column into TIMESTAMP_NS.
    """
    dtype = series.dtype
    if pd.api.types.is_bool_dtype(dtype):
        return "BOOLEAN"
    if pd.api.types.is_integer_dtype(dtype):
        return "BIGINT"
    if pd.api.types.is_float_dtype(dtype):
        return "DOUBLE"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "TIMESTAMP"
    values = series.dropna()
    if len(values) and values.map(lambda v: isinstance(v, (bool, np.bool_))).all():
        return "BOOLEAN"
    return "VARCHAR"


class BatchWriter:
    """Appends pandas batches to one DuckDB table with a fixed column list and types."""

    def __init__(self, con: duckdb.DuckDBPyConnection, table: str, *, create: bool = True):
        self.con = con
        self.table = table
        self.create = create
        self.columns: list[str] | None = None
        self.rows = 0

    def write(self, frame: pd.DataFrame) -> None:
        if self.columns is None:
            self.columns = [str(c) for c in frame.columns]
            if self.create:
                ddl = ", ".join(f"{_q(c)} {duckdb_type_for(frame[c])}" for c in self.columns)
                self.con.execute(f"CREATE TABLE {_q(self.table)} ({ddl})")
        elif [str(c) for c in frame.columns] != self.columns:
            raise ValueError(
                f"{self.table}: batch columns differ from the first batch "
                f"({sorted(set(frame.columns) ^ set(self.columns))})"
            )
        name = f"_batch_{self.table}"
        self.con.register(name, frame)
        try:
            target = f"{_q(self.table)} BY NAME" if not self.create else _q(self.table)
            self.con.execute(f"INSERT INTO {target} SELECT * FROM {name}")
        finally:
            self.con.unregister(name)
        self.rows += len(frame)


# --------------------------------------------------------------------------------------------
# Worker side
# --------------------------------------------------------------------------------------------

_CTX: dict = {}


def _worker_init(index_raw: pd.DataFrame | None, membership: pd.DataFrame | None, enrichment: pd.DataFrame | None) -> None:
    _CTX["index_raw"] = index_raw
    _CTX["membership"] = membership
    _CTX["enrichment"] = enrichment


def compute_indicator_batch(task: dict) -> pd.DataFrame:
    """Steps 5a-5d of ``calc_indicators`` for one symbol batch (runs in a worker process).

    task keys: ``input`` (indicator input rows of the batch, (symbol, trade_date) order),
    ``ranks`` (RANK_COLUMNS + symbol/trade_date for the rows kept), ``reference`` (as-of 52W
    source for these symbols, or None to use the context enrichment), and for the incremental
    append ``bars`` ({symbol: full slim adjusted OHLCV history}) and ``keep_from`` ({symbol:
    first trade_date to keep}).
    """
    import build_database as bd

    frame: pd.DataFrame = task["input"]
    bars_by_symbol = task.get("bars")
    keep_from = task.get("keep_from") or {}
    parts = []
    for symbol, group in frame.groupby("symbol", sort=False):
        if bars_by_symbol is None:
            parts.append(bd._calc_single_symbol_indicators(group))
            continue
        # Incremental append: `group` is a trailing window, `bars` the full slim history.
        history = bars_by_symbol[symbol]
        daily = bd._daily_symbol_features(group, history=history)
        start = keep_from.get(symbol)
        if start is not None:
            daily = daily[daily["trade_date"] >= start]
        parts.append(bd._higher_timeframe_features(daily, history))
    per_symbol = pd.concat(parts, ignore_index=True)
    reference = task.get("reference")
    if reference is None:
        reference = _CTX.get("enrichment")
    ranks = task["ranks"]
    if len(ranks) != len(per_symbol) or not (
        np.array_equal(ranks["symbol"].to_numpy(dtype=object), per_symbol["symbol"].to_numpy(dtype=object))
        and np.array_equal(
            pd.to_datetime(ranks["trade_date"]).to_numpy("datetime64[us]"),
            pd.to_datetime(per_symbol["trade_date"]).to_numpy("datetime64[us]"),
        )
    ):
        raise ValueError("rank rows do not line up with the batch's indicator rows")
    return bd.calc_indicators(
        None,
        reference,
        per_symbol=per_symbol,
        rank_columns=ranks.reset_index(drop=True),
        index_raw=_CTX.get("index_raw"),
        membership=_CTX.get("membership"),
        quiet=True,
    )


# --------------------------------------------------------------------------------------------
# Driver side
# --------------------------------------------------------------------------------------------

def symbol_batches(counts: pd.DataFrame, batch_rows: int) -> list[list[str]]:
    """Contiguous runs of (sorted) symbols with about ``batch_rows`` rows each."""
    batches: list[list[str]] = []
    current: list[str] = []
    rows = 0
    for symbol, n in zip(counts["symbol"], counts["n"]):
        if current and rows + int(n) > batch_rows:
            batches.append(current)
            current, rows = [], 0
        current.append(str(symbol))
        rows += int(n)
    if current:
        batches.append(current)
    return batches


def slim_index_history(index_raw: pd.DataFrame | None) -> pd.DataFrame | None:
    """Only the columns the true-RS / sector-index RS steps read (index_closes)."""
    if index_raw is None or index_raw.empty:
        return index_raw
    cols = [c for c in ("index_name", "trade_date", "close_price") if c in index_raw.columns]
    return index_raw[cols].copy()


def reference_by_symbol(reference: pd.DataFrame | None) -> dict[str, pd.DataFrame] | None:
    if reference is None or reference.empty or "effective_date" not in reference.columns:
        return None
    return {str(sym): grp for sym, grp in reference.groupby("symbol", sort=False)}


def reference_subset(ref_groups: dict[str, pd.DataFrame] | None, template: pd.DataFrame, symbols: Iterable[str]) -> pd.DataFrame:
    parts = [ref_groups[s] for s in symbols if s in ref_groups]
    if not parts:
        return template.iloc[0:0]
    return pd.concat(parts, ignore_index=True)


def run_batches(
    task_factory: Callable[[], Iterable[dict]],
    on_result: Callable[[pd.DataFrame], None],
    *,
    context: tuple,
    reset: Callable[[], None] | None = None,
    workers: int | None = None,
    label: str = "indicator batches",
    total: int | None = None,
) -> None:
    """Run ``compute_indicator_batch`` over ``task_factory()`` (a lazy iterable, consumed in
    order) and hand every result to ``on_result`` in task order. At most ``2 * workers`` tasks
    are in flight, so memory stays bounded however many batches there are.

    Like the old calc_indicators, a pool failure falls back to computing everything in this
    process (``reset`` is called first to discard results already handed over); so does
    MP_DISABLE_MULTIPROCESSING=1.
    """
    import build_database as bd

    use_mp, cores = bd.multiprocessing_settings()
    workers = max(1, min(workers or DEFAULT_WORKERS, cores))
    started = time.time()
    state = {"done": 0}

    def _deliver(result: pd.DataFrame) -> None:
        on_result(result)
        state["done"] += 1
        if total and (state["done"] % 10 == 0 or state["done"] == total):
            print(f"  {label}: {state['done']:,}/{total:,} [{time.time() - started:.0f}s elapsed]", flush=True)

    if use_mp and workers > 1:
        try:
            with concurrent.futures.ProcessPoolExecutor(
                max_workers=workers, initializer=_worker_init, initargs=context
            ) as pool:
                pending: deque = deque()
                iterator = iter(task_factory())
                exhausted = False
                while True:
                    while not exhausted and len(pending) < 2 * workers:
                        try:
                            task = next(iterator)
                        except StopIteration:
                            exhausted = True
                            break
                        pending.append(pool.submit(compute_indicator_batch, task))
                        del task
                    if not pending:
                        break
                    result = pending.popleft().result()
                    _deliver(result)
                    del result
            return
        except Exception as exc:
            if state["done"] and reset is None:
                raise
            print(f"Warning: process pool failed ({exc}); computing {label} in this process.", flush=True)
            if state["done"] and reset is not None:
                reset()
            state["done"] = 0
    _worker_init(*context)
    for task in task_factory():
        _deliver(compute_indicator_batch(task))


def compute_rank_table(con: duckdb.DuckDBPyConnection, select_sql: str, table: str = "_rs_rank_stage") -> int:
    """Cross-sectional RS columns for every row of ``select_sql`` (symbol, trade_date,
    close_price) written to ``table``; returns the row count."""
    import build_database as bd

    slim = con.execute(select_sql).fetchdf()
    inputs = bd.rs_rank_inputs(slim)
    ranks = bd.rs_rank_columns(inputs)
    out = pd.concat([slim[["symbol", "trade_date"]], ranks], axis=1)
    del slim, inputs, ranks
    con.execute(f"DROP TABLE IF EXISTS {_q(table)}")
    con.register("_rank_df", out)
    try:
        con.execute(f"CREATE TABLE {_q(table)} AS SELECT * FROM _rank_df")
    finally:
        con.unregister("_rank_df")
    n = len(out)
    del out
    gc.collect()
    return n


def stream_full_indicators(
    con: duckdb.DuckDBPyConnection,
    *,
    reference: pd.DataFrame | None,
    enrichment: pd.DataFrame,
    index_raw: pd.DataFrame | None,
    membership: pd.DataFrame | None,
    date_dtype=None,
    batch_rows: int | None = None,
    workers: int | None = None,
    table: str = "indicators_daily",
) -> int:
    """Compute indicators_daily for every row of ``prices_daily`` in ``con`` (full build)."""
    import build_database as bd

    price_cols = table_columns(con, "prices_daily")
    select_input = indicator_input_select(price_cols)
    close_expr = "adj_close_price" if "adj_close_price" in price_cols else "close_price"
    print("  5c/8: Computing cross-sectional relative strength percentiles (all rows, slim)...", flush=True)
    compute_rank_table(
        con,
        f"SELECT symbol, trade_date, CAST({_q(close_expr)} AS DOUBLE) AS close_price "
        f"FROM prices_daily ORDER BY symbol, trade_date",
    )
    rank_cols = ", ".join(_q(c) for c in ("symbol", "trade_date", *bd.RANK_COLUMNS))
    counts = con.execute("SELECT symbol, count(*) AS n FROM prices_daily GROUP BY symbol ORDER BY symbol").fetchdf()
    batches = symbol_batches(counts, batch_rows or DEFAULT_BATCH_ROWS)
    ref_groups = reference_by_symbol(reference)
    print(f"  5a/8: Calculating stock indicators in {len(batches):,} symbol batches...", flush=True)

    def tasks():
        for symbols in batches:
            lo, hi = symbols[0], symbols[-1]
            frame = con.execute(
                f"SELECT {select_input} FROM prices_daily WHERE symbol BETWEEN ? AND ? ORDER BY symbol, trade_date",
                [lo, hi],
            ).fetchdf()
            frame = match_datetime_units(frame, date_dtype)
            ranks = con.execute(
                f"SELECT {rank_cols} FROM _rs_rank_stage WHERE symbol BETWEEN ? AND ? ORDER BY symbol, trade_date",
                [lo, hi],
            ).fetchdf()
            ranks = match_datetime_units(ranks, date_dtype)
            yield {
                "input": frame,
                "ranks": ranks,
                "reference": None if ref_groups is None else reference_subset(ref_groups, reference, symbols),
            }

    holder = {"writer": BatchWriter(con, table)}
    con.execute(f"DROP TABLE IF EXISTS {_q(table)}")

    def reset():
        con.execute(f"DROP TABLE IF EXISTS {_q(table)}")
        holder["writer"] = BatchWriter(con, table)

    run_batches(
        tasks,
        lambda frame: holder["writer"].write(frame),
        context=(slim_index_history(index_raw), membership, enrichment),
        reset=reset,
        workers=workers,
        total=len(batches),
    )
    writer = holder["writer"]
    con.execute("DROP TABLE IF EXISTS _rs_rank_stage")
    return writer.rows
