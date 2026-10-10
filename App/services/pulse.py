"""Pulse tab (HarkPro/02-tab1-pulse.md, locked 2026-10-09).

Market mood vs history, participation (breadth) grid with expansion / contraction flags,
internals, money flow, groups, stocks that moved, and "days like today".

Point-in-time rules
- Every per-day reading that depends on history (archive percentile, 60-day sigma, mood) is computed
  with data up to and including that day only, so slicing the full series at `as_of` gives the same
  numbers a replay on that date would have shown.
- Archive min / max / p10 / p90 and the expansion thresholds use every session up to `as_of`.
- Forward returns (expansion log, analogs) only use sessions up to `as_of`.

The SQL and the calculations follow the prototype in HarkPro/tools/pulse_mockup/ (extract.py + template.html).
"""
from __future__ import annotations

import bisect
import math
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from App.services import db, group_state
from App.services.common import Result, no_session, unavailable

LOOKBACKS = (5, 10, 20, 60, 250)
EMA_KEYS = ("e10", "e20", "e50", "e100", "e200")
EMA_LABEL = {"e10": "10 EMA", "e20": "20 EMA", "e50": "50 EMA", "e100": "100 EMA", "e200": "200 EMA"}
EMA_PROSE = {"e10": "10-day", "e20": "20-day", "e50": "50-day", "e100": "100-day", "e200": "200-day"}
SIGMA_WINDOW = 60          # daily changes used for the cell sigma
UNUSUAL_Z = 2.0            # amber outline
INTENSITY_SIGMAS = 2.5     # colour intensity scale
XP_QUANTILE = 0.05         # expansion / contraction: top / bottom 5% of the row's own history
XP_MIN_REL = 0.15          # ... and at least 15% ...
XP_MIN_COUNT = 100         # ... and at least 100 stocks
XP_MIN_HISTORY = 60        # no flags until a row has this many daily changes
GAP_DAYS = 7               # calendar days between sessions that count as a data gap
EW_CAP = 0.20              # equal-weight market series: daily stock returns capped at ±20%
ANALOG_EXCLUDE = 25        # analogs skip the latest 25 sessions
ANALOG_SPACING = 10        # picked analogs at least 10 sessions apart
MIN_MCAP_CR = 1000.0
MOVER_KINDS = ("gainers", "losers", "turnover", "delivered", "rvol")
RVOL_MIN_TURNOVER_CR = 5.0
MOVERS_N = 20
DEAL_SESSIONS = 3
GROUP_LEVELS = {"sector": "Sector", "industry": "Industry"}
INDEX_LEVELS = {"sectoral": "Sectoral", "thematic": "Thematic"}

MOOD_PARTS = (
    ("e10", "% above 10 EMA"),
    ("e50", "% above 50 EMA"),
    ("e200", "% above 200 EMA"),
    ("upvol", "Up-volume %"),
    ("nn", "Net new 52W highs"),
    ("st2", "Stage 2 %"),
)
MOOD_BANDS = ((70, "Strong", "up"), (55, "Healthy", "up"), (45, "Mixed", "warn"), (30, "Weak", "down"), (-1, "Very weak", "down"))

ACTIONS = {
    "strong_but_cooling": "The backdrop is strong, but short-term breadth is falling fast. Do not chase breakouts today. "
                          "Keep your current positions. Add new ones when the 10-day number stops falling.",
    "cooling": "Do not add new positions today. Wait for the 10-day number to stop falling.",
    "weak": "Take fewer new trades. Use smaller size. Buy only the strongest stocks in leading groups.",
    "mixed": "Trade normal setups with care. Keep size normal or smaller until breadth turns up again.",
    "healthy": "Conditions support new trades. Use normal size. Add only to positions that show a profit.",
}

INTERNALS = (
    # key, label, unit, good direction (1 up, -1 down), one-line meaning
    ("adv", "Advancers %", "pct", 1, "Share of stocks that rose"),
    ("upvol", "Up-volume %", "pct", 1, "Volume in rising stocks"),
    ("nn", "Net new highs", "count", 1, "52-week highs minus 52-week lows"),
    ("st2", "In Stage 2", "pct", 1, "Stocks that pass the trend template"),
    ("ft", "Breakouts holding", "pct", 1, "Recent 20-day-high breakouts still above the breakout close"),
    ("vix", "India VIX", "index", -1, "Expected volatility. Lower is calmer"),
)

SOURCES = ["breadth_daily", "regime_daily", "indicators_daily"]


# --------------------------------------------------------------------------
# Small numeric helpers (pure)
# --------------------------------------------------------------------------
def clean(x: Any, nd: int | None = None) -> Any:
    """JSON-safe scalar: NaN/inf -> None, numpy -> python, optional rounding."""
    if x is None:
        return None
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        f = float(x)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, nd) if nd is not None else f
    if isinstance(x, pd.Timestamp):
        return x.date().isoformat()
    if isinstance(x, date):
        return x.isoformat()
    try:
        if pd.isna(x):
            return None
    except (TypeError, ValueError):
        pass
    return x


def expanding_pctl(values: Any) -> np.ndarray:
    """Point-in-time percentile: share (0-100) of non-null values up to and including day i that are
    strictly below day i's value. NaN where the value is missing."""
    a = np.asarray(values, dtype=float)
    out = np.full(len(a), np.nan)
    valid = ~np.isnan(a)
    hist: list[float] = []
    for i, v in enumerate(a):
        if not valid[i]:
            continue
        bisect.insort(hist, v)
        out[i] = 100.0 * bisect.bisect_left(hist, v) / len(hist)
    return out


def pctl_of(history: Any, value: float | None) -> float | None:
    """Percentile of `value` in `history` (same rule as expanding_pctl)."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    h = np.asarray(history, dtype=float)
    h = h[~np.isnan(h)]
    if not len(h):
        return None
    return float(100.0 * np.sum(h < value) / len(h))


def lower_quantile(values: Any, q: float) -> float | None:
    """sorted[floor(q * (n - 1))], the prototype's quantile."""
    a = np.sort(np.asarray(values, dtype=float))
    a = a[~np.isnan(a)]
    if not len(a):
        return None
    return float(a[int(math.floor(q * (len(a) - 1)))])


