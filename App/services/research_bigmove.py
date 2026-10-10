"""Research: big-mover case studies + setup scorecard (10-tab-research.md §12).

Port of HarkPro/tools/bigmove_study/caught.py and precision.py.

- Window: the 12 months (365 calendar days) up to the study end.
- Big mover: stock >= Rs 1,000 Cr with >= 150 sessions in the window whose lowest close in the window is
  followed by a highest close >= +100% (low -> peak).
- Presets: the rule presets of App/services/screener.py (PRESETS, kind "rules"), evaluated with the same
  rules on the same indicator columns (NULL fails the rule), plus the indicator VCP flag (is_vcp).
  The Darvas / VCP Desk queues are not part of this study.
- Fresh fire: the preset is true today and was false on each of the previous 5 sessions.
- First fire after the low (inside low -> peak): entry close, % above the low, room left to the peak, and
  the 20 EMA exit (sell at the first close below the 20 EMA).
- Re-entry ladder: enter on the first fresh fire of Delivery thrust / EMAs converge / VCP flag /
  Fresh 52W high / Near 52W high with the close above the 20 EMA; exit on a close below the 20 EMA; repeat.
- Precision: every fresh fire from the window start to 120 sessions before the study end; hit = the
  stock closes >= +50% above the fire close within the next 120 sessions. Base = all stock-days.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from App.services import db, screener
from App.services import research_lab as lab
from App.services.common import Result, no_session, unavailable

WINDOW_DAYS = 365
MIN_SESSIONS = 150
BIG_MOVE_PCT = 100.0
PRECISION_HORIZON = 120
PRECISION_HIT = 1.5
FRESH_LOOKBACK = 5

# Column of the research frame behind each screener field.
FIELD_COL = {
    "close": "close_price", "open": "open_price", "high": "high_price", "low": "low_price",
    "ema_10": "ema_10", "ema_20": "ema_20", "ema_50": "ema_50", "ema_100": "ema_100", "ema_200": "ema_200",
    "sma_50": "sma_50", "sma_150": "sma_150", "sma_200": "sma_200", "rsi_14": "rsi_14", "rsi_14_w": "rsi_14_w",
    "away_10ema_pct": "away_10ema_pct", "away_52w_high_pct": "away_52w_high_pct",
    "away_52w_low_pct": "away_52w_low_pct", "rs_percentile": "rs_percentile",
    "trend_template_pass": "trend_template_pass", "trend_template_pass_n": "trend_template_pass_n",
    "sma_200_rising": "sma_200_rising", "nr7": "nr7", "inside_bar": "inside_bar",
    "delivery_spike": "delivery_spike", "price_up_delivery_up": "price_up_delivery_up", "rvol": "rvol",
    "delivery_pct": "delivery_pct",
    # derived (same expressions as screener.FIELDS / EXTRA_COLS)
    "nr7_or_inside": "_nr7_or_inside", "new_52w_high": "_new_52w_high", "ema_spread_10_50_pct": "_ema_spread",
}
LETTERS = {"minervini_8of8": "M", "stage2_leader": "S", "ema_stack": "E", "emas_converge": "C", "near_52w_high": "N",
           "fresh_52w_high": "F", "sma_template": "T", "delivery_thrust": "D", "nr7_inside": "I", "weekly_rsi_60": "W",
           "vcp_flag": "V"}
EARLY = ("delivery_thrust", "emas_converge", "vcp_flag")
LADDER_ENTRY = ("delivery_thrust", "emas_converge", "vcp_flag", "fresh_52w_high", "near_52w_high")


def preset_specs() -> list[dict[str, Any]]:
    """Study presets: screener rule presets in screener order, then the VCP flag."""
    out = []
    for p in screener.PRESETS.values():
        if p.kind != "rules":
            continue
        out.append({"id": p.id, "name": p.label, "description": p.description, "letter": LETTERS.get(p.id, p.id[:1].upper()),
                    "category": screener.PRESET_CATEGORY.get(p.id), "rules": [dict(r) for r in p.rules],
                    "early": p.id in EARLY})
    out.append({"id": "vcp_flag", "name": "VCP flag", "description": "Indicator VCP flag (is_vcp) - not the Desk VCP queue.",
                "letter": "V", "category": "Coil", "rules": [{"field": "is_vcp", "op": "is_true"}], "early": True})
    return out


def _derive(d: pd.DataFrame) -> pd.DataFrame:
    d["_nr7_or_inside"] = d.nr7.astype(bool) | d.inside_bar.astype(bool)
    d["_new_52w_high"] = (d.high_price >= d.high_52w).fillna(False)
    e = d[["ema_10", "ema_20", "ema_50"]]
    d["_ema_spread"] = (e.max(axis=1, skipna=False) - e.min(axis=1, skipna=False)) / d.close_price.replace(0, np.nan) * 100
    return d


def _rule_mask(d: pd.DataFrame, rule: dict[str, Any]) -> pd.Series:
    field = rule["field"]
    col = "is_vcp" if field == "is_vcp" else FIELD_COL.get(field)
    if col is None:
        raise ValueError(f"screener field {field!r} has no research column")
    x = d[col]
    op = rule["op"]
    if op == "is_true":
        return x.fillna(False).astype(bool)
    if op == "is_false":
        return (~x.fillna(True).astype(bool))
    rhs = d[FIELD_COL[rule["ref"]]] if "ref" in rule else float(rule["value"])
    x = x.astype(float)
    res = {"gt": x > rhs, "gte": x >= rhs, "lt": x < rhs, "lte": x <= rhs, "eq": x == rhs}[op]
    return res.fillna(False).astype(bool)  # NULL fails closed


def _group_prior_any(flag: np.ndarray, pos: np.ndarray, n: int) -> np.ndarray:
    """True where the flag was true on any of the previous n sessions of the same symbol."""
    out = np.zeros(len(flag), dtype=bool)
    for s in range(1, n + 1):
        sh = np.zeros(len(flag), dtype=bool)
        sh[s:] = flag[:-s]
        sh &= pos >= s
        out |= sh
    return out


def add_presets(d: pd.DataFrame) -> pd.DataFrame:
    """Adds `p_<id>` (preset true) and `f_<id>` (fresh fire) columns. d sorted by symbol, date."""
    d = _derive(d)
    pos = d.groupby("symbol", sort=False).cumcount().to_numpy()
    for p in preset_specs():
        m = np.ones(len(d), dtype=bool)
        for r in p["rules"]:
            m &= _rule_mask(d, r).to_numpy()
        d["p_" + p["id"]] = m
        d["f_" + p["id"]] = m & ~_group_prior_any(m, pos, FRESH_LOOKBACK)
    return d


def window_start(end: date) -> date:
    return end - timedelta(days=WINDOW_DAYS)


def _move(x: pd.DataFrame, start: date) -> dict[str, Any] | None:
    w = x[x.trade_date >= pd.Timestamp(start)]
    if w.empty or w.close_price.notna().sum() == 0:
        return None
    i_lo = w.close_price.idxmin()
    after = w.loc[i_lo:]
    i_pk = after.close_price.idxmax()
    lo, pk = float(w.close_price[i_lo]), float(w.close_price[i_pk])
    return {"low_date": w.trade_date[i_lo], "low": lo, "peak_date": w.trade_date[i_pk], "peak": pk,
            "gain_pct": (pk / lo - 1) * 100 if lo > 0 else np.nan, "sessions": int(len(w))}


def _trail20(x: pd.DataFrame, i: Any) -> tuple[float, pd.Timestamp, bool]:
    after = x.loc[i:]
    brk = after[after.close_price < after.ema_20]
    ex = brk.iloc[0] if len(brk) else after.iloc[-1]
    return float(ex.close_price), ex.trade_date, bool(len(brk))


def first_fires(x: pd.DataFrame, mv: dict[str, Any]) -> list[dict[str, Any]]:
    win = x[(x.trade_date >= mv["low_date"]) & (x.trade_date <= mv["peak_date"])]
    out = []
    for p in preset_specs():
        f = win[win["f_" + p["id"]]]
        row = {"preset_id": p["id"], "preset": p["name"], "letter": p["letter"], "early": p["early"],
               "first_fire": None, "entry": None, "entry_vs_low_pct": None, "to_peak_pct": None,
               "trail20_pct": None, "trail20_exit": None, "trail20_open": None, "fresh_fires": int(len(f))}
        if len(f):
            i = f.index[0]
            e = float(x.close_price[i])
            xp, xd, closed = _trail20(x, i)
            row.update({"first_fire": x.trade_date[i], "entry": round(e, 2),
                        "entry_vs_low_pct": round((e / mv["low"] - 1) * 100, 1),
                        "to_peak_pct": round((mv["peak"] / e - 1) * 100, 1),
                        "trail20_pct": round((xp / e - 1) * 100, 1), "trail20_exit": xd, "trail20_open": not closed})
        out.append(row)
    return out


def ladder(x: pd.DataFrame, mv: dict[str, Any]) -> tuple[list[dict[str, Any]], float]:
    x = x[x.trade_date >= mv["low_date"]].reset_index(drop=True)
    names = {p["id"]: p["name"] for p in preset_specs()}
    fires = x[["f_" + k for k in LADDER_ENTRY]].to_numpy()
    any_fire = fires.any(axis=1)
    cl, e20 = x.close_price.to_numpy(), x.ema_20.to_numpy()
    legs, i, n = [], 0, len(x)
    while i < n:
        j = next((k for k in range(i, n) if any_fire[k] and cl[k] > e20[k]), None)
        if j is None:
            break
        why = next(k for idx, k in enumerate(LADDER_ENTRY) if fires[j, idx])
        e = next((k for k in range(j + 1, n) if cl[k] < e20[k]), None)
        open_ = e is None
        e = n - 1 if e is None else e
        legs.append({"entry_date": x.trade_date[j], "signal_id": why, "signal": names[why], "letter": LETTERS[why],
                     "entry": round(float(cl[j]), 2), "exit_date": x.trade_date[e], "exit": round(float(cl[e]), 2),
                     "pnl_pct": round((cl[e] / cl[j] - 1) * 100, 1), "open": open_})
        i = e + 1
    comp = (np.prod([1 + leg["pnl_pct"] / 100 for leg in legs]) - 1) * 100 if legs else 0.0
    return legs, float(comp)


# --------------------------------------------------------------------------
# Whole-universe studies (precomputed by Scripts/research_lab.py)
# --------------------------------------------------------------------------
def _study_frame(con: Any, end: date) -> pd.DataFrame:
    def compute() -> pd.DataFrame:
        d = lab.frame(con, end)
        d = d[d.trade_date >= pd.Timestamp(window_start(end) - timedelta(days=30))].reset_index(drop=True)
        return add_presets(d.copy())
    return lab.big_cached("research_preset_frame", (end,), compute)


def compute_movers(con: Any, end: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = _study_frame(con, end)
    start = window_start(end)
    movers, caught = [], []
    for sym, x in d.groupby("symbol", sort=False):
        w = x[x.trade_date >= pd.Timestamp(start)]
        if len(w) < MIN_SESSIONS:
            continue
        mv = _move(x, start)
        if mv is None or not (mv["gain_pct"] >= BIG_MOVE_PCT):
            continue
        legs, comp = ladder(x, mv)
        movers.append({"symbol": sym, "security_name": x.security_name.iat[0], "industry": x.industry.iat[0],
                       "mcap_cr": lab.clean(x.mcap_now.iat[0]), **{k: v for k, v in mv.items() if k != "sessions"},
                       "ladder_pct": round(comp, 1), "trades": len(legs)})
        for r in first_fires(x, mv):
            caught.append({"symbol": sym, **r})
    M = pd.DataFrame(movers)
    if not M.empty:
        M = M.sort_values("gain_pct", ascending=False).reset_index(drop=True)
        M["gain_pct"] = M.gain_pct.round(1)
    return M, pd.DataFrame(caught)


def compute_precision(con: Any, end: date) -> pd.DataFrame:
    d = _study_frame(con, end)
    days = lab.sessions(con)
    days = [x for x in days if x <= end]
    ei = lab.session_index(days, end)
    cutoff = days[max(0, ei - PRECISION_HORIZON)]
    g = d.groupby("symbol", sort=False).close_price
    fmax = g.transform(lambda s: s[::-1].rolling(PRECISION_HORIZON, min_periods=PRECISION_HORIZON).max()[::-1].shift(-1))
    hit = fmax / d.close_price >= PRECISION_HIT
    z = (d.trade_date >= pd.Timestamp(window_start(end))) & (d.trade_date <= pd.Timestamp(cutoff)) & fmax.notna()
    rows = [{"preset_id": "all", "preset": "All stock-days", "letter": None, "fires": int(z.sum()),
             "hit_pct": round(hit[z].mean() * 100, 1) if z.any() else None, "fires_rs80": None, "hit_rs80_pct": None}]
    for p in preset_specs():
        f = z & d["f_" + p["id"]]
        f80 = f & (d.rs_percentile >= 80)
        rows.append({"preset_id": p["id"], "preset": p["name"], "letter": p["letter"], "fires": int(f.sum()),
                     "hit_pct": round(hit[f].mean() * 100, 1) if f.any() else None,
                     "fires_rs80": int(f80.sum()), "hit_rs80_pct": round(hit[f80].mean() * 100, 1) if f80.any() else None})
    P = pd.DataFrame(rows)
    P["window_from"] = pd.Timestamp(window_start(end))
    P["window_to"] = pd.Timestamp(cutoff)
    return P


def movers_tables(con: Any, end: date) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    cache: dict[str, Any] = {}

    def both() -> tuple[pd.DataFrame, pd.DataFrame]:
        if "v" not in cache:
            cache["v"] = db.cached("research_movers_pair", (end,), lambda: compute_movers(con, end))
        return cache["v"]
    M, src = lab.table_or_compute(con, "research_big_movers", end, lambda: both()[0])
    C, _ = lab.table_or_compute(con, "research_caught", end, lambda: both()[1])
    return M, C, src


def precision_table(con: Any, end: date) -> tuple[pd.DataFrame, str]:
    return lab.table_or_compute(con, "research_precision", end, lambda: compute_precision(con, end))


def _precision_ctx(P: pd.DataFrame) -> dict[str, Any]:
    base = P[P.preset_id == "all"]
    return {"base_hit_pct": lab.clean(base.hit_pct.iat[0]) if len(base) else None,
            "base_n": int(base.fires.iat[0]) if len(base) else None,
            "window_from": lab.clean(P.window_from.iat[0]) if len(P) else None,
            "window_to": lab.clean(P.window_to.iat[0]) if len(P) else None,
            "rows": lab.records(P.drop(columns=["window_from", "window_to"], errors="ignore")),
            "definition": (f"Share of fresh fires followed by a close >= +{(PRECISION_HIT - 1) * 100:.0f}% within "
                           f"{PRECISION_HORIZON} sessions. False alarms = the rest.")}


def _resolve(con: Any, as_of: date | None) -> tuple[date | None, date | None]:
    resolved = db.resolve_as_of(con, as_of)
    if resolved is None:
        return None, None
    return resolved, lab.study_end(con, resolved)


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@lab.memo("scorecard")
def scorecard(as_of: date | None) -> Result:
    with db.market_conn() as con:
        resolved, end = _resolve(con, as_of)
        if end is None:
            return no_session(as_of)
        M, C, src = movers_tables(con, end)
        P, _ = precision_table(con, end)
    n = int(len(M))
    rows = []
    prec = {r["preset_id"]: r for r in lab.records(P)}
    base = prec.get("all", {}).get("hit_pct")
    for p in preset_specs():
        c = C[(C.preset_id == p["id"]) & C.first_fire.notna()] if len(C) else C
        if len(c):
            c = c.merge(M[["symbol", "gain_pct"]], on="symbol")
        pr = prec.get(p["id"], {})
        hit = pr.get("hit_pct")
        rows.append({
            "preset_id": p["id"], "preset": p["name"], "letter": p["letter"], "category": p["category"],
            "early": p["early"], "description": p["description"],
            "movers": n, "caught": int(c.symbol.nunique()) if len(c) else 0,
            "caught_pct": round(c.symbol.nunique() / n * 100) if n and len(c) else (0 if n else None),
            "entry_vs_low_pct": lab.rnd(c["entry_vs_low_pct"].median()) if len(c) else None,
            "to_peak_pct": lab.rnd(c["to_peak_pct"].median()) if len(c) else None,
            "trail20_pct": lab.rnd(c["trail20_pct"].median()) if len(c) else None,
            "fires_per_mover": lab.rnd(c["fresh_fires"].median()) if len(c) else None,
            "fires": pr.get("fires"), "hit_pct": hit,
            "false_alarm_pct": round(100 - hit, 1) if hit is not None else None,
            "lift": round(hit / base, 2) if hit is not None and base else None,
            "fires_rs80": pr.get("fires_rs80"), "hit_rs80_pct": pr.get("hit_rs80_pct"),
        })
    lad = M.ladder_pct.median() if n else None
    ctx = {"caveat": lab.CAVEAT, "study_end": end, "source": src, "window_from": window_start(end), "window_to": end,
           "movers": n, "precision": _precision_ctx(P),
           "ladder": {"median_pct": lab.rnd(lad), "median_move_pct": lab.rnd(M.gain_pct.median()) if n else None,
                      "median_trades": lab.rnd(M.trades.median()) if n else None},
           "summary": _scorecard_sentences(rows, base, n),
           "definition": (f"Big mover = stock >= Rs 1,000 Cr whose lowest close in the 12 months to {end.isoformat()} "
                          f"is followed by a close >= +{BIG_MOVE_PCT:.0f}%. Caught = a fresh fire between the low and "
                          "the peak. Fresh = true today, false on each of the previous 5 sessions.")}
    return Result(as_of=end, rows=rows, sources=["indicators_daily", "App/services/screener.py"], extra=ctx)


def _scorecard_sentences(rows: list[dict[str, Any]], base: float | None, n: int) -> list[str]:
    if not n:
        return ["No stock doubled in the window."]
    caught = [r for r in rows if r["caught_pct"] is not None and r["entry_vs_low_pct"] is not None]
    if not caught:
        return []
    early = min(caught, key=lambda r: r["entry_vs_low_pct"])
    best = max((r for r in rows if r["hit_pct"] is not None), key=lambda r: r["hit_pct"], default=None)
    s = [f"{n} stocks doubled in the window.",
         f"{early['preset']} fired nearest the low: a median {early['entry_vs_low_pct']:.0f}% above it."]
    if best and base is not None:
        s.append(f"The best preset hit +50% only {best['hit_pct']:.0f}% of the time (all stock-days: {base:.0f}%).")
    s.append("What to do: Stack evidence, keep losses small, and re-enter the stocks that keep setting up.")
    return s


@lab.memo("case_movers")
def case_movers(as_of: date | None, min_gain_pct: float = BIG_MOVE_PCT) -> Result:
    with db.market_conn() as con:
        resolved, end = _resolve(con, as_of)
        if end is None:
            return no_session(as_of)
        M, C, src = movers_tables(con, end)
    if M.empty:
        return unavailable(end, "no stock doubled in the window", ["indicators_daily"], caveat=lab.CAVEAT)
    M = M[M.gain_pct >= float(min_gain_pct)]
    early = C[C.preset_id.isin(EARLY) & C.first_fire.notna()] if len(C) else C
    first = early.sort_values("first_fire").groupby("symbol").first() if len(early) else pd.DataFrame()
    M = M.copy()
    if len(first):
        M["first_early_fire"] = M.symbol.map(first.first_fire)
        M["first_early_preset"] = M.symbol.map(first.preset)
        M["first_early_vs_low_pct"] = M.symbol.map(first.entry_vs_low_pct)
    return Result(as_of=end, rows=lab.records(M, 2), sources=["indicators_daily"],
                  extra={"caveat": lab.CAVEAT, "study_end": end, "source": src, "window_from": window_start(end),
                         "window_to": end, "min_gain_pct": min_gain_pct})


@lab.memo("case_study")
def case_study(as_of: date | None, symbol: str) -> Result:
    with db.market_conn() as con:
        resolved, end = _resolve(con, as_of)
        if end is None:
            return no_session(as_of)
        x = lab.load_frame(con, end, symbols=[symbol])
        P, _ = precision_table(con, end)
    start = window_start(end)
    if x.empty:
        return unavailable(end, f"no price history for {symbol} on or before {end.isoformat()}", ["indicators_daily"],
                           caveat=lab.CAVEAT, precision=_precision_ctx(P))
    x = add_presets(x.copy())
    w = x[x.trade_date >= pd.Timestamp(start)]
    if len(w) < 20:
        return unavailable(end, f"{symbol} has {len(w)} sessions in the window (needs 20)", ["indicators_daily"],
                           caveat=lab.CAVEAT, precision=_precision_ctx(P))
    mv = _move(x, start)
    assert mv is not None
    fires_tbl = first_fires(x, mv)
    legs, comp = ladder(x, mv)
    specs = preset_specs()
    shown = x[x.trade_date >= pd.Timestamp(start - timedelta(days=60))]
    fires = []
    for p in specs:
        f = shown[shown["f_" + p["id"]] & (shown.trade_date >= pd.Timestamp(start))]
        for _, r in f.iterrows():
            fires.append({"date": r.trade_date, "preset_id": p["id"], "preset": p["name"], "letter": p["letter"],
                          "close": round(float(r.close_price), 2), "in_move": bool(mv["low_date"] <= r.trade_date <= mv["peak_date"])})
    fires.sort(key=lambda f: (f["date"], f["letter"]))
    bars = shown[["trade_date", "open_price", "high_price", "low_price", "close_price", "volume", "ema_20"]].rename(
        columns={"trade_date": "time", "open_price": "open", "high_price": "high", "low_price": "low",
                 "close_price": "close"})
    is_big = bool(len(w) >= MIN_SESSIONS and mv["gain_pct"] >= BIG_MOVE_PCT)
    first_hit = min((r for r in fires_tbl if r["first_fire"] is not None), key=lambda r: r["first_fire"], default=None)
    summary = [f"{symbol} rose {mv['gain_pct']:.0f}% from {mv['low']:,.1f} on {mv['low_date']:%d %b %Y} "
               f"to {mv['peak']:,.1f} on {mv['peak_date']:%d %b %Y}."]
    if first_hit:
        summary.append(f"The first fresh fire was {first_hit['preset']} on {first_hit['first_fire']:%d %b %Y}, "
                       f"{first_hit['entry_vs_low_pct']:.0f}% above the low.")
    summary.append(f"The 20 EMA ladder made {len(legs)} trades and compounded {comp:+.0f}%.")
    if not is_big:
        summary.append("This stock is not a big mover in the window (low to peak < +100%).")
    ctx = {"caveat": lab.CAVEAT, "study_end": end, "window_from": start, "window_to": end, "symbol": symbol,
           "security_name": lab.clean(x.security_name.iat[0]), "industry": lab.clean(x.industry.iat[0]),
           "mcap_cr": lab.clean(x.mcap_now.iat[0]), "below_floor": bool((x.mcap_now.iat[0] or 0) < lab.MIN_MCAP_CR),
           "move": {k: lab.clean(v) for k, v in mv.items()}, "big_mover": is_big,
           "first_fires": [{k: lab.clean(v) for k, v in r.items()} for r in fires_tbl],
           "ladder": {"legs": [{k: lab.clean(v) for k, v in leg.items()} for leg in legs], "compounded_pct": round(comp, 1),
                      "trades": len(legs), "entry_presets": [p["name"] for p in specs if p["id"] in LADDER_ENTRY],
                      "rule": "Enter on the first fresh fire of an entry preset with the close above the 20 EMA. "
                              "Exit on the first close below the 20 EMA. Repeat."},
           "fires": [{k: lab.clean(v) for k, v in f.items()} for f in fires],
           "presets": [{k: p[k] for k in ("id", "name", "letter", "category", "early", "description")} for p in specs],
           "precision": _precision_ctx(P), "summary": summary}
    return Result(as_of=end, rows=lab.records(bars, 2), sources=["indicators_daily", "App/services/screener.py"], extra=ctx)
