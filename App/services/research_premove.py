"""Research View 3, "Before the big moves" (10-tab-research.md §§5, 13).

Port of HarkPro/tools/bigmove_study/premove.py + premove_split.py.

- Event ("early lift"): a stock >= Rs 1,000 Cr closes >= 20% above its 120-session low for the first time
  in 60 sessions. Only events with >= 120 earlier sessions of the stock are studied (trait warm-up).
- Outcome over the next 120 sessions: runner = a close >= +50% above the event close; fizzle = never
  +15%; the rest are left out of the rates. An outcome is used only once its 120 sessions closed on as_of.
- 30 traits at the event close: daily (D), weekly (W), monthly (M), accumulation (A), improvement (I),
  base (B). All use data on or before the event session.
- Two families: Turnaround lifts (close below the 200 EMA) and Trend lifts (above it).
- Profile: per trait, runner vs fizzle medians and the runner rate in the low vs high third (lift =
  better third / family base).
- Score: the 8 traits with the best lift; a trait is on when the value is in its better third.
  Score = traits on. Runner rate by score is in-sample; the out-of-sample check picks the traits on the
  first 60% of events (by date) and tests them on the rest.
- Regime context: the runner rate of past events by the regime quadrant on the event day, as a
  multiple of the family's base rate.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from App.services import db
from App.services import research_lab as lab
from App.services import research_regime as regime_svc
from App.services.common import Result, no_session, unavailable

HORIZON = 120
RUNNER = 1.5
FIZZLE = 1.15
LIFT = 1.2
LOW_WINDOW = 120
QUIET = 60
WARMUP = 120
SCORE_TRAITS = 8
MIN_TRAIT_N = 60
TODAY_SESSIONS = 10
FAMILIES = {
    "trend": {"label": "Trend lifts", "rule": "Close above the 200 EMA at the lift."},
    "turnaround": {"label": "Turnaround lifts", "rule": "Close below the 200 EMA at the lift."},
}
TRAITS: dict[str, str] = {
    "d_above_20ema": "D: % above 20 EMA", "d_above_50ema": "D: % above 50 EMA", "d_above_200ema": "D: % above 200 EMA",
    "d_50ema_over_200ema": "D: 50 EMA above 200 EMA %", "d_rsi14": "D: RSI 14", "d_from_52w_high": "D: % from 52W high",
    "d_above_52w_low": "D: % above 52W low",
    "w_above_10w": "W: % above 10W EMA", "w_above_30w": "W: % above 30W MA", "w_10w_over_30w": "W: 10W above 30W %",
    "w_rsi": "W: weekly RSI", "w_higher_lows": "W: higher weekly lows (of 8)", "w_30w_slope13": "W: 30W MA rising (13w slope %)",
    "m_above_10m": "M: % above 10M EMA", "m_rsi": "M: monthly RSI", "m_ret6": "M: 6M return %", "m_ret12": "M: 12M return %",
    "a_updown_50d": "A: up/down volume 50d", "a_updown_13w": "A: up/down volume 13w",
    "a_delivery_vs_6m": "A: delivery % vs 6M avg", "a_acc_minus_dist_13w": "A: accumulation minus distribution weeks (13w)",
    "a_value_20d_vs_6m": "A: traded value 20d vs 6M",
    "i_rs_now": "I: RS percentile now", "i_rs_chg_1m": "I: RS change 1M", "i_rs_chg_3m": "I: RS change 3M",
    "i_tt_checks": "I: trend-template checks (of 8)", "i_tt_gained_1m": "I: template checks gained 1M",
    "i_200ema_slope_1m": "I: 200 EMA slope 1M %",
    "b_range_50d": "B: 50d range %", "b_atr_vs_avg": "B: ATR% vs its 50d avg", "b_days_from_low": "B: days to lift from low",
}


def _days_from_low(cl: np.ndarray, starts: np.ndarray) -> np.ndarray:
    """Sessions since the lowest close of the last 120 (min 60), per symbol block."""
    out = np.full(len(cl), np.nan)
    bounds = list(starts) + [len(cl)]
    for b0, b1 in zip(bounds[:-1], bounds[1:]):
        a = cl[b0:b1].astype(float)
        a = np.where(np.isnan(a), np.inf, a)
        n = len(a)
        for i in range(min(n, LOW_WINDOW - 1)):
            if i + 1 >= QUIET:
                w = a[: i + 1]
                out[b0 + i] = len(w) - 1 - int(np.argmin(w))
        if n >= LOW_WINDOW:
            win = np.lib.stride_tricks.sliding_window_view(a, LOW_WINDOW)
            out[b0 + LOW_WINDOW - 1: b1] = LOW_WINDOW - 1 - np.argmin(win, axis=1)
    return out


def compute_events(con: Any, end: date) -> pd.DataFrame:
    d, T, pos = trait_frame(lab.frame(con, end))
    sel = d.event & (pos >= WARMUP)
    E = d.loc[sel, ["symbol", "trade_date", "close_price", "fmax", "security_name", "industry", "mcap_now"]].copy()
    for k, v in T.items():
        E[k] = v[sel].astype(float).replace([np.inf, -np.inf], np.nan)
    E["family"] = np.where(E.d_above_200ema.isna(), None, np.where(E.d_above_200ema < 0, "turnaround", "trend"))
    up = E.fmax / E.close_price
    E["outcome"] = np.where(E.fmax.isna(), None, np.where(up >= RUNNER, "runner", np.where(up < FIZZLE, "fizzle", "middle")))
    E["max_gain_pct"] = (up - 1) * 100
    return E.rename(columns={"close_price": "close", "mcap_now": "mcap_cr"}).reset_index(drop=True)


def trait_frame(d: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.Series], pd.Series]:
    """(frame with event / fmax columns, the 30 trait series, position within symbol) for a research frame
    (any set of symbols, sorted by symbol + date). Every trait uses data on or before its own session."""
    d = d[["symbol", "trade_date", "close_price", "high_price", "low_price", "volume", "delivery_pct",
           "avg_delivery_pct_20d", "ema_20", "ema_50", "ema_200", "wema_10", "wma_30", "mema_10", "rsi_14", "rsi_14_w",
           "rsi_14_m", "rs_percentile", "trend_template_pass_n", "away_52w_high_pct", "away_52w_low_pct", "atr_pct",
           "atr_pct_avg_50d", "range_50d_pct", "avg_traded_value_cr_20d", "security_name", "industry", "mcap_now"]].copy()
    d = d.reset_index(drop=True)
    g = d.groupby("symbol", sort=False)
    pos = g.cumcount()

    def roll(col: str, n: int, f: str = "mean", mp: int | None = None) -> pd.Series:
        r = g[col].rolling(n, min_periods=mp or n)
        return getattr(r, f)().reset_index(level=0, drop=True)

    def gshift(s: pd.Series, k: int) -> pd.Series:
        return s.groupby(d.symbol, sort=False).shift(k)

    cl = d.close_price
    d["low120"] = roll("close_price", LOW_WINDOW, "min", QUIET)
    lift = (cl >= LIFT * d.low120).astype(float)
    d["_lift"] = lift
    prev = g["_lift"].shift(1).groupby(d.symbol, sort=False).rolling(QUIET, min_periods=1).max().reset_index(level=0, drop=True)
    d["event"] = (lift == 1) & ~(prev.fillna(1) == 1)
    rev = d.iloc[::-1]
    fmax = rev.groupby("symbol", sort=False).close_price.rolling(HORIZON, min_periods=HORIZON).max().reset_index(level=0, drop=True)
    d["fmax"] = gshift(fmax.reindex(d.index), -1)
    # traits
    ret = g.close_price.pct_change()
    d["_up"] = np.where(ret > 0, d.volume, 0.0)
    d["_dn"] = np.where(ret < 0, d.volume, 0.0)
    T: dict[str, pd.Series] = {}
    T["d_above_20ema"] = (cl / d.ema_20 - 1) * 100
    T["d_above_50ema"] = (cl / d.ema_50 - 1) * 100
    T["d_above_200ema"] = (cl / d.ema_200 - 1) * 100
    T["d_50ema_over_200ema"] = (d.ema_50 / d.ema_200 - 1) * 100
    T["d_rsi14"] = d.rsi_14
    T["d_from_52w_high"] = d.away_52w_high_pct
    T["d_above_52w_low"] = d.away_52w_low_pct
    T["w_above_10w"] = (cl / d.wema_10 - 1) * 100
    T["w_above_30w"] = (cl / d.wma_30 - 1) * 100
    T["w_10w_over_30w"] = (d.wema_10 / d.wma_30 - 1) * 100
    T["w_rsi"] = d.rsi_14_w
    lo5 = roll("low_price", 5, "min")
    hl = sum((gshift(lo5, 5 * k) > gshift(lo5, 5 * (k + 1))).astype(int) for k in range(8))
    T["w_higher_lows"] = hl
    T["w_30w_slope13"] = (d.wma_30 / gshift(d.wma_30, 65) - 1) * 100
    T["m_above_10m"] = (cl / d.mema_10 - 1) * 100
    T["m_rsi"] = d.rsi_14_m
    T["m_ret6"] = (cl / gshift(cl, 126) - 1) * 100
    T["m_ret12"] = (cl / gshift(cl, 250) - 1) * 100
    T["a_updown_50d"] = roll("_up", 50, "sum") / roll("_dn", 50, "sum")
    T["a_updown_13w"] = roll("_up", 65, "sum") / roll("_dn", 65, "sum")
    T["a_delivery_vs_6m"] = d.avg_delivery_pct_20d - roll("delivery_pct", 126, "mean", 60)
    wk_ret = cl / gshift(cl, 5) - 1
    wk_vol = roll("volume", 5, "sum")
    d["_wk_vol"] = wk_vol
    wk_avg = g["_wk_vol"].rolling(50).mean().reset_index(level=0, drop=True)
    d["_acc"] = ((wk_ret > 0) & (wk_vol > wk_avg)).astype(float)
    d["_dist"] = ((wk_ret < 0) & (wk_vol > wk_avg)).astype(float)
    T["a_acc_minus_dist_13w"] = sum(gshift(d._acc, 5 * k) - gshift(d._dist, 5 * k) for k in range(13))
    T["a_value_20d_vs_6m"] = d.avg_traded_value_cr_20d / roll("avg_traded_value_cr_20d", 126, "mean", 60)
    T["i_rs_now"] = d.rs_percentile
    T["i_rs_chg_1m"] = d.rs_percentile - gshift(d.rs_percentile, 21)
    T["i_rs_chg_3m"] = d.rs_percentile - gshift(d.rs_percentile, 63)
    T["i_tt_checks"] = d.trend_template_pass_n
    T["i_tt_gained_1m"] = d.trend_template_pass_n - gshift(d.trend_template_pass_n, 21)
    T["i_200ema_slope_1m"] = (d.ema_200 / gshift(d.ema_200, 21) - 1) * 100
    T["b_range_50d"] = d.range_50d_pct
    T["b_atr_vs_avg"] = d.atr_pct / d.atr_pct_avg_50d
    starts = np.flatnonzero(np.r_[True, d.symbol.to_numpy()[1:] != d.symbol.to_numpy()[:-1]])
    T["b_days_from_low"] = pd.Series(_days_from_low(cl.to_numpy(), starts), index=d.index)
    return d, T, pos


def events(con: Any, end: date) -> tuple[pd.DataFrame, str]:
    return lab.table_or_compute(con, "research_premove_events", end, lambda: compute_events(con, end))


# --------------------------------------------------------------------------
# Profile / score
# --------------------------------------------------------------------------
def profile(sub: pd.DataFrame) -> list[dict[str, Any]]:
    """Runner vs fizzle medians and low/high-third runner rates per trait (sub = resolved runner/fizzle events)."""
    base = sub.runner.mean() * 100 if len(sub) else np.nan
    rows = []
    for k, label in TRAITS.items():
        x = sub[[k, "runner"]].dropna()
        if len(x) < MIN_TRAIT_N or not base:
            continue
        q = pd.qcut(x[k].rank(method="first"), 3, labels=False)
        r = x.groupby(q).runner.mean() * 100
        lo, hi = float(r.iloc[0]), float(r.iloc[-1])
        rows.append({"trait": k, "label": label, "group": label[0], "n": int(len(x)),
                     "runner_median": lab.rnd(x.loc[x.runner, k].median(), 2),
                     "fizzle_median": lab.rnd(x.loc[~x.runner, k].median(), 2),
                     "low_third_pct": round(lo, 1), "high_third_pct": round(hi, 1),
                     "better_when": "high" if hi >= lo else "low", "lift": round(max(lo, hi) / base, 2),
                     "cut_low": lab.rnd(x[k].quantile(1 / 3), 3), "cut_high": lab.rnd(x[k].quantile(2 / 3), 3)})
    return sorted(rows, key=lambda r: -r["lift"])


def pick_traits(prof: list[dict[str, Any]], n: int = SCORE_TRAITS) -> list[dict[str, Any]]:
    return [{"trait": r["trait"], "label": r["label"], "side": r["better_when"],
             "cut": r["cut_high"] if r["better_when"] == "high" else r["cut_low"], "lift": r["lift"]} for r in prof[:n]]


def score(df: pd.DataFrame, picks: list[dict[str, Any]]) -> pd.Series:
    s = pd.Series(0, index=df.index)
    for p in picks:
        v = df[p["trait"]]
        s += ((v >= p["cut"]) if p["side"] == "high" else (v <= p["cut"])).fillna(False).astype(int)
    return s


BUCKETS = [(-1, 2, "0-2"), (2, 4, "3-4"), (4, 6, "5-6"), (6, 8, "7-8")]


def bucket_of(s: int) -> str:
    return next(lbl for lo, hi, lbl in BUCKETS if lo < s <= hi)


def bucket_table(df: pd.DataFrame, sc: pd.Series) -> list[dict[str, Any]]:
    out = []
    for lo, hi, lbl in BUCKETS:
        m = (sc > lo) & (sc <= hi)
        x = df[m]
        out.append({"bucket": lbl, "events": int(len(x)),
                    "runner_pct": lab.rnd(x.runner.mean() * 100) if len(x) else None})
    return out


@lab.memo("before_moves")
def before_moves(as_of: date | None, family: str = "trend", days: int = TODAY_SESSIONS) -> Result:
    if family not in FAMILIES:
        raise ValueError(f"family must be one of {', '.join(FAMILIES)}")
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        end = lab.study_end(con, resolved)
        full_end = lab.study_end(con, None) or end
        E, source = events(con, full_end)
        R, _ = regime_svc.daily(con, full_end)
        all_days = [x for x in lab.sessions(con) if x <= end]
    if end is None or E.empty:
        return unavailable(end, "no early-lift events", ["indicators_daily"], caveat=lab.CAVEAT)
    E = E[E.trade_date <= pd.Timestamp(end)].copy()
    ei = len(all_days) - 1
    idx = {pd.Timestamp(x): i for i, x in enumerate(all_days)}
    E["_si"] = E.trade_date.map(idx)
    E["resolved"] = (ei - E._si >= HORIZON) & E.outcome.notna()
    qmap = R.set_index("trade_date").quadrant
    E["quadrant"] = E.trade_date.map(qmap)
    fam_all = E[E.family == family]
    study = fam_all[fam_all.resolved & fam_all.outcome.isin(["runner", "fizzle"])].copy()
    study["runner"] = study.outcome == "runner"
    base = study.runner.mean() * 100 if len(study) else None
    prof = profile(study)
    picks = pick_traits(prof)
    in_sample = bucket_table(study, score(study, picks)) if picks else []
    # out of sample: pick on the first 60 % (by date), test on the rest
    oos: dict[str, Any] = {"train_events": 0, "test_events": 0, "buckets": [], "test_base_pct": None}
    if len(study) >= 2 * MIN_TRAIT_N:
        st = study.sort_values("trade_date")
        cut = int(len(st) * 0.6)
        tr, te = st.iloc[:cut], st.iloc[cut:]
        p_tr = pick_traits(profile(tr))
        if p_tr:
            oos = {"train_events": int(len(tr)), "test_events": int(len(te)),
                   "train_to": lab.clean(tr.trade_date.iat[-1]), "test_from": lab.clean(te.trade_date.iat[0]),
                   "test_base_pct": lab.rnd(te.runner.mean() * 100), "traits": [p["label"] for p in p_tr],
                   "buckets": bucket_table(te, score(te, p_tr))}
    # regime multiplier
    regime_rows = []
    for q, meta in regime_svc.QUADRANTS.items():
        x = study[study.quadrant == q]
        rate = x.runner.mean() * 100 if len(x) else None
        regime_rows.append({"quadrant": q, "label": meta["label"], "events": int(len(x)),
                            "runner_pct": lab.rnd(rate), "multiplier": lab.rnd(rate / base, 2) if rate is not None and base else None})
    rmult = {r["quadrant"]: r for r in regime_rows}
    by_bucket = {b["bucket"]: b for b in in_sample}
    # today's early lifts
    lo_i = max(0, ei - max(1, int(days)) + 1)
    today = fam_all[fam_all._si >= lo_i].copy()
    if len(today) and picks:
        today["score"] = score(today, picks)
    rows = []
    for _, r in today.sort_values("trade_date", ascending=False).iterrows():
        sc = int(r.get("score", 0) or 0)
        b = bucket_of(sc)
        on = [p["label"] for p in picks if not pd.isna(r[p["trait"]]) and
              ((r[p["trait"]] >= p["cut"]) if p["side"] == "high" else (r[p["trait"]] <= p["cut"]))]
        q = r.quadrant if isinstance(r.quadrant, str) else None
        rows.append({"symbol": r.symbol, "security_name": lab.clean(r.security_name), "industry": lab.clean(r.industry),
                     "mcap_cr": lab.rnd(r.mcap_cr, 0), "lift_date": lab.clean(r.trade_date), "close": lab.rnd(r.close, 2),
                     "score": sc, "score_max": len(picks), "bucket": b,
                     "bucket_runner_pct": by_bucket.get(b, {}).get("runner_pct"),
                     "bucket_events": by_bucket.get(b, {}).get("events"),
                     "traits_on": on, "quadrant": q,
                     "quadrant_label": regime_svc.QUADRANTS.get(q or "", {}).get("label"),
                     "regime_multiplier": rmult.get(q or "", {}).get("multiplier"),
                     "above_200ema_pct": lab.rnd(r.d_above_200ema, 1), "range_50d_pct": lab.rnd(r.b_range_50d, 1),
                     "rs_percentile": lab.rnd(r.i_rs_now, 0)})
    rows.sort(key=lambda x: (-x["score"], str(x["symbol"])))
    counts = {"events": int(len(study)), "runners": int(study.runner.sum()) if len(study) else 0,
              "fizzles": int((~study.runner).sum()) if len(study) else 0, "base_runner_pct": lab.rnd(base),
              "from": lab.clean(study.trade_date.min()) if len(study) else None,
              "to": lab.clean(study.trade_date.max()) if len(study) else None,
              "middle_excluded": int((fam_all.resolved & (fam_all.outcome == "middle")).sum())}
    other = {}
    for f in FAMILIES:
        x = E[(E.family == f) & E.resolved & E.outcome.isin(["runner", "fizzle"])]
        other[f] = {"events": int(len(x)), "base_runner_pct": lab.rnd((x.outcome == "runner").mean() * 100) if len(x) else None}
    cur_q = qmap[qmap.index <= pd.Timestamp(end)].dropna()
    cur_q = cur_q.iat[-1] if len(cur_q) else None
    summary = []
    if base is not None:
        summary.append(f"{counts['events']} past {FAMILIES[family]['label'].lower()} had an outcome. "
                       f"{base:.0f}% became runners (+50% in 120 sessions).")
    if prof:
        top = prof[0]
        summary.append(f"The strongest trait was {top['label'][3:]}: runners were {top['lift']:.1f}x more common in its "
                       f"{'top' if top['better_when'] == 'high' else 'bottom'} third.")
    if cur_q and rmult.get(cur_q, {}).get("multiplier") is not None:
        summary.append(f"The market is in {regime_svc.QUADRANTS[cur_q]['label']} now. Past lifts in that quadrant ran "
                       f"{rmult[cur_q]['multiplier']:.1f}x the base rate.")
    summary.append(f"{len(rows)} stocks made an early lift in the last {days} sessions.")
    summary.append("What to do: Use the score as research. It is not a setup until it beats Setups out of sample.")
    ctx = {"caveat": lab.CAVEAT, "study_end": end, "source": source, "family": family, "families": FAMILIES,
           "family_counts": other, "counts": counts, "profile": prof, "score_traits": picks,
           "score_buckets": in_sample, "oos": oos, "regime": regime_rows, "regime_now": cur_q,
           "regime_now_label": regime_svc.QUADRANTS.get(cur_q or "", {}).get("label"),
           "today_sessions": days, "summary": summary,
           "definition": ("Early lift = a stock >= Rs 1,000 Cr closes >= 20% above its 120-session low for the first time "
                          "in 60 sessions. Runner = a close >= +50% within 120 sessions. Fizzle = never +15%. "
                          "Lifts in between are left out of the rates."),
           "score_note": "Runner rate by score is in-sample. The out-of-sample block picks the traits on older events only."}
    return Result(as_of=end, rows=rows, sources=["indicators_daily"], extra=ctx)