def trailing_std(values: Any, window: int = SIGMA_WINDOW) -> np.ndarray:
    """Population std of the `window` values before day i (day i excluded)."""
    s = pd.Series(np.asarray(values, dtype=float))
    return s.shift(1).rolling(window, min_periods=10).std(ddof=0).to_numpy()


def mood_label(score: float | None) -> tuple[str | None, str | None]:
    if score is None:
        return None, None
    for floor, word, tone in MOOD_BANDS:
        if score >= floor:
            return word, tone
    return "Very weak", "down"


def direction_qualifier(e10_now: float | None, e10_then: float | None) -> str | None:
    if e10_now is None or e10_then is None:
        return None
    if e10_now < e10_then - 10:
        return "cooling"
    if e10_now > e10_then + 10:
        return "improving"
    return None


def choose_action(mood: float | None, e10_change: float | None) -> str | None:
    """Spec §3 action rules, first match wins."""
    if mood is None:
        return None
    falling = e10_change is not None and e10_change < -10
    if mood >= 55 and falling:
        return "strong_but_cooling"
    if falling:
        return "cooling"
    if mood < 45:
        return "weak"
    if mood < 55:
        return "mixed"
    return "healthy"


def xp_thresholds(rel: Any) -> tuple[float, float] | None:
    """(contraction, expansion) thresholds on the one-day relative change of the count."""
    a = np.asarray(rel, dtype=float)
    a = a[~np.isnan(a)]
    if len(a) < XP_MIN_HISTORY:
        return None
    return (min(lower_quantile(a, XP_QUANTILE), -XP_MIN_REL), max(lower_quantile(a, 1 - XP_QUANTILE), XP_MIN_REL))


def xp_flag(rel: float | None, count_change: float | None, th: tuple[float, float] | None) -> int:
    if th is None or rel is None or count_change is None or math.isnan(rel) or math.isnan(count_change):
        return 0
    if rel >= th[1] and count_change >= XP_MIN_COUNT:
        return 1
    if rel <= th[0] and -count_change >= XP_MIN_COUNT:
        return -1
    return 0


