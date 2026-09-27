"""Big movers (spec §7.6): events, pre-move fingerprint vs matched controls, lift, precision,
catalyst attribution, taxonomy studies and the pre-move watch.

Event definition
----------------
Confirmation days (all backward-looking, knowable on the day):
  * ``upper_circuit`` - high_t >= close_{t-1} x (1 + band/100) x 0.9995 (band as of t: security_reference_daily
    price_band <= 10 days old, else stocks_master band = current band, flagged ``band_basis``);
  * ``up30_20d`` - close_t >= 1.30 x the lowest close of the previous 20 sessions;
  * ``up50_60d`` - close_t >= 1.50 x the lowest close of the previous 60 sessions.
Confirmation days of one symbol form an *episode* until 20 sessions pass without one. The episode's first
confirmation day is ``confirmed_date``; the event date T (move start) is that day for an upper circuit, else
the session after the lowest close of the look-back window (never reaching into the previous episode).
T-1 is therefore the last pre-move close; move_pct = max close over T..T+59 vs close T-1.
Eligible events: series EQ, market cap at T-1 >= ₹1,000 Cr (point-in-time, see common.pit_mcap;
``mcap_basis`` says when it falls back to price-scaled current mcap), 20-day ADV at T-1 >= ₹1 Cr,
>= 60 sessions of history.

Fingerprint
-----------
Features (FEATURES) are computed for every stock-day from data dated <= that day, then read at
T-1, T-5, T-20, T-60. Controls: up to 3 per event, same T-1 date, same Industry (falls back to Broad
Industry, then Sector, then Industry / Broad Industry with an adjacent mcap quintile), same mcap quintile (that day, among eligible stock-days), no qualifying day in
[T-20, T+60]; seeded draw. Lift = P(rule | event) / P(rule | control) with n for both, on all events and on a
purged chronological split (train / 60-session embargo / test). Thresholds are fixed a priori (RULES);
a second threshold per feature is fitted on train only (quantile grid) and reported on test.
Precision: of eligible stock-days where the rule holds, the share with an eligible event starting in the
next 20 sessions (vs the base rate), test period.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from .common import (INSUFFICIENT, LEVEL_COLS, LEVELS, MCAP_FLOOR_CR, MIN_SAMPLE, QUADRANT_ORDER, VERDICT_ORDER,
                     grolling, gshift, purged_split, to_ts_col)

log = logging.getLogger(__name__)

EPISODE_GAP = 20
MIN_RULE_HITS = 10  # movers showing a trait before its lift is read
ADV_FLOOR_CR = 1.0
MIN_HISTORY = 60
N_CONTROLS = 3
OFFSETS = (1, 5, 20, 60)
PATH_OFFSETS = range(-60, 21)
PATH_FEATURES = ("close_rel_pct", "rs_percentile", "rvol", "delivery_pct", "range_10d_pct", "vol_dryup")
SEED = 42

# a-priori rules: feature -> (op, threshold, plain meaning)
RULES: dict[str, tuple[str, float, str]] = {
    "rs_percentile": (">=", 70, "strength rank >= 70"),
    "rs_delta_20": (">=", 10, "strength rank up >= 10 pts in 20 sessions"),
    "away_52w_high_pct": (">=", -10, "within 10% of the 52W high"),
    "range_50d_pct": ("<=", 25, "50-day base depth <= 25%"),
    "base_length": (">=", 40, ">= 40 sessions since the 120-day closing high"),
    "contraction": ("<=", 0.5, "10-day range <= half the 50-day range"),
    "atr_ratio": ("<=", 0.8, "ATR% <= 0.8 × its 50-day average"),
    "vol_dryup": ("<=", 0.7, "10-day volume <= 0.7 × 50-day"),
    "rvol": (">=", 1.5, "RVOL >= 1.5 on T-1"),
    "delivery_pct": (">=", 50, "delivery >= 50%"),
    "delivery_trend": (">=", 1.2, "5-day delivery % >= 1.2 × 20-day"),
    "delivery_spike": (">=", 1, "delivery spike"),
    "ret_20d": (">=", 10, "up >= 10% in 20 sessions"),
    "ema_stack": (">=", 1, "close > 50 EMA > 200 EMA"),
    "range_10d_pct": (">=", 15, "10-day range >= 15%"),
    "range_20d_pct": (">=", 25, "20-day range >= 25%"),
    "industry_leading": (">=", 1, "Industry in Leading quadrant"),
    "broad_industry_leading": (">=", 1, "Broad Industry in Leading quadrant"),
    "sector_leading": (">=", 1, "Sector in Leading quadrant"),
    "broad_sector_leading": (">=", 1, "Broad Sector in Leading quadrant"),
    "environment_ord": (">=", 3, "environment Constructive or better"),
    "deals_5d": (">=", 1, "bulk/block deal (ex-PROP) in the last 5 sessions"),
    "deal_net_buy_5d": (">=", 1, "net deal buying in the last 5 sessions"),
    "results_within_5": (">=", 1, "results board meeting within ±5 sessions (announced by t)"),
    "corp_action_within_5": (">=", 1, "corporate action ex-date within ±5 sessions (announced by t)"),
}
FEATURES = list(RULES)


# --------------------------------------------------------------------------
# Stock-day frame
# --------------------------------------------------------------------------
def _sessions(frame: pd.DataFrame) -> np.ndarray:
    return pd.DatetimeIndex(frame["trade_date"].unique()).sort_values().to_numpy()


def _gshift(s: pd.Series, g: np.ndarray, k: int) -> pd.Series:
    return pd.Series(gshift(s.to_numpy(float), g, k), index=s.index)


def _sessions_since_flag(flag: np.ndarray, grp: np.ndarray) -> np.ndarray:
    """Rows since the last True in flag within each group (NaN before the first)."""
    idx = np.arange(len(flag), dtype=float)
    last = pd.Series(np.where(flag, idx, np.nan)).groupby(grp).ffill().to_numpy()
    return idx - last


def stock_day_frame(ind: pd.DataFrame, *, mcap: pd.DataFrame, master: pd.DataFrame | None,
                    reference: pd.DataFrame | None, env: pd.DataFrame, group_levels: dict[str, pd.DataFrame],
                    deals: pd.DataFrame | None, pr: dict | None, events_tbl: pd.DataFrame | None,
                    corp_actions: pd.DataFrame | None) -> pd.DataFrame:
    """Point-in-time features for every stock-day (rows sorted by symbol, trade_date)."""
    d = ind
    if not (d.index.equals(pd.RangeIndex(len(d))) and d["symbol"].is_monotonic_increasing):
        d = d.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    sym = d["symbol"].to_numpy()
    grp = pd.factorize(sym)[0]
    out = to_ts_col(pd.DataFrame({"symbol": d["symbol"], "series": d["series"], "trade_date": d["trade_date"]}), "trade_date")
    out["row_in_symbol"] = pd.Series(np.ones(len(d))).groupby(grp).cumsum().to_numpy() - 1
    c = d["close_price"].astype(float)
    out["close_price"] = c
    out["high_price"] = d["high_price"].astype(float)
    out["prev_close"] = _gshift(c, grp, 1)
    # `mcap` is common.pit_mcap(ind) on the same (symbol, trade_date)-sorted rows
    mk = mcap[["symbol", "trade_date", "mcap_cr", "mcap_basis"]]
    if len(mk) != len(d) or not (mk["symbol"].to_numpy() == d["symbol"].to_numpy()).all():
        mk = d[["symbol", "trade_date"]].merge(mk, on=["symbol", "trade_date"], how="left")
    out["mcap_cr"] = mk["mcap_cr"].to_numpy(float)
    out["mcap_basis"] = mk["mcap_basis"].to_numpy()
    out["adv_cr"] = pd.to_numeric(d["avg_traded_value_cr_20d"], errors="coerce").fillna(
        pd.to_numeric(d["turnover_cr"], errors="coerce")).astype("float32")
    f = lambda col: pd.to_numeric(d[col], errors="coerce").astype("float32")  # noqa: E731
    out["rs_percentile"] = f("rs_percentile")
    out["rs_delta_20"] = (out["rs_percentile"] - _gshift(out["rs_percentile"], grp, 20)).astype("float32")
    out["away_52w_high_pct"] = f("away_52w_high_pct")
    out["range_10d_pct"] = f("range_10d_pct")
    out["range_20d_pct"] = f("range_20d_pct")
    out["range_50d_pct"] = f("range_50d_pct")
    roll_max = pd.Series(grolling(c.to_numpy(float), grp, 120, "max", 20))
    out["base_length"] = _sessions_since_flag((c >= roll_max).to_numpy(), grp).astype("float32")
    out.loc[roll_max.isna().to_numpy(), "base_length"] = np.nan
    with np.errstate(invalid="ignore", divide="ignore"):
        out["contraction"] = (out["range_10d_pct"] / out["range_50d_pct"].where(out["range_50d_pct"] > 0)).astype("float32")
        out["atr_ratio"] = (f("atr_pct") / f("atr_pct_avg_50d").where(f("atr_pct_avg_50d") > 0)).astype("float32")
        out["vol_dryup"] = (f("avg_volume_10d") / f("avg_volume_50d").where(f("avg_volume_50d") > 0)).astype("float32")
    out["rvol"] = f("rvol")
    out["delivery_pct"] = f("delivery_pct")
    dp5 = pd.Series(grolling(out["delivery_pct"].to_numpy(float), grp, 5, "mean", 3))
    adp = f("avg_delivery_pct_20d")
    out["delivery_trend"] = (dp5 / adp.where(adp > 0)).astype("float32")
    ds = d["delivery_spike"]
    out["delivery_spike"] = pd.Series(ds, dtype="boolean").astype("Float32").astype("float32")
    out["ret_20d"] = ((c / _gshift(c, grp, 20) - 1) * 100).astype("float32")
    e50, e200 = f("ema_50"), f("ema_200")
    stack = ((c > e50) & (e50 > e200)).astype("float32")
    out["ema_stack"] = stack.where(e50.notna() & e200.notna())
    # taxonomy (current mapping) and group state at all four levels
    if master is not None and not master.empty:
        tax = master.drop_duplicates("symbol").set_index("symbol")
        for col in LEVEL_COLS.values():
            out[col] = out["symbol"].map(tax[col]) if col in tax.columns else None
        if "band" in tax.columns:
            out["band_current"] = out["symbol"].map(tax["band"]).astype(float)
    for level in LEVELS:
        gs = group_levels.get(level)
        col = LEVEL_COLS[level]
        name = f"{col}_leading"
        if gs is None or gs.empty or col not in out.columns:
            out[name] = np.nan
            continue
        mm = out[["trade_date", col]].merge(gs.rename(columns={"group_name": col}), on=["trade_date", col], how="left")
        q = mm["group_quadrant"]
        out[name] = np.where(q.notna(), (q == "Leading").astype(float), np.nan).astype("float32")
        if level == "Industry":
            out["industry_quadrant"] = q.to_numpy()
    if not env.empty:
        em = out[["trade_date"]].merge(env, on="trade_date", how="left")
        out["environment_state"] = em["environment_state"].to_numpy()
        out["environment_ord"] = em["environment_state"].map(VERDICT_ORDER).astype("float32").to_numpy()
    else:
        out["environment_state"], out["environment_ord"] = None, np.nan
    # band (for upper circuit)
    out["band"] = np.nan
    out["band_basis"] = None
    if reference is not None and not reference.empty and "price_band" in reference.columns:
        r = reference.dropna(subset=["price_band"])[["symbol", "effective_date", "price_band"]].sort_values("effective_date")
        need = out[["symbol", "trade_date"]].reset_index().sort_values("trade_date")
        need["symbol"] = need["symbol"].astype(str)
        r = r.assign(symbol=r["symbol"].astype(str), effective_date=pd.to_datetime(r["effective_date"]).astype("datetime64[ns]"))
        mm = pd.merge_asof(need, r, left_on="trade_date", right_on="effective_date", by="symbol",
                           direction="backward", tolerance=pd.Timedelta(days=10)).dropna(subset=["price_band"])
        out.loc[mm["index"].to_numpy(), "band"] = mm["price_band"].to_numpy(float)
        out.loc[mm["index"].to_numpy(), "band_basis"] = "reference_asof"
    if "band_current" in out.columns:
        miss = out["band_basis"].isna() & out["band_current"].notna()
        out.loc[miss, "band"] = out.loc[miss, "band_current"]
        out.loc[miss, "band_basis"] = "current_master"
    # deals (ex-PROP) in the last 5 sessions; NULL before deal coverage starts
    out["deals_5d"] = np.nan
    out["deal_net_buy_5d"] = np.nan
    if deals is not None and not deals.empty:
        dl = deals.copy()
        if "clientele" in dl.columns:
            dl = dl.loc[dl["clientele"].astype(str).str.upper() != "PROP"]
        dl["signed"] = np.where(dl["side"].astype(str).str.startswith("B"), 1.0, -1.0) * pd.to_numeric(dl["value_cr"], errors="coerce")
        per = dl.groupby(["symbol", "trade_date"]).agg(n=("signed", "size"), net=("signed", "sum")).reset_index()
        mm = out[["symbol", "trade_date"]].merge(per, on=["symbol", "trade_date"], how="left")
        n_day = mm["n"].fillna(0).to_numpy(float)
        net_day = mm["net"].fillna(0).to_numpy(float)
        n5 = grolling(n_day, grp, 5, "sum", 1)
        net5 = grolling(net_day, grp, 5, "sum", 1)
        start = pd.Timestamp(deals["trade_date"].min()) + pd.Timedelta(days=7)
        cov = (out["trade_date"] >= start).to_numpy()
        out.loc[cov, "deals_5d"] = n5[cov]
        out.loc[cov, "deal_net_buy_5d"] = (net5[cov] > 0).astype(float)
    # results board meetings / corporate actions near t, known by t (PR archive; security_events fallback)
    out["results_within_5"] = np.nan
    out["corp_action_within_5"] = np.nan
    bm, ca, cov_start, cov_end = _catalyst_sources(pr, events_tbl, corp_actions)
    sess = pd.Series(_sessions(out))
    if bm is not None and not bm.empty:
        out["results_within_5"] = _near_known(out, bm, "meeting_date", sess, cov_start, cov_end)
    if ca is not None and not ca.empty:
        out["corp_action_within_5"] = _near_known(out, ca, "ex_date", sess, cov_start, cov_end)
    return out


def _catalyst_sources(pr: dict | None, events_tbl: pd.DataFrame | None, corp_actions: pd.DataFrame | None):
    bm = ca = None
    cov_start = cov_end = None
    if pr is not None:
        b = pr.get("board_meetings")
        if b is not None and not b.empty:
            bm = b.loc[b["purpose"].str.contains("result", case=False, na=False), ["symbol", "meeting_date", "known_date"]]
        c = pr.get("corp_actions")
        if c is not None and not c.empty:
            keep = c["purpose"].str.contains("bonus|split|sub-div|rights|buy ?back|demerg|amalgam|scheme", case=False, na=False)
            ca = c.loc[keep, ["symbol", "ex_date", "known_date"]]
        files = pr.get("files")
        if files is not None and not files.empty:
            cov_start, cov_end = files["trade_date"].min(), files["trade_date"].max()
    if bm is None and events_tbl is not None and not events_tbl.empty:
        e = events_tbl.loc[events_tbl["event_type"].isin(["financial_results", "board_meeting"])]
        bm = pd.DataFrame({"symbol": e["symbol"], "meeting_date": e["event_date"], "known_date": e["event_date"]})
        cov_start, cov_end = events_tbl["event_date"].min(), events_tbl["event_date"].max()
    if ca is None and corp_actions is not None and not corp_actions.empty:
        c = corp_actions.loc[corp_actions["action_type"].isin(["bonus", "split", "rights_issue", "merger_demerger"])]
        ca = pd.DataFrame({"symbol": c["symbol"], "ex_date": c["ex_date"], "known_date": c["ex_date"] - pd.Timedelta(days=14)})
    return bm, ca, cov_start, cov_end


def _near_known(out: pd.DataFrame, ev: pd.DataFrame, date_col: str, sess: pd.Series, cov_start, cov_end,
                window: int = 5) -> np.ndarray:
    """1.0 if an event for the symbol falls within ±window sessions of t and was known (known_date <= t);
    0.0 inside source coverage; NaN outside coverage."""
    sidx = pd.Series(np.arange(len(sess)), index=pd.DatetimeIndex(sess))
    e = ev.dropna(subset=[date_col]).copy()
    e["ev_s"] = np.searchsorted(sess.to_numpy(), e[date_col].to_numpy(), side="left")
    res = np.zeros(len(out), dtype="float32")
    t_s = sidx.reindex(pd.DatetimeIndex(out["trade_date"])).to_numpy()
    rowmap = pd.Series(np.arange(len(out)), index=pd.MultiIndex.from_arrays([out["symbol"].to_numpy(), t_s]))
    rowmap = rowmap[~rowmap.index.duplicated()]
    # expand each event to the sessions within ±window of it, then look those stock-days up
    offs = np.arange(-window, window + 1)
    sym = np.repeat(e["symbol"].to_numpy(), len(offs))
    ts_ = np.repeat(e["ev_s"].to_numpy(), len(offs)) + np.tile(offs, len(e))
    known = np.repeat(e["known_date"].to_numpy(), len(offs))
    rows = rowmap.reindex(pd.MultiIndex.from_arrays([sym, ts_])).to_numpy()
    ok = np.isfinite(rows)
    rows_i = rows[ok].astype(np.int64)
    hit = known[ok] <= out["trade_date"].to_numpy()[rows_i]
    res[np.unique(rows_i[hit])] = 1.0
    if cov_start is not None:
        outside = (out["trade_date"] < pd.Timestamp(cov_start)) | (out["trade_date"] > pd.Timestamp(cov_end))
        res[outside.to_numpy()] = np.nan
    return res


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------
def _fwd_max(c: pd.Series, grp: np.ndarray, h: int) -> pd.Series:
    """max(c_t … c_{t+h-1}) per group; NaN if fewer than h forward rows."""
    return pd.Series(grolling(c.to_numpy(float), grp, h, "max", h, reverse=True), index=c.index)


def label_events(sd: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (events, per-stock-day flags q / uc / up30 / up50 / start). See module docstring."""
    grp = pd.factorize(sd["symbol"].to_numpy())[0]
    c = sd["close_price"]
    cc = c.to_numpy(float)
    pc = sd["prev_close"]
    band = sd["band"]
    n = len(sd)
    uc = (band.notna() & pc.notna() & (sd["high_price"] >= pc * (1 + band / 100) * 0.9995)).to_numpy()
    prior = gshift(cc, grp, 1)
    min20 = grolling(prior, grp, 20, "min", 1)
    min60 = grolling(prior, grp, 60, "min", 1)
    with np.errstate(invalid="ignore"):
        up30 = np.nan_to_num(cc >= 1.30 * min20, nan=0).astype(bool)
        up50 = np.nan_to_num(cc >= 1.50 * min60, nan=0).astype(bool)
    q = uc | up30 | up50
    same_prev = np.r_[False, grp[1:] == grp[:-1]]
    since = _sessions_since_flag(np.r_[False, q[:-1]] & same_prev, grp)
    prev_q_gap = np.where(np.isnan(since), np.inf, since + 1)
    first_q = q & (prev_q_gap > EPISODE_GAP)  # confirmation day c0 of a new episode
    rig = sd["row_in_symbol"].to_numpy(int)
    dates = sd["trade_date"].to_numpy()
    c0s = np.flatnonzero(first_q)
    lqb = pd.Series(np.where(q, np.arange(n), np.nan)).groupby(grp).ffill().groupby(grp).shift(1).to_numpy()
    starts, trig, confirmed = [], [], []
    for c0 in c0s:
        if uc[c0]:
            t, tg = c0, "upper_circuit"
        else:
            L = 20 if up30[c0] else 60
            lo = c0 - min(L, rig[c0])
            if np.isfinite(lqb[c0]):
                lo = max(lo, int(lqb[c0]) + 1)  # never reach back into the previous episode
            win = cc[lo:c0]
            t = (lo + int(np.nanargmin(win)) + 1) if len(win) and np.isfinite(win).any() else c0
            tg = "up30_20d" if up30[c0] else "up50_60d"
        starts.append(min(t, c0))
        trig.append(tg)
        confirmed.append(dates[c0])
    pos = np.asarray(starts, dtype=np.int64)
    start = np.zeros(n, bool)
    start[pos] = True
    flags = pd.DataFrame({"q": q, "uc": uc, "up30": up30, "up50": up50, "start": start}, index=sd.index)
    ev = sd.iloc[pos][["symbol", "series", "trade_date", "adv_cr", "band", "band_basis", "row_in_symbol",
                       *[c_ for c_ in LEVEL_COLS.values() if c_ in sd.columns],
                       *[c_ for c_ in ("environment_state", "industry_quadrant") if c_ in sd.columns]]].copy()
    prev = np.maximum(pos - 1, 0)
    ok_prev = (pos - 1 >= 0) & (grp[prev] == grp[pos])
    ev["mcap_cr_at_event"] = np.where(ok_prev, sd["mcap_cr"].to_numpy(float)[prev], np.nan)
    ev["mcap_basis"] = np.where(ok_prev, sd["mcap_basis"].to_numpy()[prev], None)
    ev["adv_cr_t1"] = np.where(ok_prev, sd["adv_cr"].to_numpy(float)[prev], np.nan)
    ev["trigger"] = trig
    ev["confirmed_date"] = pd.to_datetime(confirmed)
    moves, peaks, m20, streak, wend = [], [], [], [], []
    for p, okp in zip(pos, ok_prev):
        g = grp[p]
        e60 = p
        while e60 + 1 < n and e60 - p < 59 and grp[e60 + 1] == g:
            e60 += 1
        win = cc[p:e60 + 1]
        j = int(np.nanargmax(win)) if np.isfinite(win).any() else 0
        base = cc[p - 1] if okp else np.nan
        moves.append((win[j] / base - 1) * 100)
        peaks.append(dates[p + j])
        m20.append((np.nanmax(cc[p:min(e60, p + 19) + 1]) / base - 1) * 100)
        k = 0
        while p + k < n and grp[p + k] == g and uc[p + k]:
            k += 1
        streak.append(k)
        wend.append(dates[e60] if e60 - p == 59 else np.datetime64("NaT"))
    ev["move_pct"] = moves
    ev["move_20d_pct"] = m20
    ev["peak_date"] = pd.to_datetime(peaks)
    ev["uc_streak"] = streak
    ev["window_end_date"] = pd.to_datetime(wend)
    ev = ev.rename(columns={"trade_date": "event_date"})
    ev["eligible"] = ((ev["series"] == "EQ") & (ev["mcap_cr_at_event"] >= MCAP_FLOOR_CR) & (ev["adv_cr_t1"] >= ADV_FLOOR_CR)
                      & (ev["row_in_symbol"] >= MIN_HISTORY))
    ev["event_id"] = ev["symbol"] + ":" + pd.to_datetime(ev["event_date"]).dt.strftime("%Y%m%d")
    ev["_pos"] = pos
    ev = ev.drop_duplicates("event_id")
    return ev.reset_index(drop=True), flags


