"""Research tab (HarkPro/10-tab-research.md §§3-13): shared plumbing for the evidence studies.

The studies (regime quadrant + analogs, setup scorecard, big-mover case studies, before-the-big-moves)
are ports of the round-1 study tools in HarkPro/tools/{regime_study,bigmove_study}. Their heavy parts
are precomputed by ``Scripts/research_lab.py`` into small ``research_*`` tables. The service reads them
from the market DB when the pipeline wrote them there, else from the sidecar file
``research_lab.duckdb`` next to the market DB (``MP_RESEARCH_DB_PATH`` overrides). When neither holds
a build for the current study end, the service computes the study in-process once per DB file
(fingerprint-keyed cache) - slow on the first call, fast after.

Point in time:
- Every trait / preset / regime reading uses data on or before its own session.
- ``study_end`` is the latest *good* session on or before as_of: a short tail of sessions after a long
  calendar gap (the local Aug-Oct 2026 hole) is dropped, because rolling windows across the gap are
  wrong. With a full archive the study end is simply the latest session.
- Outcomes (forward returns, runner / fizzle, breakout follow-through) are shown only when their
  window closed on or before as_of.
- Lists use stocks >= Rs 1,000 Cr by *today's* market cap (stocks_master), as the study tools did;
  as-of market cap is a known gap (HarkPro/05-data-gaps.md #7).
"""
from __future__ import annotations

import math
import os
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterator

import duckdb
import numpy as np
import pandas as pd

from App.services import db

MIN_MCAP_CR = 1000.0
BUILD_VERSION = 1
# A tail of fewer than TAIL_MIN sessions after a calendar gap of more than GAP_DAYS is not studied.
GAP_DAYS = 20
TAIL_MIN = 20

CAVEAT = ("Retrospective research, not advice. These studies use the local archive "
          "(about two years). Re-run them on the 5-year archive before you trust a threshold.")

FRAME_COLS = (
    "symbol", "trade_date", "series", "open_price", "high_price", "low_price", "close_price", "volume",
    "delivery_pct", "avg_delivery_pct_20d", "ema_10", "ema_20", "ema_50", "ema_100", "ema_200", "ema_200_rising",
    "sma_50", "sma_150", "sma_200", "sma_200_rising", "trend_template_pass", "trend_template_pass_n",
    "rs_percentile", "rs_rank_t30", "away_10ema_pct", "away_52w_high_pct", "away_52w_low_pct", "high_52w",
    "delivery_spike", "price_up_delivery_up", "nr7", "inside_bar", "rsi_14", "rsi_14_w", "rsi_14_m", "is_vcp",
    "rvol", "wema_10", "wema_20", "wma_30", "wema_200", "mema_10", "mema_200", "atr_pct", "atr_pct_avg_50d",
    "range_50d_pct", "range_20d_pct", "avg_traded_value_cr_20d",
)
BOOL_COLS = ("ema_200_rising", "sma_200_rising", "trend_template_pass", "delivery_spike", "price_up_delivery_up",
             "nr7", "inside_bar", "is_vcp")


# --------------------------------------------------------------------------
# JSON helpers
# --------------------------------------------------------------------------
def clean(v: Any) -> Any:
    """NaN / inf -> None, numpy scalars -> python, timestamps -> date."""
    if v is None:
        return None
    if isinstance(v, (pd.Timestamp,)):
        return None if pd.isna(v) else v.date()
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return f if math.isfinite(f) else None
    if v is pd.NaT:
        return None
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    return v


def rnd(v: Any, nd: int = 1) -> float | None:
    v = clean(v)
    if v is None or isinstance(v, bool):
        return None
    try:
        return round(float(v), nd)
    except (TypeError, ValueError):
        return None


def records(df: pd.DataFrame, nd: int | None = None) -> list[dict[str, Any]]:
    if nd is not None:
        num = df.select_dtypes(include="floating").columns
        if len(num):
            df = df.copy()
            df[num] = df[num].round(nd)
    cols = list(df.columns)
    return [{c: clean(v) for c, v in zip(cols, row)} for row in df.itertuples(index=False, name=None)]


# --------------------------------------------------------------------------
# Sessions / study end
# --------------------------------------------------------------------------
def sessions(con: Any) -> list[date]:
    def compute() -> list[date]:
        rows = con.execute("SELECT DISTINCT CAST(trade_date AS DATE) FROM indicators_daily ORDER BY 1").fetchall()
        return [r[0] for r in rows]
    return db.cached("research_sessions", (), compute)


def last_good_session(days: list[date]) -> date | None:
    """Latest session, unless it sits in a short tail after a long calendar gap (then the session before)."""
    if not days:
        return None
    end = len(days)
    while end > 1:
        tail_start = None
        for i in range(end - 1, 0, -1):
            if (days[i] - days[i - 1]).days > GAP_DAYS:
                tail_start = i
                break
        if tail_start is None or end - tail_start >= TAIL_MIN:
            break
        end = tail_start
    return days[end - 1]


def study_end(con: Any, as_of: date | None) -> date | None:
    days = sessions(con)
    if as_of is not None:
        days = [d for d in days if d <= as_of]
    return last_good_session(days)


def dropped_tail(con: Any, end: date | None) -> list[date]:
    """Sessions after the study end that exist in the DB (the gap tail)."""
    if end is None:
        return []
    return [d for d in sessions(con) if d > end]


