"""Shared helpers for the evidence engine (spec §5): constants, point-in-time mcap,
environment / group-state joins, sample-size labelling, purged splits.

Conventions
- Dates are pandas Timestamps at midnight (session date).
- Percent columns are percent units (12.5 = 12.5 %). Money is ₹ crore.
- NULL (NaN) means unknown; nothing here substitutes a default.
- "Point-in-time": a value stamped t only uses rows dated <= t.
"""
from __future__ import annotations

import json
import math
from typing import Any, Iterable

import numpy as np
import pandas as pd

MIN_SAMPLE = 30
INSUFFICIENT = "insufficient sample"
MCAP_FLOOR_CR = 1000.0
LEVELS = ("Broad Sector", "Sector", "Broad Industry", "Industry")
LEVEL_COLS = {"Broad Sector": "broad_sector", "Sector": "sector", "Broad Industry": "broad_industry", "Industry": "industry"}
VERDICT_ORDER = {"Danger": 0, "Weak": 1, "Mixed": 2, "Constructive": 3, "Favourable": 4}
QUADRANT_ORDER = {"Lagging": 0, "Weakening": 1, "Improving": 2, "Leading": 3}


def ts(value: Any) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


def to_ts_col(frame: pd.DataFrame, col: str) -> pd.DataFrame:
    if col in frame.columns:
        frame[col] = pd.to_datetime(frame[col]).dt.normalize().astype("datetime64[ns]")
    return frame


def num(frame: pd.DataFrame, col: str) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[col], errors="coerce").astype("float64")


def sample_label(n: int) -> str | None:
    return None if n >= MIN_SAMPLE else INSUFFICIENT


