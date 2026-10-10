"""Sector Intel (HarkPro/07-tab-sector-intel.md, rounds 1-3d; mockup HarkPro/tools/sector_mockup/extract.py).

Readings per group (stocks >= Rs 1,000 Cr, current taxonomy, groups >= 3 members are ranked):
  near      = % of members with close within 10% of their 52W high (+ change over the window)
  nh_W      = distinct members that made a new 52W high (high > prior session's 52W high) in the window
  ad_W      = mean over the window of (advancers - decliners) / members, %
  upd_W     = delivered value on up days / all delivered value over the window, %
  tov_W     = average daily turnover over the window, Rs Cr; sh_W = average share of all-stock turnover, %
  tox_W     = turnover window average / 63-session average (attention, not direction)
  shd_W     = turnover share window average minus 63-session average, points
  ret_W/rx_W= equal-weight return over the window / minus the median group's, points
  score_W   = mean of within-level percentile ranks of near, nh_W/members, ad_W, upd_W (0-100)
  pct_*     = today's value vs the group's own last ~2 years (504 sessions, >= 40 observations)
State (Tab 2 definition): Favour / Neutral / Caution with its numeric reason.
Mood (Pulse definition): mean expanding percentile of % > 10/50/200 EMA, up-turnover %, net new highs, TT pass %.
"Working now" gauge: realised rank-IC of score_2W vs the forward 21-session excess return, averaged over the
63 sessions that ended 21 sessions before as_of (only data known on the day).

Windows gap guard (round 3c): a window counts rows, not sessions. When the calendar span of an N-session window
is longer than `max_span_days(N)` (a data gap, e.g. local 2026-08-13 -> 2026-10-08), every reading over that window
is NULL, never a two-month "1D" move.

A 1-day move <= -35% or >= +100% is treated as an unadjusted corporate action and dropped (never filled).
"""
from __future__ import annotations

import math
import threading
import warnings
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from App.services import db
from App.services.common import Result, no_session, unavailable

LEVELS: dict[str, tuple[str, str]] = {  # api key -> (stocks_master column, label)
    "sector": ("sector", "Sector"),
    "broad_industry": ("broad_industry", "Broad Industry"),
    "industry": ("industry", "Industry"),
}
WINDOWS: dict[str, int] = {"1D": 1, "1W": 5, "2W": 10, "1M": 21}
MIN_MCAP_CR = 1000.0
MIN_MEMBERS = 3
SMALL_GROUP = 5
HISTORY_DAYS = 800           # calendar days loaded: ~2 years of percentile history + 63-session warm-up
PCT_SESSIONS = 504           # "own 2 years"
PCT_MIN_OBS = 40
CHART_BARS = 160
FWD = 21
IC_DAYS = 63
WORKING_IC = 0.05
DEAL_SESSIONS = 10
FLOW_EVENTS = ("accumulate", "fresh", "distribute")  # transfers, placements and churn are not flow (08 §5.3)
SPLIT_DOWN, SPLIT_UP = -0.35, 1.0
METRICS = ["nh", "ad", "upd", "tov", "sh", "tox", "shd", "rx", "ret", "nearchg", "score"]
PCT_KEYS = ["near", "nh", "ad", "upd", "tox", "score"]
GAP_NOTE = ("Windows gap guard: a reading is blank when its window spans more calendar days than the sessions allow "
            "(a data gap). Blank is honest; a two-month move shown as 1D is not.")

# Local evidence (HarkPro/07 rounds 2-3, Oct 2024 - Jul 2026, Broad Industry). Context only; provisional.
EVIDENCE = {
    "period": "Oct 2024 - Jul 2026 (local data, current taxonomy)",
    "dir": {"cooling fast": {"ic": 0.061, "top": 55, "bot": 46},
            "steady": {"ic": 0.156, "top": 59, "bot": 43},
            "improving fast": {"ic": 0.170, "top": 63, "bot": 41}},
    "lag": {"working": 0.164, "not": 0.042},
}
READINGS_STUDY = [  # 07 §7 table (study2_readings.py)
    {"reading": "% of members within 10% of 52W high", "best_n": "level", "ic_sector": 0.160, "ic_broad_industry": 0.103, "ic_industry": 0.094, "top": 55, "bot": 45},
    {"reading": "Members making a new 52W high", "best_n": "5-10d", "ic_sector": 0.147, "ic_broad_industry": 0.103, "ic_industry": 0.069, "top": 57, "bot": 46},
    {"reading": "Advance / decline (net % of members up)", "best_n": "10-20d", "ic_sector": 0.114, "ic_broad_industry": 0.081, "ic_industry": 0.048, "top": 54, "bot": 44},
    {"reading": "Change in % near 52W high", "best_n": "20d", "ic_sector": 0.101, "ic_broad_industry": 0.087, "ic_industry": 0.049, "top": 55, "bot": 45},
    {"reading": "Return", "best_n": "20d", "ic_sector": 0.098, "ic_broad_industry": 0.098, "ic_industry": 0.035, "top": 56, "bot": 45},
    {"reading": "Up-day share of delivery value", "best_n": "10d", "ic_sector": 0.078, "ic_broad_industry": 0.077, "ic_industry": 0.036, "top": 54, "bot": 44},
    {"reading": "Turnover vs own 3M average", "best_n": "1d", "ic_sector": 0.047, "ic_broad_industry": 0.049, "ic_industry": 0.017, "top": 52, "bot": 46},
    {"reading": "Delivery % vs own 20D average", "best_n": "any", "ic_sector": 0.0, "ic_broad_industry": 0.0, "ic_industry": 0.02, "top": 49, "bot": 49},
    {"reading": "4-part score (near-high, new highs, A/D, up-day delivery)", "best_n": "10d", "ic_sector": 0.174, "ic_broad_industry": 0.124, "ic_industry": 0.080, "top": 59, "bot": 43},
]
MOOD_STUDY = [  # 07 §8 table
    {"condition": "Mood < 45", "ic_sector": 0.152, "ic_broad_industry": 0.106, "top": 58, "bot": 44, "ic_industry": 0.089},
    {"condition": "Mood 45-55", "ic_sector": 0.212, "ic_broad_industry": 0.153, "top": 61, "bot": 42, "ic_industry": 0.105},
    {"condition": "Mood >= 55", "ic_sector": 0.179, "ic_broad_industry": 0.128, "top": 58, "bot": 44, "ic_industry": 0.050},
    {"condition": "Short-term breadth cooling fast", "ic_sector": 0.133, "ic_broad_industry": 0.061, "top": 55, "bot": 46, "ic_industry": 0.049},
    {"condition": "Steady", "ic_sector": 0.221, "ic_broad_industry": 0.156, "top": 59, "bot": 43, "ic_industry": 0.102},
    {"condition": "Improving fast", "ic_sector": 0.187, "ic_broad_industry": 0.170, "top": 63, "bot": 41, "ic_industry": 0.099},
]