def eligible_mask(sd: pd.DataFrame) -> np.ndarray:
    return ((sd["series"] == "EQ") & (sd["mcap_cr"] >= MCAP_FLOOR_CR) & (sd["adv_cr"] >= ADV_FLOOR_CR)
            & (sd["row_in_symbol"] >= MIN_HISTORY)).to_numpy()


# --------------------------------------------------------------------------
# Controls
# --------------------------------------------------------------------------
def match_controls(sd: pd.DataFrame, events: pd.DataFrame, flags: pd.DataFrame, n_controls: int = N_CONTROLS,
                   seed: int = SEED) -> pd.DataFrame:
    """(event_id, control_symbol, control_pos_t, match_level) — control row = the control's T-1 row."""
    grp = pd.factorize(sd["symbol"].to_numpy())[0]
    elig = eligible_mask(sd)
    q = flags["q"].to_numpy()
    # dirty window: any qualifying day in [t-20, t+60] relative to the candidate's T-1 row t (≈ event T-1)
    qs = pd.Series(q.astype(np.int8))
    back = grolling(qs.to_numpy(float), grp, 21, "max", 1)
    fwd = grolling(qs.to_numpy(float), grp, 62, "max", 1, reverse=True)
    clean = (back == 0) & (fwd == 0)
    cand = pd.DataFrame({"pos": np.arange(len(sd)), "symbol": sd["symbol"].to_numpy(), "trade_date": sd["trade_date"].to_numpy(),
                         "mcap": sd["mcap_cr"].to_numpy()})
    for col in ("industry", "broad_industry", "sector"):
        cand[col] = sd[col].to_numpy() if col in sd.columns else None
    cand = cand.loc[elig & clean]
    # mcap quintile per date among all eligible stock-days
    allq = pd.DataFrame({"trade_date": sd["trade_date"].to_numpy()[elig], "mcap": sd["mcap_cr"].to_numpy()[elig]})
    edges = allq.groupby("trade_date")["mcap"].quantile([0.2, 0.4, 0.6, 0.8]).unstack()
    def _bucket(dates: pd.Series, mcap: np.ndarray) -> np.ndarray:
        e = edges.reindex(pd.DatetimeIndex(dates)).to_numpy()
        return np.where(np.isnan(e).all(axis=1), -1, (mcap[:, None] > e).sum(axis=1))
    cand["bucket"] = _bucket(cand["trade_date"], cand["mcap"].to_numpy(float))
    ev = events.loc[events["eligible"]].copy()
    ev["t1_date"] = sd["trade_date"].to_numpy()[ev["_pos"].to_numpy() - 1]
    ev["bucket"] = _bucket(ev["t1_date"], ev["mcap_cr_at_event"].to_numpy(float))
    rng = np.random.default_rng(seed)
    cand = cand.assign(_r=rng.random(len(cand)))
    left = ev[["event_id", "symbol", "t1_date", "bucket", *[c for c in ("industry", "broad_industry", "sector") if c in ev.columns]]]
    parts = []
    done: set = set()
    for col, tol in (("industry", 0), ("broad_industry", 0), ("sector", 0), ("industry", 1), ("broad_industry", 1)):
        if col not in left.columns:
            continue
        todo = left.loc[~left["event_id"].isin(done) & left[col].notna()]
        if todo.empty:
            continue
        m = todo.merge(cand[["pos", "symbol", "trade_date", "bucket", col, "_r"]].rename(
            columns={"symbol": "control_symbol", "trade_date": "t1_date", "bucket": "c_bucket"}), on=["t1_date", col], how="inner")
        m = m.loc[(m["control_symbol"] != m["symbol"]) & ((m["c_bucket"] - m["bucket"]).abs() <= tol)]
        if m.empty:
            continue
        m = m.sort_values(["event_id", "_r"])
        m = m.loc[m.groupby("event_id").cumcount() < n_controls]
        m["match_level"] = f"{col}+mcap_quintile" + ("" if tol == 0 else "+-1")
        parts.append(m[["event_id", "control_symbol", "pos", "match_level"]].rename(columns={"pos": "control_pos_t1"}))
        done |= set(m["event_id"])
    recs = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(
        columns=["event_id", "control_symbol", "control_pos_t1", "match_level"])
    return pd.DataFrame(recs, columns=["event_id", "control_symbol", "control_pos_t1", "match_level"])


