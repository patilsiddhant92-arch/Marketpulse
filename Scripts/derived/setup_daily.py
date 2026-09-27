"""setup_daily — Desk queue membership per session (spec §4.5, §7.2): one row per
(queue, symbol, trade_date) while the symbol is in the queue.

Queues and the predicates they reuse (never re-implemented):
  darvas_squeeze  Scripts.darvas_squeeze.calculate_darvas_box + evaluate_squeeze_bar per bar, composed
                  exactly like squeeze_frame(timeframe="D") (last bar qualifies, or a qualifying bar in
                  the last `persist_sessions` with the coil still intact). Trigger = Darvas TopBox,
                  stop = 10 EMA x 0.985 (the Action Desk contract, _assemble_darvas_queue).
  darvas_10ema    Scripts.darvas_squeeze.classify_darvas_10ema_frame on the 60-session window ending t
                  (Pullback / Trace-back / Catch-up); symbols already in darvas_squeeze that day are
                  excluded (Action Desk rule). Geometry per spec §14.1: trigger = high of t (the prior
                  session for the next open), stop = lowest low from the 10 EMA touch (signal_date) to t;
                  Catch-up has no touch => stop NULL.
  vcp             Scripts.minervini_geometry.detect_contractions on the 150-session window ending t
                  (time-ordered swings, strictly shrinking depths). Qualifies with >= 2 contractions and
                  last-T low < close <= last-T high (pivot). Trigger = pivot, stop = last-T low.
                  vdu_ratio = mean(volume, 3) / mean(volume, 20) — the analyze_manas_vcp formula.
                  Stage-2 gates from Scripts.vcp.VCP: close >= 30, within 25% of the 52W high,
                  20-day average volume >= 100k.

Pool (Action Desk POOL, point-in-time where data allows): market cap >= ₹1,000 Cr (reference as-of,
else price-scaled current — see _common.point_in_time_mcap), 20-day ADV >= ₹3 Cr, band > 5% (NULL band
passes, as on the desk), no GSM / 'STAGE 2' surveillance remark, no -RE/_RE symbols, and close above the
200 EMA (or 200 EMA not yet available) — the invariant all three desk queues enforce.

Identity: a setup is (queue, symbol, first_seen). It resets when the symbol was absent from the queue
for >= 5 sessions (spec §5). status: new | active | returning (back after 1-4 absent sessions).

Incremental: pass `since` (and `previous`, the stored table) to recompute only sessions >= since; the
returned frame is always the complete table (previous rows before `since` + recomputed rows).
"""
from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from ._common import asof_reference, clean_symbols, normalise_dates, num, point_in_time_mcap, prep_indicators

try:
    from Scripts.darvas_squeeze import DARVAS, calculate_darvas_box, classify_darvas_10ema_frame, evaluate_squeeze_bar
    from Scripts.desk_contract import POOL
    from Scripts.minervini_geometry import detect_contractions
    from Scripts.vcp import VCP
except ImportError:  # pragma: no cover - script-style import (Scripts/ on sys.path)
    from darvas_squeeze import DARVAS, calculate_darvas_box, classify_darvas_10ema_frame, evaluate_squeeze_bar  # type: ignore
    from desk_contract import POOL  # type: ignore
    from minervini_geometry import detect_contractions  # type: ignore
    from vcp import VCP  # type: ignore

QUEUES = ("darvas_squeeze", "darvas_10ema", "vcp")
EMA10_WINDOW = 60
VCP_WINDOW = 150
IDENTITY_RESET_SESSIONS = 5
SQUEEZE_STOP_FACTOR = 0.985
SQUEEZE_AGE_LOOKBACK = 60
BOX_WARMUP = 300  # Action Desk _assemble_darvas_queue: stop = 10 EMA x 0.985
CHUNK = 20_000

INDICATOR_COLUMNS = (
    "open_price", "high_price", "low_price", "close_price", "volume", "ema_10", "ema_20", "ema_200",
    "rvol", "avg_volume_20d", "avg_traded_value_cr_20d", "turnover_cr", "delivery_pct", "avg_delivery_pct_20d",
    "rs_percentile", "away_52w_high_pct", "atr_pct", "band_remarks",
)

OUTPUT_COLUMNS = [
    "trade_date", "queue", "symbol", "setup_id", "first_seen", "setup_age_sessions", "status", "signal_date",
    "close_price", "trigger_price", "stop_price", "risk_pct", "distance_to_trigger_pct",
    "rvol", "delivery_pct", "avg_delivery_pct_20d", "rs_percentile", "away_52w_high_pct", "atr_pct",
    "adv_cr", "mcap_cr", "mcap_basis", "features",
]


