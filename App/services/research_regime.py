"""Research View 1/2 (10-tab-research.md §§3, 4, 11): the two-axis regime quadrant and "days like today".

Port of HarkPro/tools/regime_study/choppy.py + quadrant.py.

- Equal-weight (EW) market of stocks >= Rs 1,000 Cr: mean daily high / low / close move (clipped +-25%).
- Index axis: Range if Choppiness(14) is in the top 40% of its own history or Kaufman efficiency ratio(20)
  is in the bottom 40%; else Trend. ADX(14) is shown beside it.
- Breakout axis: share of 50-day-high breakouts on >= 1.5x volume still above their breakout close
  5 sessions later, over the trailing 10 sessions. Failing = below its own median.
  Point in time: a breakout counts on the session it is graded (breakout day + 5), so today's reading
  never uses a close after today. (The round-1 tool counted ungraded breakouts; that leaked 5 sessions.)
- Percentiles are point in time: each day is ranked only against earlier days (expanding, 60 minimum).
- Outcome per day (for the quadrant record): follow-through of the breakouts of the NEXT 10 sessions,
  and the EW market's next 5/10/20/60-session return. Shown only once known on as_of.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from App.services import db
from App.services import research_lab as lab
from App.services.common import Result, no_session, unavailable

QUADRANTS = {
    "press": {"label": "Press", "axes": "Trend + breakouts paying", "advice": "Trade full size."},
    "narrow": {"label": "Narrow", "axes": "Trend + breakouts failing", "advice": "Trade only the few leaders that work."},
    "picker": {"label": "Stock-picker's market", "axes": "Range + breakouts paying", "advice": "Trade leaders only."},
    "chop": {"label": "Chop", "axes": "Range + breakouts failing", "advice": "Sit out or size down."},
}
HORIZONS = (5, 10, 20, 60)
ANALOG_FEATURES = {
    "above_20ema_pct": "Stocks above 20-day average (all stocks)",
    "above_50ema_pct": "Stocks above 50-day average (all stocks)",
    "above_200ema_pct": "Stocks above 200-day average (all stocks)",
    "er": "Efficiency ratio (20)",
    "chop": "Choppiness (14)",
    "ft_pct": "Breakout follow-through (10 sessions)",
    "drawdown_pct": "EW market drawdown from its high",
    "ew_ret20_pct": "EW market 20-session return",
}
ANALOG_EXCLUDE_RECENT = 25
ANALOG_MIN_GAP = 10


def _pit_rank(s: pd.Series, min_periods: int = 60) -> pd.Series:
    """Share of EARLIER values strictly below today's (point in time)."""
    vals = s.to_numpy(dtype=float)
    out = np.full(len(vals), np.nan)
    for i in range(len(vals)):
        if i + 1 < min_periods or np.isnan(vals[i]):
            continue
        past = vals[:i]
        past = past[~np.isnan(past)]
        if len(past) + 1 < min_periods:
            continue
        out[i] = (past < vals[i]).mean()
    return pd.Series(out, index=s.index)


def _adx(hi: pd.Series, lo: pd.Series, cl: pd.Series, n: int = 14) -> pd.Series:
    up, dn = hi.diff(), -lo.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([hi - lo, (hi - cl.shift(1)).abs(), (lo - cl.shift(1)).abs()], axis=1).max(axis=1)
    a = 1.0 / n
    atr = tr.ewm(alpha=a, adjust=False).mean()
    pdi = 100 * pd.Series(pdm, index=hi.index).ewm(alpha=a, adjust=False).mean() / atr
    mdi = 100 * pd.Series(mdm, index=hi.index).ewm(alpha=a, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=a, adjust=False).mean()