# --------------------------------------------------------------------------
# Features at offsets, lift, precision
# --------------------------------------------------------------------------
def _rows_at(sd_sym_codes: np.ndarray, base_pos: np.ndarray, delta: int) -> np.ndarray:
    p = base_pos + delta
    ok = (p >= 0) & (p < len(sd_sym_codes))
    pc = np.clip(p, 0, len(sd_sym_codes) - 1)
    ok &= sd_sym_codes[pc] == sd_sym_codes[np.clip(base_pos, 0, len(sd_sym_codes) - 1)]
    return np.where(ok, pc, -1)


def fingerprint_rows(sd: pd.DataFrame, events: pd.DataFrame, controls: pd.DataFrame) -> pd.DataFrame:
    """Wide frame: one row per (event_id, role, symbol, offset) with FEATURES."""
    codes = pd.factorize(sd["symbol"].to_numpy())[0]
    ev = events.loc[events["eligible"]]
    base = [pd.DataFrame({"event_id": ev["event_id"].to_numpy(), "role": "event", "symbol": ev["symbol"].to_numpy(),
                          "t1": ev["_pos"].to_numpy() - 1, "event_date": ev["event_date"].to_numpy()})]
    if not controls.empty:
        edate = ev.set_index("event_id")["event_date"]
        base.append(pd.DataFrame({"event_id": controls["event_id"].to_numpy(), "role": "control",
                                  "symbol": controls["control_symbol"].to_numpy(), "t1": controls["control_pos_t1"].to_numpy(),
                                  "event_date": controls["event_id"].map(edate).to_numpy()}))
    b = pd.concat(base, ignore_index=True)
    parts = []
    feat = sd[FEATURES].to_numpy(dtype="float32")
    for off in OFFSETS:
        rows = _rows_at(codes, b["t1"].to_numpy(), -(off - 1))
        part = b[["event_id", "role", "symbol", "event_date"]].copy()
        part["offset"] = off
        vals = np.where((rows >= 0)[:, None], feat[np.maximum(rows, 0)], np.nan)
        part[FEATURES] = vals
        parts.append(part)
    return pd.concat(parts, ignore_index=True)


