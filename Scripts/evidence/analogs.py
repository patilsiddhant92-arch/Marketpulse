"""Market analogs and stock analogs (spec §5, §7.6).

Market analogs
--------------
Daily environment vector (one row per session, all inputs dated <= t):

  above_10ema_pct, above_50ema_pct, above_200ema_pct         breadth_daily
  advance_pct_5d_avg, advance_pct_20d_avg                    breadth_daily (A/D)
  net_new_highs_pct                                          indicators: (#high >= 252d high - #low <= 252d low) / valid × 100
  midsml_vs_ema50_pct, midsml_vs_ema200_pct, midsml_ret_5d, midsml_ret_20d   NIFTY MIDSML 400 (EMAs on its own history)
  nifty_vs_ema50_pct, nifty_vs_ema200_pct, nifty_ret_20d     Nifty 50
  vix, vix_chg_5d_pct                                        India VIX
  follow_through_pct                                         breakouts (close > prior 20-day high on RVOL >= 1.5) in t-10…t-3
                                                             still above their breakout close on t; NULL if < 10 breakouts

Standardisation is point-in-time: for a query date t, every vector is z-scored with the mean/std of
the vectors dated <= t (expanding, >= 60 sessions). k-NN (k = 10, Euclidean) over candidate dates s
with s <= t - 60 sessions (excludes the most recent 60 sessions, which also guarantees the analog's
60-session forward return is known on t). Rows need a complete vector (follow-through may be NULL:
it is then left out of that query's distance for all candidates).

Stored per analog: forward MidSml400 5/20/60-session return and next-month follow-through
(mean follow_through_pct over s+1…s+21), plus regime verdict on s when regime_daily exists.

Stock analogs
-------------
`stock_analogs(pool, query, k)` — nearest past setups of the same queue on (base depth, strength rank,
RVOL, group quadrant, environment), z-scored on the candidate pool; only setups resolved before the
query date are candidates. Returns neighbours and the outcome distribution (n printed; n < 30 flagged).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .common import INSUFFICIENT, MIN_SAMPLE, QUADRANT_ORDER, VERDICT_ORDER, grolling, gshift, to_ts_col

K_ANALOGS = 10
EXCLUDE_RECENT = 60
MIN_STD_HISTORY = 60
ENV_FEATURES = [
    "above_10ema_pct", "above_50ema_pct", "above_200ema_pct", "advance_pct_5d_avg", "advance_pct_20d_avg",
    "net_new_highs_pct", "midsml_vs_ema50_pct", "midsml_vs_ema200_pct", "midsml_ret_5d", "midsml_ret_20d",
    "nifty_vs_ema50_pct", "nifty_vs_ema200_pct", "nifty_ret_20d", "vix", "vix_chg_5d_pct", "follow_through_pct",
]
OPTIONAL_FEATURES = {"follow_through_pct"}


def follow_through_series(ind: pd.DataFrame, lo: int = 3, hi: int = 10, min_breakouts: int = 10) -> pd.DataFrame:
    """(trade_date, breakouts_n, breakouts_holding, follow_through_pct) from indicators rows sorted by symbol/date."""
    d = ind[["symbol", "trade_date", "close_price", "high_price", "rvol"]].sort_values(["symbol", "trade_date"])
    codes = pd.factorize(d["symbol"].to_numpy())[0]
    prior_hi20 = grolling(gshift(d["high_price"].to_numpy(float), codes, 1), codes, 20, "max", 20)
    brk = (d["close_price"] > prior_hi20) & (pd.to_numeric(d["rvol"], errors="coerce") >= 1.5)
    n = np.zeros(len(d))
    hold = np.zeros(len(d))
    for j in range(lo, hi + 1):
        b = np.nan_to_num(gshift(brk.to_numpy(float), codes, j), nan=0).astype(bool)
        cj = gshift(d["close_price"].to_numpy(float), codes, j)
        n += b
        hold += b & (d["close_price"].to_numpy(float) > cj)
    agg = pd.DataFrame({"trade_date": d["trade_date"].to_numpy(), "n": n, "h": hold}).groupby("trade_date").sum()
    agg["follow_through_pct"] = np.where(agg["n"] >= min_breakouts, agg["h"] / agg["n"].where(agg["n"] > 0) * 100, np.nan)
    return agg.rename(columns={"n": "breakouts_n", "h": "breakouts_holding"}).reset_index()


def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False, min_periods=span).mean()


def environment_vectors(ind: pd.DataFrame, breadth: pd.DataFrame | None, index_daily: pd.DataFrame,
                        sessions: pd.Series) -> pd.DataFrame:
    """One row per market session with ENV_FEATURES (NaN where unknown) plus MidSml400 close."""
    out = pd.DataFrame({"trade_date": pd.to_datetime(pd.Series(sorted(pd.unique(sessions))))})
    if breadth is not None and not breadth.empty:
        cols = [c for c in ENV_FEATURES[:5] if c in breadth.columns]
        out = out.merge(breadth[["trade_date", *cols]], on="trade_date", how="left")
    for c in ENV_FEATURES[:5]:
        if c not in out.columns:
            out[c] = np.nan
    hi252 = pd.to_numeric(ind["high_252d"], errors="coerce")
    lo252 = pd.to_numeric(ind["low_252d"], errors="coerce")
    nh = (ind["high_price"] >= hi252) & hi252.notna()
    nl = (ind["low_price"] <= lo252) & lo252.notna()
    hl = pd.DataFrame({"trade_date": ind["trade_date"], "nh": nh, "nl": nl, "v": hi252.notna() & lo252.notna()}).groupby(
        "trade_date").sum()
    hl["net_new_highs_pct"] = (hl["nh"] - hl["nl"]) / hl["v"].where(hl["v"] > 0) * 100
    out = out.merge(hl[["net_new_highs_pct"]].reset_index(), on="trade_date", how="left")
    idx = index_daily.copy()
    for key, name in (("midsml", "NIFTY MIDSML 400"), ("nifty", "Nifty 50"), ("vix", "India VIX")):
        s = idx.loc[idx["index_name"] == name, ["trade_date", "close_price"]].drop_duplicates("trade_date").sort_values("trade_date")
        c = pd.to_numeric(s["close_price"], errors="coerce").reset_index(drop=True)
        f = pd.DataFrame({"trade_date": s["trade_date"].to_numpy()})
        if key == "vix":
            f["vix"] = c
            f["vix_chg_5d_pct"] = (c / c.shift(5) - 1) * 100
        else:
            f[f"{key}_close"] = c
            f[f"{key}_vs_ema50_pct"] = (c / _ema(c, 50) - 1) * 100
            f[f"{key}_vs_ema200_pct"] = (c / _ema(c, 200) - 1) * 100
            f[f"{key}_ret_20d"] = (c / c.shift(20) - 1) * 100
            if key == "midsml":
                f["midsml_ret_5d"] = (c / c.shift(5) - 1) * 100
                for h in (5, 20, 60):
                    f[f"fwd_midsml400_{h}d_pct"] = (c.shift(-h) / c - 1) * 100
        out = out.merge(f, on="trade_date", how="left")
    ft = follow_through_series(ind)
    out = out.merge(ft, on="trade_date", how="left")
    fts = out["follow_through_pct"]
    # next-month follow-through: mean over s+1 … s+21 sessions (future; used only as an analog's outcome)
    out["next_month_follow_through_pct"] = fts[::-1].rolling(21, min_periods=10).mean()[::-1].shift(-1)
    return out


def market_analogs(env: pd.DataFrame, k: int = K_ANALOGS, exclude_recent: int = EXCLUDE_RECENT,
                   min_history: int = MIN_STD_HISTORY, verdicts: pd.DataFrame | None = None,
                   query_dates: list | None = None) -> pd.DataFrame:
    """k nearest past sessions for every query session (see module docstring)."""
    e = env.sort_values("trade_date").reset_index(drop=True)
    X = e[ENV_FEATURES].to_numpy(float)
    core = [i for i, f in enumerate(ENV_FEATURES) if f not in OPTIONAL_FEATURES]
    complete_core = np.isfinite(X[:, core]).all(axis=1)
    dates = e["trade_date"].to_numpy()
    vmap = {}
    if verdicts is not None and not verdicts.empty:
        vmap = dict(zip(pd.to_datetime(verdicts["trade_date"]), verdicts["environment_state"]))
    csum = np.nancumsum(np.nan_to_num(X), axis=0)
    csq = np.nancumsum(np.nan_to_num(X) ** 2, axis=0)
    cnt = np.cumsum(np.isfinite(X), axis=0)
    wanted = set(pd.to_datetime(query_dates)) if query_dates is not None else None
    recs = []
    for t in range(len(e)):
        if wanted is not None and pd.Timestamp(dates[t]) not in wanted:
            continue
        if not complete_core[t] or t - exclude_recent < 0:
            continue
        n = cnt[t]
        if n[core].min() < min_history:
            continue
        with np.errstate(invalid="ignore", divide="ignore"):
            mu = csum[t] / n
            sd = np.sqrt(np.maximum(csq[t] / n - mu ** 2, 0) * n / np.maximum(n - 1, 1))
        feats = [i for i in range(len(ENV_FEATURES)) if np.isfinite(X[t, i]) and sd[i] > 0 and n[i] >= min_history]
        last = t - exclude_recent
        cand = np.arange(0, last + 1)
        cand = cand[np.isfinite(X[cand][:, feats]).all(axis=1)]
        if len(cand) < k:
            continue
        Z = (X[cand][:, feats] - mu[feats]) / sd[feats]
        zq = (X[t, feats] - mu[feats]) / sd[feats]
        dist = np.sqrt(((Z - zq) ** 2).sum(axis=1) / len(feats))
        order = np.argsort(dist, kind="stable")[:k]
        for rank, j in enumerate(order, start=1):
            s = cand[j]
            recs.append({
                "as_of_date": dates[t], "rank": rank, "analog_date": dates[s], "distance": float(dist[j]),
                "fwd_midsml400_5d_pct": e.at[s, "fwd_midsml400_5d_pct"],
                "fwd_midsml400_20d_pct": e.at[s, "fwd_midsml400_20d_pct"],
                "fwd_midsml400_60d_pct": e.at[s, "fwd_midsml400_60d_pct"],
                "next_month_follow_through_pct": e.at[s, "next_month_follow_through_pct"],
                "verdict_then": vmap.get(pd.Timestamp(dates[s])),
                "n_candidates": int(len(cand)), "n_features": int(len(feats)), "k": k,
            })
    cols = ["as_of_date", "rank", "analog_date", "distance", "fwd_midsml400_5d_pct", "fwd_midsml400_20d_pct",
            "fwd_midsml400_60d_pct", "next_month_follow_through_pct", "verdict_then", "n_candidates", "n_features", "k"]
    out = pd.DataFrame(recs, columns=cols)
    return to_ts_col(to_ts_col(out, "as_of_date"), "analog_date")


def analog_validation(analogs: pd.DataFrame, env: pd.DataFrame) -> pd.DataFrame:
    """Out-of-sample check: does the analog mean forward return predict the realised one? One row per horizon."""
    if analogs.empty:
        return pd.DataFrame(columns=["horizon", "n", "corr", "sign_agreement_pct", "label"])
    realised = env.set_index("trade_date")
    recs = []
    for h in (5, 20, 60):
        col = f"fwd_midsml400_{h}d_pct"
        m = analogs.groupby("as_of_date")[col].mean()
        r = realised[col].reindex(m.index)
        ok = m.notna() & r.notna()
        n = int(ok.sum())
        recs.append({"horizon": f"{h}d", "n": n,
                     "corr": round(float(np.corrcoef(m[ok], r[ok])[0, 1]), 3) if n >= MIN_SAMPLE else None,
                     "sign_agreement_pct": round(float((np.sign(m[ok]) == np.sign(r[ok])).mean() * 100), 1) if n >= MIN_SAMPLE else None,
                     "label": None if n >= MIN_SAMPLE else INSUFFICIENT,
                     "note": "overlapping query dates (serially correlated); n counts query sessions"})
    return pd.DataFrame(recs)


def analog_summary(rows: list[dict] | pd.DataFrame, agree_share: float = 0.7) -> dict:
    """Spread and agreement of the analogs' forward 20-session returns (used by the API)."""
    df = pd.DataFrame(rows)
    col = "fwd_midsml400_20d_pct"
    if df.empty or col not in df.columns:
        return {"n": 0, "agreement": None}
    v = pd.to_numeric(df[col], errors="coerce").dropna()
    if v.empty:
        return {"n": 0, "agreement": None}
    pos = float((v > 0).mean())
    agree = pos >= agree_share or pos <= 1 - agree_share
    return {"n": int(len(v)), "mean_20d_pct": round(float(v.mean()), 2), "median_20d_pct": round(float(v.median()), 2),
            "min_20d_pct": round(float(v.min()), 2), "max_20d_pct": round(float(v.max()), 2),
            "positive_share_pct": round(pos * 100, 1), "agreement": bool(agree),
            "warning": None if agree else "Analogs disagree: fewer than 70% point the same way over 20 sessions."}