# ---------------------------------------------------------------------------------------------
# Frame + pool
# ---------------------------------------------------------------------------------------------
def _frame(indicators: pd.DataFrame, prices: pd.DataFrame | None) -> pd.DataFrame:
    ind = prep_indicators(indicators, INDICATOR_COLUMNS)
    missing = [c for c in ("open_price", "high_price", "low_price", "close_price", "volume") if c not in ind.columns]
    if missing and prices is not None and not prices.empty:
        px = clean_symbols(prices[["symbol", "trade_date", *[c for c in missing if c in prices.columns]]].copy())
        px["trade_date"] = normalise_dates(px["trade_date"])
        px = px.drop_duplicates(["symbol", "trade_date"], keep="last")
        ind = ind.merge(px, on=["symbol", "trade_date"], how="left")
        ind = ind.sort_values(["symbol", "trade_date"], kind="mergesort").reset_index(drop=True)
    for c in INDICATOR_COLUMNS:
        if c not in ind.columns:
            ind[c] = np.nan
    return ind


def _contains_any(values: pd.Series, tokens: tuple[str, ...]) -> np.ndarray:
    """Upper-cased substring test evaluated on unique values only (remarks repeat heavily)."""
    codes, uniques = pd.factorize(values.fillna(""))
    up = pd.Index(uniques).astype(str).str.upper()
    hit = np.zeros(len(up), dtype=bool)
    for t in tokens:
        hit |= np.asarray(up.str.contains(t, regex=False), dtype=bool)
    return hit[codes] if len(codes) else np.zeros(0, dtype=bool)


