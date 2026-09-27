"""Incremental nightly append: recompute only what a new session can change, in place.

The previous append reloaded the whole price history and recomputed every indicator and
every derived table over all dates (~4.4 min at 594 sessions, growing with history, and the
whole 170-column indicators frame in RAM). This module writes the same values but only
touches what the new session(s) can change:

* prices_daily - the new rows are inserted; a symbol whose cumulative price_factor changed (a
  split/bonus newly applied) or whose history moved under a new ticker is rewritten entirely.
* indicators_daily - per symbol with new rows, the rows from ``rewrite_start`` on are replaced.
  Every daily column is causal EXCEPT the swing-point RSI divergence flags (daily, weekly,
  monthly: a swing at t needs bar t+1) and the completed-week wema_20 (a week whose Friday is a
  holiday completes only when the next session arrives), so ``rewrite_start`` goes back to the
  start of the calendar month / previous week of the first new session. The per-symbol pass
  runs over the symbol's full history with exactly the full-build code (its cost is almost
  independent of the row count, and only the full history reproduces the rolling-mean
  summation residue bit for bit - a trailing window flips e.g. sma_200_rising of flat ETFs).
* cross-sectional RS ranks - computed for every date from ``recompute_from`` (normally the
  first new session) over all symbols trading that day; ranks of older rows are unchanged and
  reused (they only feed the rs_rank_t5/15/30 lags).
* breadth_daily / sector_rotation / sector_metrics_daily - recomputed for the dates from
  ``recompute_from`` on with enough lookback for their rolling columns, then those dates are
  replaced. Whole-table recomputes happen only when the inputs of older dates changed: breadth
  when an adjusted volume history changed (factor change), sector tables when the sector
  taxonomy changed; leader_symbols of the groups whose members crossed the Rs 1,000 cr
  market-cap line (it uses today's market cap for every date) are refreshed across all dates.
* small tables (stocks_master, daily_enrichment, deals, screener_results, price_adjustments,
  index_daily) are rebuilt whole, security_reference_daily gets the new/changed reference rows.

Late inputs that change OLDER dates (a reference snapshot, index history or corporate action
arriving after its date) move ``recompute_from`` back to the earliest affected date; beyond
MAX_RECOMPUTE_SESSIONS the append raises FullRecomputeRequired and the caller falls back to the
full (streaming) recompute through the safe temp-build + swap.

Writes: under the writer lock the live DB is first backed up (dated copy, see db_backup), then
every change is applied in ONE DuckDB transaction; any error rolls the transaction back and
re-raises (fail-closed: the live DB is exactly as before). The derived tables of
Scripts/derived are built afterwards in their own transaction and are fail-soft.
"""
from __future__ import annotations

import gc
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import duckdb
import numpy as np
import pandas as pd

import build_database as bd
from price_adjustment import adjust_prices, apply_adjustments, indicator_input, summarize_adjustments
from streaming_build import (
    BREADTH_COLUMNS,
    METRICS_COLUMNS,
    ROTATION_COLUMNS,
    compute_indicator_batch,
    indicator_input_select,
    match_datetime_units,
    read_slim,
    reference_by_symbol,
    reference_subset,
    run_batches,
    slim_index_history,
    symbol_batches,
    table_columns,
)

# How far back late inputs may move the recompute before a full recompute is cheaper/safer.
MAX_RECOMPUTE_SESSIONS = 60
# breadth_daily: rolling 5/20 and shift 5/20 over dates.
BREADTH_LOOKBACK_SESSIONS = 25
# sector_rotation: session lags / diff / rolling sums of up to 20 rows per group.
ROTATION_GROUP_ROWS = 25
# sector_metrics: return_21d/63d are row shifts within each symbol.
METRICS_LOOKBACK_ROWS = 70
LEADER_MIN_CAP_CR = 1000.0
# Rows (of full history) per per-symbol batch, and worker processes for the append. The append's
# batches are small, so it can use more workers than the full build within the same memory.
BATCH_ROWS = 20000
APPEND_WORKERS = int(__import__("os").environ.get("MP_APPEND_WORKERS", "6") or 6)
TAXONOMY_COLUMNS = ("broad_sector", "sector", "broad_industry", "industry")
REFERENCE_COMPARE_COLUMNS = ("high_52w", "low_52w", "high_52w_date", "band_remarks", "market_cap_cr")
RAW_PRICE_COLUMNS = (
    "symbol", "series", "trade_date", "prev_close", "open_price", "high_price", "low_price",
    "last_price", "close_price", "avg_price", "volume", "turnover_lacs", "trades", "delivery_qty",
    "delivery_pct", "turnover_cr",
)
RANK_PERCENTILE_COLUMNS = ("rs_percentile_primary", "rs_percentile_ipo", "rs_1y_percentile", "rs_3m_percentile")


# keep_from for a symbol recomputed over its whole history
KEEP_ALL = pd.Timestamp("1900-01-01")


class _Stopwatch:
    """Prints the time since the previous mark (step timings of an append)."""

    def __init__(self, quiet: bool):
        self.quiet = quiet
        self.t = time.perf_counter()

    def __call__(self, label: str) -> None:
        now = time.perf_counter()
        if not self.quiet:
            print(f"    - {label}: {now - self.t:.1f}s", flush=True)
        self.t = now


class FullRecomputeRequired(RuntimeError):
    """The incremental path cannot reproduce a full recompute safely; nothing was written."""