def _rule(values: np.ndarray, op: str, thr: float) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        return values >= thr if op == ">=" else values <= thr


def _rates(ev: np.ndarray, ct: np.ndarray, op: str, thr: float) -> tuple[float | None, float | None, float | None, int, int]:
    e = ev[np.isfinite(ev)]
    c = ct[np.isfinite(ct)]
    if len(e) == 0 or len(c) == 0:
        return None, None, None, len(e), len(c)
    er = float(_rule(e, op, thr).mean())
    cr = float(_rule(c, op, thr).mean())
    lift = er / cr if cr > 0 else None
    return er, cr, lift, len(e), len(c)


def lift_table(fp: pd.DataFrame, sessions: pd.Series, offset: int = 1) -> tuple[pd.DataFrame, pd.Timestamp | None]:
    f = fp.loc[fp["offset"] == offset]
    train, test, test_start = purged_split(f["event_date"], sessions=sessions)
    recs = []
    for feat, (op, thr, meaning) in RULES.items():
        rec = {"feature": feat, "offset": offset, "rule": f"{feat} {op} {thr:g}", "meaning": meaning}
        for tag, mask in (("all", np.ones(len(f), bool)), ("train", train.to_numpy()), ("test", test.to_numpy())):
            sub = f.loc[mask]
            ev = sub.loc[sub["role"] == "event", feat].to_numpy(float)
            ct = sub.loc[sub["role"] == "control", feat].to_numpy(float)
            er, cr, lift, ne, nc = _rates(ev, ct, op, thr)
            sfx = "" if tag == "all" else f"_{tag}"
            k_e = int(round(er * ne)) if er is not None else 0
            k_c = int(round(cr * nc)) if cr is not None else 0
            rec.update({f"event_rate{sfx}": er, f"control_rate{sfx}": cr, f"lift{sfx}": lift,
                        f"n_events{sfx}": ne, f"n_controls{sfx}": nc, f"k_events{sfx}": k_e, f"k_controls{sfx}": k_c})
            if tag == "all":
                rec["event_median"] = float(np.nanmedian(ev)) if np.isfinite(ev).any() else None
                rec["control_median"] = float(np.nanmedian(ct)) if np.isfinite(ct).any() else None
        # threshold fitted on train only (quantile grid), evaluated on test (purged split)
        tr = f.loc[train.to_numpy()]
        ev_tr = tr.loc[tr["role"] == "event", feat].to_numpy(float)
        ct_tr = tr.loc[tr["role"] == "control", feat].to_numpy(float)
        best = None
        pooled = np.concatenate([ev_tr[np.isfinite(ev_tr)], ct_tr[np.isfinite(ct_tr)]])
        if len(pooled) >= 2 * MIN_SAMPLE and len(np.unique(pooled)) > 2:
            for qq in np.linspace(0.1, 0.9, 9):
                thr_q = float(np.quantile(pooled, qq))
                er, cr, lift, ne, nc = _rates(ev_tr, ct_tr, op, thr_q)
                if lift is None or er is None or er < 0.10 or ne < MIN_SAMPLE:
                    continue
                if best is None or lift > best[1]:
                    best = (thr_q, lift)
        if best is not None:
            te = f.loc[test.to_numpy()]
            er, cr, lift, ne, nc = _rates(te.loc[te["role"] == "event", feat].to_numpy(float),
                                          te.loc[te["role"] == "control", feat].to_numpy(float), op, best[0])
            rec.update({"fit_threshold": best[0], "fit_lift_train": best[1], "fit_lift_test": lift})
        # stable out of sample: >= 30 movers with data and >= MIN_RULE_HITS movers showing the trait in both halves
        n_ok = (min(rec.get("n_events_train") or 0, rec.get("n_events_test") or 0) >= MIN_SAMPLE
                and min(rec.get("k_events_train") or 0, rec.get("k_events_test") or 0) >= MIN_RULE_HITS)
        rec["stable_oos"] = bool(n_ok and (rec.get("lift_train") or 0) >= 1.2 and (rec.get("lift_test") or 0) >= 1.2)
        rec["label"] = None if ((rec.get("n_events") or 0) >= MIN_SAMPLE and (rec.get("k_events") or 0) >= MIN_RULE_HITS)             else INSUFFICIENT
        recs.append(rec)
    out = pd.DataFrame(recs)
    out["_ins"] = out["label"].notna()
    out = out.sort_values(["_ins", "lift"], ascending=[True, False], na_position="last").drop(columns=["_ins"])
    return out.reset_index(drop=True), test_start