# --------------------------------------------------------------------------
# Stock analogs
# --------------------------------------------------------------------------
STOCK_ANALOG_FEATURES = ["base_depth_pct", "rs_percentile", "rvol", "group_quadrant_ord", "environment_ord"]


def add_analog_ordinals(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    q = out.get("group_quadrant")
    out["group_quadrant_ord"] = q.map(QUADRANT_ORDER).astype(float) if q is not None else np.nan
    v = out.get("environment_state")
    out["environment_ord"] = v.map(VERDICT_ORDER).astype(float) if v is not None else np.nan
    return out


def stock_analogs(pool: pd.DataFrame, query: dict, k: int = 30) -> tuple[pd.DataFrame, dict]:
    """Nearest resolved setups of the same queue. `pool` = setup_outcomes rows (already filtered to
    exit_date < query date and the same queue). NaN features are imputed at the pool mean (z = 0)."""
    feats = [f for f in STOCK_ANALOG_FEATURES if f in pool.columns]
    p = pool.loc[pool["r_multiple"].notna()].copy()
    empty = {"n": 0, "hit_rate_2r": None, "avg_r": None, "median_r": None, "insufficient_sample": True,
             "label": INSUFFICIENT}
    if p.empty or not feats:
        return p.head(0), empty
    X = p[feats].to_numpy(float)
    mu = np.nanmean(X, axis=0)
    sd = np.nanstd(X, axis=0)
    sd = np.where(np.isfinite(sd) & (sd > 0), sd, 1.0)
    mu = np.where(np.isfinite(mu), mu, 0.0)
    Z = np.nan_to_num((X - mu) / sd)
    q = np.array([float(query.get(f)) if query.get(f) is not None else np.nan for f in feats])
    zq = np.nan_to_num((q - mu) / sd)
    p["distance"] = np.sqrt(((Z - zq) ** 2).mean(axis=1))
    near = p.nsmallest(k, "distance")
    n = int(len(near))
    ok = n >= MIN_SAMPLE
    r = near["r_multiple"].astype(float)
    dist = {"n": n, "k": k, "insufficient_sample": not ok, "label": None if ok else INSUFFICIENT,
            "hit_rate_2r": round(float(near["hit_2r"].astype(float).mean() * 100), 1) if ok else None,
            "avg_r": round(float(r.mean()), 2) if ok else None, "median_r": round(float(r.median()), 2) if ok else None,
            "p25_r": round(float(r.quantile(0.25)), 2) if ok else None, "p75_r": round(float(r.quantile(0.75)), 2) if ok else None}
    return near, dist