def session_index(days: list[date], d: date) -> int:
    lo, hi = 0, len(days) - 1
    ans = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if days[mid] <= d:
            ans, lo = mid, mid + 1
        else:
            hi = mid - 1
    return ans


# --------------------------------------------------------------------------
# Frame (stocks >= 1,000 Cr, all sessions <= end)
# --------------------------------------------------------------------------
def load_frame(con: Any, end: date, cols: tuple[str, ...] = FRAME_COLS, symbols: list[str] | None = None,
               min_mcap_cr: float = MIN_MCAP_CR) -> pd.DataFrame:
    have = set(db.table_columns(con, "indicators_daily"))
    pick = [c for c in cols if c in have]
    sel = ", ".join(f"i.{db.quote_ident(c)}" for c in pick)
    where, params = ["i.trade_date <= ?"], [end]
    if symbols is not None:
        where.append("i.symbol IN (SELECT unnest(?))")
        params.append(list(symbols))
    else:
        where.append("m.market_cap_cr >= ?")
        params.append(float(min_mcap_cr))
    sql = (f"SELECT {sel}, m.security_name, m.industry, m.market_cap_cr AS mcap_now FROM indicators_daily i "
           f"JOIN stocks_master m USING (symbol) WHERE {' AND '.join(where)} ORDER BY i.symbol, i.trade_date")
    d = con.execute(sql, params).df()
    for c in cols:
        if c not in d.columns:
            d[c] = np.nan
    d["trade_date"] = pd.to_datetime(d["trade_date"])
    for c in BOOL_COLS:
        d[c] = d[c].astype("boolean").fillna(False).astype(bool)
    return d.reset_index(drop=True)


def frame(con: Any, end: date) -> pd.DataFrame:
    """The whole >= 1,000 Cr frame up to `end`, cached per DB file."""
    return db.cached("research_frame", (end,), lambda: load_frame(con, end))


# --------------------------------------------------------------------------
# Derived-table store (market DB, else sidecar)
# --------------------------------------------------------------------------
def sidecar_path() -> Path:
    env = os.environ.get("MP_RESEARCH_DB_PATH", "").strip()
    return Path(env) if env else db.market_db_path().parent / "research_lab.duckdb"


@contextmanager
def _sidecar() -> Iterator[Any]:
    path = sidecar_path()
    if not path.exists():
        yield None
        return
    try:
        con = duckdb.connect(str(path), read_only=True)
    except duckdb.Error:
        yield None
        return
    try:
        yield con
    finally:
        con.close()


def _meta_ok(con: Any, end: date) -> bool:
    if con is None or not db.table_exists(con, "research_lab_meta"):
        return False
    try:
        meta = dict(con.execute("SELECT key, value FROM research_lab_meta").fetchall())
    except duckdb.Error:
        return False
    return meta.get("version") == str(BUILD_VERSION) and meta.get("study_end") == end.isoformat()


def stored_table(market_con: Any, table: str, end: date) -> pd.DataFrame | None:
    """A prebuilt research table for this study end, or None. Cached per DB file."""
    def compute() -> pd.DataFrame | None:
        if _meta_ok(market_con, end) and db.table_exists(market_con, table):
            return market_con.execute(f"SELECT * FROM {db.quote_ident(table)}").df()
        with _sidecar() as side:
            if _meta_ok(side, end) and db.table_exists(side, table):
                return side.execute(f"SELECT * FROM {db.quote_ident(table)}").df()
        return None
    side = sidecar_path()
    try:
        st = side.stat()
        skey = f"{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        skey = "none"
    return db.cached("research_stored", (table, end, skey), compute)


def table_or_compute(market_con: Any, table: str, end: date, compute: Callable[[], pd.DataFrame]) -> tuple[pd.DataFrame, str]:
    """(frame, source): the prebuilt table if present, else the in-process computation (cached)."""
    got = stored_table(market_con, table, end)
    if got is not None:
        for c in got.columns:
            if "date" in c:
                got[c] = pd.to_datetime(got[c])
        return got, "prebuilt"
    return db.cached("research_live", (table, end), compute), "computed"


def deep_clean(v: Any) -> Any:
    """Recursively make a value JSON-safe (numpy scalars, NaN, timestamps, frames)."""
    if isinstance(v, dict):
        return {str(k): deep_clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [deep_clean(x) for x in v]
    if isinstance(v, np.ndarray):
        return [deep_clean(x) for x in v.tolist()]
    if isinstance(v, pd.DataFrame):
        return records(v)
    if isinstance(v, str) or v is None or isinstance(v, bool):
        return v
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return clean(v)


def memo(tag: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Cache a study endpoint's Result per DB file (and sidecar file) and arguments; returns a copy."""
    import dataclasses
    import functools

    def wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def inner(*args: Any) -> Any:
            side = sidecar_path()
            try:
                st = side.stat()
                skey = f"{st.st_mtime_ns}:{st.st_size}"
            except OSError:
                skey = "none"
            res = db.cached("research_result:" + tag, (skey, *args), lambda: fn(*args))
            return dataclasses.replace(res, rows=list(res.rows), extra=dict(res.extra))
        inner.uncached = fn  # type: ignore[attr-defined]
        return inner
    return wrap