def fmt_json(value: Any) -> str:
    def _clean(v: Any) -> Any:
        if isinstance(v, float) and not math.isfinite(v):
            return None
        if isinstance(v, (np.floating,)):
            return None if not np.isfinite(v) else round(float(v), 4)
        if isinstance(v, (np.integer,)):
            return int(v)
        if isinstance(v, (pd.Timestamp,)):
            return v.date().isoformat()
        if isinstance(v, dict):
            return {k: _clean(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [_clean(x) for x in v]
        return v
    return json.dumps(_clean(value), separators=(",", ":"))


# --------------------------------------------------------------------------
# Point-in-time market cap
# --------------------------------------------------------------------------
def pit_mcap(
    rows: pd.DataFrame,
    *,
    pr_mcap: pd.DataFrame | None = None,
    reference: pd.DataFrame | None = None,
    master: pd.DataFrame | None = None,
    max_age_days: int = 10,
) -> pd.DataFrame:
    """Market cap (₹ Cr) for (symbol, trade_date, close_price) rows, as of each date.

    Priority (column ``mcap_basis``):
      1. ``pr_mcap``            — PR-zip MCAP file of that session or the latest one <= t within max_age_days.
      2. ``reference_asof``     — security_reference_daily.market_cap_cr, latest effective_date <= t within max_age_days.
      3. ``price_scaled_current`` — stocks_master mcap × close_t / close on the master's reference row.
         Uses today's share count: NOT point-in-time (documented fallback).
    Returns the rows with ``mcap_cr`` and ``mcap_basis`` added (index preserved).
    """
    out = rows[["symbol", "trade_date", "close_price"]].copy()
    out["_i"] = np.arange(len(out))
    out["mcap_cr"] = np.nan
    out["mcap_basis"] = pd.Series([None] * len(out), dtype="object")
    tol = pd.Timedelta(days=max_age_days)

    def _asof(src: pd.DataFrame, date_col: str, label: str) -> None:
        if src is None or src.empty:
            return
        s = src[["symbol", date_col, "mcap_cr"]].dropna().copy()
        s = to_ts_col(s, date_col).sort_values(date_col)
        s["symbol"] = s["symbol"].astype(str)
        need = out.loc[out["mcap_cr"].isna(), ["_i", "symbol", "trade_date"]].copy()
        if need.empty:
            return
        need["symbol"] = need["symbol"].astype(str)
        need = need.sort_values("trade_date")
        m = pd.merge_asof(need, s.rename(columns={date_col: "_d"}), left_on="trade_date", right_on="_d",
                          by="symbol", direction="backward", tolerance=tol)
        m = m.dropna(subset=["mcap_cr"])
        out.loc[m["_i"].to_numpy(), "mcap_cr"] = m["mcap_cr"].to_numpy()
        out.loc[m["_i"].to_numpy(), "mcap_basis"] = label

    if pr_mcap is not None and not pr_mcap.empty:
        _asof(pr_mcap, "trade_date", "pr_mcap")
    if reference is not None and not reference.empty and "market_cap_cr" in reference.columns:
        _asof(reference.rename(columns={"market_cap_cr": "mcap_cr"}), "effective_date", "reference_asof")
    if master is not None and not master.empty and "market_cap_cr" in master.columns:
        need = out["mcap_cr"].isna()
        if need.any():
            last_close = (out.sort_values("trade_date").groupby("symbol")["close_price"].last())
            mc = master.set_index("symbol")["market_cap_cr"].astype("float64")
            sym = out.loc[need, "symbol"]
            base_mcap = sym.map(mc).astype("float64")
            base_close = sym.map(last_close).astype("float64")
            scaled = base_mcap * out.loc[need, "close_price"].astype("float64") / base_close
            ok = scaled.notna() & np.isfinite(scaled)
            idx = scaled.index[ok]
            out.loc[idx, "mcap_cr"] = scaled[ok]
            out.loc[idx, "mcap_basis"] = "price_scaled_current"
    return out.drop(columns=["_i"])


def mcap_basis_summary(frame: pd.DataFrame) -> dict[str, int]:
    if "mcap_basis" not in frame.columns:
        return {}
    return {str(k): int(v) for k, v in frame["mcap_basis"].fillna("none").value_counts().items()}


# --------------------------------------------------------------------------
# Environment state and group state
# --------------------------------------------------------------------------
def environment_states(regime: pd.DataFrame | None, breadth: pd.DataFrame | None) -> pd.DataFrame:
    """(trade_date, environment_state, env_source). regime_daily.verdict preferred; else
    breadth_daily.breadth_state (a coarser, older label) so aggregates exist before regime_daily lands."""
    if regime is not None and not regime.empty and "verdict" in regime.columns:
        e = regime[["trade_date", "verdict"]].rename(columns={"verdict": "environment_state"}).copy()
        e["env_source"] = "regime_daily.verdict"
    elif breadth is not None and not breadth.empty and "breadth_state" in breadth.columns:
        e = breadth[["trade_date", "breadth_state"]].rename(columns={"breadth_state": "environment_state"}).copy()
        e["env_source"] = "breadth_daily.breadth_state"
    else:
        return pd.DataFrame(columns=["trade_date", "environment_state", "env_source"])
    e = to_ts_col(e, "trade_date")
    e["environment_state"] = e["environment_state"].astype("object").where(e["environment_state"].notna(), None)
    return e.drop_duplicates("trade_date")


def group_states(group_daily: pd.DataFrame | None, rotation: pd.DataFrame | None, level: str = "Industry") -> pd.DataFrame:
    """(trade_date, group_name, group_quadrant, quadrant_source) at one taxonomy level.
    group_daily.rrg_quadrant (floor 'all') preferred; else sector_rotation.rotation_state."""
    if group_daily is not None and not group_daily.empty and "rrg_quadrant" in group_daily.columns:
        g = group_daily
        if "floor" in g.columns:
            g = g.loc[g["floor"].astype(str) == "all"]
        g = g.loc[g["level"].astype(str) == level, ["trade_date", "group_name", "rrg_quadrant"]].rename(
            columns={"rrg_quadrant": "group_quadrant"}).copy()
        g["quadrant_source"] = "group_daily.rrg_quadrant"
    elif rotation is not None and not rotation.empty and "rotation_state" in rotation.columns:
        g = rotation.loc[rotation["level"].astype(str) == level, ["trade_date", "group_name", "rotation_state"]].rename(
            columns={"rotation_state": "group_quadrant"}).copy()
        g["quadrant_source"] = "sector_rotation.rotation_state"
    else:
        return pd.DataFrame(columns=["trade_date", "group_name", "group_quadrant", "quadrant_source"])
    g = to_ts_col(g, "trade_date")
    g["group_quadrant"] = g["group_quadrant"].astype("object").where(g["group_quadrant"].notna() & (g["group_quadrant"].astype(str) != ""), None)
    return g.drop_duplicates(["trade_date", "group_name"])


def attach_context(frame: pd.DataFrame, date_col: str, env: pd.DataFrame, groups: pd.DataFrame,
                   master: pd.DataFrame | None) -> pd.DataFrame:
    """Add taxonomy (current mapping), environment_state and group_quadrant (Industry) as of date_col."""
    out = frame.copy()
    if master is not None and not master.empty:
        tax = master[["symbol", *[c for c in LEVEL_COLS.values() if c in master.columns]]].drop_duplicates("symbol")
        out = out.drop(columns=[c for c in LEVEL_COLS.values() if c in out.columns]).merge(tax, on="symbol", how="left")
    if not env.empty:
        out = out.merge(env.rename(columns={"trade_date": date_col}), on=date_col, how="left")
    else:
        out["environment_state"], out["env_source"] = None, None
    if not groups.empty and "industry" in out.columns:
        out = out.merge(groups.rename(columns={"trade_date": date_col, "group_name": "industry"}),
                        on=[date_col, "industry"], how="left")
    else:
        out["group_quadrant"], out["quadrant_source"] = None, None
    return out


# --------------------------------------------------------------------------
# Study hygiene
# --------------------------------------------------------------------------
def purged_split(dates: pd.Series, *, test_frac: float = 0.4, embargo_sessions: int = 60,
                 sessions: Iterable[Any] | None = None) -> tuple[pd.Series, pd.Series, pd.Timestamp | None]:
    """Chronological train/test split with a purge gap.

    The last ``test_frac`` of sessions is test; the ``embargo_sessions`` sessions just before the
    test start are dropped from train (labels look up to 60 sessions ahead, so a train row inside
    the gap would overlap the test period). Returns boolean masks (train, test) and the test start.
    """
    d = pd.to_datetime(dates)
    sess = pd.Series(sorted(pd.to_datetime(pd.Series(list(sessions))).unique())) if sessions is not None else \
        pd.Series(sorted(d.dropna().unique()))
    if len(sess) < embargo_sessions + 20:
        return pd.Series(False, index=dates.index), pd.Series(False, index=dates.index), None
    cut_i = int(len(sess) * (1 - test_frac))
    test_start = pd.Timestamp(sess.iloc[cut_i])
    purge_start = pd.Timestamp(sess.iloc[max(0, cut_i - embargo_sessions)])
    train = d < purge_start
    test = d >= test_start
    return train, test, test_start


def max_drawdown_r(r_values: Iterable[float]) -> float | None:
    """Max peak-to-trough drawdown of cumulative R (trades in signal order), in R."""
    arr = np.asarray([x for x in r_values if x is not None and np.isfinite(x)], dtype=float)
    if arr.size == 0:
        return None
    eq = np.concatenate([[0.0], np.cumsum(arr)])
    peak = np.maximum.accumulate(eq)
    return float(np.max(peak - eq))


# --------------------------------------------------------------------------
# Fast per-symbol rolling windows
# --------------------------------------------------------------------------
def grolling(values: Any, codes: np.ndarray, window: int, how: str, min_periods: int | None = None,
             reverse: bool = False) -> np.ndarray:
    """Rolling max/min/sum/mean within contiguous groups (rows sorted by group), equal to
    ``s.groupby(codes).transform(lambda x: x.rolling(window, min_periods).<how>())`` but vectorised:
    roll over the whole array, then recompute the first window−1 rows of every group as an expanding
    aggregate of that group. ``reverse=True`` rolls over the rows t … t+window−1 instead."""
    v = np.asarray(values, dtype=float)
    c = np.asarray(codes)
    mp = window if min_periods is None else int(min_periods)
    if reverse:
        return grolling(v[::-1], c[::-1], window, how, mp)[::-1].copy()
    s = pd.Series(v)
    full = getattr(s.rolling(window, min_periods=mp), how)().to_numpy().copy()
    start = np.r_[True, c[1:] != c[:-1]]
    gid = np.cumsum(start) - 1
    first_pos = np.flatnonzero(start)
    rig = np.arange(len(v)) - first_pos[gid]
    head = rig < window - 1
    if head.any():
        fin = np.isfinite(v)
        cnt = pd.Series(fin.astype(np.int64)).groupby(gid).cumsum().to_numpy()
        if how == "max":
            exp = pd.Series(np.where(fin, v, -np.inf)).groupby(gid).cummax().to_numpy()
        elif how == "min":
            exp = pd.Series(np.where(fin, v, np.inf)).groupby(gid).cummin().to_numpy()
        elif how in ("sum", "mean"):
            exp = pd.Series(np.where(fin, v, 0.0)).groupby(gid).cumsum().to_numpy()
            if how == "mean":
                with np.errstate(invalid="ignore", divide="ignore"):
                    exp = exp / cnt
        else:  # pragma: no cover
            raise ValueError(how)
        exp = np.where(cnt >= max(mp, 1), exp, np.nan)
        if how == "sum" and mp == 0:
            exp = np.where(cnt >= 0, exp, np.nan)
        full[head] = exp[head]
    return full