def compute_daily(con: Any, end: date) -> pd.DataFrame:
    """One row per session <= end: EW market, both axes, PIT percentiles, quadrant, outcomes."""
    d = lab.frame(con, end)[["symbol", "trade_date", "high_price", "low_price", "close_price", "ema_50", "rvol"]].copy()
    g = d.groupby("symbol", sort=False)
    d["pc"] = g.close_price.shift(1)
    d = d[d.pc > 0].copy()
    for k, src in (("rh", "high_price"), ("rl", "low_price"), ("rc", "close_price")):
        d[k] = (d[src] / d.pc - 1).clip(-0.25, 0.25)
    g = d.groupby("symbol", sort=False)
    d["hi50"] = g.close_price.transform(lambda s: s.shift(1).rolling(50, min_periods=40).max())
    d["c5"] = g.close_price.shift(-5)
    d["bo"] = (d.close_price > d.hi50) & (d.rvol >= 1.5)
    m = d.groupby("trade_date").agg(rh=("rh", "mean"), rl=("rl", "mean"), rc=("rc", "mean"), n=("symbol", "size"))
    bo = d[d.bo & d.c5.notna()]
    m["bo_n"] = bo.groupby("trade_date").size()
    m["bo_ok"] = bo.assign(ok=bo.c5 > bo.close_price).groupby("trade_date").ok.sum()
    m = m.fillna({"bo_n": 0, "bo_ok": 0}).sort_index()
    m["idx"] = (1 + m.rc).cumprod() * 100
    m["hi"] = m.idx.shift(1) * (1 + m.rh)
    m["lo"] = m.idx.shift(1) * (1 + m.rl)
    tr = pd.concat([m.hi - m.lo, (m.hi - m.idx.shift(1)).abs(), (m.lo - m.idx.shift(1)).abs()], axis=1).max(axis=1)
    n = 14
    m["chop"] = 100 * np.log10(tr.rolling(n).sum() / (m.hi.rolling(n).max() - m.lo.rolling(n).min())) / np.log10(n)
    m["er"] = (m.idx - m.idx.shift(20)).abs() / m.idx.diff().abs().rolling(20).sum()
    m["adx"] = _adx(m.hi, m.lo, m.idx)
    # graded on breakout day + 5 (point in time)
    gn, gok = m.bo_n.shift(5), m.bo_ok.shift(5)
    m["ft_n"] = gn.rolling(10).sum()
    m["ft_pct"] = gok.rolling(10).sum() / m.ft_n.replace(0, np.nan) * 100
    m["drawdown_pct"] = (m.idx / m.idx.cummax() - 1) * 100
    m["ew_ret20_pct"] = (m.idx / m.idx.shift(20) - 1) * 100
    m["e50"] = m.idx.ewm(span=50, adjust=False).mean()
    # outcomes
    nx = lambda s: s[::-1].rolling(10).sum()[::-1].shift(-1)  # noqa: E731
    m["next10_ft_n"] = nx(m.bo_n)
    m["next10_ft_pct"] = nx(m.bo_ok) / m.next10_ft_n.replace(0, np.nan) * 100
    for h in HORIZONS:
        m[f"fwd{h}_pct"] = (m.idx.shift(-h) / m.idx - 1) * 100
    # breadth on all stocks (breadth_daily) for the analog vector
    if db.table_exists(con, "breadth_daily"):
        b = con.execute("SELECT trade_date, above_20ema_pct, above_50ema_pct, above_200ema_pct FROM breadth_daily "
                        "WHERE trade_date <= ?", [end]).df()
        b["trade_date"] = pd.to_datetime(b.trade_date)
        m = m.join(b.set_index("trade_date"), how="left")
    else:
        for c in ("above_20ema_pct", "above_50ema_pct", "above_200ema_pct"):
            m[c] = np.nan
    # point-in-time axes on the rows that have both readings
    ok = m.chop.notna() & m.ft_pct.notna() & m.er.notna()
    o = m[ok]
    m["chop_pctile"] = _pit_rank(o.chop).reindex(m.index)
    m["er_pctile"] = _pit_rank(o.er).reindex(m.index)
    m["ft_pctile"] = _pit_rank(o.ft_pct).reindex(m.index)
    has = m.chop_pctile.notna() & m.er_pctile.notna() & m.ft_pctile.notna()
    rng = (m.chop_pctile > 0.6) | (m.er_pctile < 0.4)
    fail = m.ft_pctile < 0.5
    m["index_axis"] = np.where(has, np.where(rng, "Range", "Trend"), None)
    m["breakout_axis"] = np.where(has, np.where(fail, "Failing", "Paying"), None)
    q = np.select([~rng & ~fail, ~rng & fail, rng & ~fail, rng & fail], ["press", "narrow", "picker", "chop"], None)
    m["quadrant"] = np.where(has, q, None)
    m["stocks"] = m.n
    out = m.reset_index().rename(columns={"index": "trade_date"})
    keep = ["trade_date", "stocks", "idx", "drawdown_pct", "ew_ret20_pct", "chop", "er", "adx", "ft_pct", "ft_n",
            "chop_pctile", "er_pctile", "ft_pctile", "index_axis", "breakout_axis", "quadrant",
            "above_20ema_pct", "above_50ema_pct", "above_200ema_pct", "bo_n", "bo_ok", "next10_ft_pct", "next10_ft_n",
            *[f"fwd{h}_pct" for h in HORIZONS]]
    out = out.rename(columns={"idx": "ew_index"})
    keep[keep.index("idx")] = "ew_index"
    return out[keep]


