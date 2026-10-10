"""Research Case study: the D / W / M trait strip (10-tab-research.md §§12-13).

For one stock, which of the "Before the big moves" traits were on, week by week, in the 13 weeks before its
early lift, and at the lift itself.

- Lift: the stock's early lift (research_premove: close >= 20% above its 120-session low, first time in 60
  sessions). The lift shown is the first one inside the case-study move (12-month low -> peak, as
  research_bigmove); else the move's own lift (its first close >= 20% above the move's low - the moment you
  would notice it); else the latest early lift. With none the strip is anchored on the study end.
- Family: Turnaround (close below the 200 EMA at the lift) or Trend (above), as in View 3.
- Traits and cuts: every trait of that family's runner-vs-fizzle profile (research_premove.profile on the
  past lifts whose 120-session outcome closed by the study end). A trait is "on" when its value sits in the
  better third (>= the high cut when runners had it high, <= the low cut when low). The score traits
  (the family's 8 best) are flagged.
- Columns: 14 weekly checkpoints, the lift session and the 13 checkpoints 5, 10 ... 65 sessions before it.
  Each value uses data on or before its own session (research_premove.trait_frame).

Honesty: the cuts come from every resolved lift up to the study end, so for a past lift they are partly
in-sample (later lifts shaped them). The strip describes; it does not predict.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from App.services import db
from App.services import research_bigmove as bigmove
from App.services import research_lab as lab
from App.services import research_premove as premove
from App.services.common import Result, no_session, unavailable

WEEKS = 13
STEP = 5  # sessions per week
GROUPS = {"D": "Daily", "W": "Weekly", "M": "Monthly", "A": "Accumulation", "I": "Improvement", "B": "Base"}
GROUP_ORDER = list(GROUPS)


def _is_on(v: Any, side: str, cut_low: Any, cut_high: Any) -> bool | None:
    if v is None or (isinstance(v, float) and not np.isfinite(v)) or pd.isna(v):
        return None
    if side == "high":
        return bool(v >= cut_high) if cut_high is not None else None
    return bool(v <= cut_low) if cut_low is not None else None


def _family_profile(E: pd.DataFrame, end: date, all_days: list[date], family: str) -> tuple[list[dict[str, Any]], float | None, int]:
    E = E[E.trade_date <= pd.Timestamp(end)].copy()
    idx = {pd.Timestamp(x): i for i, x in enumerate(all_days)}
    ei = len(all_days) - 1
    si = E.trade_date.map(idx)
    E["resolved"] = (ei - si >= premove.HORIZON) & E.outcome.notna()
    study = E[(E.family == family) & E.resolved & E.outcome.isin(["runner", "fizzle"])].copy()
    study["runner"] = study.outcome == "runner"
    base = float(study.runner.mean() * 100) if len(study) else None
    return premove.profile(study), base, int(len(study))


def pick_lift(d: pd.DataFrame, events: pd.DataFrame, move: dict[str, Any] | None) -> tuple[int | None, str]:
    """(row index, why): the first early lift inside the move; else the move's own lift (the first close
    >= 20% above the move's low, after it); else the latest early lift; else None."""
    if move:
        inside = events[(events.trade_date >= move["low_date"]) & (events.trade_date <= move["peak_date"])]
        if len(inside):
            return int(inside.index[0]), "first early lift inside the move"
        after = d[(d.trade_date > move["low_date"]) & (d.trade_date <= move["peak_date"]) &
                  (d.close_price >= premove.LIFT * move["low"])]
        if len(after) and int(after.index[0]) >= premove.WARMUP:
            return int(after.index[0]), "first close 20% above the move's low"
    if len(events):
        return int(events.index[-1]), "latest early lift"
    return None, "none"


