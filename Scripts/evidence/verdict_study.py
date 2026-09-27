"""Verdict calibration study (spec §6.1.5 ship gate) — research script, READ-ONLY on the DB.

Question: can a Market Environment verdict (rules on the regime_daily pillars / inputs at the
setup's signal date) separate setup outcomes (R multiples) out-of-sample?

Hygiene
- Unit of evidence = closed setup (status horizon/stopped) in setup_outcomes, keyed to the
  environment on its signal_date (known at that EOD; the fill is on a later session).
- Setups on the same day share one market path, so every t-stat is cluster-robust by signal day
  (``t_day``); a stricter variant clusters by 20-session blocks (``t_blk``), because the holding
  periods (up to 20 sessions) and the regime itself overlap across neighbouring days.
- Train = signal_date 2020-01-01 .. 2024-06-30 minus a 20-session purge before the boundary
  (their outcomes run into the test window). Test = 2024-07-01 .. end. Bucket cut points and
  every design parameter are fitted on train days only; test is evaluated once, untouched.

Usage:  python -m Scripts.evidence.verdict_study [--db PATH] [--phase diag|all] [--out FILE.json]
"""
from __future__ import annotations

import argparse
import json
from typing import Any, Callable

import duckdb
import numpy as np
import pandas as pd

DB = r"D:\Sid\MarketPulse2.0\Database\marketpulse.duckdb"
TRAIN_END = pd.Timestamp("2024-06-30")
TEST_START = pd.Timestamp("2024-07-01")
PURGE_SESSIONS = 20
BLOCK_SESSIONS = 20
GATE = {"gap_r": 0.15, "t": 2.0, "n": 30}
PILLARS = ("trend", "participation", "leadership", "follow_through", "stress")

# Raw inputs examined (regime_daily column or a derived expression), grouped by pillar.
INPUTS: dict[str, tuple[str, str]] = {
    "midsml_vs_ema50_pct": ("trend", "MidSml400 % vs 50 EMA"),
    "midsml_vs_ema200_pct": ("trend", "MidSml400 % vs 200 EMA"),
    "midsml_ema50_slope_pct": ("trend", "MidSml400 50 EMA 5-session slope %"),
    "nifty_vs_ema200_pct": ("trend", "Nifty 50 % vs 200 EMA"),
    "midsml_ret_5d_pct": ("trend", "MidSml400 5-session return %"),
    "above_50ema_pct": ("participation", "% stocks > 50 EMA"),
    "above_200ema_pct": ("participation", "% stocks > 200 EMA"),
    "above_10ema_pct": ("participation", "% stocks > 10 EMA"),
    "above_50ema_chg_5d": ("participation", "% > 50 EMA, 5-session change"),
    "ad_line_10d": ("participation", "10-session A/D sum"),
    "net_new_highs_10d_avg": ("leadership", "Net new highs, 10-session avg"),
    "net_new_highs_10d_chg_5d": ("leadership", "Net new highs avg, 5-session change"),
    "stage2_pct": ("leadership", "% passing trend template"),
    "follow_through_pct": ("follow_through", "Follow-through %"),
    "distribution_days_25": ("stress", "Distribution days (25)"),
    "vix_close": ("stress", "India VIX level"),
    "vix_1d_pct": ("stress", "VIX 1-day change %"),
    "vix_5d_pct": ("stress", "VIX 5-session change %"),
}

REGIME_COLS = [
    "trade_date", "verdict", "raw_verdict",
    *[f"{p}_status" for p in PILLARS], *[f"{p}_status_raw" for p in PILLARS],
    "midsml_close", "midsml_ema50", "midsml_ema200", "midsml_ema50_slope_pct", "nifty_close", "nifty_ema200",
    "midsml_ret_5d_pct", "above_10ema_pct", "above_50ema_pct", "above_200ema_pct", "above_50ema_chg_5d",
    "ad_line_10d", "net_new_highs_10d_avg", "net_new_highs_10d_chg_5d", "stage2_pct", "follow_through_pct",
    "distribution_days_25", "vix_close", "vix_1d_pct", "vix_5d_pct",
]


