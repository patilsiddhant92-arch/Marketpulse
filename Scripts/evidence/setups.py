"""Historical setup rows, point-in-time, from indicators_daily — so evidence exists before (or
alongside) `setup_daily`.

`historical_setups_from_indicators(indicators, mcap=None, master=None)` returns rows with the
`setup_daily` column contract: (queue, symbol, trade_date, trigger_price, stop_price, setup_id,
first_seen, setup_age_sessions, close_price, risk_pct, features, source).

Queues (each row uses only data dated <= trade_date):

- ``darvas_squeeze`` — the Desk truth table (`Scripts.darvas_squeeze.evaluate_squeeze_bar`), vectorised:
  Darvas TopBox from `calculate_darvas_box` (causal), 10/20 EMA from indicators, dry-volume gate
  (rvol <= 1.0), rising 10 EMA, candle range <= 4 %, plus the daily persistence rule (a qualifying
  bar in the last 5 sessions and the close still in the zone, range <= 6 %, rvol <= 1.5).
  Trigger = TopBox, stop = 10 EMA × 0.985 (desk contract). Box/EMA use the full history up to t
  (the Desk uses a 252-session window; the box converges within a few bars).
- ``vcp`` — `Scripts.minervini_geometry.detect_contractions` on the last 252 sessions to t, re-implemented
  on precomputed fractal flags (identical output, see tests) because calling it per stock-day costs
  ~1 ms. Gate as the Desk: >= 2 contractions, stop < close <= pivot × 1.03, close >= 30,
  20-day avg volume >= 100k. Trigger = pivot (last T high), stop = last T low.
- ``momentum`` — Minervini trend template passing, strength rank (rs_percentile) >= 70, within 15 % of
  the 52W high, close >= 10 EMA. Trigger = highest high of the last 10 sessions (incl. t), stop =
  lowest low of the same 10 sessions; rows with risk > 15 % are dropped (no synthetic stops).

Pool (all queues, as the Desk): mcap >= ₹1,000 Cr as of t (see common.pit_mcap), 20-day ADV >= ₹3 Cr,
band > 5 % or no band (current band — documented), close > 200 EMA (or 200 EMA unknown).
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right

import numpy as np
import pandas as pd

from .common import fmt_json, grolling

try:
    from Scripts.darvas_squeeze import calculate_darvas_box
    from Scripts.desk_contract import DARVAS, POOL
except ModuleNotFoundError:  # pragma: no cover - script-style import
    from darvas_squeeze import calculate_darvas_box  # type: ignore
    from desk_contract import DARVAS, POOL  # type: ignore

IDENTITY_GAP_SESSIONS = 5
VCP_WINDOW = 252
VCP_MIN_HISTORY = 60
VCP_MIN_CONTRACTIONS = 2
VCP_MAX_ABOVE_PIVOT = 1.03
VCP_MIN_AVG_VOLUME_20D = 100_000
VCP_MIN_CLOSE = 30.0
STOP_BUFFER = 0.985
MOMENTUM_MAX_RISK_PCT = 15.0
SETUP_COLUMNS = ["queue", "symbol", "trade_date", "trigger_price", "stop_price", "close_price", "risk_pct",
                 "setup_id", "first_seen", "setup_age_sessions", "features", "source"]


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------
def assign_identity(rows: pd.DataFrame, sessions: pd.Series | None = None,
                    gap: int = IDENTITY_GAP_SESSIONS) -> pd.DataFrame:
    """setup_id / first_seen / setup_age_sessions; identity resets when the symbol was absent from
    the queue for >= `gap` sessions. `sessions` = all market sessions (defaults to the dates present)."""
    if rows.empty:
        out = rows.copy()
        for c in ("setup_id", "first_seen", "setup_age_sessions"):
            out[c] = pd.Series(dtype="object")
        return out
    out = rows.sort_values(["queue", "symbol", "trade_date"]).reset_index(drop=True)
    sess = pd.Series(sorted(pd.to_datetime(sessions if sessions is not None else out["trade_date"]).unique()))
    pos = pd.Series(np.arange(len(sess)), index=pd.DatetimeIndex(sess))
    sidx = pos.reindex(pd.DatetimeIndex(out["trade_date"])).to_numpy()
    if np.isnan(sidx.astype(float)).any():
        raise ValueError("setup rows dated outside the session calendar")
    sidx = sidx.astype(np.int64)
    same = (out["queue"].to_numpy() == np.roll(out["queue"].to_numpy(), 1)) & (
        out["symbol"].to_numpy() == np.roll(out["symbol"].to_numpy(), 1))
    same[0] = False
    absent = sidx - np.roll(sidx, 1) - 1
    new = ~same | (absent >= gap)
    grp = np.cumsum(new)
    first_idx = pd.Series(np.arange(len(out))).groupby(grp).transform("min").to_numpy()
    out["first_seen"] = out["trade_date"].to_numpy()[first_idx]
    out["setup_age_sessions"] = (sidx - sidx[first_idx] + 1).astype(np.int64)
    out["setup_id"] = (out["queue"].astype(str) + ":" + out["symbol"].astype(str) + ":"
                       + pd.to_datetime(out["first_seen"]).dt.strftime("%Y%m%d"))
    return out


# --------------------------------------------------------------------------
# Pool
# --------------------------------------------------------------------------
def pool_mask(ind: pd.DataFrame, master: pd.DataFrame | None = None) -> np.ndarray:
    mcap = pd.to_numeric(ind.get("mcap_cr"), errors="coerce") if "mcap_cr" in ind.columns else pd.Series(np.nan, index=ind.index)
    adv = pd.to_numeric(ind["avg_traded_value_cr_20d"], errors="coerce").fillna(pd.to_numeric(ind["turnover_cr"], errors="coerce"))
    close = ind["close_price"].astype(float)
    e200 = pd.to_numeric(ind["ema_200"], errors="coerce")
    ok = (mcap >= float(POOL["min_mcap"])) & (adv >= float(POOL["min_adv_cr"])) & ((close > e200) | e200.isna())
    if master is not None and "band" in master.columns:
        band = ind["symbol"].map(master.drop_duplicates("symbol").set_index("symbol")["band"]).astype(float)
        ok &= band.isna() | (band > float(POOL["min_band"]))
    sym = ind["symbol"].astype(str)
    ok &= ~sym.str.endswith("-RE") & ~sym.str.endswith("_RE")
    return ok.to_numpy()


def _symbol_bounds(ind: pd.DataFrame) -> list[tuple[str, int, int]]:
    sym = ind["symbol"].to_numpy()
    starts = np.flatnonzero(np.r_[True, sym[1:] != sym[:-1]])
    ends = np.r_[starts[1:], len(sym)]
    return [(str(sym[s]), int(s), int(e)) for s, e in zip(starts, ends)]


# --------------------------------------------------------------------------
# Darvas squeeze (vectorised desk truth table)
# --------------------------------------------------------------------------
def darvas_squeeze_flags(ind: pd.DataFrame, cfg: dict | None = None) -> pd.DataFrame:
    """Per row: qualifies (bar or persistence), top_box, squeeze_pct, candle_range_pct. `ind` sorted by symbol, date."""
    p = dict(DARVAS)
    if cfg:
        p.update(cfg)
    n = len(ind)
    top = np.full(n, np.nan)
    for _, s, e in _symbol_bounds(ind):
        t, _b = calculate_darvas_box(ind["high_price"].to_numpy(float)[s:e], ind["low_price"].to_numpy(float)[s:e], boxp=5)
        top[s:e] = t
    c = ind["close_price"].to_numpy(float)
    h = ind["high_price"].to_numpy(float)
    lo = ind["low_price"].to_numpy(float)
    e10 = pd.to_numeric(ind["ema_10"], errors="coerce").to_numpy(float)
    e20 = pd.to_numeric(ind["ema_20"], errors="coerce").to_numpy(float)
    rv = pd.to_numeric(ind["rvol"], errors="coerce").to_numpy(float)
    sym = ind["symbol"].to_numpy()
    first = np.r_[True, sym[1:] != sym[:-1]]
    e10_prev = np.r_[np.nan, e10[:-1]]
    e10_prev[first] = np.nan
    with np.errstate(divide="ignore", invalid="ignore"):
        valid = (top > 0) & (e10 > 0) & (c > 0)
        sq = (top - e10) / top * 100.0
        rng = (h - lo) / c * 100.0
        dist = (top - c) / top * 100.0
        trend_ok = np.where(np.isfinite(e20) & (e20 > 0), e10 >= e20 * p["ema_trend_tol"], True)
        close_ok = (c >= e10 * p["close_floor_tol"]) & (c <= top * p["ceiling_tol"])
        range_ok = ~np.isfinite(rng) | (rng <= p["max_range_pct"])
        rising = np.where(np.isfinite(e10_prev), e10 > e10_prev, True)
        dry = np.isfinite(rv) & (rv <= float(p.get("max_rvol", 1.0)))
        bar = (valid & trend_ok & (sq >= 0) & (sq <= p["max_squeeze_pct"]) & (dist >= -0.2)
               & (dist <= p["max_squeeze_pct"]) & close_ok & range_ok & rising & dry)
    # persistence: a qualifying bar within the last `persist_sessions` bars (same symbol), still in zone
    k = int(p.get("persist_sessions", 5))
    grp = np.cumsum(first)
    recent = grolling(bar.astype(float), grp, k, "max", 1) > 0
    still_in = np.isfinite(c) & np.isfinite(e10) & np.isfinite(top) & (top > 0) & close_ok
    persist = recent & still_in
    persist &= ~np.isfinite(rng) | (rng <= float(p.get("persist_max_range_pct", 6.0)))
    persist &= ~np.isfinite(rv) | (rv <= float(p.get("persist_max_rvol", 1.5)))
    return pd.DataFrame({"qualifies": bar | persist, "bar_ok": bar, "top_box": top, "squeeze_pct": sq,
                         "candle_range_pct": rng}, index=ind.index)


# --------------------------------------------------------------------------
# VCP (detect_contractions on precomputed fractals)
# --------------------------------------------------------------------------
def fractal_flags(values: np.ndarray, kind: str, left: int = 2, right: int = 2) -> np.ndarray:
    """Same rule as minervini_geometry._fractal_indices, as a boolean array over the whole series."""
    v = np.asarray(values, dtype=float)
    n = len(v)
    out = np.zeros(n, dtype=bool)
    if n < left + right + 1:
        return out
    win = np.lib.stride_tricks.sliding_window_view(v, left + right + 1)  # rows centred at i = left..n-right-1
    centre = v[left:n - right]
    with np.errstate(invalid="ignore"):
        if kind == "high":
            ext = win.max(axis=1)
            ok = centre >= ext
        else:
            ext = win.min(axis=1)
            ok = centre <= ext
        uniq = (win == centre[:, None]).sum(axis=1) == 1
    out[left:n - right] = ok & uniq
    return out


class _SymbolArrays:
    """One symbol's arrays prepared for repeated window queries (python lists + volume prefix sums)."""

    def __init__(self, high: np.ndarray, low: np.ndarray, vol: np.ndarray):
        self.h = [float(x) for x in high]
        self.l = [float(x) for x in low]
        self.peaks = np.flatnonzero(fractal_flags(high, "high")).tolist()
        self.troughs = np.flatnonzero(fractal_flags(low, "low")).tolist()
        v = np.asarray(vol, dtype=float)
        fin = np.isfinite(v)
        self.vsum = np.concatenate([[0.0], np.cumsum(np.where(fin, v, 0.0))]).tolist()
        self.vcnt = np.concatenate([[0], np.cumsum(fin)]).tolist()

    def vmean(self, a: int, b: int) -> float:
        """nan-skipping mean of vol[a:b] (NaN when no finite value), like pandas .mean()."""
        n = self.vcnt[b] - self.vcnt[a]
        return (self.vsum[b] - self.vsum[a]) / n if n else float("nan")