def daily(con: Any, end: date) -> tuple[pd.DataFrame, str]:
    return lab.table_or_compute(con, "research_regime_daily", end, lambda: compute_daily(con, end))


# --------------------------------------------------------------------------
# As-of views
# --------------------------------------------------------------------------
def _bounded(df: pd.DataFrame, as_of: date) -> pd.DataFrame:
    """Rows <= as_of, with outcomes nulled until their window closed on as_of."""
    t = df[df.trade_date <= pd.Timestamp(as_of)].copy().reset_index(drop=True)
    n = len(t)
    pos = np.arange(n)
    left = n - 1 - pos  # sessions after the row, up to as_of
    for h in HORIZONS:
        t.loc[left < h, f"fwd{h}_pct"] = np.nan
    t.loc[left < 15, ["next10_ft_pct", "next10_ft_n"]] = np.nan
    return t


def _episodes(t: pd.DataFrame) -> pd.DataFrame:
    q = t.quadrant.where(t.quadrant.notna(), None)
    valid = t[q.notna()].copy()
    if valid.empty:
        return pd.DataFrame(columns=["quadrant", "start", "end", "sessions", "ew_move_pct", "next_quadrant",
                                     "ew_next20_pct", "open"])
    run = (valid.quadrant != valid.quadrant.shift()).cumsum()
    rows = []
    for _, x in valid.groupby(run):
        i0, i1 = x.index[0], x.index[-1]
        rows.append({"quadrant": x.quadrant.iat[0], "start": x.trade_date.iat[0], "end": x.trade_date.iat[-1],
                     "sessions": len(x),
                     "ew_move_pct": (t.ew_index[i1] / t.ew_index[i0 - 1] - 1) * 100 if i0 > 0 else np.nan,
                     "ew_next20_pct": t.fwd20_pct[i1]})
    e = pd.DataFrame(rows)
    e["next_quadrant"] = e.quadrant.shift(-1)
    e["open"] = False
    e.loc[e.index[-1], "open"] = True
    return e


def _quadrant_record(t: pd.DataFrame) -> list[dict[str, Any]]:
    k = t[t.quadrant.notna()]
    base_ft = k.next10_ft_pct.mean()
    base_f20 = k.fwd20_pct.mean()
    out = []
    for key, meta in QUADRANTS.items():
        x = k[k.quadrant == key]
        out.append({"quadrant": key, "label": meta["label"], "axes": meta["axes"], "advice": meta["advice"],
                    "days": int(len(x)), "days_graded": int(x.next10_ft_pct.notna().sum()),
                    "next10_ft_pct": lab.rnd(x.next10_ft_pct.mean()), "ew_fwd20_pct": lab.rnd(x.fwd20_pct.mean(), 2),
                    "ew_fwd20_up_pct": lab.rnd((x.fwd20_pct.dropna() > 0).mean() * 100 if x.fwd20_pct.notna().any() else None)})
    out.append({"quadrant": "all", "label": "All days", "axes": None, "advice": None, "days": int(len(k)),
                "days_graded": int(k.next10_ft_pct.notna().sum()), "next10_ft_pct": lab.rnd(base_ft),
                "ew_fwd20_pct": lab.rnd(base_f20, 2),
                "ew_fwd20_up_pct": lab.rnd((k.fwd20_pct.dropna() > 0).mean() * 100 if k.fwd20_pct.notna().any() else None)})
    return out