# ---------------------------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------------------------
def load(db: str = DB) -> tuple[pd.DataFrame, pd.DataFrame]:
    con = duckdb.connect(db, read_only=True)
    try:
        o = con.execute(
            "SELECT queue, signal_date, r_multiple, hit_2r FROM setup_outcomes "
            "WHERE status IN ('horizon', 'stopped') AND r_multiple IS NOT NULL").df()
        r = con.execute(f"SELECT {', '.join(REGIME_COLS)} FROM regime_daily ORDER BY trade_date").df()
    finally:
        con.close()
    o["signal_date"] = pd.to_datetime(o["signal_date"]).dt.normalize()
    o["hit_2r"] = o["hit_2r"].astype(float)
    r["trade_date"] = pd.to_datetime(r["trade_date"]).dt.normalize()
    r["midsml_vs_ema50_pct"] = (r["midsml_close"] / r["midsml_ema50"] - 1) * 100
    r["midsml_vs_ema200_pct"] = (r["midsml_close"] / r["midsml_ema200"] - 1) * 100
    r["nifty_vs_ema200_pct"] = (r["nifty_close"] / r["nifty_ema200"] - 1) * 100
    # trend_template_pass is False (not NULL) during its 1-year warm-up, so stage2_pct reads 0 all of
    # 2020; exactly 0 never occurs afterwards (min 1.97), so treat it as unknown here.
    r.loc[r["stage2_pct"] == 0, "stage2_pct"] = np.nan
    r["session_idx"] = np.arange(len(r))
    r["block"] = r["session_idx"] // BLOCK_SESSIONS
    sess = r["trade_date"]
    train_last = sess[sess <= TRAIN_END]
    purge_from = train_last.iloc[-PURGE_SESSIONS]  # first purged session
    r["split"] = np.where(sess >= TEST_START, "test", np.where(sess < purge_from, "train", "purged"))
    r.attrs["purge_from"] = purge_from
    return o, r


def merged(o: pd.DataFrame, r: pd.DataFrame) -> pd.DataFrame:
    """Setups joined to the environment on their signal date. Only sessions with a published verdict
    are kept (the pillars are warmed up: ~200 sessions of EMA/52W history), so every design is
    compared on the same days; 2020 is mostly warm-up (stage2_pct is 0, not NULL, there)."""
    m = o.merge(r, left_on="signal_date", right_on="trade_date", how="inner")
    return m.loc[m["verdict"].notna()].reset_index(drop=True)


# ---------------------------------------------------------------------------------------------
# Cluster-robust statistics
# ---------------------------------------------------------------------------------------------
def cmean(g: pd.DataFrame, cluster: str) -> tuple[float, float, int, int]:
    """(mean R, cluster-robust variance of the mean, n setups, n clusters)."""
    n = len(g)
    if n == 0:
        return np.nan, np.nan, 0, 0
    m = g["r_multiple"].mean()
    s = g.groupby(cluster)["r_multiple"].agg(["sum", "count"])
    c = len(s)
    if c < 2:
        return m, np.nan, n, c
    resid = s["sum"] - s["count"] * m
    var = (resid ** 2).sum() / n ** 2 * c / (c - 1)
    return float(m), float(var), n, c


