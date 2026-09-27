"""regime_daily — the Market Environment (spec §6.1): five pillars, verdict, readings, alerts.

One row per session (the trade dates present in `indicators`). Strictly point-in-time: every
input on row t is computed from rows dated <= t. A pillar whose inputs are missing gets status
NULL (the UI shows "Insufficient data"); nothing is defaulted.

Pillars and initial zones (§6.1.2, calibrated later by the evidence engine) live in ZONES;
verdict rules (§6.1.3) live in VERDICT_RULES as data so the UI can show the matched rule.
"""
from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from ._common import (
    INDIA_VIX,
    MIDSML400,
    NIFTY50,
    boolcol,
    ema,
    fmt,
    fmt_signed,
    index_series,
    new_high_low_flags,
    num,
    prep_indicators,
    sign_dir,
)

PILLARS = ("trend", "participation", "leadership", "follow_through", "stress")
STATUSES = ("Weak", "Neutral", "Healthy")
STATUS_RANK = {"Weak": 0, "Neutral": 1, "Healthy": 2}
VERDICTS = ("Danger", "Weak", "Mixed", "Constructive", "Favourable")  # worst -> best
VERDICT_RANK = {v: i for i, v in enumerate(VERDICTS)}
VERDICT_GUIDANCE = {
    "Favourable": "press",
    "Constructive": "normal size",
    "Mixed": "selective, half size",
    "Weak": "mostly cash",
    "Danger": "protect capital",
}

# ---------------------------------------------------------------------------------------------
# Initial zones (§6.1.2). Numbers are starting points, to be calibrated in the evidence engine.
# ---------------------------------------------------------------------------------------------
ZONES: dict[str, Any] = {
    "trend": {
        "benchmark": MIDSML400,
        "confirm": NIFTY50,
        "slope_sessions": 5,
        "rule": (
            "Weak if MidSml400 close < its 200 EMA; Healthy if MidSml400 close > a rising 50 EMA "
            "(50 EMA higher than 5 sessions ago) and Nifty 50 close > its 200 EMA; else Neutral."
        ),
    },
    "participation": {
        "healthy_min": 60.0,
        "weak_below": 40.0,
        "ad_sessions": 10,
        "change_sessions": 5,
        "rule": (
            "Level = mean(% of stocks above 50 EMA, % above 200 EMA): >60 Healthy, 40-60 Neutral, "
            "<40 Weak. Direction overrides level by one step: 10-session A/D sum > 0 AND % above "
            "50 EMA higher than 5 sessions ago => one step up; both negative => one step down."
        ),
    },
    "leadership": {
        "smooth_sessions": 10,
        "change_sessions": 5,
        "rule": (
            "Net new highs = official new 52W highs - new 52W lows, averaged over 10 sessions. "
            "Healthy if the average is > 0 and higher than 5 sessions ago (net highs rising); "
            "Weak if < 0 and lower than 5 sessions ago (net lows expanding); else Neutral."
        ),
    },
    "follow_through": {
        "rvol_min": 1.5,
        "window": (3, 10),
        "healthy_min": 50.0,
        "weak_below": 35.0,
        "min_breakouts": 10,
        "rule": (
            "Breakouts = close above the prior session's 20-day high on RVOL >= 1.5, in sessions "
            "t-10..t-3. Follow-through = % of those still closing above their breakout close on t. "
            ">=50 Healthy, 35-50 Neutral, <35 Weak; NULL when fewer than 10 breakouts."
        ),
    },
    "stress": {
        "dist_drop_pct": -0.2,
        "dist_sessions": 25,
        "dist_weak_min": 5,
        "dist_healthy_max": 3,
        "vix_spike_1d_pct": 20.0,
        "vix_weak_level": 25.0,
        "vix_healthy_below": 18.0,
        "vix_healthy_5d_max_pct": 10.0,
        "rule": (
            "Distribution day = MidSml400 down >= 0.2% on higher index turnover than the prior "
            "session (index_daily.turnover_cr; volume if turnover missing); counted over 25 index "
            "sessions. Weak if >= 5 distribution days, or India VIX +20% in a day, or VIX >= 25. "
            "Healthy if <= 3 distribution days, VIX < 18 and VIX 5-session change <= +10%. Else Neutral."
        ),
    },
    "timing": {
        "stretched_above": 80.0,
        "washed_out_below": 20.0,
        "rule": "% above 10 EMA > 80 stretched (wait 2-3 days), < 20 washed out; never sets the verdict.",
    },
}