def _today_sentences(row: dict[str, Any], run_len: int, rec: dict[str, Any] | None, base: dict[str, Any]) -> list[str]:
    q = QUADRANTS.get(row.get("quadrant") or "")
    if not q:
        return ["The regime is not known yet. The study needs 60 sessions of history."]
    s = [f"The market is in {q['label']} ({q['axes'].lower()}).",
         f"Choppiness is {lab.rnd(row.get('chop'), 0):.0f} and the efficiency ratio is {lab.rnd(row.get('er'), 2):.2f}."
         if row.get("chop") is not None and row.get("er") is not None else "",
         f"{lab.rnd(row.get('ft_pct'), 0):.0f}% of recent breakouts held after 5 sessions."
         if row.get("ft_pct") is not None else "",
         f"This phase is {run_len} sessions old."]
    if rec and rec.get("next10_ft_pct") is not None and base.get("next10_ft_pct") is not None:
        s.append(f"In past {q['label']} days, {rec['next10_ft_pct']:.0f}% of the next breakouts held "
                 f"(all days: {base['next10_ft_pct']:.0f}%).")
    s.append(f"What to do: {q['advice']}")
    return [x for x in s if x]


@lab.memo("regime")
def regime(as_of: date | None, days: int = 600) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        end = lab.study_end(con, resolved)
        if end is None:
            return no_session(as_of)
        df, source = daily(con, lab.study_end(con, None) or end)
        tail = lab.dropped_tail(con, end)
    t = _bounded(df, end)
    if t.empty or t.quadrant.notna().sum() == 0:
        return unavailable(end, "not enough history for the regime study (needs about 80 sessions)",
                           ["indicators_daily"], caveat=lab.CAVEAT)
    eps = _episodes(t)
    cur = eps.iloc[-1]
    rec = _quadrant_record(t)
    by = {r["quadrant"]: r for r in rec}
    last = lab.records(t.tail(1))[0]
    same = eps[(eps.quadrant == cur.quadrant) & ~eps.open]
    dur = same[same.sessions >= 3].sessions
    exits = same.next_quadrant.value_counts()
    ctx = {
        "caveat": lab.CAVEAT,
        "study_end": end, "source": source,
        "dropped_sessions": [d.isoformat() for d in tail],
        "today": {**{k: last.get(k) for k in ("trade_date", "quadrant", "index_axis", "breakout_axis", "chop", "er",
                                               "adx", "ft_pct", "ft_n", "chop_pctile", "er_pctile", "ft_pctile",
                                               "drawdown_pct", "ew_index")},
                  "label": QUADRANTS.get(last.get("quadrant") or "", {}).get("label"),
                  "advice": QUADRANTS.get(last.get("quadrant") or "", {}).get("advice"),
                  "sessions_in_phase": int(cur.sessions), "phase_start": lab.clean(cur.start)},
        "record": rec,
        "duration": {"quadrant": cur.quadrant, "past_episodes": int(len(same)), "episodes_3plus": int(len(dur)),
                     "median_sessions": lab.clean(float(dur.median())) if len(dur) else None,
                     "min_sessions": int(dur.min()) if len(dur) else None, "max_sessions": int(dur.max()) if len(dur) else None,
                     "exits": [{"to": k, "label": QUADRANTS[k]["label"], "n": int(v)} for k, v in exits.items()]},
        "episodes": lab.records(eps[eps.sessions >= 3].iloc[::-1].head(40).assign(
            ew_move_pct=lambda x: x.ew_move_pct.round(1), ew_next20_pct=lambda x: x.ew_next20_pct.round(1))),
        "summary": _today_sentences(last, int(cur.sessions), by.get(last.get("quadrant") or ""), by["all"]),
        "quadrants": QUADRANTS,
        "definition": ("Index axis: Range if Choppiness(14) is in the top 40% of its history or the efficiency "
                       "ratio(20) is in the bottom 40%, on the equal-weight market of stocks >= Rs 1,000 Cr. "
                       "Breakout axis: share of 50-day-high breakouts on >= 1.5x volume still above the breakout "
                       "close 5 sessions later, over the trailing 10 sessions; Failing = below its own median. "
                       "Percentiles rank each day only against earlier days."),
        "sample": {"from": lab.clean(t.trade_date.iat[0]), "to": end, "sessions": int(len(t)),
                   "classified": int(t.quadrant.notna().sum())},
    }
    cols = ["trade_date", "ew_index", "drawdown_pct", "chop", "er", "adx", "ft_pct", "ft_n", "chop_pctile",
            "er_pctile", "ft_pctile", "index_axis", "breakout_axis", "quadrant", "next10_ft_pct", "fwd20_pct"]
    rows = lab.records(t[cols].tail(max(1, int(days))), 4)
    return Result(as_of=end, rows=rows, sources=["indicators_daily", "breadth_daily"], extra=ctx,
                  notes=["Equal-weight market of stocks >= Rs 1,000 Cr by today's market cap (as-of cap is a data gap)."])


