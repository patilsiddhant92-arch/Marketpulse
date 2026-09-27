"""Setup outcomes (spec §5): what happened after each setup signal.

`compute_setup_outcomes(setups, prices, horizon=20)` — one row per setup identity
(queue, symbol, first_seen; identity resets after >= 5 absent sessions):

- **Fill**: on the session after any in-queue day d, if that session's high >= trigger_d
  (the trigger/stop of day d). Entry = max(open, trigger) (a gap above the trigger fills at the open).
  The order is live only while the symbol is in the queue; no fill => status ``no_fill``.
- **Risk** R = entry - stop_d; rows with no stop or stop >= trigger are ``invalid``.
- **Exit**: stop when low <= stop (day of fill included; on later days a gap below fills at the open),
  else the close of the ``horizon``-th session (fill day = session 1). Not enough forward sessions => ``open``
  (r_multiple NULL; never counted).
- ``hit_1r`` / ``hit_2r``: high reached entry + 1R / 2R strictly before the stop day (same-day tie = stop,
  conservative). MAE/MFE are % from entry (and in R) over the holding period. ``r_path`` is the close-to-close
  R path (JSON list).

`aggregate_setup_outcomes(outcomes)` — per queue × environment state × group quadrant (with 'all'
rollups): n, hit rates, avg/median R, drawdown; n < 30 => "insufficient sample" and NULL numbers.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from .common import INSUFFICIENT, MIN_SAMPLE, VERDICT_ORDER, fmt_json, max_drawdown_r, to_ts_col
from .setups import assign_identity

OUTCOME_COLUMNS = [
    "queue", "setup_id", "symbol", "signal_date", "last_seen", "trigger_date", "trigger_price", "stop_price",
    "fill_date", "entry_price", "risk_pct", "status", "exit_date", "exit_price", "exit_reason", "r_multiple",
    "hit_1r", "hit_2r", "mae_pct", "mfe_pct", "mae_r", "mfe_r", "days_held", "r_path", "horizon",
]


def _price_arrays(prices: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    p = prices[["symbol", "trade_date", "open_price", "high_price", "low_price", "close_price"]].copy()
    p = to_ts_col(p, "trade_date").sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    p["symbol"] = p["symbol"].astype(str)
    arr = {c: p[c].to_numpy(float) for c in ("open_price", "high_price", "low_price", "close_price")}
    sym = p["symbol"].to_numpy()
    codes = pd.factorize(sym)[0]
    arr["sym"] = codes
    arr["date"] = p["trade_date"].to_numpy()
    return p, arr


def compute_setup_outcomes(setups: pd.DataFrame, prices: pd.DataFrame, horizon: int = 20,
                           sessions: Iterable | None = None, carry: Iterable[str] = ()) -> pd.DataFrame:
    """See module docstring. `carry` = extra setup columns copied from the identity's first row."""
    if setups is None or setups.empty:
        return pd.DataFrame(columns=OUTCOME_COLUMNS + list(carry))
    s = setups.copy()
    s = to_ts_col(s, "trade_date")
    s["symbol"] = s["symbol"].astype(str)
    if "setup_id" not in s.columns or s["setup_id"].isna().any():
        base = s.drop(columns=[c for c in ("setup_id", "first_seen", "setup_age_sessions") if c in s.columns])
        s = assign_identity(base, pd.Series(list(sessions)) if sessions is not None else None)
    s = s.sort_values(["setup_id", "trade_date"]).reset_index(drop=True)
    p, a = _price_arrays(prices)
    n_p = len(p)
    key = pd.Series(np.arange(n_p), index=pd.MultiIndex.from_arrays([p["symbol"], p["trade_date"]]))
    pos = key.reindex(pd.MultiIndex.from_arrays([s["symbol"], s["trade_date"]])).to_numpy(dtype=float)
    trig = pd.to_numeric(s["trigger_price"], errors="coerce").to_numpy(float)
    stop = pd.to_numeric(s["stop_price"], errors="coerce").to_numpy(float)
    has = np.isfinite(pos)
    posi = np.where(has, pos, 0).astype(np.int64)
    nxt = posi + 1
    nxt_ok = has & (nxt < n_p)
    nxt_c = np.minimum(nxt, n_p - 1)
    nxt_ok &= a["sym"][nxt_c] == a["sym"][posi]
    valid_geom = np.isfinite(trig) & (trig > 0) & np.isfinite(stop) & (stop < trig)
    filled = nxt_ok & valid_geom & (a["high_price"][nxt_c] >= trig)
    s["_filled"] = filled
    s["_valid"] = valid_geom

    first = s.groupby("setup_id", sort=False).head(1).set_index("setup_id")
    last_seen = s.groupby("setup_id", sort=False)["trade_date"].max()
    any_valid = s.groupby("setup_id", sort=False)["_valid"].any()
    fills = s.loc[s["_filled"]].groupby("setup_id", sort=False).head(1).copy()
    fi = fills.index.to_numpy()
    f_pos = nxt_c[fi]
    f_trig, f_stop = trig[fi], stop[fi]
    entry = np.maximum(a["open_price"][f_pos], f_trig)
    entry = np.where(np.isfinite(entry), entry, f_trig)
    risk = entry - f_stop
    n_t = len(fills)
    H = int(horizon)
    k = np.arange(H)
    gp = f_pos[:, None] + k[None, :]
    inb = gp < n_p
    gpc = np.minimum(gp, n_p - 1)
    same = inb & (a["sym"][gpc] == a["sym"][f_pos][:, None])
    same = np.logical_and.accumulate(same, axis=1)
    lo = np.where(same, a["low_price"][gpc], np.nan)
    hi = np.where(same, a["high_price"][gpc], np.nan)
    op = np.where(same, a["open_price"][gpc], np.nan)
    cl = np.where(same, a["close_price"][gpc], np.nan)
    avail = same.sum(axis=1)

    def _first(mask: np.ndarray) -> np.ndarray:
        any_ = mask.any(axis=1)
        return np.where(any_, mask.argmax(axis=1), H + 1)

    stop_k = _first(np.nan_to_num(lo, nan=np.inf) <= f_stop[:, None])
    t1_k = _first(np.nan_to_num(hi, nan=-np.inf) >= (entry + risk)[:, None])
    t2_k = _first(np.nan_to_num(hi, nan=-np.inf) >= (entry + 2 * risk)[:, None])
    stopped = stop_k < avail
    complete = avail >= H
    exit_k = np.where(stopped, stop_k, H - 1)
    row = np.arange(n_t)
    exk = np.clip(exit_k, 0, H - 1)
    stop_fill = np.where(exit_k == 0, f_stop, np.minimum(np.nan_to_num(op[row, exk], nan=np.inf), f_stop))
    exit_px = np.where(stopped, stop_fill, cl[row, exk])
    closed = stopped | complete
    status = np.where(stopped, "stopped", np.where(complete, "horizon", "open"))
    r = np.where(closed & (risk > 0), (exit_px - entry) / risk, np.nan)
    upto = k[None, :] <= exit_k[:, None]
    lo_h = np.where(upto, lo, np.nan)
    hi_h = np.where(upto, hi, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"), pd.option_context("mode.chained_assignment", None):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            mn = np.nanmin(lo_h, axis=1)
            mx = np.nanmax(hi_h, axis=1)
        mn = np.where(stopped, np.minimum(mn, exit_px), mn)
        mae_pct = (mn / entry - 1) * 100
        mfe_pct = (mx / entry - 1) * 100
        mae_r = (mn - entry) / risk
        mfe_r = (mx - entry) / risk
    hit1 = (t1_k < stop_k) & (t1_k <= exit_k) & closed
    hit2 = (t2_k < stop_k) & (t2_k <= exit_k) & closed
    exit_date = np.where(closed, a["date"][np.minimum(f_pos + exk, n_p - 1)], np.datetime64("NaT"))
    paths = []
    for i in range(n_t):
        if not closed[i] or not risk[i] > 0:
            paths.append(None)
            continue
        cp = (cl[i, : exit_k[i] + 1] - entry[i]) / risk[i]
        cp[-1] = r[i]
        paths.append(fmt_json([round(float(x), 2) for x in cp]))

    trades = pd.DataFrame({
        "setup_id": fills["setup_id"].to_numpy(),
        "trigger_date": fills["trade_date"].to_numpy(),
        "trigger_price": f_trig, "stop_price": f_stop,
        "fill_date": a["date"][f_pos], "entry_price": entry,
        "risk_pct": np.where(entry > 0, risk / entry * 100, np.nan),
        "status": status, "exit_date": exit_date,
        "exit_price": np.where(closed, exit_px, np.nan),
        "exit_reason": np.where(stopped, "stop", np.where(complete, "horizon", None)),
        "r_multiple": r,
        "hit_1r": np.where(closed, hit1, None), "hit_2r": np.where(closed, hit2, None),
        "mae_pct": np.where(closed, mae_pct, np.nan), "mfe_pct": np.where(closed, mfe_pct, np.nan),
        "mae_r": np.where(closed, mae_r, np.nan), "mfe_r": np.where(closed, mfe_r, np.nan),
        "days_held": np.where(closed, exit_k + 1, np.nan),
        "r_path": paths,
    }).set_index("setup_id")

    out = pd.DataFrame(index=first.index)
    out["queue"] = first["queue"]
    out["symbol"] = first["symbol"]
    out["signal_date"] = first["first_seen"] if "first_seen" in first.columns else first["trade_date"]
    out["last_seen"] = last_seen
    out = out.join(trades, how="left")
    out["trigger_date"] = out["trigger_date"].where(out["trigger_date"].notna(), None)
    no_fill = out["fill_date"].isna()
    out.loc[no_fill, "status"] = np.where(any_valid.reindex(out.index[no_fill]).to_numpy(), "no_fill", "invalid")
    out.loc[no_fill, "trigger_price"] = pd.to_numeric(first.loc[no_fill[no_fill].index, "trigger_price"], errors="coerce")
    out.loc[no_fill, "stop_price"] = pd.to_numeric(first.loc[no_fill[no_fill].index, "stop_price"], errors="coerce")
    out["horizon"] = H
    for c in carry:
        if c in first.columns:
            out[c] = first[c]
    out = out.reset_index().rename(columns={"index": "setup_id"})
    for c in ("signal_date", "last_seen", "trigger_date", "fill_date", "exit_date"):
        out[c] = pd.to_datetime(out[c])
    out["days_held"] = pd.to_numeric(out["days_held"], errors="coerce").astype("Int64")
    for c in ("hit_1r", "hit_2r"):
        out[c] = out[c].astype("boolean")
    return out[OUTCOME_COLUMNS + [c for c in carry if c in out.columns]].sort_values(
        ["signal_date", "queue", "symbol"]).reset_index(drop=True)


# --------------------------------------------------------------------------
# Aggregates
# --------------------------------------------------------------------------
STAT_METRICS = ["hit_rate_1r", "hit_rate_2r", "win_rate", "avg_r", "median_r", "avg_mae_pct", "avg_mfe_pct",
                "max_drawdown_r", "avg_days_held"]


def _stats(g: pd.DataFrame) -> dict:
    closed = g.loc[g["r_multiple"].notna()].sort_values("signal_date")
    n = int(len(closed))
    signals = int(len(g))
    fills = int(g["fill_date"].notna().sum())
    rec = {"n": n, "n_signals": signals, "n_filled": fills,
           "fill_rate": round(fills / signals * 100, 1) if signals else None,
           "insufficient_sample": n < MIN_SAMPLE, "label": INSUFFICIENT if n < MIN_SAMPLE else None}
    if n < MIN_SAMPLE:
        rec.update({m: None for m in STAT_METRICS})
        return rec
    r = closed["r_multiple"].astype(float)
    rec.update({
        "hit_rate_1r": round(float(closed["hit_1r"].astype(float).mean() * 100), 1),
        "hit_rate_2r": round(float(closed["hit_2r"].astype(float).mean() * 100), 1),
        "win_rate": round(float((r > 0).mean() * 100), 1),
        "avg_r": round(float(r.mean()), 3), "median_r": round(float(r.median()), 3),
        "avg_mae_pct": round(float(closed["mae_pct"].mean()), 2), "avg_mfe_pct": round(float(closed["mfe_pct"].mean()), 2),
        "max_drawdown_r": round(max_drawdown_r(r.tolist()) or 0.0, 2),
        "avg_days_held": round(float(closed["days_held"].astype(float).mean()), 1),
    })
    return rec


def aggregate_setup_outcomes(outcomes: pd.DataFrame, dims: tuple[str, ...] = ("queue", "environment_state", "group_quadrant")) -> pd.DataFrame:
    """Stats for every combination of dims with 'all' rollups (grouping sets)."""
    if outcomes is None or outcomes.empty:
        return pd.DataFrame(columns=list(dims) + ["n", "n_signals", "n_filled", "fill_rate", "insufficient_sample", "label"] + STAT_METRICS)
    o = outcomes.copy()
    for d in dims:
        o[d] = o[d].astype("object").where(o[d].notna(), "unknown").astype(str) if d in o.columns else "unknown"
    recs = []
    import itertools
    for mask in itertools.product([True, False], repeat=len(dims)):
        use = [d for d, m in zip(dims, mask) if m]
        groups = o.groupby(use, sort=True) if use else [((), o)]
        for key, g in groups:
            key = key if isinstance(key, tuple) else (key,)
            rec = {d: "all" for d in dims}
            rec.update(dict(zip(use, key)))
            rec.update(_stats(g))
            recs.append(rec)
    return pd.DataFrame(recs)


def environment_calibration(outcomes: pd.DataFrame, min_gap_r: float = 0.15, min_t: float = 2.0) -> pd.DataFrame:
    """Verdict rules validated against outcomes (spec §6.1.5 ship gate), per queue and 'all'.

    Rows kind='state': n / avg_r / hit_rate_2r per environment state. Rows kind='ship_gate':
    good = Favourable+Constructive, bad = Weak+Danger; gap = avg_r(good) - avg_r(bad), Welch t,
    passes = both n >= 30 and gap >= min_gap_r and t >= min_t."""
    cols = ["queue", "kind", "environment_state", "n", "avg_r", "median_r", "hit_rate_2r", "label",
            "n_good", "n_bad", "avg_r_good", "avg_r_bad", "gap_r", "welch_t", "passes", "rule"]
    if outcomes is None or outcomes.empty or "environment_state" not in outcomes.columns:
        return pd.DataFrame(columns=cols)
    o = outcomes.loc[outcomes["r_multiple"].notna()].copy()
    recs = []
    for q, g in [("all", o), *list(o.groupby("queue"))]:
        for st, gs in g.groupby(g["environment_state"].astype("object").fillna("unknown")):
            n = len(gs)
            ok = n >= MIN_SAMPLE
            recs.append({"queue": q, "kind": "state", "environment_state": st, "n": n,
                         "avg_r": round(float(gs["r_multiple"].mean()), 3) if ok else None,
                         "median_r": round(float(gs["r_multiple"].median()), 3) if ok else None,
                         "hit_rate_2r": round(float(gs["hit_2r"].astype(float).mean() * 100), 1) if ok else None,
                         "label": None if ok else INSUFFICIENT})
        good = g.loc[g["environment_state"].isin(["Favourable", "Constructive"]), "r_multiple"].astype(float)
        bad = g.loc[g["environment_state"].isin(["Weak", "Danger"]), "r_multiple"].astype(float)
        ng, nb = len(good), len(bad)
        rec = {"queue": q, "kind": "ship_gate", "environment_state": None, "n": ng + nb, "n_good": ng, "n_bad": nb,
               "rule": f"avg R(Favourable+Constructive) - avg R(Weak+Danger) >= {min_gap_r} R, Welch t >= {min_t}, both n >= {MIN_SAMPLE}"}
        if ng >= MIN_SAMPLE and nb >= MIN_SAMPLE:
            gap = float(good.mean() - bad.mean())
            se = float(np.sqrt(good.var(ddof=1) / ng + bad.var(ddof=1) / nb))
            t = gap / se if se > 0 else None
            rec.update({"avg_r_good": round(float(good.mean()), 3), "avg_r_bad": round(float(bad.mean()), 3),
                        "gap_r": round(gap, 3), "welch_t": round(t, 2) if t is not None else None,
                        "passes": bool(gap >= min_gap_r and (t or 0) >= min_t)})
        else:
            rec.update({"label": INSUFFICIENT, "passes": None})
        recs.append(rec)
    out = pd.DataFrame(recs)
    for c in cols:
        if c not in out.columns:
            out[c] = None
    out["_o"] = out["environment_state"].map(VERDICT_ORDER)
    return out.sort_values(["queue", "kind", "_o"]).drop(columns=["_o"])[cols].reset_index(drop=True)