def gap_stats(good: pd.DataFrame, bad: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {"n_good": len(good), "n_bad": len(bad),
                           "days_good": good["signal_date"].nunique(), "days_bad": bad["signal_date"].nunique()}
    mg, vg, _, _ = cmean(good, "signal_date")
    mb, vb, _, _ = cmean(bad, "signal_date")
    _, vgb, _, cg = cmean(good, "block")
    _, vbb, _, cb = cmean(bad, "block")
    gap = mg - mb
    out.update({"avg_r_good": mg, "avg_r_bad": mb, "gap_r": gap,
                "t_day": gap / np.sqrt(vg + vb) if (vg + vb) > 0 else np.nan,
                "t_blk": gap / np.sqrt(vgb + vbb) if (vgb + vbb) > 0 else np.nan,
                "blocks_good": cg, "blocks_bad": cb})
    out["passes"] = bool(out["n_good"] >= GATE["n"] and out["n_bad"] >= GATE["n"] and gap >= GATE["gap_r"]
                         and out["t_day"] >= GATE["t"])
    return out


def bucket_row(g: pd.DataFrame) -> dict[str, Any]:
    m, v, n, c = cmean(g, "signal_date")
    return {"n": n, "days": c, "avg_r": m, "se_day": np.sqrt(v) if v == v else np.nan,
            "hit_2r": g["hit_2r"].mean() * 100 if n else np.nan}


# ---------------------------------------------------------------------------------------------
# Diagnosis
# ---------------------------------------------------------------------------------------------
def train_days(r: pd.DataFrame) -> pd.DataFrame:
    return r.loc[(r["split"] == "train") & r["verdict"].notna()]


def quintile_edges(r: pd.DataFrame, col: str) -> np.ndarray:
    v = train_days(r)[col].dropna()
    return np.unique(np.quantile(v, [0.2, 0.4, 0.6, 0.8]))


def diag_inputs(m: pd.DataFrame, r: pd.DataFrame, split: str) -> list[dict[str, Any]]:
    rows = []
    mm = m.loc[m["split"] == split]
    for col, (pillar, label) in INPUTS.items():
        edges = quintile_edges(r, col)
        b = np.digitize(mm[col], edges)
        b = pd.Series(np.where(mm[col].isna(), -1, b), index=mm.index)
        rec: dict[str, Any] = {"input": col, "pillar": pillar, "label": label, "edges": [round(float(e), 2) for e in edges]}
        for q in range(len(edges) + 1):
            rec[f"Q{q + 1}"] = bucket_row(mm.loc[b == q])
        top, bot = mm.loc[b == len(edges)], mm.loc[b == 0]
        rec["top_minus_bottom"] = gap_stats(top, bot)
        per_q = {}
        for qn, gq in mm.groupby("queue"):
            bq = b.loc[gq.index]
            per_q[qn] = gap_stats(gq.loc[bq == len(edges)], gq.loc[bq == 0])
        rec["by_queue"] = per_q
        rows.append(rec)
    return rows


def diag_status(m: pd.DataFrame, split: str, col: str, levels: list[str]) -> dict[str, Any]:
    mm = m.loc[m["split"] == split]
    out: dict[str, Any] = {}
    for q, g in [("all", mm), *list(mm.groupby("queue"))]:
        out[q] = {lv: bucket_row(g.loc[g[col] == lv]) for lv in levels}
    return out


# ---------------------------------------------------------------------------------------------
# Candidate designs: each returns a function day-frame -> Series of 'good' / 'bad' / 'mid'.
# Every parameter is fitted on train days only.
# ---------------------------------------------------------------------------------------------
def label_verdict(col: str) -> Callable[[pd.DataFrame], pd.Series]:
    def f(d: pd.DataFrame) -> pd.Series:
        v = d[col]
        return pd.Series(np.where(v.isin(["Favourable", "Constructive"]), "good",
                                  np.where(v.isin(["Weak", "Danger"]), "bad", "mid")), index=d.index)
    return f


def run_design(name: str, desc: str, labeller: Callable[[pd.DataFrame], pd.Series], m: pd.DataFrame,
               params: dict[str, Any] | None = None) -> dict[str, Any]:
    lab = labeller(m)
    res: dict[str, Any] = {"design": name, "desc": desc, "params": params or {}}
    for split in ("train", "test"):
        s = m["split"] == split
        res[split] = gap_stats(m.loc[s & (lab == "good")], m.loc[s & (lab == "bad")])
        res[split]["share_days_good"] = float(m.loc[s].assign(l=lab).drop_duplicates("signal_date")["l"].eq("good").mean())
        res[split]["share_days_bad"] = float(m.loc[s].assign(l=lab).drop_duplicates("signal_date")["l"].eq("bad").mean())
        res[split]["by_queue"] = {q: gap_stats(g.loc[lab.loc[g.index] == "good"], g.loc[lab.loc[g.index] == "bad"])
                                  for q, g in m.loc[s].groupby("queue")}
    return res


def fit_best_single(m: pd.DataFrame, r: pd.DataFrame) -> tuple[str, int, float, float]:
    """Train only: input whose top-vs-bottom tercile gap (by day-clustered t) is largest in |t|;
    sign chosen by the train gap. Returns (col, sign, lo_cut, hi_cut)."""
    tr = m.loc[m["split"] == "train"]
    best = None
    for col in INPUTS:
        v = train_days(r)[col].dropna()
        lo, hi = np.quantile(v, [1 / 3, 2 / 3])
        g = gap_stats(tr.loc[tr[col] > hi], tr.loc[tr[col] < lo])
        if best is None or abs(g["t_day"]) > abs(best[1]["t_day"]):
            best = (col, g, lo, hi)
    col, g, lo, hi = best
    return col, (1 if g["gap_r"] > 0 else -1), float(lo), float(hi)


def fit_composite(m: pd.DataFrame, r: pd.DataFrame) -> tuple[dict[str, float], dict[str, tuple[float, float]], float, float]:
    """Train only: equal-weight sum of z-scored inputs, each signed by the sign of its train
    top-vs-bottom quintile gap, kept only if that gap has |t_day| >= 1. Cut = train terciles."""
    tr = m.loc[m["split"] == "train"]
    rt = train_days(r)
    signs, norms = {}, {}
    for col in INPUTS:
        v = rt[col].dropna()
        e = np.quantile(v, [0.2, 0.8])
        g = gap_stats(tr.loc[tr[col] > e[1]], tr.loc[tr[col] < e[0]])
        if abs(g["t_day"]) >= 1.0:
            signs[col] = 1.0 if g["gap_r"] > 0 else -1.0
            norms[col] = (float(v.mean()), float(v.std()))
    score_tr = composite(rt, signs, norms)
    lo, hi = np.quantile(score_tr.dropna(), [1 / 3, 2 / 3])
    return signs, norms, float(lo), float(hi)


def composite(d: pd.DataFrame, signs: dict[str, float], norms: dict[str, tuple[float, float]]) -> pd.Series:
    if not signs:
        return pd.Series(np.nan, index=d.index)
    z = sum(signs[c] * (d[c] - norms[c][0]) / norms[c][1] for c in signs)
    return z / len(signs)


def fit_tree(m: pd.DataFrame, r: pd.DataFrame, min_days: int = 120) -> list[dict[str, Any]]:
    """Train only: a depth-2 split tree on day-level mean R (weighted by setups) over the pillar
    INPUTS with tercile candidate thresholds; each leaf needs >= min_days train days. Leaves are
    labelled good/bad/mid by train leaf mean vs the train mean +- 0.1R. Returns leaf rules."""
    tr = m.loc[m["split"] == "train"]
    day = tr.groupby("signal_date").agg(s=("r_multiple", "sum"), n=("r_multiple", "count"))
    day = day.join(r.set_index("trade_date")[list(INPUTS)], how="left")

    def sse(dd: pd.DataFrame) -> float:
        if dd["n"].sum() == 0:
            return 0.0
        mu = dd["s"].sum() / dd["n"].sum()
        return float(((dd["s"] / dd["n"] - mu) ** 2 * dd["n"]).sum())

    def best_split(dd: pd.DataFrame) -> tuple[str, float] | None:
        base, best = sse(dd), None
        for col in INPUTS:
            v = dd[col].dropna()
            if len(v) < 2 * min_days:
                continue
            for q in (1 / 3, 1 / 2, 2 / 3):
                thr = float(np.quantile(v, q))
                left, right = dd.loc[dd[col] <= thr], dd.loc[dd[col] > thr]
                if len(left) < min_days or len(right) < min_days:
                    continue
                gain = base - sse(left) - sse(right)
                if best is None or gain > best[0]:
                    best = (gain, col, thr)
        return None if best is None else (best[1], best[2])

    leaves: list[dict[str, Any]] = []
    s1 = best_split(day)
    if s1 is None:
        return leaves
    for side1, sub in (("<=", day.loc[day[s1[0]] <= s1[1]]), (">", day.loc[day[s1[0]] > s1[1]])):
        s2 = best_split(sub)
        parts = [((s1[0], side1, s1[1]),)]
        if s2 is not None:
            parts = [((s1[0], side1, s1[1]), (s2[0], "<=", s2[1])), ((s1[0], side1, s1[1]), (s2[0], ">", s2[1]))]
        for conds in parts:
            leaves.append({"conds": [(c, op, round(t, 3)) for c, op, t in conds]})
    mu = day["s"].sum() / day["n"].sum()
    for lf in leaves:
        mask = leaf_mask(day, lf["conds"])
        lm = day.loc[mask, "s"].sum() / max(day.loc[mask, "n"].sum(), 1)
        lf["train_mean"] = float(lm)
        lf["train_days"] = int(mask.sum())
        lf["label"] = "good" if lm >= mu + 0.1 else ("bad" if lm <= mu - 0.1 else "mid")
    return leaves


def leaf_mask(d: pd.DataFrame, conds: list[tuple[str, str, float]]) -> pd.Series:
    mask = pd.Series(True, index=d.index)
    for c, op, t in conds:
        mask &= (d[c] <= t) if op == "<=" else (d[c] > t)
    return mask


def designs(m: pd.DataFrame, r: pd.DataFrame) -> list[dict[str, Any]]:
    out = []
    # A. The published verdict as it stands (no fitting).
    out.append(run_design("A_published", "Current published verdict (hysteresis), Fav+Con vs Weak+Danger",
                          label_verdict("verdict"), m))
    # A'. Same rules on today's raw statuses (no hysteresis).
    out.append(run_design("A_raw", "Current rules on raw (unsmoothed) statuses", label_verdict("raw_verdict"), m))

    # B. Trend pillar alone (no fitting): good = Trend Healthy, bad = Trend Weak.
    def trend_only(d):
        t = d["trend_status"]
        return pd.Series(np.where(t == "Healthy", "good", np.where(t == "Weak", "bad", "mid")), index=d.index)
    out.append(run_design("B_trend_only", "Trend status alone: Healthy=good, Weak=bad", trend_only, m))

    # C. Best single input on train (terciles).
    col, sign, lo, hi = fit_best_single(m, r)

    def single(d):
        v = d[col] * sign
        a, b = sorted((lo * sign, hi * sign))
        return pd.Series(np.where(v > b, "good", np.where(v < a, "bad", "mid")), index=d.index).where(d[col].notna(), "mid")
    out.append(run_design("C_best_single", f"Best single train input ({col}, sign {sign:+d}), train terciles",
                          single, m, {"input": col, "sign": sign, "lo": lo, "hi": hi}))

    # D. Equal-weight signed composite (train-selected inputs), train terciles.
    signs, norms, clo, chi = fit_composite(m, r)

    def comp(d):
        z = composite(d, signs, norms)
        return pd.Series(np.where(z > chi, "good", np.where(z < clo, "bad", "mid")), index=d.index).where(z.notna(), "mid")
    out.append(run_design("D_composite", "Equal-weight signed z-composite of train-significant inputs, train terciles",
                          comp, m, {"signs": signs, "lo": clo, "hi": chi}))

    # E. Depth-2 split tree (<= 4 leaf rules) on the inputs.
    leaves = fit_tree(m, r)

    def tree(d):
        lab = pd.Series("mid", index=d.index)
        for lf in leaves:
            lab[leaf_mask(d, lf["conds"])] = lf["label"]
        return lab
    out.append(run_design("E_tree", "Depth-2 split tree on inputs (<=4 leaf rules), leaves labelled on train",
                          tree, m, {"leaves": leaves}))
    return out


# ---------------------------------------------------------------------------------------------
def _clean(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if not np.isfinite(x) else round(float(x), 4)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if isinstance(x, pd.Timestamp):
        return x.date().isoformat()
    return x


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB)
    ap.add_argument("--phase", default="all", choices=["diag", "all"])
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    o, r = load(a.db)
    m = merged(o, r)
    res: dict[str, Any] = {
        "split": {"train": [str(r.loc[r.split == "train", "trade_date"].min().date()), str(r.loc[r.split == "train", "trade_date"].max().date())],
                  "purged_from": str(r.attrs["purge_from"].date()),
                  "test": [str(r.loc[r.split == "test", "trade_date"].min().date()), str(r.loc[r.split == "test", "trade_date"].max().date())]},
        "n": {s: {"setups": int((m.split == s).sum()), "days": int(m.loc[m.split == s, "signal_date"].nunique())}
              for s in ("train", "purged", "test")},
    }
    splits = ("train",) if a.phase == "diag" else ("train", "test")
    for s in splits:
        mm = m.loc[m.split == s]
        res[f"overall_{s}"] = {q: bucket_row(g) for q, g in [("all", mm), *list(mm.groupby("queue"))]}
        res[f"inputs_{s}"] = diag_inputs(m, r, s)
        res[f"verdict_{s}"] = diag_status(m, s, "verdict", ["Favourable", "Constructive", "Mixed", "Weak", "Danger"])
        for p in PILLARS:
            res[f"{p}_{s}"] = diag_status(m, s, f"{p}_status", ["Healthy", "Neutral", "Weak"])
    if a.phase == "all":
        res["designs"] = designs(m, r)
    txt = json.dumps(_clean(res), indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(txt)
    else:
        print(txt)


if __name__ == "__main__":
    main()