def _pool(ind: pd.DataFrame, master: pd.DataFrame | None, reference: pd.DataFrame | None,
          target: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Pool flag (evaluated on target rows only), market cap, ADV and mcap basis per row."""
    n = len(ind)
    rows = np.flatnonzero(target)
    mcap_s, basis_s = point_in_time_mcap(ind, master, None)  # price-scaled current (vectorised)
    mcap = mcap_s.to_numpy(dtype=float).copy()
    basis = basis_s.to_numpy(dtype=object).copy()
    sub = ind.iloc[rows]
    ref_mcap = asof_reference(sub, reference, "market_cap_cr").to_numpy()
    has = np.isfinite(ref_mcap)
    mcap[rows[has]] = ref_mcap[has]
    basis[rows[has]] = "reference_asof"
    adv_s = num(ind, "avg_traded_value_cr_20d")
    adv = adv_s.where(adv_s.notna(), num(ind, "turnover_cr")).to_numpy(dtype=float)
    sym = sub["symbol"]
    ok = adv[rows] >= POOL["min_adv_cr"]
    remarks = sub["band_remarks"].astype("object")
    if master is not None and not master.empty:
        ok &= mcap[rows] >= POOL["min_mcap"]
        m = clean_symbols(master.copy()).drop_duplicates("symbol", keep="last").set_index("symbol")
        band = asof_reference(sub, reference, "price_band")
        if "band" in m.columns:
            band = band.where(band.notna(), sym.map(pd.to_numeric(m["band"], errors="coerce")))
        ok &= (band.fillna(20.0) > POOL["min_band"]).to_numpy(dtype=bool)
        if "band_remarks" in m.columns:
            remarks = remarks.where(remarks.notna(), sym.map(m["band_remarks"]))
    ok &= ~_contains_any(remarks, ("GSM", "STAGE 2"))
    ok &= ~(sym.str.endswith("-RE") | sym.str.endswith("_RE")).to_numpy(dtype=bool)
    close = num(sub, "close_price")
    e200 = num(sub, "ema_200")
    ok &= ((close > e200) | e200.isna()).to_numpy(dtype=bool) & close.notna().to_numpy()
    pool = np.zeros(n, dtype=bool)
    pool[rows] = ok
    return pool, mcap, adv, basis


# ---------------------------------------------------------------------------------------------
# Darvas squeeze (daily)
# ---------------------------------------------------------------------------------------------
def _darvas_squeeze(ind: pd.DataFrame, pool: np.ndarray, target: np.ndarray) -> pd.DataFrame:
    params = dict(DARVAS)
    n = len(ind)
    high = ind["high_price"].to_numpy(dtype=float)
    low = ind["low_price"].to_numpy(dtype=float)
    close = ind["close_price"].to_numpy(dtype=float)
    opn = ind["open_price"].to_numpy(dtype=float)
    e10 = ind["ema_10"].to_numpy(dtype=float)
    e20 = ind["ema_20"].to_numpy(dtype=float)
    rvol = ind["rvol"].to_numpy(dtype=float)
    sym = ind["symbol"].to_numpy()
    starts = np.flatnonzero(np.r_[True, sym[1:] != sym[:-1]])
    ends = np.r_[starts[1:], n]
    pos = np.empty(n, dtype=np.int64)  # position within the symbol's history
    for st, en in zip(starts, ends):
        pos[st:en] = np.arange(en - st)
    persist_n = int(params["persist_sessions"])
    # Bars that can matter: pool target rows and up to SQUEEZE_AGE_LOOKBACK bars before them
    # (persistence looks back persist_n bars; squeeze_age counts back further).
    tgt = pool & target
    need = np.zeros(n, dtype=bool)
    for k in range(max(persist_n, SQUEEZE_AGE_LOOKBACK)):
        j = np.arange(n) + k
        ok = j < n
        jj = np.where(ok, j, 0)
        need |= ok & tgt[jj] & (pos[jj] >= k)
    # Darvas box per symbol, from BOX_WARMUP bars before its first needed bar (full history on a
    # full build; the desk itself builds the box on the last 252 sessions).
    top = np.full(n, np.nan)
    bottom = np.full(n, np.nan)
    for st, en in zip(starts, ends):
        hits = np.flatnonzero(need[st:en])
        if len(hits) == 0:
            continue
        s0 = st + max(0, int(hits[0]) - BOX_WARMUP)
        top[s0:en], bottom[s0:en] = calculate_darvas_box(high[s0:en], low[s0:en], boxp=5)
    e10_prev = np.r_[np.nan, e10[:-1]]
    e10_prev[pos == 0] = np.nan
    with np.errstate(divide="ignore", invalid="ignore"):
        sq = (top - e10) / top * 100.0
        rng = (high - low) / close * 100.0
    cand = need & (top > 0) & (e10 > 0) & (close > 0) & (sq >= 0) & (sq <= float(params["max_squeeze_pct"]))
    bar_ok = np.zeros(n, dtype=bool)
    failed_low = np.zeros(n, dtype=bool)
    ema_floor = np.full(n, np.nan)
    for i in np.flatnonzero(cand):
        rv = rvol[i]
        st = evaluate_squeeze_bar(
            close[i], top[i], bottom[i], e10[i], high=high[i], low=low[i], open_price=opn[i], ema20=e20[i],
            rvol=float(rv) if np.isfinite(rv) else None,
            ema10_prev=float(e10_prev[i]) if np.isfinite(e10_prev[i]) else None,
            max_candle_range_pct=None, cfg=params,
        )
        bar_ok[i] = st["qualifies"]
        failed_low[i] = st["failed_low"]
        ema_floor[i] = st["ema_floor"]
    # squeeze_frame(D) composition on each target bar.
    hit_any = np.zeros(n, dtype=bool)
    last_hit = np.full(n, -1, dtype=np.int64)
    for k in range(persist_n - 1, -1, -1):  # oldest first so the most recent hit wins
        j = np.arange(n) - k
        valid = (j >= 0) & (pos >= k)
        jj = np.where(valid, j, 0)
        h = valid & bar_ok[jj]
        hit_any |= h
        last_hit = np.where(h, jj, last_hit)
    still_in = np.isfinite(close) & np.isfinite(e10) & np.isfinite(top) & (top > 0) \
        & (close >= e10 * float(params["close_floor_tol"])) & (close <= top * float(params["ceiling_tol"]))
    persist_ok = hit_any & still_in
    persist_ok &= ~np.isfinite(rng) | (rng <= float(params["persist_max_range_pct"]))
    persist_ok &= ~np.isfinite(rvol) | (rvol <= float(params["persist_max_rvol"]))
    qualifies = (bar_ok | persist_ok) & (pos >= 4) & tgt
    signal = np.where(bar_ok, np.arange(n), last_hit)
    # squeeze_age: consecutive qualifying bars ending at i; box_age: consecutive identical TopBox.
    age = _run_length(bar_ok, pos, bar_ok)
    top_key = np.where(np.isfinite(top), top, -1.0)
    box_age = _run_length(top_key, pos, np.isfinite(top))
    sq5 = np.r_[np.full(5, np.nan), sq[:-5]] if n > 5 else np.full(n, np.nan)
    sq5[pos < 5] = np.nan
    idx = np.flatnonzero(qualifies)
    dates = ind["trade_date"].to_numpy()
    out = pd.DataFrame({
        "_row": idx, "signal_date": dates[signal[idx]], "trigger_price": top[idx],
        "stop_price": np.round(e10[idx] * SQUEEZE_STOP_FACTOR, 2),
    })
    out["features"] = [json.dumps({
        "darvas_top": _r(top[i]), "darvas_bottom": _r(bottom[i]), "squeeze_pct": _r(sq[i]),
        "squeeze_pct_5d_ago": _r(sq5[i]), "tightening": bool(np.isfinite(sq[i]) and np.isfinite(sq5[i]) and sq[i] < sq5[i]),
        "candle_range_pct": _r(rng[i]), "squeeze_age": int(age[i]), "box_age_sessions": int(box_age[i]),
        "failed_low": bool(failed_low[i]), "ema_floor": _r(ema_floor[i]), "persisted": bool(not bar_ok[i]),
    }) for i in idx]
    return out


def _run_length(values: np.ndarray, pos: np.ndarray, active: np.ndarray) -> np.ndarray:
    """Length of the run of equal `values` ending at each row (runs restart at each symbol's first
    row); 0 where `active` is False."""
    new_run = (pos == 0) | (values != np.r_[values[:1], values[:-1]])
    run_id = np.cumsum(new_run)
    length = pd.Series(np.ones(len(values))).groupby(run_id).cumsum().to_numpy(dtype=np.int64)
    return np.where(active, length, 0)


def _r(x: Any, nd: int = 4) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, nd) if np.isfinite(v) else None


# ---------------------------------------------------------------------------------------------
# Darvas 10 EMA
# ---------------------------------------------------------------------------------------------
def _windows(rows: np.ndarray, sym_start: np.ndarray, width: int) -> tuple[np.ndarray, np.ndarray]:
    """Concatenated row indices of the windows [max(start, r-width+1), r] and their owner ids."""
    lo = np.maximum(sym_start[rows], rows - width + 1)
    lengths = rows - lo + 1
    owner = np.repeat(np.arange(len(rows)), lengths)
    offsets = np.arange(lengths.sum()) - np.repeat(np.cumsum(lengths) - lengths, lengths)
    return np.repeat(lo, lengths) + offsets, owner


def _darvas_10ema(ind: pd.DataFrame, pool: np.ndarray, target: np.ndarray, exclude: np.ndarray, sym_start: np.ndarray) -> pd.DataFrame:
    n = len(ind)
    close = ind["close_price"].to_numpy(dtype=float)
    high = ind["high_price"].to_numpy(dtype=float)
    low = ind["low_price"].to_numpy(dtype=float)
    e10 = ind["ema_10"].to_numpy(dtype=float)
    pos = np.arange(n) - sym_start
    e10_prev = np.where(pos > 0, np.r_[np.nan, e10[:-1]], np.nan)
    # Necessary conditions checked first inside classify_darvas_10ema_frame (a strict superset filter).
    cand = pool & target & ~exclude & (pos >= 9) & (e10 > e10_prev) & (close > e10) & (high >= e10)
    rows = np.flatnonzero(cand)
    cols = ["open_price", "high_price", "low_price", "close_price", "volume", "ema_10", "rvol", "trade_date"]
    arrays = {c: ind[c].to_numpy() for c in cols}
    results = []
    for k in range(0, len(rows), CHUNK):
        chunk = rows[k:k + CHUNK]
        widx, owner = _windows(chunk, sym_start, EMA10_WINDOW)
        frame = pd.DataFrame({c: arrays[c][widx] for c in cols})
        frame.insert(0, "symbol", owner)
        res = classify_darvas_10ema_frame(frame)
        if res.empty:
            continue
        res["_row"] = chunk[res["symbol"].astype(int).to_numpy()]
        results.append(res)
    if not results:
        return pd.DataFrame(columns=["_row", "signal_date", "trigger_price", "stop_price", "features"])
    res = pd.concat(results, ignore_index=True)
    r = res["_row"].to_numpy()
    sig = pd.to_datetime(res["signal_date"]).to_numpy()
    dates = ind["trade_date"].to_numpy()
    # stop = lowest low from the signal (10 EMA touch) session to t; Catch-up has no touch.
    stops = np.full(len(res), np.nan)
    for j, (row, sd, fl) in enumerate(zip(r, sig, res["flavor"])):
        if fl == "Catch-up":
            continue
        lo = row
        while lo > sym_start[row] and dates[lo] > sd:
            lo -= 1
        stops[j] = np.nanmin(low[lo:row + 1])
    out = pd.DataFrame({"_row": r, "signal_date": sig, "trigger_price": high[r], "stop_price": stops})
    out["features"] = [json.dumps({"flavor": fl, "away_10ema_pct": _r(aw), "thrust_pct": _r(th), "ema_10": _r(e)})
                       for fl, aw, th, e in zip(res["flavor"], res["away_10ema_pct"], res["thrust_pct"], res["ema_10"])]
    return out


# ---------------------------------------------------------------------------------------------
# VCP
# ---------------------------------------------------------------------------------------------
def _vcp(ind: pd.DataFrame, pool: np.ndarray, target: np.ndarray, sym_start: np.ndarray) -> pd.DataFrame:
    n = len(ind)
    close = ind["close_price"].to_numpy(dtype=float)
    pos = np.arange(n) - sym_start
    away = num(ind, "away_52w_high_pct").to_numpy()
    avgv = num(ind, "avg_volume_20d").to_numpy()
    gate = (close >= float(VCP["min_close_price"])) \
        & (np.isnan(away) | (away >= float(VCP["max_away_52w_high_pct"]))) \
        & (np.isnan(avgv) | (avgv >= float(VCP["min_avg_volume_20d"])))
    cand = pool & target & gate & (pos >= 29)
    vol = pd.Series(ind["volume"].to_numpy(dtype=float))
    g = vol.groupby(ind["symbol"].to_numpy(), sort=False)
    v3 = g.rolling(3, min_periods=3).mean().reset_index(level=0, drop=True).sort_index().to_numpy()
    v20 = g.rolling(20, min_periods=20).mean().reset_index(level=0, drop=True).sort_index().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        vdu = np.where(v20 > 0, np.round(v3 / v20, 2), np.nan)
    ohlcv = pd.DataFrame({"trade_date": ind["trade_date"].to_numpy(), "high_price": ind["high_price"].to_numpy(dtype=float),
                          "low_price": ind["low_price"].to_numpy(dtype=float), "volume": ind["volume"].to_numpy(dtype=float)})
    dates = ind["trade_date"].to_numpy()
    recs = []
    for row in np.flatnonzero(cand):
        lo = max(sym_start[row], row - VCP_WINDOW + 1)
        seq = detect_contractions(ohlcv.iloc[lo:row + 1].reset_index(drop=True))
        if len(seq.contractions) < 2 or seq.pivot is None or seq.stop is None:
            continue
        c = close[row]
        if not (seq.stop < c <= seq.pivot):
            continue
        last = seq.contractions[-1]
        end_row = int(np.searchsorted(dates[lo:row + 1], np.datetime64(pd.Timestamp(last.end_date)))) + lo
        recs.append({
            "_row": row, "signal_date": pd.Timestamp(last.end_date), "trigger_price": float(seq.pivot),
            "stop_price": float(seq.stop),
            "features": json.dumps({
                "n_contractions": len(seq.contractions),
                "depths_pct": [round(x.depth_pct, 2) for x in seq.contractions],
                "bars": [x.bars for x in seq.contractions],
                "volume_ratios": [round(x.volume_ratio, 3) for x in seq.contractions],
                "weeks": seq.weeks, "footprint": seq.footprint, "vdu_ratio": _r(vdu[row], 2),
                "sessions_since_last_t": int(row - end_row),
            }),
        })
    if not recs:
        return pd.DataFrame(columns=["_row", "signal_date", "trigger_price", "stop_price", "features"])
    return pd.DataFrame(recs)


# ---------------------------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------------------------
def _identity(df: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    if df.empty:
        for c in ("setup_id", "first_seen", "setup_age_sessions", "status"):
            df[c] = pd.Series(dtype="object")
        return df
    si_map = pd.Series(np.arange(len(calendar)), index=calendar)
    df = df.sort_values(["queue", "symbol", "trade_date"], kind="mergesort").reset_index(drop=True)
    si = df["trade_date"].map(si_map).to_numpy(dtype=np.int64)
    same = (df["queue"].to_numpy() == np.r_[None, df["queue"].to_numpy()[:-1]]) \
        & (df["symbol"].to_numpy() == np.r_[None, df["symbol"].to_numpy()[:-1]])
    gap = np.where(same, si - np.r_[0, si[:-1]] - 1, 10**9)  # sessions absent before this row
    new_ep = gap >= IDENTITY_RESET_SESSIONS
    ep = np.cumsum(new_ep)
    first_idx = pd.Series(np.arange(len(df))).groupby(ep).transform("first").to_numpy()
    df["first_seen"] = df["trade_date"].to_numpy()[first_idx]
    df["setup_age_sessions"] = si - si[first_idx] + 1
    df["status"] = np.where(new_ep, "new", np.where(gap == 0, "active", "returning"))
    df["setup_id"] = df["queue"] + ":" + df["symbol"] + ":" + pd.to_datetime(df["first_seen"]).dt.strftime("%Y%m%d")
    return df


def build_setup_daily(
    indicators: pd.DataFrame,
    prices: pd.DataFrame | None = None,
    *,
    master: pd.DataFrame | None = None,
    reference: pd.DataFrame | None = None,
    since: Any = None,
    previous: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build setup_daily. Without `master` the market-cap/band pool gates are skipped (all other
    gates apply). `since`/`previous` enable incremental runs (see module docstring)."""
    ind = _frame(indicators, prices)
    if ind.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    calendar = pd.DatetimeIndex(sorted(ind["trade_date"].unique()))
    since_ts = pd.Timestamp(since).normalize() if since is not None else calendar[0]
    target = (ind["trade_date"] >= since_ts).to_numpy()
    pool, mcap, adv, basis = _pool(ind, master, reference, target)
    sym = ind["symbol"].to_numpy()
    starts = np.flatnonzero(np.r_[True, sym[1:] != sym[:-1]])
    sym_start = np.repeat(starts, np.diff(np.r_[starts, len(ind)]))

    sq = _darvas_squeeze(ind, pool, target)
    in_sq = np.zeros(len(ind), dtype=bool)
    in_sq[sq["_row"].to_numpy(dtype=np.int64)] = True
    e10 = _darvas_10ema(ind, pool, target, in_sq, sym_start)
    vcp = _vcp(ind, pool, target, sym_start)
    parts = []
    for q, frame in (("darvas_squeeze", sq), ("darvas_10ema", e10), ("vcp", vcp)):
        if frame.empty:
            continue
        frame = frame.copy()
        frame["queue"] = q
        parts.append(frame)
    new = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["_row", "signal_date", "trigger_price", "stop_price", "features", "queue"])
    r = new["_row"].to_numpy(dtype=np.int64)
    new["trade_date"] = ind["trade_date"].to_numpy()[r]
    new["symbol"] = sym[r]
    new["close_price"] = ind["close_price"].to_numpy(dtype=float)[r]
    for c in ("rvol", "delivery_pct", "avg_delivery_pct_20d", "rs_percentile", "away_52w_high_pct", "atr_pct"):
        new[c] = num(ind, c).to_numpy()[r]
    new["adv_cr"] = adv[r]
    new["mcap_cr"] = mcap[r]
    new["mcap_basis"] = basis[r]
    trig = pd.to_numeric(new["trigger_price"], errors="coerce")
    stop = pd.to_numeric(new["stop_price"], errors="coerce")
    new["trigger_price"] = trig
    new["stop_price"] = stop
    new["risk_pct"] = ((trig - stop) / trig * 100.0).where((trig > 0) & (stop > 0) & (stop < trig))
    new["distance_to_trigger_pct"] = ((trig / new["close_price"] - 1.0) * 100.0).where(new["close_price"] > 0)
    new["signal_date"] = pd.to_datetime(new["signal_date"]).dt.normalize()
    new = new.drop(columns=["_row"])

    if previous is not None and not previous.empty:
        prev = previous.copy()
        prev["trade_date"] = normalise_dates(prev["trade_date"])
        prev = prev[prev["trade_date"] < since_ts]
        keep = [c for c in OUTPUT_COLUMNS if c in prev.columns and c not in ("setup_id", "first_seen", "setup_age_sessions", "status")]
        new = pd.concat([prev[keep], new], ignore_index=True)
        calendar = pd.DatetimeIndex(sorted(set(calendar) | set(prev["trade_date"].unique())))
    out = _identity(new, calendar)
    out = out.sort_values(["trade_date", "queue", "symbol"], kind="mergesort").reset_index(drop=True)
    return out[OUTPUT_COLUMNS]