def contractions_window(arr: "_SymbolArrays", lo: int, hi: int, *, min_bars: int = 8,
                        min_depth: float = 3.0) -> list[tuple[int, int, int, float, float, float, int, float]]:
    """Scripts.minervini_geometry.detect_contractions on the window [lo, hi] (inclusive positions of one
    symbol's arrays), using fractals precomputed on the whole series: a fractal at i needs bars i±2, so the
    window's fractals are exactly the global ones in [lo+2, hi−2].

    Returns [(peak_i, trough_i, next_peak_i, peak, trough, depth_pct, bars, volume_ratio)]."""
    if hi - lo + 1 < 30:
        return []
    high, low, P, T = arr.h, arr.l, arr.peaks, arr.troughs
    p0, p1 = bisect_left(P, lo + 2), bisect_right(P, hi - 2)
    t0, t1 = bisect_left(T, lo + 2), bisect_right(T, hi - 2)
    if p1 - p0 < 2 or t1 - t0 < 1:
        return []
    base = None
    for k in range(p1 - 1, p0 - 1, -1):
        p = P[k]
        j = bisect_left(T, p, t0, t1) - 1
        if j < t0:
            continue
        t = T[j]
        if high[t] and (high[p] / low[t] - 1) >= 0.20:
            base = k
            break
    if base is None:
        base = p1 - 1
    out = []
    prev_depth = 999.0
    for k in range(base, p1 - 1):
        p, nxt = P[k], P[k + 1]
        m0, m1 = bisect_right(T, p, t0, t1), bisect_left(T, nxt, t0, t1)
        if m0 >= m1:
            continue
        t = T[m0]
        for j in range(m0 + 1, m1):
            if low[T[j]] < low[t]:
                t = T[j]
        bars = nxt - p
        if bars < min_bars:
            continue
        pk, tr = high[p], low[t]
        if pk <= 0:
            continue
        depth = (pk - tr) / pk * 100
        if depth < min_depth:
            continue
        if depth >= prev_depth:
            break
        avg_base = arr.vmean(max(lo, p - 20), p + 1) or 1.0
        avg_t = arr.vmean(p, nxt + 1) or 1.0
        out.append((p, t, nxt, pk, tr, depth, bars, avg_t / avg_base if avg_base else 1.0))
        prev_depth = depth
        if len(out) >= 4:
            break
    return out