def forward_event_label(sd: pd.DataFrame, events: pd.DataFrame, horizon: int = 20) -> np.ndarray:
    """1 if an eligible event of the same symbol starts within the next `horizon` rows; NaN if too few rows left."""
    grp = pd.factorize(sd["symbol"].to_numpy())[0]
    flag = np.zeros(len(sd), dtype=np.int8)
    ev = events.loc[events["eligible"], "_pos"].to_numpy()
    flag[ev] = 1
    s = pd.Series(flag)
    win = pd.Series(grolling(s.to_numpy(float), grp, horizon, "max", horizon, reverse=True))  # rows t … t+h-1
    return win.groupby(grp).shift(-1).to_numpy(float)  # rows t+1 … t+h


def _rule_mask(sd: pd.DataFrame, feats: list[str], how: str) -> np.ndarray:
    hits = []
    for ft in feats:
        op, thr, _ = RULES[ft]
        v = sd[ft].to_numpy(float)
        hits.append(np.isfinite(v) & _rule(v, op, thr))
    if how == "any2":
        return np.sum(hits, axis=0) >= 2
    return np.logical_and.reduce(hits)


def precision_table(sd: pd.DataFrame, label: np.ndarray, lift: pd.DataFrame, sessions: pd.Series,
                    top: int = 3) -> tuple[pd.DataFrame, list[str], dict | None]:
    """Precision of trait rules over eligible stock-days: P(event starts within 20 sessions | rule), percent.

    Traits = the `top` features ranked by TRAIN lift (>= 10 trait hits, lift >= 1.2); the combination rule for
    the watch list is chosen on TRAIN precision and reported on TEST (purged split), so the printed
    precision is out of sample."""
    elig = eligible_mask(sd) & np.isfinite(label)
    train_m, test_m, test_start = purged_split(sd["trade_date"], sessions=sessions)
    train = elig & train_m.to_numpy()
    test = elig & test_m.to_numpy()
    base_tr = float(label[train].mean() * 100) if train.any() else None
    base_te = float(label[test].mean() * 100) if test.any() else None
    cand = lift.loc[(lift["k_events_train"].fillna(0) >= MIN_RULE_HITS) & (lift["lift_train"].fillna(0) >= 1.2)]
    traits = cand.sort_values("lift_train", ascending=False)["feature"].head(top).tolist()
    rules: list[tuple[str, list[str], str]] = [(f, [f], "all") for f in lift["feature"]]
    if len(traits) >= 2:
        from itertools import combinations
        for pair in combinations(traits, 2):
            rules.append((" & ".join(pair), list(pair), "all"))
        if len(traits) >= 3:
            rules.append((" & ".join(traits), traits, "all"))
            rules.append((f">=2 of {', '.join(traits)}", traits, "any2"))
    recs = []
    for name, feats, how in rules:
        m = _rule_mask(sd, feats, how)
        mtr, mte = m & train, m & test
        ntr, nte = int(mtr.sum()), int(mte.sum())
        ptr = float(label[mtr].mean() * 100) if ntr else None
        pte = float(label[mte].mean() * 100) if nte else None
        recs.append({"rule": name, "traits": feats, "combo": len(feats) > 1,
                     "n_train": ntr, "precision_train": ptr, "base_rate_train": base_tr,
                     "precision_lift_train": (ptr / base_tr) if (ptr is not None and base_tr) else None,
                     "n_stock_days": nte, "precision_20d": pte, "base_rate_20d": base_te,
                     "precision_lift": (pte / base_te) if (pte is not None and base_te) else None,
                     "period_start": test_start, "label": None if nte >= MIN_SAMPLE else INSUFFICIENT})
    out = pd.DataFrame(recs)
    out["selected"] = False
    combos = out.loc[out["combo"] & (out["n_train"] >= MIN_SAMPLE)]
    chosen = None
    if not combos.empty and combos["precision_lift_train"].notna().any():
        i = combos["precision_lift_train"].idxmax()
        out.loc[i, "selected"] = True
        chosen = out.loc[i].to_dict()
    out = out.sort_values(["selected", "precision_lift"], ascending=[False, False], na_position="last").reset_index(drop=True)
    return out, traits, chosen