def _fmt_int(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{int(round(v)):,}"


def _signed(v: float, nd: int = 0) -> str:
    s = f"{v:+.{nd}f}"
    return s


# --------------------------------------------------------------------------
# The full market series (cached per DB fingerprint), derived columns
# --------------------------------------------------------------------------
def _load_market(con: Any) -> pd.DataFrame:
    if not db.table_exists(con, "breadth_daily"):
        return pd.DataFrame()
    has_regime = db.table_exists(con, "regime_daily")
    rsel = ("r.new_highs AS nh, r.new_lows AS nl, r.stage2_pct AS st2, r.follow_through_pct AS ft, r.vix_close AS vix"
            if has_regime else "NULL AS nh, NULL AS nl, NULL AS st2, NULL AS ft, NULL AS vix")
    rjoin = "LEFT JOIN regime_daily r ON r.trade_date = b.trade_date" if has_regime else ""
    b = con.execute(f"""
        SELECT b.trade_date AS d, b.stocks, b.advancers AS adv_n, b.decliners AS decl_n,
               b.advance_volume_pct AS upvol,
               b.above_10ema_pct AS e10, b.above_20ema_pct AS e20, b.above_50ema_pct AS e50,
               b.above_100ema_pct AS e100, b.above_200ema_pct AS e200, {rsel}
        FROM breadth_daily b {rjoin}
        ORDER BY b.trade_date""").df()
    m = con.execute(f"""
        SELECT trade_date AS d, sum(turnover_cr) AS tov, sum(delivery_qty * close_price) / 1e7 AS dlv,
               avg(least(greatest(CASE WHEN prev_close > 0 THEN close_price / prev_close - 1 END, -{EW_CAP}), {EW_CAP})) AS ewret
        FROM indicators_daily GROUP BY 1 ORDER BY 1""").df()
    df = b.merge(m, on="d", how="left")
    df["d"] = pd.to_datetime(df["d"]).dt.date
    return df


def derive(df: pd.DataFrame) -> pd.DataFrame:
    """Add every point-in-time derived column. Pure: depends only on rows up to each day."""
    df = df.copy().reset_index(drop=True)
    num = lambda c: pd.to_numeric(df[c], errors="coerce").astype(float)  # noqa: E731
    for c in ("stocks", "adv_n", "decl_n", "upvol", *EMA_KEYS, "nh", "nl", "st2", "ft", "vix", "tov", "dlv", "ewret"):
        df[c] = num(c) if c in df else np.nan
    df["nn"] = df["nh"] - df["nl"]
    tot = df["adv_n"] + df["decl_n"]
    df["adv"] = np.where(tot > 0, 100.0 * df["adv_n"] / tot.replace(0, np.nan), np.nan)
    dates = pd.to_datetime(pd.Series(df["d"]))
    df["gap_days"] = dates.diff().dt.days
    df["gap_before"] = df["gap_days"] > GAP_DAYS
    for k in EMA_KEYS:
        cnt = df[k] * df["stocks"] / 100.0
        df[f"{k}_n"] = cnt
        df[f"{k}_chg"] = df[k].diff()
        df[f"{k}_dn"] = cnt.diff()
        prev = cnt.shift(1)
        df[f"{k}_rel"] = np.where(prev > 0, cnt / prev - 1, np.nan)
        df[f"{k}_sd"] = trailing_std(df[f"{k}_chg"])
        df[f"{k}_pctl"] = expanding_pctl(df[k])
    for k in ("upvol", "nn", "st2", "adv", "ft", "vix"):
        df[f"{k}_pctl"] = expanding_pctl(df[k])
    parts = np.vstack([df[f"{k}_pctl"].to_numpy() for k, _ in MOOD_PARTS])
    with np.errstate(all="ignore"):
        cnt = np.sum(~np.isnan(parts), axis=0)
        df["mood"] = np.where(cnt > 0, np.nansum(parts, axis=0) / np.maximum(cnt, 1), np.nan)
    df["mood_parts_n"] = cnt
    df["ew"] = 100.0 * (1 + df["ewret"].fillna(0)).cumprod()
    df["e50c5"] = df["e50"] - df["e50"].shift(5)
    df["tov_avg20"] = df["tov"].shift(1).rolling(20, min_periods=20).mean()
    df["dshare"] = np.where(df["tov"] > 0, 100.0 * df["dlv"] / df["tov"], np.nan)
    df["dshare_avg20"] = df["dshare"].shift(1).rolling(20, min_periods=20).mean()
    return df


def full_frame() -> pd.DataFrame:
    def compute() -> pd.DataFrame:
        with db.market_conn() as con:
            raw = _load_market(con)
        return derive(raw) if not raw.empty else raw

    return db.cached("pulse_full", (), compute)


class Ctx:
    """The market frame sliced at as_of, plus as_of-wide stats."""

    def __init__(self, df: pd.DataFrame, as_of: date):
        self.df = df[df["d"] <= as_of].reset_index(drop=True)
        self.as_of = as_of
        self.L = len(self.df) - 1
        self.th = {k: xp_thresholds(self.df.loc[~self.df["gap_before"], f"{k}_rel"]) for k in EMA_KEYS}

    def at(self, col: str, i: int) -> float | None:
        if i < 0 or i > self.L:
            return None
        return clean(self.df.at[i, col])

    def back(self, n: int) -> int:
        return max(0, self.L - n)

    def flag(self, k: str, i: int) -> int:
        if i <= 0 or bool(self.df.at[i, "gap_before"]):
            return 0
        return xp_flag(self.at(f"{k}_rel", i), self.at(f"{k}_dn", i), self.th[k])

    def events(self) -> list[dict[str, Any]]:
        out = []
        for k in EMA_KEYS:
            th = self.th[k]
            if th is None:
                continue
            rel = self.df[f"{k}_rel"].to_numpy()
            dn = self.df[f"{k}_dn"].to_numpy()
            gap = self.df["gap_before"].to_numpy()
            for i in range(1, self.L + 1):
                if gap[i]:
                    continue
                f = xp_flag(float(rel[i]), float(dn[i]), th)
                if f:
                    out.append({"i": i, "k": k, "f": f})
        return out

    def fwd(self, i: int, n: int) -> float | None:
        if i + n > self.L:
            return None
        a, b = self.at("ew", i), self.at("ew", i + n)
        if not a or b is None:
            return None
        return 100.0 * (b / a - 1)

    def date(self, i: int) -> str:
        return self.df.at[i, "d"].isoformat()

    def gap_warning(self, lookback: int = 1) -> str | None:
        """Warning when a data gap falls inside the comparison window."""
        lo = max(1, self.L - max(lookback, 1) + 1)
        gaps = self.df.index[(self.df.index >= lo) & self.df["gap_before"]].tolist()
        if not gaps:
            return None
        i = gaps[-1]
        return (f"Data gap: no sessions between {self.date(i - 1)} and {self.date(i)}. "
                f"Changes across this gap are not one-day changes.")


def _ctx(as_of: date | None) -> tuple[Ctx | None, Result | None]:
    with db.market_conn() as con:
        if not db.table_exists(con, "breadth_daily"):
            return None, unavailable(None, "breadth_daily missing", SOURCES)
        d = db.resolve_as_of(con, as_of)
    if d is None:
        return None, no_session(as_of)
    df = full_frame()
    if df.empty or not (df["d"] <= d).any():
        return None, unavailable(d, "no breadth sessions on or before as_of", SOURCES)
    ctx = Ctx(df, d)
    if ctx.df["d"].iloc[-1] != d:
        # breadth lags indicators: answer for the last breadth session and say so
        return Ctx(df, ctx.df["d"].iloc[-1]), None
    return ctx, None


def _lb(lookback: int) -> int:
    if lookback not in LOOKBACKS:
        raise ValueError(f"lookback must be one of {LOOKBACKS}")
    return lookback


# --------------------------------------------------------------------------
# Analogs (shared with summary)
# --------------------------------------------------------------------------
def _analogs(ctx: Ctx, k: int = 8) -> list[dict[str, Any]]:
    df, L = ctx.df, ctx.L
    t = df.iloc[L]
    if L < ANALOG_EXCLUDE + 20 or any(pd.isna(t[c]) for c in ("e50", "e50c5", "e10")):
        return []
    cand = df.iloc[: L - ANALOG_EXCLUDE + 1].copy()
    cand["dist"] = ((cand.e50 - t.e50) / 10) ** 2 + ((cand.e50c5 - t.e50c5) / 6) ** 2 + ((cand.e10 - t.e10) / 12) ** 2
    cand = cand.dropna(subset=["dist"])
    picks: list[int] = []
    for i in cand.sort_values("dist", kind="mergesort").index:
        if any(abs(i - p) < ANALOG_SPACING for p in picks):
            continue
        picks.append(int(i))
        if len(picks) == k:
            break
    out = []
    for i in sorted(picks):
        out.append({
            "trade_date": ctx.date(i),
            "e50": clean(df.at[i, "e50"], 1), "e50c5": clean(df.at[i, "e50c5"], 1), "e10": clean(df.at[i, "e10"], 1),
            "fwd_10d_pct": clean(ctx.fwd(i, 10), 2), "fwd_20d_pct": clean(ctx.fwd(i, 20), 2),
            "distance": clean(cand.at[i, "dist"], 4),
        })
    return out


def _median(vals: list[float | None]) -> float | None:
    v = [x for x in vals if x is not None]
    return float(np.median(v)) if v else None


# --------------------------------------------------------------------------
# Summary: mood, commentary, action
# --------------------------------------------------------------------------
def commentary(ctx: Ctx, lookback: int, analogs: list[dict[str, Any]]) -> dict[str, Any]:
    """Sentences (04-writing-style.md) + action. Every number here is also on screen."""
    L, lb = ctx.L, ctx.back(lookback)
    e10, e10o = ctx.at("e10", L), ctx.at("e10", lb)
    e50 = ctx.at("e50", L)
    mood, mood_o = ctx.at("mood", L), ctx.at("mood", lb)
    lines: list[dict[str, Any]] = []
    flags = []
    for k in ("e200", "e100", "e50", "e20", "e10"):  # longest average first
        f = ctx.flag(k, L)
        if f:
            flags.append({"key": k, "dir": f, "from": clean(ctx.at(f"{k}_n", L - 1), 0), "to": clean(ctx.at(f"{k}_n", L), 0),
                          "rel_pct": clean(100 * ctx.at(f"{k}_rel", L), 1)})
    if flags:
        x = flags[0]
        n_hist = sum(1 for e in ctx.events() if e["k"] == x["key"] and e["f"] == x["dir"])
        x["n_history"] = n_hist
        word = "expansion" if x["dir"] > 0 else "contraction"
        lines.append({"kind": "flag", "lead": f"Breadth {word}.",
                      "text": f"Stocks above their {EMA_PROSE[x['key']]} average went from {_fmt_int(x['from'])} to "
                              f"{_fmt_int(x['to'])} ({_signed(x['rel_pct'], 0)}%) in one day. "
                              f"A move this big happened on {n_hist} days in our history."})
    if e10 is not None and e10o is not None:
        word = "fell" if e10 < e10o - 5 else "rose" if e10 > e10o + 5 else "held steady"
        lines.append({"kind": "short", "lead": f"Short-term breadth {word}.",
                      "text": f"{e10:.0f}% of stocks are above their 10-day average. "
                              f"{lookback} sessions ago, the number was {e10o:.0f}%."})
    if e50 is not None:
        state = "healthy" if e50 >= 55 else "neutral" if e50 >= 45 else "weak"
        p50 = ctx.at("e50_pctl", L)
        lines.append({"kind": "medium", "lead": f"The medium trend is {state}.",
                      "text": f"{e50:.0f}% of stocks are above their 50-day average. "
                              f"This level is higher than on {p50:.0f}% of days in our history."})
    a, d = ctx.at("adv_n", L), ctx.at("decl_n", L)
    nh, nl = ctx.at("nh", L), ctx.at("nl", L)
    if a is not None and d is not None:
        s = f"{_fmt_int(a)} stocks rose and {_fmt_int(d)} fell today."
        if nh is not None and nl is not None:
            s += f" {_fmt_int(nh)} stocks made a new 52-week high and {_fmt_int(nl)} made a new low."
        lines.append({"kind": "ad", "lead": None, "text": s})
    t, t20 = ctx.at("tov", L), ctx.at("tov_avg20", L)
    if t is not None and t20:
        pct = 100 * (t / t20 - 1)
        lines.append({"kind": "turnover", "lead": None,
                      "text": f"Turnover was ₹{_fmt_int(t)} Cr. That is {'more' if t > t20 else 'less'} than the "
                              f"20-day average by {abs(pct):.0f}%."})
    e10_change = (e10 - e10o) if e10 is not None and e10o is not None else None
    rule = choose_action(mood, e10_change)
    up = sum(1 for x in analogs if (x["fwd_20d_pct"] or 0) > 0)
    return {
        "lines": lines,
        "flags": flags,
        "action_rule": rule,
        "action": ACTIONS.get(rule) if rule else None,
        "history_line": (f"In {len(analogs)} similar past setups, the average stock rose over the next 20 sessions "
                         f"{up} times.") if analogs else None,
        "analogs_n": len(analogs),
        "analogs_up_20d": up,
        "e10_change": clean(e10_change, 1),
        "mood_prev": clean(mood_o, 1),
    }


def summary(as_of: date | None, lookback: int = 5) -> Result:
    lookback = _lb(lookback)
    ctx, err = _ctx(as_of)
    if err:
        return err
    L, lb = ctx.L, ctx.back(lookback)
    mood = ctx.at("mood", L)
    if mood is None:
        return unavailable(ctx.as_of, "mood readings are missing for this session", SOURCES)
    label, tone = mood_label(mood)
    qual = direction_qualifier(ctx.at("e10", L), ctx.at("e10", lb))
    ana = _analogs(ctx)
    com = commentary(ctx, lookback, ana)
    n = max(lookback, 20)
    spark = [{"trade_date": ctx.date(i), "mood": clean(ctx.df.at[i, "mood"], 1)} for i in range(max(0, L - n), L + 1)]
    parts = [{"key": k, "label": lab, "value": ctx.at(k, L), "pctl": clean(ctx.at(f"{k}_pctl", L), 1)} for k, lab in MOOD_PARTS]
    row = {
        "trade_date": ctx.as_of.isoformat(),
        "lookback": lookback,
        "ref_date": ctx.date(lb),
        "mood": clean(mood, 1),
        "mood_label": label,
        "mood_tone": tone,
        "qualifier": qual,
        "qualifier_text": {"cooling": "and cooling fast", "improving": "and improving fast"}.get(qual or ""),
        "mood_change": clean(mood - com["mood_prev"], 1) if com["mood_prev"] is not None else None,
        "mood_prev": com["mood_prev"],
        "mood_parts": parts,
        "mood_parts_known": int(ctx.df.at[L, "mood_parts_n"]),
        "mood_series": spark,
        "commentary": com["lines"],
        "action_rule": com["action_rule"],
        "action": com["action"],
        "history_line": com["history_line"],
        "analogs_n": com["analogs_n"],
        "analogs_up_20d": com["analogs_up_20d"],
        "e10_change": com["e10_change"],
        "flags": com["flags"],
        "sessions_in_archive": L + 1,
        "archive_start": ctx.date(0),
        "data_warning": ctx.gap_warning(lookback),
    }
    notes = ["Mood score is a prototype: average history-percentile of six readings. Not yet tested against forward returns."]
    if row["mood_parts_known"] < len(MOOD_PARTS):
        notes.append(f"Only {row['mood_parts_known']} of {len(MOOD_PARTS)} mood readings exist for this session.")
    return Result(as_of=ctx.as_of, rows=[row], sources=SOURCES, notes=notes,
                  extra={"lookbacks": list(LOOKBACKS), "bands": [{"min": f, "label": w} for f, w, _ in MOOD_BANDS]})


# --------------------------------------------------------------------------
# Breadth grid + trend chart
# --------------------------------------------------------------------------
def breadth(as_of: date | None, sessions: int | None = None, lookback: int = 5) -> Result:
    lookback = _lb(lookback)
    ctx, err = _ctx(as_of)
    if err:
        return err
    L = ctx.L
    sessions = sessions or max(lookback, 20) + 1
    rows = []
    for i in range(max(0, L - sessions + 1), L + 1):
        r: dict[str, Any] = {"trade_date": ctx.date(i), "stocks": clean(ctx.df.at[i, "stocks"], 0),
                             "gap_before": bool(ctx.df.at[i, "gap_before"])}
        for k in EMA_KEYS:
            chg, sd = ctx.at(f"{k}_chg", i), ctx.at(f"{k}_sd", i)
            z = chg / sd if chg is not None and sd else None
            r[k] = {
                "pct": clean(ctx.at(k, i), 2),
                "count": clean(ctx.at(f"{k}_n", i), 0),
                "chg": clean(chg, 2),
                "chg_count": clean(ctx.at(f"{k}_dn", i), 0),
                "rel_pct": clean(None if ctx.at(f"{k}_rel", i) is None else 100 * ctx.at(f"{k}_rel", i), 1),
                "sd60": clean(sd, 3),
                "z": clean(z, 2),
                "unusual": bool(z is not None and abs(z) > UNUSUAL_Z),
                "intensity": clean(min(0.85, abs(chg) / max(sd * INTENSITY_SIGMAS, 0.1)), 3) if chg is not None and sd else 0.0,
                "flag": ctx.flag(k, i),
                "pctl": clean(ctx.at(f"{k}_pctl", i), 1),
            }
        rows.append(r)
    lb = ctx.back(lookback)
    stats = []
    for k in EMA_KEYS:
        col = ctx.df[k]
        th = ctx.th[k]
        stats.append({
            "key": k, "label": EMA_LABEL[k],
            "min": clean(col.min(), 2), "max": clean(col.max(), 2),
            "p10": clean(lower_quantile(col, 0.1), 2), "p90": clean(lower_quantile(col, 0.9), 2),
            "today": clean(ctx.at(k, L), 2), "today_count": clean(ctx.at(f"{k}_n", L), 0),
            "lb_value": clean(ctx.at(k, lb), 2), "lb_count": clean(ctx.at(f"{k}_n", lb), 0),
            "delta": clean((ctx.at(k, L) or 0) - (ctx.at(k, lb) or 0), 2) if ctx.at(k, lb) is not None else None,
            "delta_count": clean((ctx.at(f"{k}_n", L) or 0) - (ctx.at(f"{k}_n", lb) or 0), 0) if ctx.at(f"{k}_n", lb) is not None else None,
            "pctl": clean(ctx.at(f"{k}_pctl", L), 1),
            "xp_lo_pct": clean(100 * th[0], 1) if th else None,
            "xp_hi_pct": clean(100 * th[1], 1) if th else None,
        })
    return Result(as_of=ctx.as_of, rows=rows, sources=["breadth_daily"],
                  extra={"lookback": lookback, "lb_date": ctx.date(lb), "archive_start": ctx.date(0),
                         "sessions_in_archive": L + 1, "stats": stats,
                         "xp_rule": {"quantile": XP_QUANTILE, "min_rel_pct": 100 * XP_MIN_REL, "min_count": XP_MIN_COUNT,
                                     "min_history": XP_MIN_HISTORY},
                         "data_warning": ctx.gap_warning(min(lookback, 10))})


# --------------------------------------------------------------------------
# Internals cards
# --------------------------------------------------------------------------
def internals(as_of: date | None, sessions: int | None = None, lookback: int = 5) -> Result:
    lookback = _lb(lookback)
    ctx, err = _ctx(as_of)
    if err:
        return err
    L = ctx.L
    sessions = sessions or max(lookback, 20) + 1
    rows = []
    for key, label, unit, good, meaning in INTERNALS:
        v = ctx.at(key, L)
        prior = ctx.df[key].iloc[max(0, L - lookback):L]
        avg = clean(prior.mean()) if prior.notna().any() else None
        series = [{"trade_date": ctx.date(i), "value": clean(ctx.df.at[i, key], 2)} for i in range(max(0, L - sessions + 1), L + 1)]
        known = int(ctx.df[key].notna().sum())
        rows.append({
            "key": key, "label": label, "unit": unit, "good_direction": good, "meaning": meaning,
            "value": clean(v, 2), "lb_avg": clean(avg, 2),
            "change": clean(v - avg, 2) if v is not None and avg is not None else None,
            "pctl": clean(ctx.at(f"{key}_pctl", L), 1),
            "history_sessions": known,
            "series": series,
            "data_warning": None if v is not None else f"No {label} reading for this session.",
        })
    notes = []
    if ctx.df["vix"].notna().sum() < 120:
        notes.append(f"India VIX has only {int(ctx.df['vix'].notna().sum())} sessions of history; its percentile is weak.")
    return Result(as_of=ctx.as_of, rows=rows, sources=["breadth_daily", "regime_daily"], notes=notes,
                  extra={"lookback": lookback})


# --------------------------------------------------------------------------
# Expansion log
# --------------------------------------------------------------------------
def expansions(as_of: date | None, limit: int = 8) -> Result:
    ctx, err = _ctx(as_of)
    if err:
        return err
    ev = ctx.events()
    by: dict[tuple[int, int], dict[str, Any]] = {}
    for e in ev:
        by.setdefault((e["i"], e["f"]), {"i": e["i"], "f": e["f"], "ks": []})["ks"].append(e["k"])
    days = sorted(by.values(), key=lambda x: -x["i"])
    rows = []
    for x in days[:limit]:
        i = x["i"]
        k = "e20" if "e20" in x["ks"] else x["ks"][-1]
        rows.append({
            "trade_date": ctx.date(i), "is_today": i == ctx.L, "dir": x["f"],
            "signal": "Expansion" if x["f"] > 0 else "Contraction",
            "keys": x["ks"], "shown_key": k,
            "from": clean(ctx.at(f"{k}_n", i - 1), 0), "to": clean(ctx.at(f"{k}_n", i), 0),
            "rel_pct": clean(100 * ctx.at(f"{k}_rel", i), 1),
            "fwd_10d_pct": clean(ctx.fwd(i, 10), 2), "fwd_20d_pct": clean(ctx.fwd(i, 20), 2),
        })
    stats = []
    for k in ("e20", "e50", "e200"):
        s: dict[str, Any] = {"key": k, "label": EMA_LABEL[k]}
        for f, name in ((1, "expansions"), (-1, "contractions")):
            f20 = [ctx.fwd(e["i"], 20) for e in ev if e["k"] == k and e["f"] == f and e["i"] + 20 <= ctx.L]
            all_n = sum(1 for e in ev if e["k"] == k and e["f"] == f)
            s[name] = {"n": all_n, "n_with_fwd": len(f20), "median_fwd_20d_pct": clean(_median(f20), 2),
                       "up_20d": sum(1 for v in f20 if v is not None and v > 0)}
        stats.append(s)
    th = [{"key": k, "lo_pct": clean(100 * ctx.th[k][0], 1) if ctx.th[k] else None,
           "hi_pct": clean(100 * ctx.th[k][1], 1) if ctx.th[k] else None} for k in EMA_KEYS]
    return Result(as_of=ctx.as_of, rows=rows, sources=["breadth_daily", "indicators_daily"],
                  extra={"stats": stats, "thresholds": th, "total_days": len(days),
                         "archive_start": ctx.date(0)},
                  notes=["Forward returns: equal-weight average of all stocks, daily returns capped at ±20%."])


# --------------------------------------------------------------------------
# Analogs
# --------------------------------------------------------------------------
def analogs(as_of: date | None, k: int = 8) -> Result:
    ctx, err = _ctx(as_of)
    if err:
        return err
    rows = _analogs(ctx, k)
    L = ctx.L
    f10 = [r["fwd_10d_pct"] for r in rows]
    f20 = [r["fwd_20d_pct"] for r in rows]
    today = {"trade_date": ctx.date(L), "e50": clean(ctx.at("e50", L), 1), "e50c5": clean(ctx.at("e50c5", L), 1),
             "e10": clean(ctx.at("e10", L), 1)}
    if not rows:
        return unavailable(ctx.as_of, f"need more than {ANALOG_EXCLUDE + 20} sessions of history", SOURCES, today=today)
    return Result(as_of=ctx.as_of, rows=rows, sources=["breadth_daily", "indicators_daily"],
                  extra={"today": today, "median_fwd_10d_pct": clean(_median(f10), 2),
                         "median_fwd_20d_pct": clean(_median(f20), 2),
                         "up_20d": sum(1 for v in f20 if v is not None and v > 0), "k": k,
                         "excluded_recent": ANALOG_EXCLUDE,
                         "method": "Nearest by % above 50 EMA, its 5-day change and % above 10 EMA; picks 10+ sessions apart."})


# --------------------------------------------------------------------------
# Money flow
# --------------------------------------------------------------------------
def _group_frame(con: Any, as_of: date, level: str, n_sessions: int) -> pd.DataFrame:
    return con.execute(
        """
        SELECT trade_date AS d, group_name AS name, members, ret_ew_1d, ret_ew_5d, ret_ew_21d, ret_ew_63d,
               turnover_cr, turnover_share_pct, turnover_share_20d_avg, turnover_share_delta, delivery_value_cr,
               pct_above_50ema, rank, rank_n, rank_chg_5d, rank_chg_20d, rrg_quadrant, days_in_quadrant,
               rs_ratio, rs_momentum, deal_net_10s_cr
        FROM group_daily
        WHERE level = ? AND floor = 'all' AND trade_date <= ?
          AND trade_date >= (SELECT min(d) FROM (SELECT DISTINCT trade_date AS d FROM group_daily
                             WHERE trade_date <= ? ORDER BY d DESC LIMIT ?))
        ORDER BY d
        """, [level, as_of, as_of, n_sessions]).df()


def _pct100(v: Any) -> float | None:
    f = clean(v)
    return None if f is None else round(100 * f, 2)


def flow(as_of: date | None, sessions: int | None = None, lookback: int = 5) -> Result:
    lookback = _lb(lookback)
    ctx, err = _ctx(as_of)
    if err:
        return err
    L = ctx.L
    sessions = sessions or min(max(lookback, 20), 60)
    rows = [{"trade_date": ctx.date(i), "turnover_cr": clean(ctx.df.at[i, "tov"], 0),
             "delivered_cr": clean(ctx.df.at[i, "dlv"], 0), "turnover_avg20_cr": clean(ctx.df.at[i, "tov_avg20"], 0),
             "delivery_share_pct": clean(ctx.df.at[i, "dshare"], 1), "gap_before": bool(ctx.df.at[i, "gap_before"])}
            for i in range(max(0, L - sessions + 1), L + 1)]
    t, t20 = ctx.at("tov", L), ctx.at("tov_avg20", L)
    headline = {
        "turnover_cr": clean(t, 0), "turnover_avg20_cr": clean(t20, 0),
        "turnover_vs20_pct": clean(100 * (t / t20 - 1), 1) if t is not None and t20 else None,
        "delivered_cr": clean(ctx.at("dlv", L), 0),
        "delivery_share_pct": clean(ctx.at("dshare", L), 1),
        "delivery_share_avg20_pct": clean(ctx.at("dshare_avg20", L), 1),
    }
    sectors: list[dict[str, Any]] = []
    with db.market_conn() as con:
        if db.table_exists(con, "group_daily"):
            g = _group_frame(con, ctx.as_of, "Sector", 1)
            g = g[pd.to_datetime(g["d"]).dt.date == ctx.as_of]
            for r in g.to_dict("records"):
                sectors.append({
                    "name": r["name"], "members": clean(r["members"]),
                    "turnover_cr": clean(r["turnover_cr"], 1), "share_pct": clean(r["turnover_share_pct"], 2),
                    "share_avg20_pct": clean(r["turnover_share_20d_avg"], 2), "share_delta": clean(r["turnover_share_delta"], 2),
                    "ret_1d_pct": _pct100(r["ret_ew_1d"]), "ret_1w_pct": _pct100(r["ret_ew_5d"]),
                    "ret_1m_pct": _pct100(r["ret_ew_21d"]), "ret_3m_pct": _pct100(r["ret_ew_63d"]),
                })
    sectors.sort(key=lambda s: -(s["share_delta"] if s["share_delta"] is not None else -1e9))
    return Result(as_of=ctx.as_of, rows=rows, sources=["indicators_daily", "group_daily"],
                  extra={"headline": headline, "sectors": sectors,
                         "data_warning": ctx.gap_warning(20)},
                  notes=["Turnover and delivery use all stocks. Sector rows: group_daily level Sector, floor all, equal weight."])


# --------------------------------------------------------------------------
# Groups table
# --------------------------------------------------------------------------
def groups(as_of: date | None, level: str = "sector") -> Result:
    level = level.lower()
    with db.market_conn() as con:
        d = db.resolve_as_of(con, as_of)
        if d is None:
            return no_session(as_of)
        if level in GROUP_LEVELS:
            if not db.table_exists(con, "group_daily"):
                return unavailable(d, "group_daily missing", ["group_daily"])
            g = _group_frame(con, d, GROUP_LEVELS[level], 63)
            return _group_rows(g, d, level, group_state.states_on(con, d, level))
        if level in INDEX_LEVELS:
            if not db.table_exists(con, "index_daily"):
                return unavailable(d, "index_daily missing", ["index_daily"])
            return _index_rows(con, d, INDEX_LEVELS[level])
    raise ValueError(f"level must be one of {[*GROUP_LEVELS, *INDEX_LEVELS]}")


def _group_rows(g: pd.DataFrame, d: date, level: str, states: dict[str, tuple[str, str]] | None = None) -> Result:
    if g.empty:
        return unavailable(d, "no group rows on or before as_of", ["group_daily"])
    g = g.copy()
    g["d"] = pd.to_datetime(g["d"]).dt.date
    rows = []
    for name, gg in g.groupby("name", sort=False):
        last = gg.iloc[-1]
        if last["d"] != d:
            continue
        st = (states or {}).get(name)
        rows.append({
            "name": name, "members": clean(last["members"]),
            "state": st[0] if st else None, "state_reason": st[1] if st else None,
            "ret_1d_pct": _pct100(last["ret_ew_1d"]), "ret_1w_pct": _pct100(last["ret_ew_5d"]),
            "ret_1m_pct": _pct100(last["ret_ew_21d"]), "ret_3m_pct": _pct100(last["ret_ew_63d"]),
            "turnover_cr": clean(last["turnover_cr"], 1), "share_pct": clean(last["turnover_share_pct"], 2),
            "share_delta": clean(last["turnover_share_delta"], 2), "delivered_cr": clean(last["delivery_value_cr"], 1),
            "pct_above_50ema": clean(last["pct_above_50ema"], 1),
            "rank": clean(last["rank"]), "rank_n": clean(last["rank_n"]),
            # rank_chg_5d > 0 means the rank number grew (worse); expose "places gained" (+ = better)
            "rank_gain_1w": clean(-last["rank_chg_5d"]) if clean(last["rank_chg_5d"]) is not None else None,
            "rrg_quadrant": clean(last["rrg_quadrant"]), "days_in_quadrant": clean(last["days_in_quadrant"]),
            "deal_net_10s_cr": clean(last["deal_net_10s_cr"], 1),
            "share_history": [clean(v, 2) for v in gg["turnover_share_pct"].tail(63)],
        })
    notes = ["Equal-weight group returns over all stocks (group_daily floor 'all').",
             "State (Favour / Neutral / Caution) is the one group state every tab shows: " + group_state.RULE]
    if level == "industry":
        notes.append("The table shows the top 40 industries by the sort column.")
    return Result(as_of=d, rows=rows, sources=["group_daily"], notes=notes, extra={"level": level})


def _index_rows(con: Any, d: date, category: str) -> Result:
    from App.thematic_engine import CANONICAL_44_INDICES as C44

    names = [n for n, v in C44.items() if v.get("category") == category]
    ph = ",".join(["?"] * len(names))
    ix = con.execute(
        f"""SELECT trade_date AS d, index_name AS name, close_price, return_1d_pct, return_5d_pct, return_20d_pct,
                   return_63d_pct, distance_ema_20_pct, distance_ema_50_pct, trend_state, new_52w_high
            FROM index_daily WHERE trade_date <= ? AND index_name IN ({ph})
              AND trade_date >= ?::DATE - INTERVAL 70 DAY ORDER BY d""", [d, *names, d]).df()
    rows = []
    if not ix.empty:
        ix["d"] = pd.to_datetime(ix["d"]).dt.date
        for name, gg in ix.groupby("name", sort=False):
            last = gg.iloc[-1]
            if last["d"] != d:
                continue
            rows.append({
                "name": name, "category": category, "close": clean(last["close_price"], 2),
                "ret_1d_pct": clean(last["return_1d_pct"], 2), "ret_1w_pct": clean(last["return_5d_pct"], 2),
                "ret_1m_pct": clean(last["return_20d_pct"], 2), "ret_3m_pct": clean(last["return_63d_pct"], 2),
                "vs_20ema_pct": clean(last["distance_ema_20_pct"], 2), "vs_50ema_pct": clean(last["distance_ema_50_pct"], 2),
                "trend_state": clean(last["trend_state"]), "new_52w_high": bool(clean(last["new_52w_high"]) or False),
                "close_history": [clean(v, 2) for v in gg["close_price"].tail(30)],
            })
    if not rows:
        return unavailable(d, f"no {category.lower()} index rows on {d.isoformat()} (index_daily history is short)",
                           ["index_daily"], level=category.lower())
    notes = []
    if all(r["ret_3m_pct"] is None for r in rows):
        notes.append("3M returns are empty: index_daily has too little history (data gap #3).")
    return Result(as_of=d, rows=rows, sources=["index_daily"], notes=notes,
                  extra={"level": category.lower(),
                         "data_warning": notes[0] if notes else None})


# --------------------------------------------------------------------------
# Stocks that moved
# --------------------------------------------------------------------------
def movers(as_of: date | None, kind: str = "gainers", min_mcap: float = MIN_MCAP_CR, n: int = MOVERS_N) -> Result:
    if kind not in MOVER_KINDS:
        raise ValueError(f"kind must be one of {MOVER_KINDS}")
    with db.market_conn() as con:
        d = db.resolve_as_of(con, as_of)
        if d is None:
            return no_session(as_of)
        df = _stock_frame(con, d)
        deal_syms = _deal_symbols(con, d)
    universe_all = len(df)
    df = df[df["mcap"].notna() & (df["mcap"] >= min_mcap)].copy()
    universe_floor = len(df)
    df = df[df["chg"].notna()]
    if kind == "rvol":
        df = df[(df["tov"] >= RVOL_MIN_TURNOVER_CR) & df["rvol"].notna()]
    key, asc = {"gainers": ("chg", False), "losers": ("chg", True), "turnover": ("tov", False),
                "delivered": ("dlv", False), "rvol": ("rvol", False)}[kind]
    df = df[df[key].notna()].sort_values([key, "symbol"], ascending=[asc, True]).head(n)
    rows = [shape_mover(r, d, deal_syms) for r in df.to_dict("records")]
    basis = sorted({r["mcap_basis"] for r in rows})
    notes = []
    if "latest" in basis:
        notes.append("Some market caps are the latest value, not the as-of value (no security_reference_daily row on or "
                     "before this date). Data gap #7.")
    return Result(as_of=d, rows=rows, sources=["indicators_daily", "security_reference_daily", "stocks_master", "deals"],
                  notes=notes,
                  extra={"kind": kind, "min_mcap_cr": min_mcap, "universe_all": universe_all,
                         "universe_floor": universe_floor,
                         "chips_missing": ["RES", "NEWS"],
                         "chip_rules": {"DEAL": f"bulk/block deal in the last {DEAL_SESSIONS} sessions",
                                        "52W": "fresh 52-week high", "IPO": "listed < 365 days before as-of",
                                        "BAND": "price band / surveillance remark", "EXT": "(close - 10 EMA) > 3 x ADR%"}})


def _stock_frame(con: Any, d: date) -> pd.DataFrame:
    has_ref = db.table_exists(con, "security_reference_daily")
    ref = """LEFT JOIN (SELECT symbol, arg_max(market_cap_cr, effective_date) AS mcap_ref
                        FROM security_reference_daily WHERE effective_date <= ? AND market_cap_cr IS NOT NULL
                        GROUP BY symbol) ref USING (symbol)""" if has_ref else ""
    params: list[Any] = [d] if has_ref else []
    mref = "ref.mcap_ref" if has_ref else "NULL"
    return con.execute(f"""
        SELECT i.symbol, sm.security_name AS name, sm.sector, sm.industry, i.series,
               {mref} AS mcap_ref, sm.market_cap_cr AS mcap_latest, sm.listing_date,
               i.close_price AS close, CASE WHEN i.prev_close > 0 THEN (i.close_price / i.prev_close - 1) * 100 END AS chg,
               i.return_5d_pct AS r5, i.return_1m_pct AS r21, i.turnover_cr AS tov,
               i.delivery_qty * i.close_price / 1e7 AS dlv, i.delivery_pct AS dp, i.avg_delivery_pct_20d AS dp20,
               i.rvol, i.rs_percentile AS rs, i.adr_20_pct AS adr, i.away_10ema_pct AS x10,
               i.is_fresh_52w_high AS h52, i.band_remarks AS band
        FROM indicators_daily i
        LEFT JOIN stocks_master sm USING (symbol)
        {ref}
        WHERE i.trade_date = ?""", [*params, d]).df().assign(
        mcap=lambda x: x["mcap_ref"].where(x["mcap_ref"].notna(), x["mcap_latest"]))


def _deal_symbols(con: Any, d: date) -> set[str]:
    if not db.table_exists(con, "deals"):
        return set()
    sess = db.recent_sessions(con, d, DEAL_SESSIONS)
    if not sess:
        return set()
    return {r[0] for r in con.execute("SELECT DISTINCT symbol FROM deals WHERE trade_date BETWEEN ? AND ?",
                                      [sess[-1], d]).fetchall()}


def chips_for(r: dict[str, Any], d: date, deal_syms: set[str]) -> list[str]:
    chips = []
    if r.get("symbol") in deal_syms:
        chips.append("DEAL")
    if clean(r.get("h52")):
        chips.append("52W")
    ld = db.to_date(r.get("listing_date"))
    if ld is not None and 0 <= (d - ld).days < 365:
        chips.append("IPO")
    band = (clean(r.get("band")) or "")
    if isinstance(band, str) and band.strip() not in ("", "-"):
        chips.append("BAND")
    adr, x10 = clean(r.get("adr")), clean(r.get("x10"))
    if adr and x10 is not None and adr > 0 and x10 / adr > 3:
        chips.append("EXT")
    return chips


def shape_mover(r: dict[str, Any], d: date, deal_syms: set[str]) -> dict[str, Any]:
    dp, dp20 = clean(r.get("dp")), clean(r.get("dp20"))
    band = clean(r.get("band"))
    return {
        "symbol": r["symbol"], "name": clean(r.get("name")), "sector": clean(r.get("sector")),
        "industry": clean(r.get("industry")), "series": clean(r.get("series")),
        "close": clean(r.get("close"), 2), "chg_1d_pct": clean(r.get("chg"), 2),
        "ret_1w_pct": clean(r.get("r5"), 2), "ret_1m_pct": clean(r.get("r21"), 2),
        "turnover_cr": clean(r.get("tov"), 2), "rvol": clean(r.get("rvol"), 2),
        "delivered_cr": clean(r.get("dlv"), 2), "delivery_pct": clean(dp, 1),
        "delivery_vs_20d": clean(dp / dp20, 2) if dp is not None and dp20 else None,
        "rs_percentile": clean(r.get("rs"), 0), "mcap_cr": clean(r.get("mcap"), 0),
        "mcap_basis": "as_of" if clean(r.get("mcap_ref")) is not None else "latest",
        "chips": chips_for(r, d, deal_syms),
        "band_remark": band.strip() if isinstance(band, str) and band.strip() not in ("", "-") else None,
    }