@lab.memo("trait_strip")
def trait_strip(as_of: date | None, symbol: str) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        end = lab.study_end(con, resolved)
        full_end = lab.study_end(con, None) or end
        if end is None:
            return no_session(as_of)
        x = lab.load_frame(con, end, symbols=[symbol])
        E, source = premove.events(con, full_end)
        all_days = [d for d in lab.sessions(con) if d <= end]
    if x.empty:
        return unavailable(end, f"no price history for {symbol} on or before {end.isoformat()}", ["indicators_daily"],
                           caveat=lab.CAVEAT)
    d, T, pos = premove.trait_frame(x)
    if len(d) < premove.WARMUP:
        return unavailable(end, f"{symbol} has {len(d)} sessions (the traits need {premove.WARMUP})", ["indicators_daily"],
                           caveat=lab.CAVEAT)
    ev = d[d.event & (pos >= premove.WARMUP)]
    move = bigmove._move(d, bigmove.window_start(end))
    lift, why = pick_lift(d, ev, move)
    li = lift if lift is not None else int(d.index[-1])
    anchor = d.trade_date[li]
    family_val = T["d_above_200ema"].iat[li]
    family = None if pd.isna(family_val) else ("turnaround" if family_val < 0 else "trend")
    if family is None:
        return unavailable(end, f"{symbol} has no 200 EMA at {anchor:%d %b %Y}", ["indicators_daily"], caveat=lab.CAVEAT)
    prof, base, n_study = _family_profile(E, end, all_days, family)
    if not prof:
        return unavailable(end, f"not enough resolved {family} lifts to set the trait cuts", ["indicators_daily"],
                           caveat=lab.CAVEAT)
    picks = {p["trait"] for p in premove.pick_traits(prof)}
    cols = [li - STEP * k for k in range(WEEKS, -1, -1) if li - STEP * k >= 0]
    col_dates = [d.trade_date[i] for i in cols]
    labels = [("lift" if lift is not None else "now") if i == li else f"-{(li - i) // STEP}w" for i in cols]
    rows: list[dict[str, Any]] = []
    order = {g: n for n, g in enumerate(GROUP_ORDER)}
    for p in sorted(prof, key=lambda r: (order.get(r["group"], 9), -r["lift"])):
        k = p["trait"]
        vals = [lab.rnd(T[k].iat[i], 2) for i in cols]
        on = [_is_on(v, p["better_when"], p["cut_low"], p["cut_high"]) for v in vals]
        before = on[:-1]
        rows.append({"trait": k, "label": p["label"][3:], "group": p["group"], "group_label": GROUPS.get(p["group"], p["group"]),
                     "better_when": p["better_when"], "cut": p["cut_high"] if p["better_when"] == "high" else p["cut_low"],
                     "lift": p["lift"], "score_trait": k in picks, "values": vals, "on": on,
                     "on_at_lift": on[-1], "weeks_on": int(sum(1 for o in before if o)),
                     "weeks_known": int(sum(1 for o in before if o is not None)),
                     "runner_median": p["runner_median"], "fizzle_median": p["fizzle_median"]})
    groups = []
    for g in GROUP_ORDER:
        gr = [r for r in rows if r["group"] == g]
        if not gr:
            continue
        groups.append({"group": g, "label": GROUPS[g], "traits": len(gr),
                       "on": [int(sum(1 for r in gr if r["on"][j])) for j in range(len(cols))]})
    score = [int(sum(1 for r in rows if r["score_trait"] and r["on"][j])) for j in range(len(cols))]
    at = {g["group"]: g["on"][-1] for g in groups}
    tot = {g["group"]: g["traits"] for g in groups}
    fam_label = premove.FAMILIES[family]["label"]
    summary = []
    if lift is not None:
        summary.append(f"{symbol} made a {fam_label[:-1].lower()} on {anchor:%d %b %Y} at {float(d.close_price[li]):,.1f} "
                       f"({why}).")
    else:
        summary.append(f"{symbol} made no early lift with enough history. The strip shows the last 13 weeks to "
                       f"{anchor:%d %b %Y}.")
    summary.append("At the " + ("lift" if lift is not None else "latest session") + ": " +
                   ", ".join(f"{at[g]} of {tot[g]} {GROUPS[g].lower()}" for g in ("D", "W", "M") if g in at) +
                   " traits were on.")
    summary.append(f"Score traits on: {score[-1]} of {len(picks)} (13 weeks earlier: {score[0]}).")
    if base is not None:
        summary.append(f"Past {fam_label.lower()} became runners {base:.0f}% of the time (n = {n_study}).")
    ctx = {"caveat": lab.CAVEAT, "study_end": end, "source": source, "symbol": symbol,
           "lift": {"date": anchor, "close": lab.rnd(d.close_price[li], 2), "found": lift is not None, "why": why,
                    "family": family, "family_label": fam_label},
           "move": {k: lab.clean(v) for k, v in move.items()} if move else None,
           "columns": [{"date": dt, "label": lb} for dt, lb in zip(col_dates, labels)],
           "groups": groups, "score": score, "score_max": len(picks), "family_base_runner_pct": lab.rnd(base),
           "family_events": n_study, "summary": summary,
           "definition": ("A trait is on when its value sits in the better third of past "
                          f"{fam_label.lower()} (runners vs fizzles). Columns are weekly (every 5 sessions) up to the lift."),
           "in_sample_note": ("The cuts use every resolved lift to the study end, so for a past lift they are partly "
                              "in-sample. Read the strip as a description, not a forecast.")}
    return Result(as_of=end, rows=rows, sources=["indicators_daily"], extra=ctx)