def price_paths(sd: pd.DataFrame, events: pd.DataFrame) -> list:
    """Per event: close at T-60 … T+20 as % change vs the T-1 close (None where no bar)."""
    codes = pd.factorize(sd["symbol"].to_numpy())[0]
    base = events["_pos"].to_numpy()
    close = sd["close_price"].to_numpy(float)
    ref = _rows_at(codes, base, -1)
    refc = np.where(ref >= 0, close[np.maximum(ref, 0)], np.nan)
    offs = list(PATH_OFFSETS)
    mat = np.full((len(base), len(offs)), np.nan)
    for j, off in enumerate(offs):
        rows = _rows_at(codes, base, off)
        mat[:, j] = np.where(rows >= 0, close[np.maximum(rows, 0)] / refc * 100 - 100, np.nan)
    return [[None if not np.isfinite(x) else round(float(x), 2) for x in row] for row in mat]


def feature_paths(sd: pd.DataFrame, events: pd.DataFrame, controls: pd.DataFrame) -> pd.DataFrame:
    codes = pd.factorize(sd["symbol"].to_numpy())[0]
    ev = events.loc[events["eligible"]]
    t0 = {"event": ev["_pos"].to_numpy(), "control": controls["control_pos_t1"].to_numpy() + 1 if not controls.empty else np.array([], int)}
    close = sd["close_price"].to_numpy(float)
    recs = []
    for role, base in t0.items():
        if len(base) == 0:
            continue
        ref = _rows_at(codes, base, -1)
        refc = np.where(ref >= 0, close[np.maximum(ref, 0)], np.nan)
        for off in PATH_OFFSETS:
            rows = _rows_at(codes, base, off)
            ok = rows >= 0
            for feat in PATH_FEATURES:
                if feat == "close_rel_pct":
                    v = np.where(ok, close[np.maximum(rows, 0)] / refc * 100 - 100, np.nan)
                else:
                    v = np.where(ok, sd[feat].to_numpy(float)[np.maximum(rows, 0)], np.nan)
                v = v[np.isfinite(v)]
                recs.append({"role": role, "offset": off, "feature": feat, "n": int(len(v)),
                             "median": float(np.median(v)) if len(v) else None,
                             "p25": float(np.quantile(v, 0.25)) if len(v) else None,
                             "p75": float(np.quantile(v, 0.75)) if len(v) else None})
    return pd.DataFrame(recs)