def _q(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _ts(value) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


@dataclass
class AppendPlan:
    latest_date: pd.Timestamp
    first_new: pd.Timestamp
    recompute_from: pd.Timestamp
    new_rows: pd.DataFrame                      # raw new rows after symbol changes
    moved_rows: pd.DataFrame                    # stored (orig_symbol, trade_date, symbol) renamed/dropped
    full_symbols: set[str]                      # rewritten over their whole history
    factor_changed: set[str]
    adjustments: pd.DataFrame
    date_dtype: object
    reasons: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------------------------
# Planning (read-only)
# --------------------------------------------------------------------------------------------

def _require_current_schema(con) -> None:
    tables = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    for needed in ("prices_daily", "indicators_daily", "breadth_daily", "sector_rotation", "stocks_master"):
        if needed not in tables:
            raise FullRecomputeRequired(f"{needed} is missing")
    price_cols = set(table_columns(con, "prices_daily"))
    if "price_factor" not in price_cols or "adj_close_price" not in price_cols:
        raise FullRecomputeRequired("prices_daily has no price-adjustment columns (built by older code)")
    ind_cols = set(table_columns(con, "indicators_daily"))
    for col in ("price_factor", "rs_rank_t30", "wema_20", "setup_class", "database_high"):
        if col not in ind_cols:
            raise FullRecomputeRequired(f"indicators_daily has no {col} column (built by older code)")
    if "sector_metrics_daily" not in tables:
        raise FullRecomputeRequired("sector_metrics_daily is missing")


def _apply_symbol_changes_to_new(con, new_prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Symbol changes exactly as merge_new_prices applies them to (stored + new) rows.

    Returns (new rows after renames, moved stored rows with columns orig_symbol, trade_date,
    symbol (None = dropped as a same-day duplicate)). Only symbols named in the change file can
    move, so only their stored rows are loaded."""
    changes = bd.load_symbol_changes()
    empty_moved = pd.DataFrame({"orig_symbol": pd.Series(dtype=object), "trade_date": pd.Series(dtype="datetime64[us]"), "symbol": pd.Series(dtype=object)})
    if changes is None or changes.empty:
        return new_prices, empty_moved
    from universe import apply_symbol_changes

    involved = sorted(set(changes["old_symbol"].astype(str)) | set(changes["new_symbol"].astype(str)))
    con.register("_involved", pd.DataFrame({"symbol": involved}))
    try:
        stored = con.execute(
            f"SELECT {', '.join(_q(c) for c in RAW_PRICE_COLUMNS)} FROM prices_daily WHERE symbol IN (SELECT symbol FROM _involved)"
        ).fetchdf()
    finally:
        con.unregister("_involved")
    stored = match_datetime_units(stored, new_prices["trade_date"].dtype)
    stored["_stored"] = True
    stored["_orig_symbol"] = stored["symbol"]
    fresh = new_prices[new_prices["symbol"].isin(involved)].copy()
    fresh["_stored"] = False
    fresh["_orig_symbol"] = fresh["symbol"]
    merged = pd.concat([stored, fresh], ignore_index=True)
    merged["trade_date"] = pd.to_datetime(merged["trade_date"])
    merged = merged.sort_values(["symbol", "trade_date"]).drop_duplicates(["symbol", "trade_date"], keep="last")
    renamed = apply_symbol_changes(merged, changes)
    kept_stored = renamed[renamed["_stored"]]
    moved = kept_stored[kept_stored["symbol"] != kept_stored["_orig_symbol"]][["_orig_symbol", "trade_date", "symbol"]]
    survivors = set(zip(kept_stored["_orig_symbol"], kept_stored["trade_date"]))
    dropped = stored[[(s, d) not in survivors for s, d in zip(stored["_orig_symbol"], stored["trade_date"])]]
    dropped = dropped[["_orig_symbol", "trade_date"]].assign(symbol=None)
    moved = pd.concat([moved, dropped], ignore_index=True).rename(columns={"_orig_symbol": "orig_symbol"})
    new_involved = renamed[~renamed["_stored"]].drop(columns=["_stored", "_orig_symbol"])
    others = new_prices[~new_prices["symbol"].isin(involved)]
    new_rows = pd.concat([others, new_involved], ignore_index=True)
    new_rows = new_rows.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    if new_rows.duplicated(["symbol", "trade_date"]).any():
        raise RuntimeError("new session rows are not unique per (symbol, trade_date) after symbol changes")
    return new_rows, moved


def _first_change_points(slim: pd.DataFrame, stored_mask: np.ndarray, new_factor: np.ndarray) -> tuple[set[str], dict[str, pd.Timestamp]]:
    """Symbols whose stored price_factor changed, and for the non-uniform ones the first date
    whose return vs an earlier row changed (a change point of new/old factor)."""
    old = slim["price_factor"].to_numpy(dtype="float64")
    changed_rows = stored_mask & ~((old == new_factor) | (np.isnan(old) & np.isnan(new_factor)))
    changed = set(slim.loc[changed_rows, "symbol"].astype(str))
    points: dict[str, pd.Timestamp] = {}
    if not changed:
        return changed, points
    sub = slim[stored_mask & slim["symbol"].isin(changed).to_numpy()].copy()
    sub["_ratio"] = new_factor[stored_mask & slim["symbol"].isin(changed).to_numpy()] / sub["price_factor"].to_numpy(dtype="float64")
    for symbol, grp in sub.sort_values(["symbol", "trade_date"]).groupby("symbol", sort=False):
        r = grp["_ratio"].to_numpy()
        diff = np.flatnonzero(r[1:] != r[:-1])
        if len(diff):
            points[str(symbol)] = _ts(grp["trade_date"].iloc[diff[0] + 1])
    return changed, points


def _late_reference_date(con, reference: pd.DataFrame, before: pd.Timestamp) -> pd.Timestamp | None:
    """Earliest effective_date < ``before`` whose reference snapshot (the columns the build
    reads) is new or differs from the stored security_reference_daily."""
    if reference is None or reference.empty:
        return None
    tables = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    if "security_reference_daily" not in tables:
        return None
    stored_cols = set(table_columns(con, "security_reference_daily"))
    cols = [c for c in REFERENCE_COMPARE_COLUMNS if c in reference.columns and c in stored_cols]
    old = reference[pd.to_datetime(reference["effective_date"]) < before][["symbol", "effective_date", *cols]].copy()
    if old.empty:
        return None
    old = old.drop_duplicates(["symbol", "effective_date"], keep="last")
    con.register("_ref_old", old)
    try:
        cond = " AND ".join(
            ["s.symbol = r.symbol", "CAST(s.effective_date AS TIMESTAMP) = CAST(r.effective_date AS TIMESTAMP)"]
            + [f"s.{_q(c)} IS NOT DISTINCT FROM r.{_q(c)}" for c in cols]
        )
        value = con.execute(
            f"SELECT min(r.effective_date) FROM _ref_old r WHERE NOT EXISTS (SELECT 1 FROM security_reference_daily s WHERE {cond})"
        ).fetchone()[0]
    finally:
        con.unregister("_ref_old")
    return _ts(value) if value is not None else None


def _late_index_date(con, index_features: pd.DataFrame | None, before: pd.Timestamp, names: Iterable[str]) -> pd.Timestamp | None:
    """Earliest trade_date < ``before`` where the close of an index the build reads (the RS
    benches and every mapped sector index) is new or differs from the stored index_daily."""
    if index_features is None or index_features.empty:
        return None
    tables = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    if "index_daily" not in tables:
        return None
    names = sorted({str(n) for n in names if n})
    frame = index_features[index_features["index_name"].astype(str).isin(names)]
    frame = frame[pd.to_datetime(frame["trade_date"]) < before][["index_name", "trade_date", "close_price"]]
    if frame.empty:
        return None
    con.register("_idx_new", frame)
    con.register("_idx_names", pd.DataFrame({"index_name": names}))
    try:
        value = con.execute(
            """
            SELECT min(trade_date) FROM (
                SELECT n.trade_date FROM _idx_new n
                WHERE NOT EXISTS (SELECT 1 FROM index_daily s WHERE s.index_name = n.index_name
                                  AND CAST(s.trade_date AS TIMESTAMP) = CAST(n.trade_date AS TIMESTAMP)
                                  AND s.close_price IS NOT DISTINCT FROM n.close_price)
                UNION ALL
                SELECT s.trade_date FROM index_daily s
                WHERE s.index_name IN (SELECT index_name FROM _idx_names) AND s.trade_date < ?
                  AND NOT EXISTS (SELECT 1 FROM _idx_new n WHERE n.index_name = s.index_name
                                  AND CAST(s.trade_date AS TIMESTAMP) = CAST(n.trade_date AS TIMESTAMP))
            )
            """,
            [before.to_pydatetime()],
        ).fetchone()[0]
    finally:
        con.unregister("_idx_new")
        con.unregister("_idx_names")
    return _ts(value) if value is not None else None


def _sessions_between(con, start: pd.Timestamp, end: pd.Timestamp) -> int:
    return int(
        con.execute(
            "SELECT count(DISTINCT trade_date) FROM prices_daily WHERE trade_date >= ? AND trade_date < ?",
            [start.to_pydatetime(), end.to_pydatetime()],
        ).fetchone()[0]
    )


def month_window_start(first_new: pd.Timestamp) -> pd.Timestamp:
    """Earliest date a session on ``first_new`` can change for a symbol that traded every
    session: the previous calendar month-end (its monthly bar label; the swing flags of that bar
    need the current month's bar) and the Monday of the previous week (weekly swing flags, a
    holiday-shortened week completing late for wema_20). ``rewrite_starts`` generalises this
    per symbol for symbols with gaps."""
    month_start = first_new.replace(day=1)
    week_start = first_new - pd.Timedelta(days=first_new.weekday())
    return min(month_start - pd.Timedelta(days=1), week_start - pd.Timedelta(days=7))


def rewrite_starts(con, symbols: list[str], recompute_from: pd.Timestamp) -> dict[str, pd.Timestamp]:
    """Per symbol with new rows: the first stored row whose value the new sessions can change.

    The only non-causal columns are the swing-point flags (daily/weekly/monthly RSI
    divergence: a swing at bar t needs bar t+1) and wema_20 (a week completes when a session
    on/after its calendar Friday exists). New rows extend or add the symbol's LAST weekly and
    monthly bar, so the rows that can change are those mapped (as-of) to the bar BEFORE the last
    one - i.e. every row on/after the label of the symbol's previous trading week (its Friday)
    and previous trading month (its calendar month-end) - plus the last row (daily swing).
    A symbol without such a previous bar is rewritten from its first row.
    """
    if not symbols:
        return {}
    con.register("_new_syms", pd.DataFrame({"symbol": symbols}))
    try:
        rows = con.execute(
            """
            WITH p AS (
                SELECT p.symbol, CAST(p.trade_date AS DATE) AS d,
                       CAST(p.trade_date AS DATE) + to_days(CAST((5 - isodow(p.trade_date) + 7) % 7 AS INTEGER)) AS fri,
                       date_trunc('month', p.trade_date) AS mon
                FROM prices_daily p JOIN _new_syms USING (symbol)
            ), last AS (
                SELECT symbol, max(d) AS d_last, max(fri) AS fri_last, max(mon) AS mon_last, min(d) AS d_first FROM p GROUP BY symbol
            )
            SELECT l.symbol, l.d_first, l.d_last,
                   max(p.fri) FILTER (WHERE p.fri < l.fri_last) AS prev_fri,
                   last_day(max(p.mon) FILTER (WHERE p.mon < l.mon_last)) AS prev_month_end
            FROM last l JOIN p USING (symbol)
            GROUP BY l.symbol, l.d_first, l.d_last
            """
        ).fetchall()
    finally:
        con.unregister("_new_syms")
    out: dict[str, pd.Timestamp] = {}
    for symbol, d_first, d_last, prev_fri, prev_month_end in rows:
        if prev_fri is None or prev_month_end is None:
            start = _ts(d_first)
        else:
            start = min(_ts(prev_fri), _ts(prev_month_end), _ts(d_last))
        out[str(symbol)] = min(start, recompute_from)
    for symbol in symbols:  # brand-new symbols (no stored rows)
        out.setdefault(symbol, recompute_from)
    return out


# --------------------------------------------------------------------------------------------
# The append
# --------------------------------------------------------------------------------------------

def incremental_append(db_path: Path, new_prices: pd.DataFrame, *, root: Path, equity: pd.DataFrame, quiet: bool = False) -> dict:
    """Append ``new_prices`` (raw bhavcopy rows newer than the DB) to ``db_path`` in place.

    Caller holds the writer lock. Raises FullRecomputeRequired (nothing written) when the
    incremental path cannot reproduce a full recompute; any other error after the backup rolls
    the transaction back (live DB unchanged) and propagates.
    """
    t0 = time.perf_counter()
    timings: dict[str, float] = {}

    def lap(name: str) -> None:
        timings[name] = round(time.perf_counter() - t0 - sum(timings.values()), 1)
        if not quiet:
            print(f"  [incremental] {name}: {timings[name]:.1f}s", flush=True)

    db_path = Path(db_path)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        _require_current_schema(con)
        plan, ctx = _plan(con, new_prices, root=root, equity=equity, quiet=quiet)
        lap("plan")
        computed = _compute(con, plan, ctx, quiet=quiet)
        lap("compute indicators")
    finally:
        con.close()
    gc.collect()

    import db_backup

    backup = db_backup.backup_database(db_path)
    lap("backup")
    con = duckdb.connect(str(db_path))
    try:
        con.execute("BEGIN TRANSACTION")
        try:
            summary = _write(con, plan, ctx, computed, quiet=quiet)
            from migrations import _apply_always_on_repairs

            _apply_always_on_repairs(con)
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
        lap("write transaction")
        con.execute("CHECKPOINT")
        _derived_step(con, quiet=quiet)
        lap("derived tables")
    finally:
        con.close()
    summary.update({"backup": backup, "timings_s": timings, "reasons": plan.reasons})
    return summary


def _plan(con, new_prices: pd.DataFrame, *, root: Path, equity: pd.DataFrame, quiet: bool) -> tuple[AppendPlan, dict]:
    from price_adjustment import actions_from_corporate_actions_table
    from reference_history import load_reference_history

    sw = _Stopwatch(quiet)
    latest_date = _ts(con.execute("SELECT max(trade_date) FROM prices_daily").fetchone()[0])
    new_prices = new_prices.copy()
    new_prices["trade_date"] = pd.to_datetime(new_prices["trade_date"])
    date_dtype = new_prices["trade_date"].dtype
    new_rows, moved = _apply_symbol_changes_to_new(con, new_prices)
    first_new = _ts(new_rows["trade_date"].min())
    reasons: list[str] = []
    sw("symbol changes")

    # --- adjustments over every row (slim), exactly as adjust_prices sees the merged history.
    slim = con.execute("SELECT symbol, trade_date, close_price, prev_close, price_factor FROM prices_daily").fetchdf()
    slim = match_datetime_units(slim, date_dtype)
    if not moved.empty:
        key = pd.MultiIndex.from_frame(slim[["symbol", "trade_date"]])
        mkey = pd.MultiIndex.from_frame(moved[["orig_symbol", "trade_date"]].rename(columns={"orig_symbol": "symbol"}))
        pos = key.get_indexer(mkey)
        new_sym = slim["symbol"].to_numpy(dtype=object).copy()
        new_sym[pos] = moved["symbol"].to_numpy(dtype=object)
        slim["symbol"] = new_sym
        slim = slim[slim["symbol"].notna()]
    stored_n = len(slim)
    fresh = new_rows[["symbol", "trade_date", "close_price", "prev_close"]].copy()
    fresh["price_factor"] = np.nan
    slim = pd.concat([slim, fresh], ignore_index=True)
    stored_mask = np.zeros(len(slim), dtype=bool)
    stored_mask[:stored_n] = True
    try:
        extra = actions_from_corporate_actions_table(con.execute("SELECT * FROM corporate_actions").fetchdf())
    except Exception as exc:  # noqa: BLE001 - same policy as append_database._load_extra_actions
        print(f"Warning: corporate_actions table unavailable ({exc}); no extra actions fed to adjust_prices.")
        extra = None
    adjusted, adjustments = adjust_prices(slim[["symbol", "trade_date", "close_price", "prev_close"]], root, extra_actions=extra)
    print(summarize_adjustments(adjustments))
    sw("price adjustments over all rows")
    new_factor = adjusted["price_factor"].to_numpy(dtype="float64")
    factor_changed, change_points = _first_change_points(slim, stored_mask, new_factor)
    del adjusted, slim
    gc.collect()

    renamed = set()
    if not moved.empty:
        renamed = set(moved["orig_symbol"].astype(str)) | set(moved["symbol"].dropna().astype(str))
        reasons.append(f"symbol changes moved {len(moved):,} stored rows ({', '.join(sorted(renamed)[:6])})")
        # a new ticker that already had stored rows: its older ranks change from its first row
        con.register("_renamed", pd.DataFrame({"symbol": sorted(set(moved["symbol"].dropna().astype(str)))}))
        try:
            first_existing = con.execute("SELECT min(trade_date) FROM prices_daily WHERE symbol IN (SELECT symbol FROM _renamed)").fetchone()[0]
        finally:
            con.unregister("_renamed")
        if first_existing is not None:
            change_points["__rename__"] = _ts(first_existing)
    if factor_changed:
        reasons.append(f"price_factor changed for {len(factor_changed)} symbols ({', '.join(sorted(factor_changed)[:6])})")

    # --- late inputs that change older dates
    reference_history = load_reference_history(root)
    sw("reference history")
    candidates = [first_new, *change_points.values()]
    late_ref = _late_reference_date(con, reference_history, first_new)
    if late_ref is not None:
        reasons.append(f"late reference snapshot from {late_ref.date()}")
        candidates.append(late_ref)
    index_raw, membership = bd.load_benchmark_inputs()
    sw("index history")
    try:
        index_features = bd.build_index_features(index_raw) if not isinstance(index_raw, BaseException) else None
    except Exception:  # noqa: BLE001
        index_features = None
    names: set = set()
    if "sector_index_name" in set(table_columns(con, "indicators_daily")):
        names = {r[0] for r in con.execute("SELECT DISTINCT sector_index_name FROM indicators_daily WHERE sector_index_name IS NOT NULL").fetchall()}
    from true_rs import BENCH_MIDSML400, BENCH_NIFTY50

    late_idx = _late_index_date(con, index_features, first_new, names | {BENCH_NIFTY50, BENCH_MIDSML400})
    if late_idx is not None:
        reasons.append(f"index history changed from {late_idx.date()}")
        candidates.append(late_idx)
    sw("late-input checks")
    recompute_from = min(candidates)
    if recompute_from < first_new:
        n = _sessions_between(con, recompute_from, first_new)
        if n > MAX_RECOMPUTE_SESSIONS:
            raise FullRecomputeRequired(
                f"older dates changed back to {recompute_from.date()} ({n} sessions > {MAX_RECOMPUTE_SESSIONS}): "
                + "; ".join(reasons)
            )

    # --- master / enrichment inputs (as the old append built them)
    sector = bd.read_sector()
    mcap = bd.read_market_cap()
    bands = bd.read_price_band()
    pe = bd.read_pe()
    high52 = bd.read_52_week()
    latest = con.execute(
        "SELECT symbol, arg_max(series, trade_date) AS series, max(trade_date) AS trade_date, arg_max(close_price, trade_date) AS close_price FROM prices_daily GROUP BY symbol"
    ).fetchdf()
    latest = match_datetime_units(latest, date_dtype)
    if not moved.empty:
        latest = latest[~latest["symbol"].isin(renamed)]
        con.register("_renamed_all", pd.DataFrame({"symbol": sorted(renamed)}))
        try:
            extra_latest = con.execute(
                "SELECT symbol, series, trade_date, close_price FROM prices_daily WHERE symbol IN (SELECT symbol FROM _renamed_all)"
            ).fetchdf()
        finally:
            con.unregister("_renamed_all")
        extra_latest = match_datetime_units(extra_latest, date_dtype)
        mk = moved.set_index(["orig_symbol", "trade_date"])["symbol"]
        mapped = [mk.get((s, d), s) for s, d in zip(extra_latest["symbol"], extra_latest["trade_date"])]
        extra_latest["symbol"] = mapped
        extra_latest = extra_latest[extra_latest["symbol"].notna()]
        latest = pd.concat([latest, extra_latest], ignore_index=True)
    latest_prices = pd.concat([latest, new_rows[["symbol", "series", "trade_date", "close_price"]]], ignore_index=True)
    enrichment = bd.build_enrichment(mcap, bands, pe, high52, pd.DataFrame(), pd.DataFrame())
    master = bd.build_master(equity, sector, latest_prices, mcap, bands, pe)

    sw("master / enrichment")
    stored_master = con.execute("SELECT * FROM stocks_master").fetchdf()
    tax_cols = [c for c in TAXONOMY_COLUMNS if c in master.columns and c in stored_master.columns]
    a = master.set_index("symbol")[tax_cols].fillna("").astype(str)
    b = stored_master.drop_duplicates("symbol", keep="last").set_index("symbol")[tax_cols].fillna("").astype(str)
    common = a.index.intersection(b.index)
    taxonomy_changed = bool((a.loc[common] != b.loc[common]).any(axis=None)) or len(tax_cols) != len(TAXONOMY_COLUMNS)
    if not taxonomy_changed:
        # a symbol that gained/lost a classification also regroups history
        only_new = a.index.difference(b.index)
        taxonomy_changed = bool((a.loc[only_new] != "").any(axis=None))
    if taxonomy_changed:
        reasons.append("sector taxonomy changed: sector tables recomputed over all dates")

    def eligible(frame: pd.DataFrame) -> pd.Series:
        if "market_cap_cr" not in frame.columns:
            return pd.Series(False, index=frame["symbol"])
        return pd.Series((pd.to_numeric(frame["market_cap_cr"], errors="coerce").fillna(0.0) >= LEADER_MIN_CAP_CR).to_numpy(), index=frame["symbol"])

    e_new = eligible(master.drop_duplicates("symbol", keep="last"))
    e_old = eligible(stored_master.drop_duplicates("symbol", keep="last"))
    allsyms = e_new.index.union(e_old.index)
    flipped = set(allsyms[e_new.reindex(allsyms, fill_value=False).to_numpy() != e_old.reindex(allsyms, fill_value=False).to_numpy()].astype(str))

    plan = AppendPlan(
        latest_date=latest_date,
        first_new=first_new,
        recompute_from=recompute_from,
        new_rows=new_rows,
        moved_rows=moved,
        full_symbols=factor_changed | renamed,
        factor_changed=factor_changed,
        adjustments=adjustments,
        date_dtype=date_dtype,
        reasons=reasons,
    )
    ctx = {
        "reference_history": reference_history,
        "index_raw": index_raw,
        "membership": membership,
        "index_features": index_features,
        "enrichment": enrichment,
        "master": master,
        "mcap": mcap, "bands": bands, "pe": pe, "high52": high52,
        "taxonomy_changed": taxonomy_changed,
        "leader_flipped": flipped,
    }
    if not quiet:
        print(
            f"  [incremental] {len(new_rows):,} new rows for {new_rows['trade_date'].nunique()} session(s) from {first_new.date()}; "
            f"recompute_from {recompute_from.date()}; full-history symbols {len(plan.full_symbols)}"
            + (f"; {'; '.join(reasons)}" if reasons else ""),
            flush=True,
        )
    return plan, ctx


def _compute(con, plan: AppendPlan, ctx: dict, *, quiet: bool) -> dict:
    """Adjusted rows to write and the recomputed indicator rows (not written yet)."""
    sw = _Stopwatch(quiet)
    date_dtype = plan.date_dtype
    price_cols = table_columns(con, "prices_daily")
    raw_cols = [c for c in RAW_PRICE_COLUMNS if c in price_cols]
    new_syms = set(plan.new_rows["symbol"].astype(str))
    full = set(plan.full_symbols)
    moved = plan.moved_rows

    # ---- affected symbols and where each one's rewrite starts
    stored_after = {
        r[0]
        for r in con.execute(
            "SELECT DISTINCT symbol FROM prices_daily WHERE trade_date >= ?", [plan.recompute_from.to_pydatetime()]
        ).fetchall()
    }
    renamed_away = set(moved["orig_symbol"].astype(str)) if not moved.empty else set()
    tail_syms = sorted(((new_syms | stored_after) - full))
    new_starts = rewrite_starts(con, sorted(new_syms - full), plan.recompute_from)
    start = {s: new_starts.get(s, plan.recompute_from) for s in tail_syms}

    # ---- raw rows needed: trailing window (tail symbols) / full history (full symbols)
    window_raw, stored_adj = _load_windows(con, raw_cols, price_cols, start, date_dtype)
    full_raw = _load_full_history(con, raw_cols, full, moved, date_dtype)
    new_rows = plan.new_rows[[c for c in raw_cols if c in plan.new_rows.columns]]
    raw = pd.concat([f for f in (window_raw, full_raw, new_rows) if not f.empty], ignore_index=True)
    raw["trade_date"] = pd.to_datetime(raw["trade_date"]).astype(date_dtype)
    raw = raw.sort_values(["symbol", "trade_date"], kind="stable").reset_index(drop=True)
    adjusted = apply_adjustments(raw, plan.adjustments)
    del raw, window_raw, full_raw
    _check_stored_adjustments(adjusted, stored_adj, full)
    sw("windows + adjustments")

    new_keys = set(zip(plan.new_rows["symbol"], plan.new_rows["trade_date"]))
    is_new = np.fromiter(((s, d) in new_keys for s, d in zip(adjusted["symbol"], adjusted["trade_date"])), dtype=bool, count=len(adjusted))
    is_full = adjusted["symbol"].isin(full).to_numpy()
    prices_to_write = adjusted[is_new | is_full].reset_index(drop=True)

    ind_window = indicator_input(adjusted)
    # indicator input of the rows that are not (or no longer correctly) in prices_daily
    ind_fresh = ind_window[is_new | is_full].reset_index(drop=True)
    del adjusted
    gc.collect()

    # ---- keep_from per symbol (full symbols keep everything)
    keep_from = dict(start)
    for s in full:
        keep_from[s] = KEEP_ALL

    # ---- cross-sectional ranks (window closes suffice: 252-row lookback)
    ranks = _rank_columns(con, ind_window, plan, keep_from, date_dtype)
    sw("RS ranks")
    del ind_window
    gc.collect()

    # ---- per-symbol pass over each affected symbol's FULL history, in batches
    affected = sorted(set(start) | full)
    stored_counts = dict(con.execute("SELECT symbol, count(*) FROM prices_daily GROUP BY symbol").fetchall())
    fresh_counts = ind_fresh.groupby("symbol").size().to_dict()
    counts = pd.DataFrame({
        "symbol": affected,
        "n": [(0 if s in full else stored_counts.get(s, 0)) + fresh_counts.get(s, 0) for s in affected],
    })
    batches = symbol_batches(counts, BATCH_ROWS)
    ref_groups = reference_by_symbol(ctx["reference_history"])
    reference = ctx["reference_history"]
    enrichment = ctx["enrichment"]
    fresh_by_symbol = {s: g for s, g in ind_fresh.groupby("symbol", sort=False)}
    rank_by_symbol = {s: g for s, g in ranks.groupby("symbol", sort=False)}
    select_input = indicator_input_select(price_cols)

    def tasks():
        for symbols in batches:
            stored_syms = [s for s in symbols if s not in full]
            parts = []
            if stored_syms:
                con.register("_batch_syms", pd.DataFrame({"symbol": stored_syms}))
                try:
                    stored = con.execute(
                        f"SELECT {select_input} FROM prices_daily WHERE symbol IN (SELECT symbol FROM _batch_syms) ORDER BY symbol, trade_date"
                    ).fetchdf()
                finally:
                    con.unregister("_batch_syms")
                parts.append(match_datetime_units(stored, date_dtype))
            parts.extend(fresh_by_symbol[s] for s in symbols if s in fresh_by_symbol)
            frame = pd.concat(parts, ignore_index=True)
            frame = frame.sort_values(["symbol", "trade_date"], kind="stable").reset_index(drop=True)
            rank_rows = pd.concat([rank_by_symbol[s] for s in symbols], ignore_index=True)
            yield {
                "input": frame,
                "ranks": rank_rows,
                "keep_from": {s: keep_from[s] for s in symbols},
                "reference": None if ref_groups is None else reference_subset(ref_groups, reference, symbols),
            }

    results: list[pd.DataFrame] = []
    run_batches(
        tasks,
        results.append,
        context=(slim_index_history(ctx["index_raw"]) if not isinstance(ctx["index_raw"], BaseException) else ctx["index_raw"], ctx["membership"], enrichment),
        reset=results.clear,
        total=len(batches),
        label="incremental indicator batches",
        workers=APPEND_WORKERS,
    )
    indicators = pd.concat(results, ignore_index=True) if results else pd.DataFrame()
    del results
    if not quiet:
        print(f"  [incremental] recomputed {len(indicators):,} indicator rows for {len(affected):,} symbols", flush=True)
    return {
        "prices": prices_to_write,
        "indicators": indicators,
        "rewrite_start": start,
        "full": full,
        "renamed_away": renamed_away,
    }


def _load_windows(con, raw_cols, price_cols, start: dict, date_dtype) -> tuple[pd.DataFrame, pd.DataFrame]:
    """For every tail symbol: its stored rows from rewrite_start on plus DAILY_LOOKBACK_ROWS
    rows before (fewer only when the history is shorter). Returns (raw rows, stored adj
    columns of those rows for the consistency check)."""
    if not start:
        return pd.DataFrame(columns=raw_cols), pd.DataFrame()
    starts = pd.DataFrame({"symbol": list(start), "rewrite_start": pd.to_datetime(list(start.values()))})
    adj_cols = [c for c in price_cols if c.startswith("adj_") or c == "price_factor"]
    con.register("_starts", starts)
    try:
        frame = con.execute(
            f"""
            WITH w AS (
                SELECT p.*, s.rewrite_start,
                       row_number() OVER (PARTITION BY p.symbol ORDER BY p.trade_date DESC) AS rn_desc,
                       count(*) FILTER (WHERE p.trade_date >= s.rewrite_start) OVER (PARTITION BY p.symbol) AS n_keep
                FROM prices_daily p JOIN _starts s USING (symbol)
            )
            SELECT {', '.join(_q(c) for c in raw_cols + adj_cols)} FROM w
            WHERE rn_desc <= n_keep + {bd.DAILY_LOOKBACK_ROWS}
            ORDER BY symbol, trade_date
            """
        ).fetchdf()
    finally:
        con.unregister("_starts")
    frame = match_datetime_units(frame, date_dtype)
    return frame[raw_cols], frame[["symbol", "trade_date", *adj_cols]]


def _load_full_history(con, raw_cols, full: set, moved: pd.DataFrame, date_dtype) -> pd.DataFrame:
    """Stored raw rows of the full-recompute symbols (after symbol changes)."""
    if not full:
        return pd.DataFrame(columns=raw_cols)
    sources = set(full)
    if not moved.empty:
        sources |= set(moved.loc[moved["symbol"].isin(full), "orig_symbol"].astype(str))
    con.register("_full_src", pd.DataFrame({"symbol": sorted(sources)}))
    try:
        frame = con.execute(
            f"SELECT {', '.join(_q(c) for c in raw_cols)} FROM prices_daily WHERE symbol IN (SELECT symbol FROM _full_src) ORDER BY symbol, trade_date"
        ).fetchdf()
    finally:
        con.unregister("_full_src")
    frame = match_datetime_units(frame, date_dtype)
    if not moved.empty:
        mk = moved.set_index(["orig_symbol", "trade_date"])["symbol"]
        frame["symbol"] = [mk.get((s, d), s) if (s, d) in mk.index else s for s, d in zip(frame["symbol"], frame["trade_date"])]
        frame = frame[frame["symbol"].notna()]
    frame = frame[frame["symbol"].isin(full)]
    return frame.sort_values(["symbol", "trade_date"], kind="stable").drop_duplicates(["symbol", "trade_date"], keep="first")


def _check_stored_adjustments(adjusted: pd.DataFrame, stored_adj: pd.DataFrame, full: set) -> None:
    """Fail closed if re-adjusting a stored window row does not reproduce the stored adj_*
    values (the first row of each window is skipped: its adj_prev_close falls back to
    prev_close * factor because the row before it is not in the window)."""
    if stored_adj is None or stored_adj.empty:
        return
    cols = [c for c in stored_adj.columns if c not in ("symbol", "trade_date")]
    merged = stored_adj.merge(adjusted[["symbol", "trade_date", *cols]], on=["symbol", "trade_date"], how="left", suffixes=("_old", ""))
    first = merged.groupby("symbol", sort=False).cumcount() == 0
    check = merged[~first & ~merged["symbol"].isin(full)]
    for col in cols:
        a = check[f"{col}_old"].to_numpy(dtype="float64")
        b = check[col].to_numpy(dtype="float64")
        bad = ~((a == b) | (np.isnan(a) & np.isnan(b)))
        if bad.any():
            row = check[bad].iloc[0]
            raise RuntimeError(
                f"stored {col} for {row['symbol']} {pd.Timestamp(row['trade_date']).date()} does not match the recomputed "
                f"adjustment ({row[f'{col}_old']!r} vs {row[col]!r}); refusing an incremental append"
            )


def _rank_columns(con, ind_input: pd.DataFrame, plan: AppendPlan, keep_from: dict, date_dtype) -> pd.DataFrame:
    """RANK_COLUMNS for the rows each symbol keeps: percentiles recomputed for dates >=
    recompute_from (every symbol trading then is in ``ind_input``), stored percentiles reused
    for older rows, rs_rank_t* lags taken over the window."""
    frame = ind_input[["symbol", "trade_date", "close_price"]].reset_index(drop=True)
    inputs = bd.rs_rank_inputs(frame)
    recent = (frame["trade_date"] >= plan.recompute_from).to_numpy()
    pct = pd.DataFrame(index=frame.index, columns=list(RANK_PERCENTILE_COLUMNS), dtype="float64")
    if recent.any():
        fresh = bd.rs_percentiles(inputs[recent])
        pct.loc[recent, list(RANK_PERCENTILE_COLUMNS)] = fresh[list(RANK_PERCENTILE_COLUMNS)].to_numpy()
    older = ~recent
    if older.any():
        stored = _stored_percentiles(con, frame[older], plan, date_dtype)
        pct.loc[older, list(RANK_PERCENTILE_COLUMNS)] = stored[list(RANK_PERCENTILE_COLUMNS)].to_numpy()
    ranks = bd.rs_rank_columns(inputs, percentiles=pct.astype("float64"))
    out = pd.concat([frame[["symbol", "trade_date"]], ranks], axis=1)
    kf = out["symbol"].map(keep_from)
    return out[(out["trade_date"] >= kf).to_numpy()].reset_index(drop=True)


def _stored_percentiles(con, rows: pd.DataFrame, plan: AppendPlan, date_dtype) -> pd.DataFrame:
    keys = rows[["symbol", "trade_date"]].copy()
    keys["_pos"] = np.arange(len(keys))
    keys["src_symbol"] = keys["symbol"]
    moved = plan.moved_rows
    if not moved.empty:
        back = moved.dropna(subset=["symbol"]).set_index(["symbol", "trade_date"])["orig_symbol"]
        keys["src_symbol"] = [back.get((s, d), s) if (s, d) in back.index else s for s, d in zip(keys["symbol"], keys["trade_date"])]
    con.register("_pct_keys", keys[["src_symbol", "trade_date", "_pos"]])
    try:
        cols = ", ".join(f"i.{_q(c)}" for c in RANK_PERCENTILE_COLUMNS)
        got = con.execute(
            f"SELECT k._pos, {cols} FROM _pct_keys k LEFT JOIN indicators_daily i ON i.symbol = k.src_symbol AND i.trade_date = k.trade_date ORDER BY k._pos"
        ).fetchdf()
    finally:
        con.unregister("_pct_keys")
    if len(got) != len(keys):
        raise RuntimeError("stored rank lookup returned duplicate rows")
    return got


# --------------------------------------------------------------------------------------------
# Write phase (inside one transaction)
# --------------------------------------------------------------------------------------------

def _insert(con, table: str, frame: pd.DataFrame) -> None:
    if frame is None or frame.empty:
        return
    table_cols = set(table_columns(con, table))
    extra = [c for c in frame.columns if c not in table_cols]
    if extra:
        raise RuntimeError(f"{table}: computed rows have columns the live table lacks: {extra[:8]}")
    con.register("_ins", frame)
    try:
        con.execute(f"INSERT INTO {_q(table)} BY NAME SELECT * FROM _ins")
    finally:
        con.unregister("_ins")


def _replace_table(con, table: str, frame: pd.DataFrame, indexes: Iterable[str] = ()) -> None:
    """CREATE OR REPLACE ``table`` from ``frame`` - the same CREATE TABLE AS the temp build uses."""
    con.register("_repl", frame)
    try:
        con.execute(f"CREATE OR REPLACE TABLE {_q(table)} AS SELECT * FROM _repl")
    finally:
        con.unregister("_repl")
    for ddl in indexes:
        con.execute(ddl)


def _write(con, plan: AppendPlan, ctx: dict, computed: dict, *, quiet: bool) -> dict:
    sw = _Stopwatch(quiet)
    date_dtype = plan.date_dtype
    full = computed["full"]
    moved = plan.moved_rows

    # -- prices_daily
    if not moved.empty:
        con.register("_moved", moved[["orig_symbol", "trade_date"]])
        try:
            con.execute("DELETE FROM prices_daily p WHERE EXISTS (SELECT 1 FROM _moved m WHERE m.orig_symbol = p.symbol AND m.trade_date = p.trade_date)")
            con.execute("DELETE FROM indicators_daily p WHERE EXISTS (SELECT 1 FROM _moved m WHERE m.orig_symbol = p.symbol AND m.trade_date = p.trade_date)")
        finally:
            con.unregister("_moved")
    if full:
        con.register("_full", pd.DataFrame({"symbol": sorted(full)}))
        try:
            con.execute("DELETE FROM prices_daily WHERE symbol IN (SELECT symbol FROM _full)")
            con.execute("DELETE FROM indicators_daily WHERE symbol IN (SELECT symbol FROM _full)")
        finally:
            con.unregister("_full")
    _insert(con, "prices_daily", computed["prices"])

    # -- indicators_daily: replace each tail symbol's rows from its rewrite start
    starts = pd.DataFrame({"symbol": list(computed["rewrite_start"]), "rewrite_start": pd.to_datetime(list(computed["rewrite_start"].values()))})
    if not starts.empty:
        con.register("_starts", starts)
        try:
            con.execute(
                "DELETE FROM indicators_daily i WHERE EXISTS (SELECT 1 FROM _starts s WHERE s.symbol = i.symbol AND i.trade_date >= s.rewrite_start)"
            )
        finally:
            con.unregister("_starts")
    _insert(con, "indicators_daily", computed["indicators"])
    sw("prices_daily + indicators_daily")

    # -- whole-table small outputs
    _replace_table(con, "price_adjustments", plan.adjustments)
    index_features = ctx["index_features"]
    if index_features is not None and not index_features.empty:
        _replace_table(con, "index_daily", index_features, ["CREATE INDEX IF NOT EXISTS idx_index_daily_date_name ON index_daily(trade_date, index_name)"])
    _update_reference(con, ctx["reference_history"])
    master = ctx["master"]
    _replace_table(con, "stocks_master", master)
    sw("adjustments / index / reference / master")

    deals = bd.enrich_deals_from_db(con, bd.read_all_deals(), master, date_dtype)
    metrics_from = plan.recompute_from
    changed_deal_date = _first_changed_deal_date(con, deals)
    if changed_deal_date is not None and changed_deal_date < metrics_from:
        metrics_from = changed_deal_date
    _replace_table(con, "deals", deals, ["CREATE INDEX IF NOT EXISTS idx_deals_symbol_date ON deals(symbol, trade_date)"])
    latest_deals = deals[deals["trade_date"] == deals["trade_date"].max()] if not deals.empty else deals
    enrichment = bd.build_enrichment(ctx["mcap"], ctx["bands"], ctx["pe"], ctx["high52"], latest_deals, pd.DataFrame())
    _replace_table(con, "daily_enrichment", enrichment)
    sw("deals + enrichment")

    # -- per-date derived tables
    breadth_full = bool(plan.factor_changed)
    _update_breadth(con, plan.recompute_from, date_dtype, full_recompute=breadth_full)
    sw("breadth_daily")
    rotation = _update_sector_rotation(con, master, plan.recompute_from, date_dtype, full_recompute=ctx["taxonomy_changed"], flipped=ctx["leader_flipped"])
    sw("sector_rotation")
    reference_for_metrics = ctx["reference_history"]
    if reference_for_metrics is None or reference_for_metrics.empty:
        try:
            reference_for_metrics = con.execute("SELECT * FROM security_reference_daily").fetchdf()
        except duckdb.Error:
            reference_for_metrics = pd.DataFrame()
    # as append_database.load_index_for_metrics: fresh MA/ind_close history, else the stored table
    index_for_metrics = index_features
    if index_for_metrics is None or index_for_metrics.empty:
        tables = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
        index_for_metrics = con.execute("SELECT * FROM index_daily").fetchdf() if "index_daily" in tables else pd.DataFrame()
    _update_sector_metrics(
        con, master, reference_for_metrics, index_for_metrics, deals, metrics_from, date_dtype, full_recompute=ctx["taxonomy_changed"]
    )
    sw("sector_metrics_daily")
    latest = read_slim(
        con, "indicators_daily", table_columns(con, "indicators_daily"),
        where="trade_date = (SELECT max(trade_date) FROM indicators_daily)", date_dtype=date_dtype,
    )
    latest = latest[[c for c in _indicator_frame_columns(computed["indicators"], latest)]]
    screener = bd.make_screener_results(latest, master, deals, rotation)
    _replace_table(con, "screener_results", screener, ["CREATE INDEX IF NOT EXISTS idx_screener_name ON screener_results(screener_name)"])
    return {
        "new_rows": int(len(plan.new_rows)),
        "db_date": pd.Timestamp(plan.new_rows["trade_date"].max()).date().isoformat(),
        "indicator_rows": int(len(computed["indicators"])),
        "full_symbols": sorted(full),
        "recompute_from": plan.recompute_from.date().isoformat(),
    }


def _indicator_frame_columns(computed: pd.DataFrame, latest: pd.DataFrame) -> list[str]:
    """Column order of a freshly computed indicators frame (the live table may carry ALTER-added
    columns at the end); any live-only columns follow."""
    order = [c for c in computed.columns if c in latest.columns] if not computed.empty else list(latest.columns)
    return order + [c for c in latest.columns if c not in order]


def _update_reference(con, reference: pd.DataFrame | None) -> None:
    """security_reference_daily := stored rows + reference_history, reference winning on
    (symbol, effective_date) - what the temp build's preserved-table merge produces."""
    if reference is None or reference.empty:
        return
    tables = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    ref = reference.drop_duplicates(["symbol", "effective_date"], keep="last")
    if "security_reference_daily" not in tables:
        _replace_table(con, "security_reference_daily", ref)
        con.execute("CREATE INDEX IF NOT EXISTS idx_reference_symbol_date ON security_reference_daily(symbol, effective_date)")
        return
    stored = con.execute("SELECT * FROM security_reference_daily").fetchdf()
    merged = pd.concat([stored, ref], ignore_index=True).drop_duplicates(["symbol", "effective_date"], keep="last")
    _replace_table(con, "security_reference_daily", merged, [
        "CREATE INDEX IF NOT EXISTS idx_reference_symbol_date ON security_reference_daily(symbol, effective_date)"
    ])


def _first_changed_deal_date(con, deals: pd.DataFrame) -> pd.Timestamp | None:
    tables = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    if "deals" not in tables or deals is None:
        return None
    cols = [c for c in ("deal_type", "trade_date", "symbol", "client_name", "side", "quantity", "price", "deal_value_cr") if c in deals.columns]
    stored_cols = set(table_columns(con, "deals"))
    cols = [c for c in cols if c in stored_cols]
    if "trade_date" not in cols or deals.empty:
        return None
    con.register("_deals_new", deals[cols])
    try:
        collist = ", ".join(_q(c) for c in cols)
        value = con.execute(
            f"""SELECT min(trade_date) FROM (
                    (SELECT {collist} FROM _deals_new EXCEPT ALL SELECT {collist} FROM deals)
                    UNION ALL
                    (SELECT {collist} FROM deals EXCEPT ALL SELECT {collist} FROM _deals_new))"""
        ).fetchone()[0]
    finally:
        con.unregister("_deals_new")
    return _ts(value) if value is not None else None


def _dates_before(con, table: str, before: pd.Timestamp, n: int) -> pd.Timestamp | None:
    row = con.execute(
        f"SELECT min(trade_date) FROM (SELECT DISTINCT trade_date FROM {_q(table)} WHERE trade_date < ? ORDER BY trade_date DESC LIMIT {int(n)})",
        [before.to_pydatetime()],
    ).fetchone()
    return _ts(row[0]) if row and row[0] is not None else None


def _replace_dates(con, table: str, frame: pd.DataFrame, since: pd.Timestamp) -> None:
    con.execute(f"DELETE FROM {_q(table)} WHERE trade_date >= ?", [since.to_pydatetime()])
    if frame is not None and not frame.empty:
        _insert(con, table, frame[pd.to_datetime(frame["trade_date"]) >= since])


def _update_breadth(con, since: pd.Timestamp, date_dtype, *, full_recompute: bool) -> None:
    if full_recompute:
        _replace_table(con, "breadth_daily", bd.build_breadth_daily(read_slim(con, "indicators_daily", BREADTH_COLUMNS, date_dtype=date_dtype)),
                       ["CREATE INDEX IF NOT EXISTS idx_breadth_date ON breadth_daily(trade_date)"])
        return
    lo = _dates_before(con, "indicators_daily", since, BREADTH_LOOKBACK_SESSIONS) or since
    frame = read_slim(con, "indicators_daily", BREADTH_COLUMNS, where="trade_date >= ?", params=[lo.to_pydatetime()], date_dtype=date_dtype)
    _replace_dates(con, "breadth_daily", bd.build_breadth_daily(frame), since)


def _rotation_lookback_start(con, master: pd.DataFrame, since: pd.Timestamp) -> pd.Timestamp | None:
    """Earliest date needed so that every sector_rotation group has its last
    ROTATION_GROUP_ROWS group-sessions before ``since`` (session lags / diff / rolling sums are
    counted in the group's own rows). None = from the start of the table."""
    levels = [c for c in ("broad_sector", "sector", "broad_industry", "industry") if c in master.columns]
    tax = master.drop_duplicates("symbol", keep="last")[["symbol", *levels]]
    con.register("_tax", tax)
    try:
        parts = " UNION ALL ".join(
            f"SELECT DISTINCT '{c}' AS lvl, CAST(t.{_q(c)} AS VARCHAR) AS grp, i.trade_date FROM indicators_daily i "
            f"JOIN _tax t USING (symbol) WHERE i.trade_date < ? AND t.{_q(c)} IS NOT NULL AND trim(CAST(t.{_q(c)} AS VARCHAR)) <> ''"
            for c in levels
        )
        value = con.execute(
            f"""SELECT min(trade_date) FROM (
                    SELECT trade_date, row_number() OVER (PARTITION BY lvl, grp ORDER BY trade_date DESC) AS rn FROM ({parts})
                ) WHERE rn <= {ROTATION_GROUP_ROWS}""",
            [since.to_pydatetime()] * len(levels),
        ).fetchone()[0]
    finally:
        con.unregister("_tax")
    return _ts(value) if value is not None else None


def _update_sector_rotation(con, master: pd.DataFrame, since: pd.Timestamp, date_dtype, *, full_recompute: bool, flipped: set) -> pd.DataFrame:
    """Recompute sector_rotation for dates >= ``since`` (with each group's lookback) and return
    those rows (the screener reads them)."""
    if full_recompute:
        rotation = bd.build_sector_rotation(read_slim(con, "indicators_daily", ROTATION_COLUMNS, date_dtype=date_dtype), master)
        _replace_table(con, "sector_rotation", rotation, ["CREATE INDEX IF NOT EXISTS idx_sector_rotation ON sector_rotation(level, group_name, trade_date)"])
        return rotation
    lo = _rotation_lookback_start(con, master, since)
    where, params = ("trade_date >= ?", [lo.to_pydatetime()]) if lo is not None else ("", [])
    frame = read_slim(con, "indicators_daily", ROTATION_COLUMNS, where=where, params=params, date_dtype=date_dtype)
    rotation = bd.build_sector_rotation(frame, master)
    del frame
    _replace_dates(con, "sector_rotation", rotation, since)
    if flipped:
        _refresh_leaders(con, master, flipped, date_dtype)
    return rotation[pd.to_datetime(rotation["trade_date"]) >= since] if not rotation.empty else rotation


def _refresh_leaders(con, master: pd.DataFrame, flipped: set, date_dtype) -> None:
    """leader_symbols uses today's market cap for every date: when a symbol crosses the Rs 1,000
    cr line, rewrite leader_symbols of its groups (all levels) over all dates."""
    levels = {"Broad Sector": "broad_sector", "Sector": "sector", "Broad Industry": "broad_industry", "Industry": "industry"}
    m = master.drop_duplicates("symbol", keep="last").set_index("symbol")
    for level, col in levels.items():
        if col not in m.columns:
            continue
        groups = {str(g) for g in m.loc[m.index.intersection(list(flipped)), col].dropna() if str(g).strip() != ""}
        if not groups:
            continue
        members = sorted(m.index[m[col].astype(str).isin(groups)].astype(str))
        con.register("_members", pd.DataFrame({"symbol": members}))
        try:
            rows = read_slim(con, "indicators_daily", ("symbol", "trade_date", "rs_percentile"),
                             where="symbol IN (SELECT symbol FROM _members)", date_dtype=date_dtype)
        finally:
            con.unregister("_members")
        d = rows.merge(master[["symbol", col, "market_cap_cr"]].drop_duplicates("symbol", keep="last"), on="symbol", how="left")
        d = d.dropna(subset=[col])
        d = d[d[col].astype(str).str.strip() != ""]
        leader_map = bd.leader_symbols_map(d, col)
        keys = d[["trade_date", col]].drop_duplicates().rename(columns={col: "group_name"})
        if leader_map is None:
            keys["leader_symbols"] = ""
        else:
            keys = keys.merge(leader_map.rename("leader_symbols").reset_index().rename(columns={col: "group_name"}), on=["trade_date", "group_name"], how="left")
            keys["leader_symbols"] = keys["leader_symbols"].fillna("")
        keys["level"] = level
        con.register("_leaders", keys)
        try:
            con.execute(
                "UPDATE sector_rotation SET leader_symbols = l.leader_symbols FROM _leaders l "
                "WHERE sector_rotation.level = l.level AND sector_rotation.group_name = l.group_name AND sector_rotation.trade_date = l.trade_date"
            )
        finally:
            con.unregister("_leaders")


def _update_sector_metrics(con, master, reference, index_features, deals, since: pd.Timestamp, date_dtype, *, full_recompute: bool) -> None:
    if full_recompute:
        frame = read_slim(con, "indicators_daily", METRICS_COLUMNS, date_dtype=date_dtype)
        metrics = bd.compute_sector_metrics(frame, master, reference, index_features, deals)
        _replace_table(con, "sector_metrics_daily", metrics, ["CREATE INDEX IF NOT EXISTS idx_sector_metrics ON sector_metrics_daily(level, group_name, trade_date)"])
        return
    cols = ", ".join(_q(c) for c in METRICS_COLUMNS if c in set(table_columns(con, "indicators_daily")))
    frame = con.execute(
        f"""
        WITH r AS (
            SELECT {cols},
                   count(*) FILTER (WHERE trade_date >= ?) OVER (PARTITION BY symbol) AS n_keep,
                   row_number() OVER (PARTITION BY symbol ORDER BY trade_date DESC) AS rn_desc
            FROM indicators_daily
        )
        SELECT {cols} FROM r WHERE n_keep > 0 AND rn_desc <= n_keep + {METRICS_LOOKBACK_ROWS}
        ORDER BY symbol, trade_date
        """,
        [since.to_pydatetime()],
    ).fetchdf()
    frame = match_datetime_units(frame, date_dtype)
    metrics = bd.compute_sector_metrics(frame, master, reference, index_features, deals)
    _replace_dates(con, "sector_metrics_daily", metrics, since)


# --------------------------------------------------------------------------------------------
# Derived tables (Scripts/derived) - fail-soft
# --------------------------------------------------------------------------------------------

def _derived_step(con, *, quiet: bool) -> None:
    """Rebuild the Scripts/derived tables in their own transaction; a failure is reported
    loudly but never undoes the committed price/indicator append."""
    try:
        import derived_tables_step
    except Exception as exc:  # pragma: no cover
        print(f"WARNING: derived tables not rebuilt ({exc})", flush=True)
        return
    derived_tables_step.rebuild_in_place(con, incremental=True, quiet=quiet)