def vcp_rows(ind: pd.DataFrame, pool: np.ndarray) -> pd.DataFrame:
    close = ind["close_price"].to_numpy(float)
    avgv = pd.to_numeric(ind["avg_volume_20d"], errors="coerce").to_numpy(float)
    cand = pool & (close >= VCP_MIN_CLOSE) & (~np.isfinite(avgv) | (avgv >= VCP_MIN_AVG_VOLUME_20D))
    H = ind["high_price"].to_numpy(float)
    L = ind["low_price"].to_numpy(float)
    V = pd.to_numeric(ind["volume"], errors="coerce").to_numpy(float)
    recs = []
    for sym, s, e in _symbol_bounds(ind):
        rows = np.flatnonzero(cand[s:e])
        rows = rows[rows + 1 >= VCP_MIN_HISTORY]
        if rows.size == 0:
            continue
        arr = _SymbolArrays(H[s:e], L[s:e], V[s:e])
        for r in rows.tolist():
            cs = contractions_window(arr, max(0, r - VCP_WINDOW + 1), r)
            if len(cs) < VCP_MIN_CONTRACTIONS:
                continue
            pivot, stop = cs[-1][3], cs[-1][4]
            c = close[s + r]
            if not (stop < c <= pivot * VCP_MAX_ABOVE_PIVOT):
                continue
            recs.append((s + r, pivot, stop, len(cs), [round(x[5], 2) for x in cs], [x[6] for x in cs],
                         max(1, int(round(sum(x[6] for x in cs) / 5))), int(r - cs[-1][2])))
    if not recs:
        return pd.DataFrame(columns=["_row", "trigger_price", "stop_price", "features"])
    df = pd.DataFrame(recs, columns=["_row", "trigger_price", "stop_price", "n", "depths", "bars", "weeks", "since_last_t"])
    df["features"] = [fmt_json({"n_contractions": n, "depths_pct": d, "bars": b, "weeks": w, "sessions_since_last_t": st})
                      for n, d, b, w, st in zip(df["n"], df["depths"], df["bars"], df["weeks"], df["since_last_t"])]
    return df[["_row", "trigger_price", "stop_price", "features"]]


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def historical_setups_from_indicators(indicators: pd.DataFrame, master: pd.DataFrame | None = None,
                                      queues: tuple[str, ...] = ("darvas_squeeze", "vcp", "momentum"),
                                      sessions: pd.Series | None = None) -> pd.DataFrame:
    """Point-in-time setup rows for each queue. `indicators` must carry mcap_cr (common.pit_mcap)."""
    ind = indicators.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    pool = pool_mask(ind, master)
    parts = []
    close = ind["close_price"].to_numpy(float)
    if "darvas_squeeze" in queues:
        f = darvas_squeeze_flags(ind)
        m = f["qualifies"].to_numpy() & pool
        e10 = pd.to_numeric(ind["ema_10"], errors="coerce").to_numpy(float)
        d = pd.DataFrame({"_row": np.flatnonzero(m)})
        d["trigger_price"] = f["top_box"].to_numpy()[m]
        d["stop_price"] = e10[m] * STOP_BUFFER
        d["features"] = [fmt_json({"squeeze_pct": a, "candle_range_pct": b, "signal_bar": bool(c)}) for a, b, c in zip(
            f["squeeze_pct"].to_numpy()[m], f["candle_range_pct"].to_numpy()[m], f["bar_ok"].to_numpy()[m])]
        d["queue"] = "darvas_squeeze"
        parts.append(d)
    if "vcp" in queues:
        d = vcp_rows(ind, pool)
        d["queue"] = "vcp"
        parts.append(d)
    if "momentum" in queues:
        codes = pd.factorize(ind["symbol"].to_numpy())[0]
        hh = grolling(ind["high_price"].to_numpy(float), codes, 10, "max", 10)
        ll = grolling(ind["low_price"].to_numpy(float), codes, 10, "min", 10)
        ttp = ind["trend_template_pass"].astype("boolean").fillna(False).to_numpy(bool)
        rs = pd.to_numeric(ind["rs_percentile"], errors="coerce").to_numpy(float)
        away = pd.to_numeric(ind["away_52w_high_pct"], errors="coerce").to_numpy(float)
        e10 = pd.to_numeric(ind["ema_10"], errors="coerce").to_numpy(float)
        with np.errstate(invalid="ignore", divide="ignore"):
            risk = (hh - ll) / hh * 100
            m = pool & ttp & (rs >= 70) & (away >= -15) & (close >= e10) & np.isfinite(risk) & (risk > 0) & (
                risk <= MOMENTUM_MAX_RISK_PCT)
        d = pd.DataFrame({"_row": np.flatnonzero(m), "trigger_price": hh[m], "stop_price": ll[m]})
        d["features"] = [fmt_json({"rs_percentile": a, "away_52w_high_pct": b}) for a, b in zip(rs[m], away[m])]
        d["queue"] = "momentum"
        parts.append(d)
    if not parts:
        return pd.DataFrame(columns=SETUP_COLUMNS)
    allp = pd.concat(parts, ignore_index=True)
    rows = allp["_row"].to_numpy(np.int64)
    allp["symbol"] = ind["symbol"].to_numpy()[rows]
    allp["trade_date"] = ind["trade_date"].to_numpy()[rows]
    allp["close_price"] = close[rows]
    tp, sp = allp["trigger_price"].astype(float), allp["stop_price"].astype(float)
    allp["risk_pct"] = np.where((tp > 0) & (sp < tp), (tp - sp) / tp * 100, np.nan)
    allp["source"] = "indicators_history"
    allp = assign_identity(allp.drop(columns=["_row"]), sessions if sessions is not None else ind["trade_date"])
    return allp[SETUP_COLUMNS]