# --------------------------------------------------------------------------
# Catalysts
# --------------------------------------------------------------------------
def attribute_catalysts(sd: pd.DataFrame, events: pd.DataFrame, pr: dict | None, events_tbl: pd.DataFrame | None,
                        corp_actions: pd.DataFrame | None, deals: pd.DataFrame | None, window: int = 3,
                        sector_share: float = 0.5, sector_move_pct: float = 10.0) -> pd.DataFrame:
    """Per eligible event: results ±3 sessions · deal ±3 · corporate action ±3 · sector-wide (>= 50 % of the
    Industry's members, >= 3 with data, up >= 10 % from T-1 to T+19) · unexplained. Post-hoc (may look ahead);
    coverage columns say whether each source existed for the date."""
    ev = events.loc[events["eligible"]].copy()
    sess = _sessions(sd)
    t_s = np.searchsorted(sess, ev["event_date"].to_numpy())
    bm, ca, cov_start, cov_end = _catalyst_sources(pr, events_tbl, corp_actions)

    def _near(src: pd.DataFrame | None, date_col: str) -> tuple[np.ndarray, np.ndarray]:
        hit = np.zeros(len(ev), bool)
        covered = np.zeros(len(ev), bool)
        if src is None or src.empty:
            return hit, covered
        covered = np.ones(len(ev), bool) if cov_start is None else (
            (ev["event_date"] >= pd.Timestamp(cov_start)) & (ev["event_date"] <= pd.Timestamp(cov_end))).to_numpy()
        s = src.dropna(subset=[date_col]).copy()
        s["s"] = np.searchsorted(sess, s[date_col].to_numpy())
        k = pd.DataFrame({"symbol": ev["symbol"].to_numpy(), "t_s": t_s, "_i": np.arange(len(ev))})
        mm = k.merge(s[["symbol", "s"]], on="symbol")
        ok = (mm["s"] - mm["t_s"]).abs() <= window
        hit[np.unique(mm.loc[ok, "_i"].to_numpy())] = True
        return hit & covered, covered

    res_hit, res_cov = _near(bm, "meeting_date")
    ca_hit, ca_cov = _near(ca, "ex_date")
    deal_hit = np.zeros(len(ev), bool)
    deal_cov = np.zeros(len(ev), bool)
    if deals is not None and not deals.empty:
        dstart = pd.Timestamp(deals["trade_date"].min())
        deal_cov = (ev["event_date"] >= dstart + pd.Timedelta(days=5)).to_numpy()
        dl = deals.copy()
        if "clientele" in dl.columns:
            dl = dl.loc[dl["clientele"].astype(str).str.upper() != "PROP"]
        dl["s"] = np.searchsorted(sess, dl["trade_date"].to_numpy())
        k = pd.DataFrame({"symbol": ev["symbol"].to_numpy(), "t_s": t_s, "_i": np.arange(len(ev))})
        mm = k.merge(dl[["symbol", "s"]].drop_duplicates(), on="symbol")
        ok = (mm["s"] - mm["t_s"]).abs() <= window
        deal_hit[np.unique(mm.loc[ok, "_i"].to_numpy())] = True
        deal_hit &= deal_cov
    # sector-wide: share of Industry members up >= sector_move_pct from T-1 to T+19
    grp = pd.factorize(sd["symbol"].to_numpy())[0]
    c = sd["close_price"]
    f19 = pd.Series(gshift(c.to_numpy(float), grp, -19), index=c.index)
    p1 = pd.Series(gshift(c.to_numpy(float), grp, 1), index=c.index)
    fwd = ((f19 / p1 - 1) * 100).to_numpy(float)
    share = np.full(len(ev), np.nan)
    if "industry" in sd.columns:
        tmp = pd.DataFrame({"trade_date": sd["trade_date"].to_numpy(), "industry": sd["industry"].to_numpy(),
                            "moved": np.where(np.isfinite(fwd), (fwd >= sector_move_pct).astype(float), np.nan)})
        agg = tmp.dropna(subset=["moved"]).groupby(["trade_date", "industry"])["moved"].agg(["mean", "size"])
        agg = agg.loc[agg["size"] >= 3, "mean"]
        share = agg.reindex(pd.MultiIndex.from_arrays([ev["event_date"], ev["industry"]])).to_numpy(float)
    sector_hit = np.nan_to_num(share, nan=0) >= sector_share
    cats = []
    for i in range(len(ev)):
        lst = [n for n, h in (("results", res_hit[i]), ("deal", deal_hit[i]), ("corporate_action", ca_hit[i]),
                              ("sector", sector_hit[i])) if h]
        cats.append(lst)
    ev["catalysts"] = [",".join(x) if x else "unexplained" for x in cats]
    details = []
    for i in range(len(ev)):
        parts = []
        if res_hit[i]:
            parts.append("results board meeting within 3 sessions")
        if deal_hit[i]:
            parts.append("bulk/block deal (ex-PROP) within 3 sessions")
        if ca_hit[i]:
            parts.append("corporate action ex-date within 3 sessions")
        if sector_hit[i]:
            parts.append(f"{share[i] * 100:.0f}% of the Industry up >= {sector_move_pct:g}% over T-1..T+19")
        if not parts:
            gaps = [n for n, cov in (("results", res_cov[i]), ("deals", deal_cov[i])) if not cov]
            parts.append("no catalyst found" + (f" (no {'/'.join(gaps)} data for this date)" if gaps else ""))
        details.append("; ".join(parts))
    ev["catalyst_detail"] = details
    ev["catalyst"] = [x[0] if x else "unexplained" for x in cats]
    ev["industry_moved_share"] = share
    ev["results_covered"] = res_cov
    ev["deals_covered"] = deal_cov
    ev["corp_actions_covered"] = ca_cov
    return ev[["event_id", "catalyst", "catalysts", "catalyst_detail", "industry_moved_share", "results_covered", "deals_covered",
               "corp_actions_covered"]]


def catalyst_stats(events: pd.DataFrame) -> pd.DataFrame:
    ev = events.loc[events["eligible"]]
    recs = []
    for scope, g in (("all", ev), ("deals_covered", ev.loc[ev["deals_covered"].astype(bool)]),
                     ("results_covered", ev.loc[ev["results_covered"].astype(bool)])):
        n = len(g)
        if n == 0:
            continue
        exploded = g["catalysts"].str.split(",").explode()
        for cat in ("results", "deal", "corporate_action", "sector", "unexplained"):
            k = int((exploded == cat).groupby(level=0).any().sum())
            recs.append({"scope": scope, "catalyst": cat, "n_events": n, "n_with": k,
                         "share_pct": round(k / n * 100, 1), "primary_n": int((g["catalyst"] == cat).sum()),
                         "label": None if n >= MIN_SAMPLE else INSUFFICIENT})
    return pd.DataFrame(recs, columns=["scope", "catalyst", "n_events", "n_with", "share_pct", "primary_n", "label"])


# --------------------------------------------------------------------------
# Taxonomy studies
# --------------------------------------------------------------------------
def group_studies(sd: pd.DataFrame, events: pd.DataFrame, label: np.ndarray) -> pd.DataFrame:
    """Big movers by taxonomy level: events, eligible stock-days, event rate per 1,000 stock-days, lift vs all."""
    elig = eligible_mask(sd)
    ev = events.loc[events["eligible"]]
    overall = len(ev) / max(int(elig.sum()), 1) * 1000
    recs = []
    for level in LEVELS:
        col = LEVEL_COLS[level]
        if col not in sd.columns:
            continue
        days = pd.Series(sd[col].to_numpy()[elig]).value_counts()
        g = ev.groupby(col)
        n_ev = g.size()
        med = g["move_pct"].median()
        uc = g["trigger"].apply(lambda s: float((s == "upper_circuit").mean() * 100))
        for name, nd in days.items():
            ne = int(n_ev.get(name, 0))
            rate = ne / nd * 1000 if nd else None
            recs.append({"level": level, "group_name": name, "n_events": ne, "eligible_stock_days": int(nd),
                         "events_per_1000_days": round(rate, 3) if rate is not None else None,
                         "lift_vs_all": round(rate / overall, 2) if (rate is not None and overall) else None,
                         "median_move_pct": round(float(med.get(name)), 1) if ne else None,
                         "upper_circuit_share_pct": round(float(uc.get(name)), 1) if ne else None,
                         "label": None if ne >= MIN_SAMPLE else INSUFFICIENT})
    cols = ["level", "group_name", "n_events", "eligible_stock_days", "events_per_1000_days", "lift_vs_all",
            "median_move_pct", "upper_circuit_share_pct", "label"]
    return pd.DataFrame(recs, columns=cols).sort_values(["level", "n_events"], ascending=[True, False]).reset_index(drop=True)