@lab.memo("analogs")
def analogs(as_of: date | None, k: int = 10) -> Result:
    """The k nearest past sessions by the regime feature vector, at least 10 sessions apart."""
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        end = lab.study_end(con, resolved)
        df, source = daily(con, lab.study_end(con, None) or end)
    t = _bounded(df, end)
    feats = list(ANALOG_FEATURES)
    x = t[feats].astype(float)
    mu, sd = x.mean(), x.std().replace(0, np.nan)
    z = (x - mu) / sd
    today = z.iloc[-1]
    if t.empty or today.isna().any():
        return unavailable(end, "today's feature vector is incomplete", ["indicators_daily", "breadth_daily"],
                           caveat=lab.CAVEAT)
    dist = np.sqrt(((z - today) ** 2).sum(axis=1, min_count=len(feats)))
    cand = dist.iloc[: max(0, len(t) - ANALOG_EXCLUDE_RECENT)].dropna().sort_values()
    picks: list[int] = []
    for i in cand.index:
        if all(abs(i - j) >= ANALOG_MIN_GAP for j in picks):
            picks.append(i)
        if len(picks) >= k:
            break
    sel = t.loc[picks].copy()
    sel["distance"] = dist[picks].round(3)
    sel["quadrant_label"] = sel.quadrant.map(lambda q: QUADRANTS.get(q or "", {}).get("label"))
    cols = ["trade_date", "distance", "quadrant", "quadrant_label", *feats, *[f"fwd{h}_pct" for h in HORIZONS],
            "next10_ft_pct"]
    rows = lab.records(sel[cols], 3)
    for r in rows:
        r["analog_date"] = r.pop("trade_date")
    base_rows = t.iloc[: max(0, len(t) - 1)]
    horizons = []
    for h in HORIZONS:
        col = f"fwd{h}_pct"
        a, b = sel[col].dropna(), base_rows[col].dropna()
        horizons.append({"horizon": h, "n": int(len(a)), "median": lab.rnd(a.median(), 2) if len(a) else None,
                         "mean": lab.rnd(a.mean(), 2) if len(a) else None,
                         "min": lab.rnd(a.min(), 2) if len(a) else None, "max": lab.rnd(a.max(), 2) if len(a) else None,
                         "up_pct": lab.rnd((a > 0).mean() * 100, 0) if len(a) else None,
                         "base_median": lab.rnd(b.median(), 2) if len(b) else None,
                         "base_up_pct": lab.rnd((b > 0).mean() * 100, 0) if len(b) else None, "base_n": int(len(b))})
    h20 = next(h for h in horizons if h["horizon"] == 20)
    summary = []
    if h20["n"]:
        summary.append(f"{h20['n']} past days looked most like today.")
        summary.append(f"20 sessions later, the equal-weight market was higher in {h20['up_pct']:.0f}% of them "
                       f"(all days: {h20['base_up_pct']:.0f}%).")
        summary.append(f"The median move was {h20['median']:+.1f}% (all days: {h20['base_median']:+.1f}%).")
        if h20["n"] < 10:
            summary.append("The sample is small. Treat this as a description, not a forecast.")
    ctx = {"caveat": lab.CAVEAT, "study_end": end, "source": source, "k": len(rows),
           "features": [{"key": f, "label": ANALOG_FEATURES[f], "today": lab.rnd(t[f].iat[-1], 2)} for f in feats],
           "horizons": horizons, "summary": summary,
           "method": (f"Each session is described by {len(feats)} readings, each standardised by its history up to "
                      f"{end.isoformat()}. Distance is Euclidean. Picks are at least {ANALOG_MIN_GAP} sessions apart. "
                      f"The last {ANALOG_EXCLUDE_RECENT} sessions are excluded (their outcome is not known yet). "
                      "India VIX is left out: local index history holds only about 32 sessions.")}
    return Result(as_of=end, rows=rows, sources=["indicators_daily", "breadth_daily"], extra=ctx)


