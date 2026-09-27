"""Shared helpers for the derived-table builders (point-in-time, vectorised).

Everything here is causal: a value on session t only uses rows dated <= t.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

# Canonical index names in index_daily (ind_close_all naming), with aliases seen in older files.
NIFTY50 = "Nifty 50"
MIDSML400 = "NIFTY MIDSML 400"
INDIA_VIX = "India VIX"
INDEX_ALIASES: dict[str, tuple[str, ...]] = {
    NIFTY50: ("Nifty 50", "NIFTY 50", "NIFTY"),
    MIDSML400: ("NIFTY MIDSML 400", "Nifty MidSmallcap 400", "NIFTY MIDSMALLCAP 400", "Nifty MidSml 400"),
    INDIA_VIX: ("India VIX", "INDIA VIX"),
}

# Non-security aggregate rows that must never enter a builder (spec §4.4).
NON_SECURITY_SYMBOLS = frozenset({"TOTAL", "GRAND TOTAL", ""})

# New 52W high/low validity: a symbol needs more than this many own sessions of history when
# the prior row carries no official NSE 52W snapshot (high_52w_date NULL); otherwise the
# fallback high_252d is a partial window and would overcount "new highs".
MIN_SESSIONS_FOR_52W = 252
# A session's new-high/new-low counts are published only when at least this share of rows is valid.
MIN_VALID_SHARE_52W = 0.5


def normalise_dates(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce").dt.normalize()


def clean_symbols(frame: pd.DataFrame, col: str = "symbol") -> pd.DataFrame:
    """Upper-case/strip symbols and drop aggregate rows such as TOTAL (cleans uniques only)."""
    if frame is None or frame.empty or col not in frame.columns:
        return frame
    codes, uniques = pd.factorize(frame[col], use_na_sentinel=True)
    clean = pd.Index(uniques).astype(str).str.strip().str.upper()
    bad = clean.isin(NON_SECURITY_SYMBOLS)
    keep = (codes >= 0) & ~np.asarray(bad)[np.where(codes >= 0, codes, 0)]
    out = frame.loc[keep].copy()
    out[col] = np.asarray(clean, dtype=object)[codes[keep]]
    return out


def num(frame: pd.DataFrame, col: str) -> pd.Series:
    """Numeric column (float) or an all-NaN series when absent."""
    if col in frame.columns:
        return pd.to_numeric(frame[col], errors="coerce").astype(float)
    return pd.Series(np.nan, index=frame.index, dtype=float)


def boolcol(frame: pd.DataFrame, col: str) -> pd.Series:
    """Boolean column as float 1/0 with NaN for NULL (so sums/means skip unknowns)."""
    if col not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    s = frame[col]
    out = pd.Series(np.nan, index=frame.index, dtype=float)
    known = s.notna().to_numpy()
    out[known] = s[known].astype(bool).astype(float).to_numpy()
    return out


def prep_indicators(indicators: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    """Copy of the needed indicator columns, cleaned and sorted by (symbol, trade_date)."""
    wanted = ["symbol", "trade_date", *[c for c in columns if c not in ("symbol", "trade_date")]]
    present = [c for c in dict.fromkeys(wanted) if c in indicators.columns]
    out = indicators[present].copy()
    out = clean_symbols(out)
    out["trade_date"] = normalise_dates(out["trade_date"])
    out = out.dropna(subset=["trade_date"])
    out = out.drop_duplicates(["symbol", "trade_date"], keep="last")
    out = out.sort_values(["symbol", "trade_date"], kind="mergesort").reset_index(drop=True)
    return out


def index_series(index_daily: pd.DataFrame | None, canonical: str) -> pd.DataFrame:
    """One index's rows (date-indexed, sorted): close_price, turnover_cr, volume. Empty if absent."""
    cols = ["close_price", "turnover_cr", "volume"]
    empty = pd.DataFrame(columns=cols, index=pd.DatetimeIndex([], name="trade_date"), dtype=float)
    if index_daily is None or index_daily.empty or "index_name" not in index_daily.columns:
        return empty
    names = index_daily["index_name"].astype("string").str.strip().str.upper()
    aliases = {a.upper() for a in INDEX_ALIASES.get(canonical, (canonical,))}
    sub = index_daily.loc[names.isin(aliases).to_numpy(dtype=bool)].copy()
    if sub.empty:
        return empty
    out = pd.DataFrame(
        {
            "trade_date": normalise_dates(sub["trade_date"]),
            "close_price": num(sub, "close_price"),
            "turnover_cr": num(sub, "turnover_cr"),
            "volume": num(sub, "volume"),
        }
    )
    out = out.dropna(subset=["trade_date"]).sort_values("trade_date")
    out = out.drop_duplicates("trade_date", keep="last").set_index("trade_date")
    return out