def group_entry_study(sd: pd.DataFrame, group_levels: dict[str, pd.DataFrame], index_daily: pd.DataFrame,
                      horizons: tuple[int, ...] = (20, 60)) -> pd.DataFrame:
    """Forward equal-weight member return minus MidSml400 after a group *enters* Leading (per level)."""
    grp = pd.factorize(sd["symbol"].to_numpy())[0]
    c = sd["close_price"]
    mid = index_daily.loc[index_daily["index_name"] == "NIFTY MIDSML 400", ["trade_date", "close_price"]].drop_duplicates(
        "trade_date").set_index("trade_date")["close_price"].astype(float).sort_index()
    recs = []
    for h in horizons:
        fwd = (pd.Series(gshift(c.to_numpy(float), grp, -h), index=c.index) / c - 1) * 100
        mfwd = (mid.shift(-h) / mid - 1) * 100
        for level, gs in group_levels.items():
            col = LEVEL_COLS[level]
            if gs is None or gs.empty or col not in sd.columns:
                continue
            g = gs.sort_values(["group_name", "trade_date"]).copy()
            prev = g.groupby("group_name")["group_quadrant"].shift(1)
            ent = g.loc[(g["group_quadrant"] == "Leading") & prev.notna() & (prev != "Leading"), ["trade_date", "group_name"]]
            if ent.empty:
                continue
            tmp = pd.DataFrame({"trade_date": sd["trade_date"].to_numpy(), "group_name": sd[col].to_numpy(), "fwd": fwd.to_numpy()})
            gm = tmp.dropna(subset=["fwd"]).groupby(["trade_date", "group_name"])["fwd"].mean()
            v = gm.reindex(pd.MultiIndex.from_frame(ent)).to_numpy(float)
            ex = v - mfwd.reindex(pd.DatetimeIndex(ent["trade_date"])).to_numpy(float)
            ex = ex[np.isfinite(ex)]
            n = len(ex)
            ok = n >= MIN_SAMPLE
            recs.append({"level": level, "horizon": f"{h}d", "n_entries": n,
                         "avg_excess_pct": round(float(ex.mean()), 2) if ok else None,
                         "median_excess_pct": round(float(np.median(ex)), 2) if ok else None,
                         "hit_rate_pct": round(float((ex > 0).mean() * 100), 1) if ok else None,
                         "label": None if ok else INSUFFICIENT,
                         "quadrant_source": gs["quadrant_source"].iloc[0] if "quadrant_source" in gs.columns and len(gs) else None})
    return pd.DataFrame(recs, columns=["level", "horizon", "n_entries", "avg_excess_pct", "median_excess_pct",
                                       "hit_rate_pct", "label", "quadrant_source"])


def pre_move_watch(sd: pd.DataFrame, chosen: dict | None, last_sessions: int = 60) -> pd.DataFrame:
    """Eligible stock-days in the last N sessions matching the watch rule (chosen on train, precision from test)."""
    cols = ["trade_date", "symbol", "rule", "matched_traits", "n_traits", "precision_20d", "base_rate_20d", "n", "label"]
    if not chosen:
        return pd.DataFrame(columns=cols)
    feats = list(chosen["traits"])
    how = "any2" if str(chosen["rule"]).startswith(">=2") else "all"
    sess = _sessions(sd)[-last_sessions:]
    m = eligible_mask(sd) & sd["trade_date"].isin(sess).to_numpy() & _rule_mask(sd, feats, how)
    sub = sd.loc[m]
    hits = {ft: np.isfinite(sub[ft].to_numpy(float)) & _rule(sub[ft].to_numpy(float), *RULES[ft][:2]) for ft in feats}
    out = pd.DataFrame({"trade_date": sub["trade_date"].to_numpy(), "symbol": sub["symbol"].to_numpy()})
    out["rule"] = chosen["rule"]
    out["matched_traits"] = [[ft for ft in feats if hits[ft][i]] for i in range(len(sub))]
    out["n_traits"] = [len(x) for x in out["matched_traits"]]
    out["precision_20d"] = chosen.get("precision_20d")
    out["base_rate_20d"] = chosen.get("base_rate_20d")
    out["n"] = int(chosen.get("n_stock_days") or 0)
    out["label"] = "research"
    return out[cols]


def build_big_moves(sd: pd.DataFrame, *, pr, events_tbl, corp_actions, deals, group_levels, index_daily,
                    sessions: pd.Series) -> dict[str, pd.DataFrame]:
    events, flags = label_events(sd)
    controls = match_controls(sd, events, flags)
    fp = fingerprint_rows(sd, events, controls)
    lift, test_start = lift_table(fp, sessions)
    label = forward_event_label(sd, events)
    precision, traits, chosen = precision_table(sd, label, lift, sessions)
    cats = attribute_catalysts(sd, events, pr, events_tbl, corp_actions, deals)
    events = events.merge(cats, on="event_id", how="left")
    events["path_pct"] = price_paths(sd, events)
    events["path_start_offset"] = PATH_OFFSETS.start
    n_ctrl = controls.groupby("event_id").size() if not controls.empty else pd.Series(dtype=int)
    events["n_controls"] = events["event_id"].map(n_ctrl).fillna(0).astype(int)
    paths = feature_paths(sd, events, controls)
    groups = group_studies(sd, events, label)
    entries = group_entry_study(sd, group_levels, index_daily)
    watch = pre_move_watch(sd, chosen)
    ev_out = events.loc[events["eligible"]].drop(columns=["_pos", "row_in_symbol", "eligible", "series", "mcap_cr"],
                                                 errors="ignore").rename(columns={"adv_cr": "adv_cr_t0"})
    lift_long = fp.melt(id_vars=["event_id", "role", "symbol", "event_date", "offset"], value_vars=FEATURES,
                        var_name="feature", value_name="value")
    return {"big_move_events": ev_out.reset_index(drop=True), "big_move_features": lift_long,
            "big_move_controls": controls, "big_move_lift": lift, "big_move_precision": precision,
            "big_move_paths": paths, "big_move_catalyst_stats": catalyst_stats(events),
            "big_move_group_stats": groups, "group_entry_study": entries, "pre_move_watch": watch,
            "_all_events": events}