# ---------------------------------------------------------------------------------------------
# Verdict rules (§6.1.3) — evaluated top to bottom, first match wins. A condition lists the
# statuses that satisfy it; a NULL pillar never satisfies a condition. Rule R0 (checked first
# in code): Trend or Participation NULL, or fewer than 4 pillars known => verdict NULL.
# ---------------------------------------------------------------------------------------------
VERDICT_RULES: list[dict[str, Any]] = [
    {"rule_id": "R1", "verdict": "Danger", "conditions": {"trend": ["Weak"], "stress": ["Weak"]},
     "text": "Trend Weak and Stress Weak"},
    {"rule_id": "R2", "verdict": "Danger",
     "conditions": {"trend": ["Weak"], "participation": ["Weak"], "follow_through": ["Weak"]},
     "text": "Trend, Participation and Follow-through all Weak"},
    {"rule_id": "R3", "verdict": "Weak", "conditions": {"trend": ["Weak"]},
     "text": "Trend Weak"},
    {"rule_id": "R4", "verdict": "Weak", "conditions": {"participation": ["Weak"], "follow_through": ["Weak"]},
     "text": "Participation Weak and Follow-through Weak"},
    {"rule_id": "R5", "verdict": "Weak", "conditions": {"stress": ["Weak"], "leadership": ["Weak"]},
     "text": "Stress Weak and Leadership Weak"},
    {"rule_id": "R6", "verdict": "Favourable",
     "conditions": {"trend": ["Healthy"], "participation": ["Healthy", "Neutral"], "follow_through": ["Healthy"],
                    "leadership": ["Healthy", "Neutral"], "stress": ["Healthy", "Neutral"]},
     "text": "Trend Healthy, Participation >= Neutral, Follow-through Healthy, Leadership and Stress not Weak"},
    {"rule_id": "R7", "verdict": "Constructive",
     "conditions": {"trend": ["Healthy"], "participation": ["Healthy", "Neutral"],
                    "follow_through": ["Healthy", "Neutral"], "stress": ["Healthy", "Neutral"]},
     "text": "Trend Healthy, Participation and Follow-through >= Neutral, Stress not Weak"},
    {"rule_id": "R8", "verdict": "Constructive",
     "conditions": {"trend": ["Neutral"], "participation": ["Healthy"], "follow_through": ["Healthy"],
                    "stress": ["Healthy", "Neutral"]},
     "text": "Trend Neutral but Participation and Follow-through Healthy, Stress not Weak"},
    {"rule_id": "R9", "verdict": "Mixed", "conditions": {},
     "text": "No stronger or weaker rule matched"},
]
INSUFFICIENT_RULE = {"rule_id": "R0", "verdict": None,
                     "text": "Trend or Participation unknown, or fewer than 4 pillars known"}

# Direction tolerances (goodness-oriented change smaller than this = flat).
DIRECTION_TOL = {"trend": 0.25, "participation": 1.0, "leadership": 1.0, "follow_through": 2.0, "stress": 0.25}
DIRECTION_HORIZONS = {"1d": 1, "1w": 5, "1m": 21}

INDICATOR_COLUMNS = (
    "close_price", "prev_close", "high_price", "low_price", "ema_10", "ema_50", "ema_200",
    "high_20d", "rvol", "high_52w", "low_52w", "high_52w_date", "trend_template_pass",
)