def ema(series: pd.Series, span: int) -> pd.Series:
    """Causal EMA (adjust=False); NULL until `span` observations exist."""
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def new_high_low_flags(ind: pd.DataFrame) -> pd.DataFrame:
    """Per-row official new 52W high / low flags (float 1/0, NaN when not determinable).

    Source: indicators_daily.high_52w / low_52w, which the EOD build fills point-in-time from
    NSE's official 52W snapshots (CM_52_wk_High_low / PR `hl`, via security_reference_daily,
    as-of join, never future) with a trailing 252-session fallback where no snapshot exists.
    A new high on t is high_t > the symbol's high_52w as of the PREVIOUS session (today's bar is
    never compared with a 52W value that may already contain it); new low mirrors with low_52w.
    A row is valid only if the prior value exists and either came from an official snapshot
    (high_52w_date not NULL on the prior row) or the symbol has > 252 own sessions of history.
    Without high_52w/low_52w columns a 252-session rolling max/min of high/low is used.
    `ind` must be sorted by (symbol, trade_date).
    """
    sym = ind["symbol"]
    high = num(ind, "high_price")
    low = num(ind, "low_price")
    n_hist = ind.groupby("symbol", sort=False).cumcount() + 1
    if "high_52w" in ind.columns and "low_52w" in ind.columns:
        prior_hi = num(ind, "high_52w").groupby(sym, sort=False).shift(1)
        prior_lo = num(ind, "low_52w").groupby(sym, sort=False).shift(1)
        if "high_52w_date" in ind.columns:
            off = ind["high_52w_date"].notna().astype(float).groupby(sym, sort=False).shift(1)
            official_prev = off.fillna(0.0).astype(bool)
        else:
            official_prev = pd.Series(False, index=ind.index)
        valid = prior_hi.notna() & prior_lo.notna() & (official_prev | (n_hist > MIN_SESSIONS_FOR_52W))
    else:
        w = MIN_SESSIONS_FOR_52W
        hi_roll = high.groupby(sym, sort=False).rolling(w, min_periods=w).max().reset_index(level=0, drop=True)
        lo_roll = low.groupby(sym, sort=False).rolling(w, min_periods=w).min().reset_index(level=0, drop=True)
        prior_hi = hi_roll.sort_index().groupby(sym, sort=False).shift(1)
        prior_lo = lo_roll.sort_index().groupby(sym, sort=False).shift(1)
        valid = prior_hi.notna() & prior_lo.notna()
    valid = (valid & high.notna() & low.notna()).to_numpy(dtype=bool)
    nh = np.where(valid, (high > prior_hi).to_numpy(dtype=float), np.nan)
    nl = np.where(valid, (low < prior_lo).to_numpy(dtype=float), np.nan)
    return pd.DataFrame({"new_high": nh, "new_low": nl, "valid_52w": valid}, index=ind.index)


def sign_dir(delta: pd.Series, tol: float) -> pd.Series:
    """'improving' / 'deteriorating' / 'flat' from a goodness-oriented change; NULL stays NULL."""
    out = pd.Series(None, index=delta.index, dtype="object")
    d = delta.to_numpy(dtype=float)
    out[d > tol] = "improving"
    out[d < -tol] = "deteriorating"
    out[np.abs(d) <= tol] = "flat"
    return out


def fmt(x, nd: int = 1, suffix: str = "") -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "n/a"
    if not np.isfinite(v):
        return "n/a"
    return f"{v:.{nd}f}{suffix}"


def fmt_signed(x, nd: int = 1, suffix: str = "") -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "n/a"
    if not np.isfinite(v):
        return "n/a"
    return f"{v:+.{nd}f}{suffix}"