_LOCK = threading.Lock()


# --------------------------------------------------------------------------
# Small helpers (pure, unit-tested)
# --------------------------------------------------------------------------
def max_span_days(n: int) -> int:
    """Longest calendar span an n-session window may cover before it counts as a data gap.
    5 sessions = 7 days, +10% for exchange holidays, +8 days of slack
    (1D -> 10, 1W -> 16, 2W -> 24, 1M -> 41, 63 -> 106, 252 -> 397)."""
    return int(math.ceil(n * 7 / 5 * 1.1)) + 8


def gap_mask(dates: list[pd.Timestamp] | pd.DatetimeIndex, n: int) -> np.ndarray:
    """True where the n-session window ending at that date spans a data gap (reading must be NULL)."""
    d = pd.DatetimeIndex(dates)
    out = np.zeros(len(d), dtype=bool)
    if n <= 0 or len(d) <= n:
        return out
    span = (d[n:] - d[:-n]).days
    out[n:] = np.asarray(span) > max_span_days(n)
    return out


def fwd_gap_mask(dates: list[pd.Timestamp] | pd.DatetimeIndex, n: int) -> np.ndarray:
    """True where the next n sessions span a data gap (forward return must not be used)."""
    d = pd.DatetimeIndex(dates)
    out = np.zeros(len(d), dtype=bool)
    if len(d) > n:
        span = (d[n:] - d[:-n]).days
        out[:-n] = np.asarray(span) > max_span_days(n)
    return out


def own_percentile(hist: np.ndarray, min_obs: int = PCT_MIN_OBS) -> float | None:
    """Percentile (0-100) of the last value within `hist` (NaN ignored); None when too short."""
    h = np.asarray(hist, dtype=float)
    if h.size == 0 or not np.isfinite(h[-1]):
        return None
    v = h[np.isfinite(h)]
    if v.size < min_obs:
        return None
    return float((v <= h[-1]).mean() * 100)


def mood_label(score: float | None) -> str | None:
    if score is None:
        return None
    return "Strong" if score >= 70 else "Healthy" if score >= 55 else "Mixed" if score >= 45 else "Weak" if score >= 30 else "Very weak"


def breadth_direction(a10chg: float | None) -> str | None:
    if a10chg is None:
        return None
    return "cooling fast" if a10chg < -10 else "improving fast" if a10chg > 10 else "steady"


def context_verdict(working: bool | None, direction: str | None) -> dict[str, str]:
    """Plain-English verdict beside the score (04-writing-style.md)."""
    if working is None:
        return {"text": "The ranking's recent record is unknown. The database lacks the history to test it.",
                "todo": "Use the board as a map. Check each group's chart before you act."}
    if not working:
        return {"text": "Group ranking did not work in the last 3 months. Top groups did no better than bottom groups.",
                "todo": "Treat the board as a map, not a signal. Pick stocks on their own charts."}
    if direction == "cooling fast":
        return {"text": "Group ranking worked lately. Short-term breadth is falling fast. In this state the ranking worked about half as well.",
                "todo": "Use only the top of the board. Wait for breadth to steady before you add new groups."}
    return {"text": "Group ranking worked in the last 3 months. Top-fifth groups beat the median group more often than bottom-fifth groups.",
            "todo": "Look for new setups in the top fifth of the board. Avoid the bottom fifth."}


def _r(v: Any, nd: int) -> float | None:
    return db.num(v, nd)


def _wide_rank_pct(frames: list[pd.DataFrame], elig: pd.DataFrame) -> pd.DataFrame:
    """Mean within-date percentile rank (0-100) of the given wide frames over eligible groups."""
    acc = None
    for f in frames:
        rk = f.where(elig).rank(axis=1, pct=True)
        acc = rk if acc is None else acc + rk
    return acc / len(frames) * 100


# --------------------------------------------------------------------------
# Load + compute (cached per DB fingerprint and as_of)
# --------------------------------------------------------------------------
def _load_stocks(con, as_of: date) -> pd.DataFrame:
    start = as_of - timedelta(days=HISTORY_DAYS)
    p = con.execute(
        """
        SELECT i.symbol, i.trade_date d, i.open_price o, i.high_price hi, i.low_price lo, i.close_price c,
               i.prev_close pc, i.turnover_cr t, i.delivery_qty * i.close_price / 1e7 dv, i.high_52w h52,
               i.ema_50 e50, i.rs_percentile rs, m.security_name nm, m.market_cap_cr mcap,
               m.sector, m.broad_industry, m.industry
        FROM indicators_daily i JOIN stocks_master m USING (symbol)
        WHERE m.market_cap_cr >= ? AND i.trade_date <= ? AND i.trade_date >= ?
        ORDER BY i.symbol, i.trade_date
        """,
        [MIN_MCAP_CR, as_of, start],
    ).df()
    p["d"] = pd.to_datetime(p["d"])
    return p


def _load_turnover_all(con, as_of: date) -> pd.Series:
    """All-stock turnover per session (share denominators use all stocks: standing rule)."""
    start = as_of - timedelta(days=HISTORY_DAYS)
    s = con.execute("SELECT trade_date d, sum(turnover_cr) t FROM indicators_daily WHERE trade_date <= ? AND trade_date >= ? "
                    "GROUP BY 1 ORDER BY 1", [as_of, start]).df()
    s["d"] = pd.to_datetime(s["d"])
    return s.set_index("d")["t"]