# ---------------------------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------------------------
def _index_block(index_daily: pd.DataFrame | None, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Index-derived inputs, computed on each index's own session history, then aligned."""
    out = pd.DataFrame(index=dates)
    ms = index_series(index_daily, MIDSML400)
    nf = index_series(index_daily, NIFTY50)
    vx = index_series(index_daily, INDIA_VIX)
    z = ZONES["stress"]
    if not ms.empty:
        c = ms["close_price"]
        e50 = ema(c, 50)
        block = pd.DataFrame(
            {
                "midsml_close": c,
                "midsml_ema20": ema(c, 20),
                "midsml_ema50": e50,
                "midsml_ema200": ema(c, 200),
                "midsml_ema50_slope_pct": (e50 / e50.shift(ZONES["trend"]["slope_sessions"]) - 1.0) * 100.0,
                "midsml_ret_1d_pct": (c / c.shift(1) - 1.0) * 100.0,
                "midsml_ret_3d_pct": (c / c.shift(3) - 1.0) * 100.0,
                "midsml_ret_5d_pct": (c / c.shift(5) - 1.0) * 100.0,
            }
        )
        up = (c > c.shift(1)).astype(float).where(c.shift(1).notna())
        block["midsml_up_3d"] = up.rolling(3, min_periods=3).sum() == 3
        flow = ms["turnover_cr"].where(ms["turnover_cr"].notna(), ms["volume"])
        dist = (block["midsml_ret_1d_pct"] <= z["dist_drop_pct"]) & (flow > flow.shift(1))
        known = block["midsml_ret_1d_pct"].notna() & flow.notna() & flow.shift(1).notna()
        block["midsml_dist_day"] = dist.where(known)
        block["distribution_days_25"] = block["midsml_dist_day"].astype(float).rolling(
            z["dist_sessions"], min_periods=z["dist_sessions"]).sum()
        block["distribution_source"] = np.where(ms["turnover_cr"].notna(), "index turnover_cr",
                                                np.where(ms["volume"].notna(), "index volume", None))
        out = out.join(block, how="left")
    if not nf.empty:
        c = nf["close_price"]
        r1 = (c / c.shift(1) - 1.0) * 100.0
        flow = nf["turnover_cr"].where(nf["turnover_cr"].notna(), nf["volume"])
        known = r1.notna() & flow.notna() & flow.shift(1).notna()
        nd = ((r1 <= z["dist_drop_pct"]) & (flow > flow.shift(1))).where(known)
        block = pd.DataFrame(
            {
                "nifty_close": c,
                "nifty_ema50": ema(c, 50),
                "nifty_ema200": ema(c, 200),
                "nifty_distribution_days_25": nd.astype(float).rolling(z["dist_sessions"], min_periods=z["dist_sessions"]).sum(),
            }
        )
        out = out.join(block, how="left")
    if not vx.empty:
        c = vx["close_price"]
        block = pd.DataFrame(
            {
                "vix_close": c,
                "vix_1d_pct": (c / c.shift(1) - 1.0) * 100.0,
                "vix_5d_pct": (c / c.shift(5) - 1.0) * 100.0,
            }
        )
        out = out.join(block, how="left")
    for col in (
        "midsml_close", "midsml_ema20", "midsml_ema50", "midsml_ema200", "midsml_ema50_slope_pct",
        "midsml_ret_1d_pct", "midsml_ret_3d_pct", "midsml_ret_5d_pct", "midsml_up_3d", "midsml_dist_day",
        "distribution_days_25", "distribution_source", "nifty_close", "nifty_ema50", "nifty_ema200",
        "nifty_distribution_days_25", "vix_close", "vix_1d_pct", "vix_5d_pct",
    ):
        if col not in out.columns:
            out[col] = np.nan
    return out


def _stock_block(ind: pd.DataFrame, dates: pd.DatetimeIndex, breadth: pd.DataFrame | None) -> pd.DataFrame:
    """Breadth, new highs/lows, Stage-2 count and follow-through from per-stock rows."""
    close = num(ind, "close_price")
    sym = ind["symbol"]
    g_close = close.groupby(sym, sort=False)
    prev = num(ind, "prev_close")
    prev = prev.where(prev.notna(), g_close.shift(1))

    def pct_above(col: str) -> pd.Series:
        ref = num(ind, col)
        known = close.notna() & ref.notna()
        return pd.Series(np.where(known, (close > ref).astype(float), np.nan), index=ind.index)

    known_move = close.notna() & prev.notna()
    frame = pd.DataFrame(
        {
            "trade_date": ind["trade_date"],
            "above10": pct_above("ema_10"),
            "above50": pct_above("ema_50"),
            "above200": pct_above("ema_200"),
            "adv": np.where(known_move, (close > prev).astype(float), np.nan),
            "dec": np.where(known_move, (close < prev).astype(float), np.nan),
            "stage2": boolcol(ind, "trend_template_pass"),
        }
    )
    flags = new_high_low_flags(ind)
    frame["new_high"] = flags["new_high"].to_numpy()
    frame["new_low"] = flags["new_low"].to_numpy()
    frame["valid52"] = flags["valid_52w"].to_numpy().astype(float)
    frame["rows"] = 1.0

    # Follow-through: breakout events and whether today's close still holds above them.
    hi20 = num(ind, "high_20d")
    if hi20.isna().all():
        hi20 = num(ind, "high_price").groupby(sym, sort=False).rolling(20, min_periods=20).max().reset_index(level=0, drop=True).sort_index()
    prior_hi20 = hi20.groupby(sym, sort=False).shift(1)
    rvol = num(ind, "rvol")
    zf = ZONES["follow_through"]
    event_known = close.notna() & prior_hi20.notna() & rvol.notna()
    event = pd.Series(np.where(event_known, ((close > prior_hi20) & (rvol >= zf["rvol_min"])).astype(float), 0.0), index=ind.index)
    lo, hi = zf["window"]
    ft_n = np.zeros(len(ind))
    ft_hold = np.zeros(len(ind))
    g_event = event.groupby(sym, sort=False)
    for k in range(lo, hi + 1):
        ev_k = g_event.shift(k).fillna(0.0).to_numpy()
        c_k = g_close.shift(k).to_numpy()
        ft_n += ev_k
        ft_hold += ev_k * (close.to_numpy() > c_k)
    frame["ft_n"] = ft_n
    frame["ft_hold"] = ft_hold

    agg = frame.groupby("trade_date", sort=True).agg(
        stocks=("rows", "sum"),
        above_10ema_pct=("above10", "mean"),
        above_50ema_pct=("above50", "mean"),
        above_200ema_pct=("above200", "mean"),
        advancers=("adv", "sum"),
        decliners=("dec", "sum"),
        stage2_count=("stage2", "sum"),
        stage2_known=("stage2", "count"),
        new_highs=("new_high", "sum"),
        new_lows=("new_low", "sum"),
        valid52=("valid52", "sum"),
        breakouts_n=("ft_n", "sum"),
        breakouts_holding=("ft_hold", "sum"),
    )
    for c in ("above_10ema_pct", "above_50ema_pct", "above_200ema_pct"):
        agg[c] = agg[c] * 100.0
    thin = agg["valid52"] < 0.5 * agg["stocks"]
    agg.loc[thin, ["new_highs", "new_lows"]] = np.nan
    agg.loc[agg["stage2_known"] == 0, "stage2_count"] = np.nan
    agg["stage2_pct"] = agg["stage2_count"] / agg["stage2_known"].where(agg["stage2_known"] > 0) * 100.0
    agg = agg.reindex(dates)
    agg["participation_source"] = np.where(agg["stocks"].notna(), "indicators_daily", None)

    if breadth is not None and not breadth.empty and "trade_date" in breadth.columns:
        b = breadth.copy()
        b["trade_date"] = pd.to_datetime(b["trade_date"], errors="coerce").dt.normalize()
        b = b.dropna(subset=["trade_date"]).drop_duplicates("trade_date", keep="last").set_index("trade_date").reindex(dates)
        used = pd.Series(False, index=dates)
        for col in ("above_10ema_pct", "above_50ema_pct", "above_200ema_pct", "advancers", "decliners"):
            if col in b.columns:
                bv = pd.to_numeric(b[col], errors="coerce")
                used |= bv.notna()
                agg[col] = bv.where(bv.notna(), agg[col])
        agg.loc[used.to_numpy(), "participation_source"] = "breadth_daily"
    return agg.drop(columns=["valid52", "stage2_known"])


# ---------------------------------------------------------------------------------------------
# Pillar statuses
# ---------------------------------------------------------------------------------------------
def _status(weak: pd.Series, healthy: pd.Series, known: pd.Series) -> pd.Series:
    out = pd.Series(None, index=weak.index, dtype="object")
    k = known.fillna(False).to_numpy(dtype=bool)
    w = weak.fillna(False).to_numpy(dtype=bool)
    h = healthy.fillna(False).to_numpy(dtype=bool)
    out[k] = "Neutral"
    out[k & h] = "Healthy"
    out[k & w] = "Weak"
    return out


def _pillars(d: pd.DataFrame) -> pd.DataFrame:
    # Trend
    known = d[["midsml_close", "midsml_ema50", "midsml_ema200", "midsml_ema50_slope_pct", "nifty_close", "nifty_ema200"]].notna().all(axis=1)
    weak = d["midsml_close"] < d["midsml_ema200"]
    healthy = (d["midsml_close"] > d["midsml_ema50"]) & (d["midsml_ema50_slope_pct"] > 0) & (d["nifty_close"] > d["nifty_ema200"])
    d["trend_status"] = _status(weak, healthy, known)
    d["trend_score"] = (d["midsml_close"] / d["midsml_ema50"] - 1.0) * 100.0

    # Participation
    zp = ZONES["participation"]
    d["ad_line_10d"] = (d["advancers"] - d["decliners"]).rolling(zp["ad_sessions"], min_periods=zp["ad_sessions"]).sum()
    d["above_50ema_chg_5d"] = d["above_50ema_pct"] - d["above_50ema_pct"].shift(zp["change_sessions"])
    level = (d["above_50ema_pct"] + d["above_200ema_pct"]) / 2.0
    d["participation_level"] = level
    base = np.where(level > zp["healthy_min"], 2, np.where(level >= zp["weak_below"], 1, 0)).astype(float)
    up = (d["ad_line_10d"] > 0) & (d["above_50ema_chg_5d"] > 0)
    down = (d["ad_line_10d"] < 0) & (d["above_50ema_chg_5d"] < 0)
    step = np.where(up, 1, np.where(down, -1, 0))
    d["participation_direction"] = np.where(up, "up", np.where(down, "down", "none"))
    lvl = np.clip(base + step, 0, 2)
    pknown = level.notna() & d["ad_line_10d"].notna() & d["above_50ema_chg_5d"].notna()
    status = pd.Series(None, index=d.index, dtype="object")
    for rank, name in enumerate(STATUSES):
        status[(pknown & (lvl == rank)).to_numpy()] = name
    d["participation_status"] = status
    d["participation_score"] = level

    # Leadership
    zl = ZONES["leadership"]
    d["net_new_highs"] = d["new_highs"] - d["new_lows"]
    d["net_new_highs_10d_avg"] = d["net_new_highs"].rolling(zl["smooth_sessions"], min_periods=zl["smooth_sessions"]).mean()
    d["net_new_highs_10d_chg_5d"] = d["net_new_highs_10d_avg"] - d["net_new_highs_10d_avg"].shift(zl["change_sessions"])
    known = d["net_new_highs_10d_avg"].notna() & d["net_new_highs_10d_chg_5d"].notna()
    healthy = (d["net_new_highs_10d_avg"] > 0) & (d["net_new_highs_10d_chg_5d"] > 0)
    weak = (d["net_new_highs_10d_avg"] < 0) & (d["net_new_highs_10d_chg_5d"] < 0)
    d["leadership_status"] = _status(weak, healthy, known)
    d["leadership_score"] = d["net_new_highs_10d_avg"]

    # Follow-through
    zf = ZONES["follow_through"]
    enough = d["breakouts_n"] >= zf["min_breakouts"]
    d["follow_through_pct"] = (d["breakouts_holding"] / d["breakouts_n"] * 100.0).where(enough)
    ft = d["follow_through_pct"]
    d["follow_through_status"] = _status(ft < zf["weak_below"], ft >= zf["healthy_min"], ft.notna())
    d["follow_through_score"] = ft

    # Stress: any known Weak condition decides; Healthy/Neutral need every input known.
    zs = ZONES["stress"]
    dd = d["distribution_days_25"]
    weak = (dd >= zs["dist_weak_min"]) | (d["vix_1d_pct"] >= zs["vix_spike_1d_pct"]) | (d["vix_close"] >= zs["vix_weak_level"])
    all_known = dd.notna() & d["vix_close"].notna() & d["vix_1d_pct"].notna() & d["vix_5d_pct"].notna()
    healthy = (dd <= zs["dist_healthy_max"]) & (d["vix_close"] < zs["vix_healthy_below"]) & (d["vix_5d_pct"] <= zs["vix_healthy_5d_max_pct"])
    known = all_known | weak.fillna(False)
    d["stress_status"] = _status(weak, healthy & all_known, known)
    d["stress_score"] = -d["vix_close"]  # goodness-oriented: falling VIX = improving

    for p in PILLARS:
        for label, h in DIRECTION_HORIZONS.items():
            d[f"{p}_dir_{label}"] = sign_dir(d[f"{p}_score"] - d[f"{p}_score"].shift(h), DIRECTION_TOL[p])
    return d


# ---------------------------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------------------------
def _rule_mask(d: pd.DataFrame, rule: dict[str, Any]) -> np.ndarray:
    mask = np.ones(len(d), dtype=bool)
    for pillar, allowed in rule["conditions"].items():
        mask &= d[f"{pillar}_status"].isin(allowed).to_numpy(dtype=bool)
    return mask


def _verdict(d: pd.DataFrame) -> pd.DataFrame:
    n_known = sum(d[f"{p}_status"].notna().astype(int) for p in PILLARS)
    sufficient = (d["trend_status"].notna() & d["participation_status"].notna() & (n_known >= 4)).to_numpy(dtype=bool)
    verdict = np.full(len(d), None, dtype=object)
    rule_id = np.full(len(d), INSUFFICIENT_RULE["rule_id"], dtype=object)
    rule_text = np.full(len(d), INSUFFICIENT_RULE["text"], dtype=object)
    decided = ~sufficient
    for rule in VERDICT_RULES:
        hit = _rule_mask(d, rule) & ~decided
        verdict[hit] = rule["verdict"]
        rule_id[hit] = rule["rule_id"]
        rule_text[hit] = rule["text"]
        decided |= hit
    d["pillars_known"] = n_known
    d["verdict"] = verdict
    d["verdict_guidance"] = [VERDICT_GUIDANCE.get(v) if v else None for v in verdict]
    d["rule_id"] = rule_id
    d["rule_text"] = rule_text

    v = pd.Series(verdict, index=d.index, dtype="object")
    key = v.fillna("__NULL__")
    streak = (key != key.shift()).cumsum()
    start_dates = pd.Series(d.index, index=d.index).groupby(streak.to_numpy()).transform("first")
    days = streak.groupby(streak.to_numpy()).cumcount() + 1
    prev_of_streak = key.shift().where(key != key.shift())
    prev_of_streak = prev_of_streak.groupby(streak.to_numpy()).transform("first")
    isnull = v.isna().to_numpy()
    d["days_in_state"] = np.where(isnull, np.nan, days.to_numpy(dtype=float))
    d["state_since"] = pd.Series(start_dates.to_numpy(), index=d.index).where(~isnull)
    prev = prev_of_streak.replace("__NULL__", None)
    d["previous_state"] = prev.where(~isnull)
    cur_rank = v.map(VERDICT_RANK)
    prev_rank = d["previous_state"].map(VERDICT_RANK)
    d["state_change"] = np.where(cur_rank.notna() & prev_rank.notna(),
                                 np.where(cur_rank > prev_rank, "improved", "worsened"), None)
    d.loc[d["previous_state"].isna(), "state_change"] = None
    d["state_change_date"] = d["state_since"].where(d["previous_state"].notna())
    return d


# ---------------------------------------------------------------------------------------------
# Plain sentences, connected readings, alerts
# ---------------------------------------------------------------------------------------------
def _pillar_texts(d: pd.DataFrame) -> pd.DataFrame:
    def trend(r) -> str | None:
        if pd.isna(r.midsml_close) or pd.isna(r.midsml_ema50) or pd.isna(r.midsml_ema200):
            return None
        rel50 = (r.midsml_close / r.midsml_ema50 - 1) * 100
        rel200 = (r.midsml_close / r.midsml_ema200 - 1) * 100
        slope = "rising" if r.midsml_ema50_slope_pct > 0 else "falling"
        nifty = "n/a"
        if pd.notna(r.nifty_close) and pd.notna(r.nifty_ema200):
            nifty = "above" if r.nifty_close > r.nifty_ema200 else "below"
        return (f"MidSml400 {fmt(r.midsml_close, 0)} is {fmt_signed(rel50)}% vs its {slope} 50 EMA and "
                f"{fmt_signed(rel200)}% vs its 200 EMA; Nifty 50 is {nifty} its 200 EMA.")

    def participation(r) -> str | None:
        if pd.isna(r.above_50ema_pct):
            return None
        return (f"{fmt(r.above_50ema_pct, 0)}% of stocks are above their 50 EMA and {fmt(r.above_200ema_pct, 0)}% above "
                f"their 200 EMA; 10-day A/D {fmt_signed(r.ad_line_10d, 0)}.")

    def leadership(r) -> str | None:
        if pd.isna(r.new_highs):
            return None
        return (f"{fmt(r.new_highs, 0)} new 52W highs vs {fmt(r.new_lows, 0)} lows today; 10-day net average "
                f"{fmt_signed(r.net_new_highs_10d_avg, 1)}; {fmt(r.stage2_count, 0)} stocks pass the trend template.")

    def follow(r) -> str | None:
        if pd.isna(r.follow_through_pct):
            if pd.notna(r.breakouts_n):
                return f"Only {fmt(r.breakouts_n, 0)} breakouts in t-10..t-3 — too few to judge."
            return None
        return (f"{fmt(r.follow_through_pct, 0)}% of {fmt(r.breakouts_n, 0)} recent 20-day-high breakouts on RVOL >= 1.5 "
                f"are still above their breakout close.")

    def stress(r) -> str | None:
        parts = []
        if pd.notna(r.vix_close):
            parts.append(f"India VIX {fmt(r.vix_close, 1)} ({fmt_signed(r.vix_1d_pct, 1)}% 1D, {fmt_signed(r.vix_5d_pct, 1)}% 5D)")
        if pd.notna(r.distribution_days_25):
            parts.append(f"{fmt(r.distribution_days_25, 0)} distribution days in 25 sessions on MidSml400")
        return "; ".join(parts) + "." if parts else None

    rows = list(d.itertuples())
    d["trend_text"] = [trend(r) for r in rows]
    d["participation_text"] = [participation(r) for r in rows]
    d["leadership_text"] = [leadership(r) for r in rows]
    d["follow_through_text"] = [follow(r) for r in rows]
    d["stress_text"] = [stress(r) for r in rows]
    return d


# Connected readings (§6.1.4): id, condition (as documentation) and a text template citing values.
CONNECTED_READINGS: list[dict[str, str]] = [
    {"id": "narrow_rally", "when": "MidSml400 up each of the last 3 sessions AND % above 50 EMA lower than 3 sessions ago"},
    {"id": "leaders_holding", "when": "MidSml400 5-session return < 0 AND new 52W highs over the last 5 sessions > the 5 before"},
    {"id": "pullback_buy_window", "when": "% above 10 EMA < 20 AND % above 200 EMA > 60"},
    {"id": "choppy", "when": "Participation Neutral or Healthy AND Follow-through Weak"},
    {"id": "hidden_selling", "when": "Trend Healthy AND distribution days in 25 sessions >= 4"},
    {"id": "benchmark_split", "when": "Nifty 50 and MidSml400 on opposite sides of their 50 EMA"},
]


def _readings(d: pd.DataFrame) -> pd.DataFrame:
    nh5 = d["new_highs"].rolling(5, min_periods=5).sum()
    nh5_prev = nh5.shift(5)
    a50_3 = d["above_50ema_pct"].shift(3)
    masks = {
        "narrow_rally": (d["midsml_up_3d"] == True) & (d["above_50ema_pct"] < a50_3),  # noqa: E712
        "leaders_holding": (d["midsml_ret_5d_pct"] < 0) & (nh5 > nh5_prev),
        "pullback_buy_window": (d["above_10ema_pct"] < ZONES["timing"]["washed_out_below"]) & (d["above_200ema_pct"] > 60),
        "choppy": d["participation_status"].isin(["Neutral", "Healthy"]) & (d["follow_through_status"] == "Weak"),
        "hidden_selling": (d["trend_status"] == "Healthy") & (d["distribution_days_25"] >= 4),
        "benchmark_split": ((d["nifty_close"] > d["nifty_ema50"]) != (d["midsml_close"] > d["midsml_ema50"]))
        & d[["nifty_close", "nifty_ema50", "midsml_close", "midsml_ema50"]].notna().all(axis=1),
    }
    masks = {k: v.fillna(False).to_numpy(dtype=bool) for k, v in masks.items()}
    out: list[str] = []
    for i, r in enumerate(d.itertuples()):
        fired = []
        if masks["narrow_rally"][i]:
            fired.append({"id": "narrow_rally", "text": (
                f"Narrow rally: MidSml400 up 3 sessions ({fmt_signed(r.midsml_ret_3d_pct, 1)}%) while stocks above "
                f"50 EMA fell from {fmt(a50_3.iloc[i], 0)}% to {fmt(r.above_50ema_pct, 0)}%.")})
        if masks["leaders_holding"][i]:
            fired.append({"id": "leaders_holding", "text": (
                f"Leaders holding: {fmt(nh5.iloc[i], 0)} new 52W highs in 5 sessions (vs {fmt(nh5_prev.iloc[i], 0)} before) "
                f"while MidSml400 is {fmt_signed(r.midsml_ret_5d_pct, 1)}% over 5 sessions.")})
        if masks["pullback_buy_window"][i]:
            fired.append({"id": "pullback_buy_window", "text": (
                f"Pullback-buy window: only {fmt(r.above_10ema_pct, 0)}% above 10 EMA inside a healthy base "
                f"({fmt(r.above_200ema_pct, 0)}% above 200 EMA).")})
        if masks["choppy"][i]:
            fired.append({"id": "choppy", "text": (
                f"Choppy: participation {r.participation_status} ({fmt(r.participation_level, 0)}%) but only "
                f"{fmt(r.follow_through_pct, 0)}% of breakouts are holding.")})
        if masks["hidden_selling"][i]:
            fired.append({"id": "hidden_selling", "text": (
                f"Hidden selling: trend Healthy but {fmt(r.distribution_days_25, 0)} distribution days in 25 sessions.")})
        if masks["benchmark_split"][i]:
            n_rel = (r.nifty_close / r.nifty_ema50 - 1) * 100
            m_rel = (r.midsml_close / r.midsml_ema50 - 1) * 100
            fired.append({"id": "benchmark_split", "text": (
                f"Benchmark split: Nifty 50 {fmt_signed(n_rel, 1)}% vs its 50 EMA, MidSml400 {fmt_signed(m_rel, 1)}%.")})
        out.append(json.dumps(fired))
    d["connected_readings"] = out
    d["connected_readings_n"] = [sum(masks[k][i] for k in masks) for i in range(len(d))]
    return d


def _timing(d: pd.DataFrame) -> pd.DataFrame:
    z = ZONES["timing"]
    a10 = d["above_10ema_pct"]
    state = np.where(a10 > z["stretched_above"], "stretched",
                     np.where(a10 < z["washed_out_below"], "washed_out",
                              np.where(a10.notna(), "normal", None)))
    notes = []
    for s, v in zip(state, a10):
        if s == "stretched":
            notes.append(f"Stretched: {fmt(v, 0)}% above 10 EMA — breakouts tend to pull back; wait 2-3 days.")
        elif s == "washed_out":
            notes.append(f"Washed out: {fmt(v, 0)}% above 10 EMA — bounces tend to start here.")
        else:
            notes.append(None)
    d["timing_state"] = state
    d["timing_note"] = notes
    return d


def _alerts(d: pd.DataFrame) -> pd.DataFrame:
    zs = ZONES["stress"]
    prev_v = d["verdict"].shift(1)
    d["alert_state_change"] = (d["verdict"].notna() & prev_v.notna() & (d["verdict"] != prev_v)).to_numpy(dtype=bool)
    dd = d["distribution_days_25"]
    d["alert_distribution_5"] = ((dd >= zs["dist_weak_min"]) & (dd.shift(1) < zs["dist_weak_min"])).fillna(False).to_numpy(dtype=bool)
    ft = d["follow_through_pct"]
    wf = ZONES["follow_through"]["weak_below"]
    d["alert_follow_through_low"] = ((ft < wf) & (ft.shift(1) >= wf)).fillna(False).to_numpy(dtype=bool)
    d["alert_vix_spike"] = (d["vix_1d_pct"] >= zs["vix_spike_1d_pct"]).fillna(False).to_numpy(dtype=bool)
    texts = []
    for i, r in enumerate(d.itertuples()):
        a = []
        if r.alert_state_change:
            a.append({"id": "state_change", "text": f"Environment {r.state_change or 'changed'}: {prev_v.iloc[i]} -> {r.verdict} (rule {r.rule_id})."})
        if r.alert_distribution_5:
            a.append({"id": "distribution_5", "text": f"Distribution days reached {fmt(r.distribution_days_25, 0)} in 25 sessions."})
        if r.alert_follow_through_low:
            a.append({"id": "follow_through_low", "text": f"Follow-through fell to {fmt(r.follow_through_pct, 0)}% (< 35%)."})
        if r.alert_vix_spike:
            a.append({"id": "vix_spike", "text": f"India VIX spiked {fmt_signed(r.vix_1d_pct, 1)}% to {fmt(r.vix_close, 1)}."})
        texts.append(json.dumps(a))
    d["alerts"] = texts
    d["alert_any"] = d[["alert_state_change", "alert_distribution_5", "alert_follow_through_low", "alert_vix_spike"]].any(axis=1)
    return d


OUTPUT_COLUMNS = [
    "trade_date", "verdict", "verdict_guidance", "rule_id", "rule_text", "pillars_known",
    "days_in_state", "state_since", "previous_state", "state_change", "state_change_date",
    *[f"{p}_status" for p in PILLARS],
    *[f"{p}_dir_{h}" for p in PILLARS for h in DIRECTION_HORIZONS],
    *[f"{p}_text" for p in PILLARS],
    # trend inputs
    "midsml_close", "midsml_ema20", "midsml_ema50", "midsml_ema200", "midsml_ema50_slope_pct",
    "midsml_ret_1d_pct", "midsml_ret_5d_pct", "nifty_close", "nifty_ema50", "nifty_ema200",
    # participation inputs
    "stocks", "above_10ema_pct", "above_50ema_pct", "above_200ema_pct", "advancers", "decliners",
    "ad_line_10d", "above_50ema_chg_5d", "participation_level", "participation_direction", "participation_source",
    # leadership inputs
    "new_highs", "new_lows", "net_new_highs", "net_new_highs_10d_avg", "net_new_highs_10d_chg_5d",
    "stage2_count", "stage2_pct",
    # follow-through inputs
    "breakouts_n", "breakouts_holding", "follow_through_pct",
    # stress inputs
    "vix_close", "vix_1d_pct", "vix_5d_pct", "midsml_dist_day", "distribution_days_25",
    "nifty_distribution_days_25", "distribution_source",
    # timing, readings, alerts
    "timing_state", "timing_note", "connected_readings", "connected_readings_n",
    "alert_state_change", "alert_distribution_5", "alert_follow_through_low", "alert_vix_spike",
    "alert_any", "alerts",
]


def build_regime_daily(
    index_daily: pd.DataFrame,
    indicators: pd.DataFrame,
    breadth: pd.DataFrame | None = None,
    reference: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build regime_daily. `reference` (security_reference_daily) is accepted for API symmetry;
    official 52W values already reach this builder through indicators.high_52w/low_52w
    (as-of joined from the same reference snapshots in the EOD build)."""
    _ = reference
    ind = prep_indicators(indicators, INDICATOR_COLUMNS)
    if ind.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    dates = pd.DatetimeIndex(sorted(ind["trade_date"].unique()), name="trade_date")
    d = _index_block(index_daily, dates).join(_stock_block(ind, dates, breadth), how="left")
    d = _pillars(d)
    d = _verdict(d)
    d = _pillar_texts(d)
    d = _timing(d)
    d = _readings(d)
    d = _alerts(d)
    d = d.reset_index().rename(columns={"index": "trade_date"})
    out = d[OUTPUT_COLUMNS].copy()
    out["midsml_dist_day"] = out["midsml_dist_day"].map(lambda x: None if pd.isna(x) else bool(x)).astype("object")
    return out


def verdict_rules_table() -> pd.DataFrame:
    """The published rule table (for the UI 'matched rule' popover)."""
    rows = [{"rule_id": INSUFFICIENT_RULE["rule_id"], "verdict": None, "conditions": "{}", "text": INSUFFICIENT_RULE["text"]}]
    rows += [{"rule_id": r["rule_id"], "verdict": r["verdict"], "conditions": json.dumps(r["conditions"]), "text": r["text"]}
             for r in VERDICT_RULES]
    return pd.DataFrame(rows)