# --------------------------------------------------------------------------
# Index study (§6): EW market drawdowns + size leadership
# --------------------------------------------------------------------------
def compute_size_daily(con: Any, end: date) -> pd.DataFrame:
    """EW indices of large (top 100 by cap), mid (101-250) and small (rest >= 1,000 Cr) stocks."""
    d = lab.frame(con, end)[["symbol", "trade_date", "close_price", "mcap_now"]].copy()
    rank = d.drop_duplicates("symbol").set_index("symbol").mcap_now.rank(ascending=False, method="first")
    d["band"] = d.symbol.map(lambda s: "large" if rank[s] <= 100 else ("mid" if rank[s] <= 250 else "small"))
    d["rc"] = (d.close_price / d.groupby("symbol", sort=False).close_price.shift(1) - 1).clip(-0.25, 0.25)
    w = d.dropna(subset=["rc"]).groupby(["trade_date", "band"]).rc.mean().unstack()
    out = (1 + w.fillna(0)).cumprod() * 100
    out.columns = [f"ew_{c}" for c in out.columns]
    return out.reset_index()


@lab.memo("index_study")
def index_study(as_of: date | None) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        end = lab.study_end(con, resolved)
        full_end = lab.study_end(con, None) or end
        df, source = daily(con, full_end)
        size, _ = lab.table_or_compute(con, "research_size_daily", full_end, lambda: compute_size_daily(con, full_end))
        idx_sessions = 0
        if db.table_exists(con, "index_daily"):
            idx_sessions = int(con.execute("SELECT count(DISTINCT trade_date) FROM index_daily WHERE index_name = 'Nifty 50' "
                                           "AND trade_date <= ?", [end]).fetchone()[0])
    t = _bounded(df, end)
    if t.empty:
        return no_session(as_of)
    s = size[size.trade_date <= pd.Timestamp(end)].reset_index(drop=True)
    # drawdowns > 8 % on the EW market
    idx = t.ew_index.to_numpy()
    dates = t.trade_date.tolist()
    rows, peak_i, i = [], 0, 0
    n = len(idx)
    while i < n:
        if idx[i] >= idx[peak_i]:
            peak_i = i
            i += 1
            continue
        # in a drawdown from peak_i: find where it recovers
        j = i
        trough_i = i
        while j < n and idx[j] < idx[peak_i]:
            if idx[j] < idx[trough_i]:
                trough_i = j
            j += 1
        depth = (idx[trough_i] / idx[peak_i] - 1) * 100
        if depth <= -8:
            rec_i = j if j < n else None
            rows.append({"peak_date": dates[peak_i], "trough_date": dates[trough_i], "depth_pct": round(depth, 1),
                         "sessions_down": trough_i - peak_i,
                         "recovered_date": dates[rec_i] if rec_i is not None else None,
                         "sessions_to_recover": (rec_i - trough_i) if rec_i is not None else None,
                         "breadth_above_50ema_at_low": lab.rnd(t.above_50ema_pct.iat[trough_i]),
                         "ongoing": rec_i is None})
        peak_i = j if j < n else peak_i
        i = j
    dd_now = float(t.drawdown_pct.iat[-1])
    lead = []
    for h in (20, 60):
        if len(s) > h:
            r = {b: (s[f"ew_{b}"] / s[f"ew_{b}"].shift(h) - 1) * 100 for b in ("large", "mid", "small") if f"ew_{b}" in s}
            rr = pd.DataFrame(r).dropna()
            leader = rr.idxmax(axis=1)
            lead.append({"horizon": h, **{f"{b}_pct": lab.rnd(rr[b].iat[-1], 1) for b in rr.columns},
                         "leader_now": leader.iat[-1] if len(leader) else None,
                         **{f"{b}_led_share_pct": lab.rnd((leader == b).mean() * 100, 0) for b in rr.columns},
                         "n": int(len(rr))})
    series = t[["trade_date", "ew_index", "drawdown_pct"]].merge(s, on="trade_date", how="left")
    ctx = {"caveat": lab.CAVEAT, "study_end": end, "source": source,
           "today_drawdown_pct": round(dd_now, 1),
           "series": lab.records(series, 2),
           "leadership": lead,
           "index_history_sessions": idx_sessions,
           "notes": ["Size bands use today's market cap: top 100 = large, 101-250 = mid, the rest >= Rs 1,000 Cr = small.",
                     f"Nifty 50 / MidSml400 / Smallcap250 cycles need index history. Local index_daily holds "
                     f"{idx_sessions} sessions (data gap #3: run Scripts/backfill_index_history.py)."]}
    return Result(as_of=end, rows=lab.records(pd.DataFrame(rows)) if rows else [],
                  sources=["indicators_daily", "breadth_daily"], extra=ctx)