def _prepare(p: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    g = p.groupby("symbol", sort=False)
    prev = g["c"].shift(1).fillna(p["pc"])
    r = p["c"] / prev - 1
    bad = (r <= SPLIT_DOWN) | (r >= SPLIT_UP)
    p["r"] = r.where(~bad)
    for k in ("o", "hi", "lo"):
        p["r" + k] = (p[k] / prev - 1).where(~bad)
    p["adv"] = np.sign(p["r"])
    p["near"] = (p["c"] >= 0.9 * p["h52"]).astype(float).where(p["h52"].notna())
    ph = g["h52"].shift(1)
    p["nh"] = (p["hi"] > ph).astype(float).where(ph.notna())
    p["upd"] = p["dv"] * (p["r"] > 0)
    p["a50"] = (p["c"] > p["e50"]).astype(float).where(p["e50"].notna())
    # distinct members with a new 52W high within the window (stock-level rolling max on a date grid)
    nh_w = p.pivot_table(index="d", columns="symbol", values="nh", aggfunc="max").reindex(dates)
    nh_w.index.name = "d"
    for wk, n in WINDOWS.items():
        roll = nh_w.rolling(n, min_periods=1).max()
        roll[gap_mask(dates, n)] = np.nan
        st = roll.stack().rename("nhw_" + wk).reset_index()
        p = p.merge(st, on=["d", "symbol"], how="left")
    return p


def _level(p: pd.DataFrame, lv: str, dates: pd.DatetimeIndex, tall: pd.Series) -> dict[str, Any]:
    col = LEVELS[lv][0]
    q = p[p[col].notna()]
    agg = q.groupby([col, "d"]).agg(
        n=("symbol", "size"), r=("r", "mean"), ro=("ro", "mean"), rhi=("rhi", "mean"), rlo=("rlo", "mean"),
        adv=("adv", "mean"), near=("near", "mean"), t=("t", "sum"), dv=("dv", "sum"), upd=("upd", "sum"),
        a50=("a50", "mean"))
    agg = agg.join(q.groupby([col, "d"])[["nhw_" + k for k in WINDOWS]].sum(min_count=1))

    def wide(c: str) -> pd.DataFrame:
        return agg[c].unstack(col).reindex(dates)

    W = {c: wide(c) for c in agg.columns}
    n = W["n"]
    elig = n >= MIN_MEMBERS
    idx = np.exp(np.log1p(W["r"].fillna(0)).cumsum()) * 100
    idx = idx.where(n.notna().cummax())
    sh = W["t"].div(tall.reindex(dates), axis=0) * 100

    def roll(f: pd.DataFrame, w: int, how: str = "mean") -> pd.DataFrame:
        out = getattr(f.rolling(w, min_periods=max(1, w // 2)), how)()
        out[gap_mask(dates, w)] = np.nan
        return out

    t63, sh63 = roll(W["t"], 63), roll(sh, 63)
    sh5, sh20 = roll(sh, 5), roll(sh, 20)
    out: dict[str, pd.DataFrame] = {"n": n, "near": W["near"] * 100, "a50": W["a50"] * 100, "idx": idx}
    for wk, N in WINDOWS.items():
        g = gap_mask(dates, N)
        nh = W["nhw_" + wk]
        ad = roll(W["adv"], N) * 100
        upd = roll(W["upd"], N, "sum") / roll(W["dv"], N, "sum").replace(0, np.nan) * 100
        tov = roll(W["t"], N)
        shw = roll(sh, N)
        ret = (idx / idx.shift(N) - 1) * 100
        ret[g] = np.nan
        nearchg = (W["near"] - W["near"].shift(N)) * 100
        nearchg[g] = np.nan
        out.update({f"nh_{wk}": nh, f"ad_{wk}": ad, f"upd_{wk}": upd, f"tov_{wk}": tov, f"sh_{wk}": shw,
                    f"tox_{wk}": tov / t63.replace(0, np.nan), f"shd_{wk}": shw - sh63, f"ret_{wk}": ret,
                    f"rx_{wk}": ret.sub(ret.where(elig).median(axis=1), axis=0), f"nearchg_{wk}": nearchg})
        out[f"score_{wk}"] = _wide_rank_pct([W["near"], nh / n, ad, upd], elig & nh.notna() & ad.notna() & upd.notna())
    ret63 = (idx / idx.shift(63) - 1) * 100
    ret63[gap_mask(dates, 63)] = np.nan
    out.update({"ret_63": ret63, "sh5": sh5, "sh20": sh20,
                "e50idx": idx.ewm(span=50, adjust=False).mean(),
                # equal-weight candles (rebased index)
                "o": idx.shift(1) * (1 + W["ro"]), "h": idx.shift(1) * (1 + W["rhi"]), "l": idx.shift(1) * (1 + W["rlo"])})
    return {"col": col, "w": out, "elig": elig}


def _states(w: dict[str, pd.DataFrame], elig: pd.DataFrame, i: int) -> tuple[pd.Series, pd.Series]:
    """Favour / Neutral / Caution at row i (Tab 2 definition) and its numeric reason."""
    row = {k: v.iloc[i] for k, v in w.items() if isinstance(v, pd.DataFrame)}
    e = elig.iloc[i]
    med21 = row["ret_1M"].where(e).median()
    med63 = row["ret_63"].where(e).median()
    a50, r21, idx, e50, sh5, sh20, r63 = (row["a50"], row["ret_1M"], row["idx"], row["e50idx"], row["sh5"], row["sh20"], row["ret_63"])
    fav = (a50 >= 60) & (r21 > med21) & (idx > e50)
    cau = ((sh5 < 0.85 * sh20) & (r21 < 0)) | ((a50 < 40) & (r63 < med63))
    state = pd.Series(np.where(fav, "Favour", np.where(cau, "Caution", "Neutral")), index=a50.index)
    why = {}
    for gname in a50.index:
        a = a50.get(gname)
        rx = (r21.get(gname) - med21) if pd.notna(r21.get(gname)) and pd.notna(med21) else None
        s = state[gname]
        if s == "Favour":
            why[gname] = f"{a:.0f}% of members are above the 50 EMA. 1M return beats the median group by {rx:+.1f} pts. The index is above its 50 EMA."
        elif s == "Caution" and pd.notna(a) and a < 40:
            why[gname] = f"Only {a:.0f}% of members are above the 50 EMA. 3M return is below the median group."
        elif s == "Caution":
            ratio = sh5.get(gname) / sh20.get(gname) * 100 if sh20.get(gname) else float("nan")
            why[gname] = f"Turnover share fell to {ratio:.0f}% of its 20D average. The group fell {r21.get(gname):.1f}% in 1M."
        else:
            parts = []
            if pd.notna(a):
                parts.append(f"{a:.0f}% of members are above the 50 EMA.")
            if rx is not None:
                parts.append(f"1M return vs the median group: {rx:+.1f} pts.")
            why[gname] = " ".join(parts) or "Not enough data for a state."
    return state, pd.Series(why)


def _reliability(w: dict[str, pd.DataFrame], elig: pd.DataFrame, dates: pd.DatetimeIndex) -> dict[str, Any]:
    idx = w["idx"]
    fwd = (idx.shift(-FWD) / idx - 1) * 100
    fwd[fwd_gap_mask(dates, FWD)] = np.nan
    x = fwd.where(elig)
    x = x.sub(x.median(axis=1), axis=0)
    sc = w["score_2W"].where(elig)
    end = len(dates) - 1 - FWD            # latest signal day whose next 21 sessions are known
    start = max(0, end - IC_DAYS + 1)
    ics, tops, bots, used = [], 0, 0, []
    ntop = nbot = 0
    for i in range(start, end + 1) if end >= 0 else []:
        a, b = sc.iloc[i], x.iloc[i]
        ok = a.notna() & b.notna()
        if ok.sum() <= 8:
            continue
        a, b = a[ok], b[ok]
        ics.append(a.rank().corr(b.rank()))
        used.append(dates[i])
        qn = pd.qcut(a.rank(method="first"), 5, labels=False)
        tops += int((b[qn == 4] > 0).sum())
        ntop += int((qn == 4).sum())
        bots += int((b[qn == 0] > 0).sum())
        nbot += int((qn == 0).sum())
    if not ics:
        return {"ic": None, "top": None, "bot": None, "days": 0, "from": None, "to": None, "working": None}
    ic = float(np.nanmean(ics))
    return {"ic": round(ic, 3), "top": round(tops / ntop * 100) if ntop else None, "bot": round(bots / nbot * 100) if nbot else None,
            "days": len(ics), "from": str(min(used).date()), "to": str(max(used).date()), "working": bool(ic > WORKING_IC)}


def _mood(con, as_of: date) -> dict[str, Any]:
    m = con.execute(
        """SELECT trade_date d, avg((close_price>ema_10)::int) a10, avg((close_price>ema_50)::int) a50,
                  avg((close_price>ema_200)::int) a200,
                  sum(CASE WHEN close_price>prev_close THEN turnover_cr ELSE 0 END)/nullif(sum(turnover_cr),0) upv,
                  (sum((close_price>=high_52w*0.999)::int)-sum((close_price<=low_52w*1.001)::int))*1.0/count(*) nnh,
                  avg(trend_template_pass::int) s2
           FROM indicators_daily WHERE trade_date <= ? GROUP BY 1 ORDER BY 1""", [as_of]).df()
    if m.empty:
        return {"score": None, "label": None, "dir": None, "a10chg": None, "spark": [], "note": "no sessions"}
    m["d"] = pd.to_datetime(m["d"])
    cols = ["a10", "a50", "a200", "upv", "nnh", "s2"]
    pcts = []
    for k in cols:
        v = m[k].to_numpy(dtype=float)
        pc = np.full(len(v), np.nan)
        for i in range(59, len(v)):
            pc[i] = own_percentile(v[: i + 1], 60) if np.isfinite(v[i]) else np.nan
        pcts.append(pc)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        mood = np.nanmean(np.vstack(pcts), axis=0) if len(m) >= 60 else np.full(len(m), np.nan)
    a10chg = (m["a10"] - m["a10"].shift(10)) * 100
    a10chg[gap_mask(m["d"], 10)] = np.nan
    score = db.num(mood[-1], 1)
    chg = db.num(a10chg.iloc[-1], 1)
    return {"score": None if score is None else round(score), "label": mood_label(score), "dir": breadth_direction(chg),
            "a10chg": chg, "a10": db.num(m["a10"].iloc[-1] * 100, 1),
            "spark": [db.num(v, 1) for v in mood[-120:]], "spark_dates": [str(d.date()) for d in m["d"].iloc[-120:]],
            "note": "Pulse mood: mean percentile (vs the archive so far) of % above 10/50/200 EMA, up-turnover %, net new highs and trend-template pass %."}


def _deals(con, as_of: date, dates: pd.DatetimeIndex) -> tuple[pd.DataFrame | None, str | None]:
    """Per-symbol deal flow over the last DEAL_SESSIONS sessions (ex transfers, placements, churn; PROP excluded)."""
    if not db.table_exists(con, "deal_session_net"):
        return None, "deal_session_net not built"
    if len(dates) <= DEAL_SESSIONS:
        return None, "not enough sessions"
    if gap_mask(dates, DEAL_SESSIONS)[-1]:
        return None, "the 10-session deal window spans a data gap"
    start = dates[-DEAL_SESSIONS]
    d = con.execute(
        """SELECT symbol, trade_date, event_type, net_value_cr_ex_prop net FROM deal_session_net
           WHERE trade_date >= ? AND trade_date <= ?""", [start.date(), as_of]).df()
    if d.empty:
        return pd.DataFrame(columns=["symbol", "flow", "last_event", "sessions"]), None
    d = d.sort_values("trade_date")
    flow = d[d["event_type"].isin(FLOW_EVENTS)].groupby("symbol")["net"].sum(min_count=1)
    last = d.groupby("symbol").agg(last_event=("event_type", "last"), sessions=("trade_date", "nunique"))
    return last.join(flow.rename("flow")).reset_index(), None


def _compute(as_of: date) -> dict[str, Any] | None:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return None
        p = _load_stocks(con, resolved)
        tall = _load_turnover_all(con, resolved)
        mood = _mood(con, resolved)
        dates = pd.DatetimeIndex(sorted(tall.index.unique()))
        deals, deal_reason = _deals(con, resolved, dates)
    if p.empty:
        return {"as_of": resolved, "empty": True, "mood": mood}
    p = _prepare(p, dates)
    i = len(dates) - 1
    today = p[p["d"] == dates[i]]
    levels = {}
    for lv in LEVELS:
        L = _level(p, lv, dates, tall)
        L["state"], L["why"] = _states(L["w"], L["elig"], i)
        L["rel"] = _reliability(L["w"], L["elig"], dates)
        levels[lv] = L
    return {"as_of": resolved, "empty": False, "dates": dates, "p_today": today, "levels": levels, "mood": mood,
            "deals": deals, "deal_reason": deal_reason, "last_clean": _last_clean(dates), "gaps": {wk: bool(gap_mask(dates, n)[-1]) for wk, n in WINDOWS.items()}}


def _last_clean(dates: pd.DatetimeIndex) -> str | None:
    """Latest session whose 1M window does not span a data gap (the latest good session for the board)."""
    m = gap_mask(dates, WINDOWS["1M"])
    ok = np.where(~m)[0]
    ok = ok[ok >= WINDOWS["1M"]]
    return str(dates[ok[-1]].date()) if ok.size else None


def _state(as_of: date | None) -> dict[str, Any] | None:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
    if resolved is None:
        return None
    with _LOCK:
        return db.cached("sectors.state", (resolved,), lambda: _compute(resolved))


def _level_key(level: str) -> str:
    lv = str(level or "").strip().lower()
    if lv not in LEVELS:
        raise ValueError(f"level must be one of {', '.join(LEVELS)}")
    return lv


def parse_group_id(gid: str) -> tuple[str, str]:
    lv, _, name = str(gid or "").partition(":")
    lv = lv.strip().lower()
    if lv not in LEVELS or not name:
        raise ValueError("group id must look like '<level>:<name>', level one of " + ", ".join(LEVELS))
    return lv, name


def _context(S: dict[str, Any], lv: str) -> dict[str, Any]:
    rel = S["levels"][lv]["rel"] if not S.get("empty") else {"working": None}
    mood = S["mood"]
    verdict = context_verdict(rel.get("working"), mood.get("dir"))
    return {"mood": mood, "reliability": rel, "verdict": verdict["text"], "what_to_do": verdict["todo"],
            "evidence": EVIDENCE, "evidence_now": EVIDENCE["dir"].get(mood.get("dir") or "", None)}


# --------------------------------------------------------------------------
# Public services
# --------------------------------------------------------------------------
def board(as_of: date | None, level: str = "broad_industry") -> Result:
    if str(level).strip().lower() == "index":
        return index_board(as_of)
    lv = _level_key(level)
    S = _state(as_of)
    if S is None:
        return no_session(as_of)
    if S.get("empty"):
        return unavailable(S["as_of"], "no stocks >= Rs 1,000 Cr with prices", ["indicators_daily", "stocks_master"])
    L = S["levels"][lv]
    w, i = L["w"], len(S["dates"]) - 1
    names = [g for g in w["n"].columns if pd.notna(w["n"].iloc[i, w["n"].columns.get_loc(g)])]
    today = S["p_today"]
    col = L["col"]
    lead = today.sort_values("rs", ascending=False, na_position="last").groupby(col)["symbol"].apply(lambda s: list(s[:3]))
    deals = S["deals"]
    dmap = None
    if deals is not None:
        dm = today[["symbol", col]].merge(deals, on="symbol", how="inner")
        dmap = dm.groupby(col).agg(buy=("flow", lambda s: int((s > 0).sum())), sell=("flow", lambda s: int((s < 0).sum())),
                                   flow=("flow", lambda s: s.sum(min_count=1)), any_=("symbol", "size"))
    hist0 = max(0, i - PCT_SESSIONS + 1)
    rows = []
    for g in names:
        j = w["n"].columns.get_loc(g)
        n = int(w["n"].iloc[i, j])
        row: dict[str, Any] = {
            "id": f"{lv}:{g}", "level": lv, "group_name": g, "stocks": n, "small": n < SMALL_GROUP, "ranked": n >= MIN_MEMBERS,
            "state": L["state"].get(g), "state_reason": L["why"].get(g),
            "near": _r(w["near"].iloc[i, j], 1), "a50": _r(w["a50"].iloc[i, j], 1),
            "leaders": lead.get(g, []),
        }
        for wk in WINDOWS:
            for k in METRICS:
                v = w[f"{k}_{wk}"].iloc[i, j]
                row[f"{k}_{wk}"] = _r(v, 2 if k in ("tox", "shd", "sh") else 0 if k == "tov" else 1)
            if not row["ranked"]:
                row[f"score_{wk}"] = None
        pct: dict[str, float | None] = {"near": None}
        pct["near"] = own_percentile(w["near"].iloc[hist0:i + 1, j].to_numpy())
        for wk in WINDOWS:
            for k in PCT_KEYS[1:]:
                pv = own_percentile(w[f"{k}_{wk}"].iloc[hist0:i + 1, j].to_numpy())
                pct[f"{k}_{wk}"] = None if pv is None else round(pv)
        pct["near"] = None if pct["near"] is None else round(pct["near"])
        row["pct"] = pct
        if dmap is not None:
            dr = dmap.loc[g] if g in dmap.index else None
            row["deals_buy_10d"] = int(dr["buy"]) if dr is not None else 0
            row["deals_sell_10d"] = int(dr["sell"]) if dr is not None else 0
            row["deals_flow_10d_cr"] = _r(dr["flow"], 1) if dr is not None else 0.0
        else:
            row["deals_buy_10d"] = row["deals_sell_10d"] = row["deals_flow_10d_cr"] = None
        rows.append(row)
    rows.sort(key=lambda r: (r["score_2W"] is None, -(r["score_2W"] or 0)))
    gaps = [wk for wk, on in S["gaps"].items() if on]
    notes = ["Stocks >= Rs 1,000 Cr, current taxonomy and market cap (not point-in-time). Turnover share uses all stocks.",
             "Score = average within-level rank of near-52W-high %, new highs, A/D and up-day delivery share. "
             "Thresholds are provisional until the five-year point-in-time recheck.",
             "Turnover means attention, not direction: no forward edge measured.",
             "Deals 10D: net-buy / net-sell names and flow Rs Cr over 10 sessions; PROP, transfers, placements and churn excluded. Context only."]
    if gaps:
        notes.append(f"{GAP_NOTE} Blank windows on {S['as_of']}: {', '.join(gaps)}.")
    if S["deal_reason"]:
        notes.append(f"Deals 10D unavailable: {S['deal_reason']}.")
    extra = {"level": lv, "level_label": LEVELS[lv][1], "windows": list(WINDOWS), "gap_windows": gaps,
             "last_clean_session": S.get("last_clean"),
             "deals_reason": S["deal_reason"], **_context(S, lv)}
    status = "partial" if gaps else "ok"
    return Result(as_of=S["as_of"], rows=rows, status=status,
                  reason=(f"data gap: {', '.join(gaps)} windows are blank" if gaps else None),
                  sources=["indicators_daily", "stocks_master", "deal_session_net"], notes=notes, extra=extra,
                  metric_keys=[])


def context(as_of: date | None, level: str = "broad_industry") -> Result:
    lv = "broad_industry" if str(level).strip().lower() == "index" else _level_key(level)
    S = _state(as_of)
    if S is None:
        return no_session(as_of)
    c = _context(S, lv)
    return Result(as_of=S["as_of"], rows=[{"level": lv, **{k: v for k, v in c.items() if k != "evidence"}}],
                  sources=["indicators_daily"], extra={"evidence": EVIDENCE})


def charts(as_of: date | None, ids: list[str], bars: int = CHART_BARS) -> Result:
    if not ids:
        raise ValueError("pass at least one id")
    if len(ids) > 12:
        raise ValueError("at most 12 ids per call")
    S = _state(as_of)
    if S is None:
        return no_session(as_of)
    if S.get("empty"):
        return unavailable(S["as_of"], "no stocks >= Rs 1,000 Cr with prices", ["indicators_daily"])
    dates = S["dates"]
    rows = []
    for gid in ids:
        lv, name = parse_group_id(gid)
        w = S["levels"][lv]["w"]
        if name not in w["idx"].columns:
            rows.append({"id": gid, "group_name": name, "bars": [], "rs": [], "near": [], "reason": "unknown group"})
            continue
        c = w["idx"][name]
        o = w["o"][name].fillna(c)
        h = pd.concat([w["h"][name].fillna(c), o, c], axis=1).max(axis=1)
        lo = pd.concat([w["l"][name].fillna(c), o, c], axis=1).min(axis=1)
        frame = pd.DataFrame({"o": o, "h": h, "l": lo, "c": c, "near": w["near"][name]}).dropna(subset=["c"]).tail(bars + 60)
        out_bars = [{"time": str(d.date()), "open": round(float(r.o), 2), "high": round(float(r.h), 2),
                     "low": round(float(r.l), 2), "close": round(float(r.c), 2)} for d, r in frame.iterrows()]
        rows.append({"id": gid, "group_name": name, "level": lv, "bars": out_bars,
                     "near": [{"time": str(d.date()), "value": db.num(v, 1)} for d, v in frame["near"].items()]})
    # RS vs the equal-weight market of all >= 1000 Cr stocks
    ew = _market_ew(S)
    for row in rows:
        if not row.get("bars"):
            continue
        rs = []
        base = None
        for b in row["bars"]:
            m = ew.get(b["time"])
            if m is None or not m:
                rs.append({"time": b["time"], "value": None})
                continue
            v = b["close"] / m
            base = base or v
            rs.append({"time": b["time"], "value": round(v / base * 100, 2)})
        row["rs"] = rs
    gaps = [str(dates[k].date()) for k in np.where(gap_mask(dates, 1))[0]]
    notes = ["Equal-weight group candles from member OHLC, rebased to 100. RS line vs the equal-weight market of stocks >= Rs 1,000 Cr "
             "(MidSml400 history is too short locally)."]
    if gaps:
        notes.append(f"Data gap before {', '.join(gaps)}: the candle on that date spans the gap.")
    return Result(as_of=S["as_of"], rows=rows, sources=["indicators_daily", "stocks_master"], notes=notes,
                  extra={"gap_dates": gaps})


def _market_ew(S: dict[str, Any]) -> dict[str, float]:
    def build() -> dict[str, float]:
        w = S["levels"]["sector"]["w"]
        # stock-level EW market = member-count-weighted mean of sector EW daily returns
        r = (w["idx"] / w["idx"].shift(1) - 1)
        n = w["n"]
        mr = (r * n).sum(axis=1, min_count=1) / n.where(r.notna()).sum(axis=1, min_count=1)
        idx = np.exp(np.log1p(mr.fillna(0)).cumsum()) * 100
        return {str(d.date()): float(v) for d, v in idx.items()}
    if "_ew" not in S:
        S["_ew"] = build()
    return S["_ew"]


def members(as_of: date | None, group_id: str) -> Result:
    lv, name = parse_group_id(group_id)
    S = _state(as_of)
    if S is None:
        return no_session(as_of)
    if S.get("empty"):
        return unavailable(S["as_of"], "no stocks >= Rs 1,000 Cr with prices", ["indicators_daily"])
    col = LEVELS[lv][0]
    t = S["p_today"]
    m = t[t[col] == name].copy()
    if m.empty:
        raise KeyError(group_id)
    dates = S["dates"]
    with db.market_conn() as con:
        back = dates[-1 - WINDOWS["1M"]] if len(dates) > WINDOWS["1M"] else None
        r1m: dict[str, float] = {}
        if back is not None and not gap_mask(dates, WINDOWS["1M"])[-1]:
            old = con.execute("SELECT symbol, close_price FROM indicators_daily WHERE trade_date = ? AND symbol IN (SELECT unnest(?))",
                              [back.date(), list(m["symbol"])]).fetchall()
            om = {s: c for s, c in old}
            r1m = {s: (c / om[s] - 1) * 100 for s, c in zip(m["symbol"], m["c"]) if om.get(s)}
    deals = S["deals"]
    dd = deals.set_index("symbol") if deals is not None and not deals.empty else None
    gap1 = bool(gap_mask(dates, 1)[-1])
    rows = []
    for x in m.sort_values("rs", ascending=False, na_position="last").itertuples():
        r1 = r1m.get(x.symbol)
        rows.append({
            "symbol": x.symbol, "security_name": db.text(x.nm), "market_cap_cr": _r(x.mcap, 0), "close": _r(x.c, 2),
            "rs_percentile": _r(x.rs, 0), "change_1d_pct": None if gap1 else _r(None if pd.isna(x.r) else x.r * 100, 1),
            "return_1m_pct": None if r1 is None or abs(r1) > 300 else round(r1, 1),
            "from_52w_high_pct": _r((x.c / x.h52 - 1) * 100 if x.h52 else None, 1),
            "near_52w_high": bool(x.h52 and x.c >= 0.9 * x.h52), "above_50ema": None if pd.isna(x.a50) else bool(x.a50 == 1),
            "new_high_1w": None if pd.isna(getattr(x, "nhw_1W")) else bool(getattr(x, "nhw_1W") == 1),
            "deal_flow_10d_cr": _r(dd.loc[x.symbol, "flow"], 1) if dd is not None and x.symbol in dd.index else None,
            "deal_last_event": db.text(dd.loc[x.symbol, "last_event"]) if dd is not None and x.symbol in dd.index else None,
        })
    return Result(as_of=S["as_of"], rows=rows, sources=["indicators_daily", "stocks_master", "deal_session_net"],
                  extra={"group_id": group_id, "level": lv, "group_name": name},
                  notes=["Members with market cap >= Rs 1,000 Cr (current), sorted by RS percentile."])


def index_board(as_of: date | None) -> Result:
    """Official NSE sectoral + thematic indices: price readings only (constituent lists are a data gap)."""
    try:
        from App.thematic_engine import CANONICAL_44_INDICES as C44
    except Exception:  # pragma: no cover - optional module
        C44 = {}
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        if not db.table_exists(con, "index_daily"):
            return unavailable(resolved, "index_daily not built", ["index_daily"], level="index")
        ix = con.execute("SELECT index_name, trade_date d, close_price c FROM index_daily WHERE trade_date <= ? ORDER BY 1, 2",
                         [resolved]).df()
    ix["d"] = pd.to_datetime(ix["d"])
    ref = ix[ix["index_name"].str.upper() == "NIFTY MIDSML 400"].set_index("d")["c"]

    def rets(s: pd.Series) -> dict[str, float | None]:
        dts = pd.DatetimeIndex(s.index)
        out = {}
        for wk, n in WINDOWS.items():
            if len(s) <= n or gap_mask(dts, n)[-1]:
                out[wk] = None
            else:
                out[wk] = round(float((s.iloc[-1] / s.iloc[-1 - n] - 1) * 100), 2)
        return out

    refr = rets(ref) if not ref.empty and ref.index[-1] == pd.Timestamp(resolved) else {wk: None for wk in WINDOWS}
    rows = []
    for name, meta in C44.items():
        clean = str(meta.get("clean_name", name)).upper()
        s = ix[ix["index_name"].str.upper() == clean]
        if s.empty:
            s = ix[ix["index_name"] == name]
        if s.empty:
            rows.append({"id": f"index:{name}", "group_name": name, "category": meta.get("category"), "close": None,
                         "sessions": 0, "stale": True, **{f"ret_{wk}": None for wk in WINDOWS}, **{f"rs_{wk}": None for wk in WINDOWS},
                         "above_20ema": None})
            continue
        c = s.set_index("d")["c"]
        stale = c.index[-1] != pd.Timestamp(resolved)
        rr = rets(c) if not stale else {wk: None for wk in WINDOWS}
        e20 = c.ewm(span=20, adjust=False).mean().iloc[-1] if len(c) >= 20 else None
        rows.append({"id": f"index:{name}", "group_name": name, "category": meta.get("category"), "close": _r(c.iloc[-1], 2),
                     "sessions": int(len(c)), "stale": bool(stale),
                     **{f"ret_{wk}": rr[wk] for wk in WINDOWS},
                     **{f"rs_{wk}": (round(rr[wk] - refr[wk], 2) if rr[wk] is not None and refr.get(wk) is not None else None) for wk in WINDOWS},
                     "above_20ema": None if e20 is None else bool(c.iloc[-1] > e20)})
    found = sum(1 for r in rows if r["sessions"])
    depth = max((r["sessions"] for r in rows), default=0)
    notes = ["Index level shows price readings only. Near-high %, new highs, A/D and delivery need each index's constituent "
             "list, which the database does not hold (data gap).",
             f"{found} of {len(C44)} indices found; up to {depth} sessions of index history locally."]
    gaps = [wk for wk in WINDOWS if all(r[f"ret_{wk}"] is None for r in rows)] if rows else []
    if gaps:
        notes.append(f"{GAP_NOTE} Blank windows: {', '.join(gaps)}.")
    return Result(as_of=resolved, rows=rows, status="partial",
                  reason="index constituents missing: price readings only", sources=["index_daily"], notes=notes,
                  extra={"level": "index", "level_label": "Index", "windows": list(WINDOWS), "gap_windows": gaps})


HEATMAP_SQL = """
WITH b AS (
  SELECT symbol, trade_date, close_price c, turnover_cr t, volume v, delivery_qty * close_price / 1e7 dv,
    100 * (close_price / nullif(open_price, 0) - 1) co, 100 * (open_price / nullif(prev_close, 0) - 1) gap,
    rvol, atr_pct_primary vol, delivery_pct dp, away_52w_high_pct a52, rs_percentile rs,
    return_3m_pct r63, return_6m_pct r126, return_12m_pct r252,
    lag(close_price, 1) OVER w c1, lag(close_price, 5) OVER w c5, lag(close_price, 21) OVER w c21,
    datediff('day', lag(trade_date, 1) OVER w, trade_date) s1, datediff('day', lag(trade_date, 5) OVER w, trade_date) s5,
    datediff('day', lag(trade_date, 21) OVER w, trade_date) s21, datediff('day', lag(trade_date, 63) OVER w, trade_date) s63,
    datediff('day', lag(trade_date, 126) OVER w, trade_date) s126, datediff('day', lag(trade_date, 252) OVER w, trade_date) s252,
    avg(turnover_cr) OVER (PARTITION BY symbol ORDER BY trade_date ROWS 19 PRECEDING) t20,
    datediff('day', lag(trade_date, 19) OVER w, trade_date) s20
  FROM indicators_daily WHERE trade_date <= ? AND trade_date >= ?
  WINDOW w AS (PARTITION BY symbol ORDER BY trade_date))
SELECT b.symbol, m.security_name, m.sector, m.broad_industry, m.industry, m.market_cap_cr mc, c, t, t20, s20, v, dv, co, gap,
  rvol, vol, dp, a52, rs, r63, r126, r252, s63, s126, s252,
  100 * (c / c1 - 1) r1, 100 * (c / c5 - 1) r5, 100 * (c / c21 - 1) r21, s1, s5, s21
FROM b JOIN stocks_master m USING (symbol)
WHERE b.trade_date = ? AND t > 0 AND m.sector IS NOT NULL
"""


def heatmap(as_of: date | None) -> Result:
    """TradingView-style stock heatmap rows (07 §3d). All stocks; the client applies the >= Rs 1,000 Cr toggle."""
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        df = con.execute(HEATMAP_SQL, [resolved, resolved - timedelta(days=420), resolved]).df()
    guard = {"r1": ("s1", 1), "r5": ("s5", 5), "r21": ("s21", 21), "r63": ("s63", 63), "r126": ("s126", 126),
             "r252": ("s252", 252), "t20": ("s20", 19)}
    blank_counts: dict[str, int] = {}
    gap1 = df["s1"].notna() & (df["s1"] > max_span_days(1))
    for col, (span, n) in guard.items():
        bad = df[span].notna() & (df[span] > max_span_days(n))
        if bad.any():
            blank_counts[col] = int(bad.sum())
        df.loc[bad, col] = np.nan
    df.loc[gap1, "gap"] = np.nan  # the opening gap vs a close two months back is not a 1-day gap
    for col in ("r1", "r5", "r21"):  # unadjusted split / bonus guard
        df.loc[(df[col] <= -35) | (df[col] >= 100), col] = np.nan
    # A field is "gapped" for the session when most stocks lose it (a market-wide data gap), not a few illiquid names.
    blanked = [c for c, k in blank_counts.items() if k >= 0.5 * max(1, len(df))]
    rows = []
    for x in df.itertuples(index=False):
        rows.append({
            "symbol": x.symbol, "security_name": db.text(x.security_name), "sector": db.text(x.sector),
            "broad_industry": db.text(x.broad_industry), "industry": db.text(x.industry), "mc": _r(x.mc, 0), "c": _r(x.c, 2),
            "r1": _r(x.r1, 2), "r5": _r(x.r5, 2), "r21": _r(x.r21, 2), "t": _r(x.t, 2), "t20": _r(x.t20, 2),
            "v": db.integer(x.v), "dv": _r(x.dv, 2), "co": _r(x.co, 2), "gap": _r(x.gap, 2),
            "r63": _r(x.r63, 1), "r126": _r(x.r126, 1), "r252": _r(x.r252, 1), "rvol": _r(x.rvol, 2), "vol": _r(x.vol, 2),
            "dp": _r(x.dp, 1), "a52": _r(x.a52, 1), "rs": _r(x.rs, 0),
        })
    notes = ["Tile = one stock, grouped by taxonomy. Size and colour metrics as in TradingView's heatmap. "
             "A 1-day move <= -35% or >= +100% is treated as an unadjusted corporate action and left blank."]
    if blanked:
        notes.append(f"{GAP_NOTE} Blank on {resolved}: {', '.join(blanked)}.")
    few = {c: k for c, k in blank_counts.items() if c not in blanked}
    if few:
        notes.append("Blank for stocks with missing sessions in the window: "
                     + ", ".join(f"{c} ({k})" for c, k in few.items()) + ".")
    return Result(as_of=resolved, rows=rows, status="partial" if blanked else "ok",
                  reason=(f"data gap: {', '.join(blanked)} blank" if blanked else None),
                  sources=["indicators_daily", "stocks_master"], notes=notes,
                  extra={"gap_fields": blanked, "blank_counts": blank_counts})


def group_studies(as_of: date | None, level: str = "broad_industry") -> Result:
    """Group studies moved here from Research (10 §2): evidence-engine tables when built, plus the local
    Sector Intel evidence (07 rounds 2-3)."""
    from App.services import research

    lv = _level_key(level)
    res = research.group_studies(as_of, lv)
    res.extra = {**(res.extra or {}), "readings_study": READINGS_STUDY, "mood_study": MOOD_STUDY, "evidence": EVIDENCE,
                 "study_period": EVIDENCE["period"]}
    res.notes = list(res.notes or []) + [
        "Readings study: IC = average daily rank correlation with the next 21 sessions' return vs the median group "
        "(stocks >= Rs 1,000 Cr, groups >= 3 members). Top / bottom = % of days the top / bottom fifth beat the median group.",
        "Local data, one market cycle, current taxonomy. Recheck on the five-year archive before locking any threshold."]
    return res
