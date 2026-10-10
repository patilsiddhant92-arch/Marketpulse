"""One group state for every tab: Favour / Neutral / Caution with one numeric reason.

Pulse owns it (HarkPro/07-tab-sector-intel.md §4.1, 11-implementation-plan.md "Backlog for the cross-tab pass").
Sector Intel, Setups and the Pulse groups table all read it from here, so the same group on the same date shows
the same state everywhere.

Universe: `group_daily`, floor 'all' (every stock, equal weight) — the same rows the Pulse groups table shows.
Rule (locked Tab 2 spec, 'Pulse -> Setups link'):
  Favour : >= 60% of members above the 50 EMA, beating the median group of the level over 21D, EW index above its 50 EMA.
  Caution: turnover share 5D avg < 85% of its 20D avg while the group fell over 5D (money leaving),
           or < 40% above the 50 EMA and lagging the median group over 63D.
  Neutral: everything else (and groups with too little history).
"Median group" is the median over the groups of the same level on the same session (point-in-time).
"""
from __future__ import annotations

import math
import threading
from datetime import date
from typing import Any

import pandas as pd

from App.services import db
from App.services.common import Result, no_session, unavailable

FAVOUR, NEUTRAL, CAUTION = "Favour", "Neutral", "Caution"
STATES = (FAVOUR, NEUTRAL, CAUTION)
STATE_ORDER = {FAVOUR: 0, NEUTRAL: 1, CAUTION: 2}
FLOOR = "all"
# api key -> group_daily.level
LEVELS: dict[str, str] = {
    "broad_sector": "Broad Sector",
    "sector": "Sector",
    "broad_industry": "Broad Industry",
    "industry": "Industry",
}
SOURCES = ["group_daily"]
RULE = ("Favour: >= 60% of members above the 50 EMA, beating the median group over 21D, EW index above its 50 EMA. "
        "Caution: turnover share 5D avg < 85% of its 20D avg while the group fell over 5D, or < 40% above the "
        "50 EMA and lagging the median group over 63D. Otherwise Neutral. Universe: all stocks (group_daily floor 'all').")
_LOCK = threading.Lock()


def _f(x: Any) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def rule(a50: float | None, x21: float | None, x63: float | None, r5: float | None,
         sh5: float | None, sh20: float | None, ew: float | None, ew50: float | None) -> tuple[str, str]:
    """The pure rule: (state, numeric reason). Inputs in percent / points; None = unknown."""
    a50, x21, x63, r5 = _f(a50), _f(x21), _f(x63), _f(r5)
    sh5, sh20, ew, ew50 = _f(sh5), _f(sh20), _f(ew), _f(ew50)
    if x21 is None or a50 is None:
        return NEUTRAL, "Not enough group history."
    if sh20 and sh5 is not None and sh5 < 0.85 * sh20 and (r5 or 0) < 0:
        return CAUTION, (f"Money leaving: turnover share {sh5:.2f}% vs {sh20:.2f}% 20D avg. "
                         f"Group {r5:+.1f}% in 5D.")
    if x21 > 0 and a50 >= 60 and ew is not None and ew50 is not None and ew > ew50:
        return FAVOUR, f"Trending: {a50:.0f}% of stocks above 50 EMA. {x21:+.1f} pts vs median group in 21D."
    if (x63 or 0) < 0 and a50 < 40:
        return CAUTION, f"Weak: {a50:.0f}% above 50 EMA. {x63:+.1f} pts vs median group in 63D."
    return NEUTRAL, f"{a50:.0f}% above 50 EMA. {x21:+.1f} pts vs median group in 21D."


def level_key(level: str | None) -> str:
    lv = str(level or "").strip().lower().replace(" ", "_")
    if lv not in LEVELS:
        raise ValueError(f"level must be one of {', '.join(LEVELS)}")
    return lv


def _compute_frame(con: Any, lv: str, as_of: date) -> pd.DataFrame:
    gd = con.execute("""
        SELECT trade_date d, group_name n, members, ret_ew_5d r5, ret_ew_21d r21, ret_ew_63d r63, pct_above_50ema a50,
               turnover_share_pct sh, turnover_share_5d_avg sh5, turnover_share_20d_avg sh20, ew_index ew, ew_index_ema50 ew50
        FROM group_daily WHERE level = ? AND floor = ? AND trade_date <= ? ORDER BY d, n""",
                     [LEVELS[lv], FLOOR, as_of]).df()
    if gd.empty:
        return gd
    gd["d"] = pd.to_datetime(gd["d"])
    gd["x21"] = gd.r21 - gd.groupby("d").r21.transform("median")
    gd["x63"] = gd.r63 - gd.groupby("d").r63.transform("median")
    st = [rule(*v) for v in zip(gd.a50, gd.x21, gd.x63, gd.r5, gd.sh5, gd.sh20, gd.ew, gd.ew50)]
    gd["state"] = [s[0] for s in st]
    gd["why"] = [s[1] for s in st]
    # consecutive sessions in the current state (runs per group)
    gd = gd.sort_values(["n", "d"]).reset_index(drop=True)
    run_id = (gd.state != gd.groupby("n").state.shift()).cumsum()
    gd["in_state"] = gd.groupby(run_id).cumcount() + 1
    gd["state_since"] = gd.groupby(run_id).d.transform("first")
    return gd.sort_values(["d", "n"]).reset_index(drop=True)


def frame(con: Any, as_of: date, level: str = "industry") -> pd.DataFrame:
    """Every session on or before as_of x every group of the level, with state / why / in_state.

    Columns: d (Timestamp), n (group name), members, r5, r21, r63, a50, sh, sh5, sh20, ew, ew50, x21, x63,
    state, why, in_state, state_since. Cached per (level, as_of)."""
    lv = level_key(level)
    with _LOCK:
        return db.cached("group_state.frame", (lv, as_of), lambda: _compute_frame(con, lv, as_of))


def states_on(con: Any, as_of: date, level: str = "industry") -> dict[str, tuple[str, str]]:
    """{group name: (state, reason)} on the as_of session (empty when the session has no group rows)."""
    gd = frame(con, as_of, level)
    if gd.empty:
        return {}
    t = gd[gd.d == pd.Timestamp(as_of)]
    return {n: (s, w) for n, s, w in zip(t.n, t.state, t.why)}


def lookup(as_of: date | None, level: str = "industry") -> tuple[date | None, dict[str, tuple[str, str]]]:
    """Resolve as_of and return (resolved, {group: (state, reason)}). Opens its own connection."""
    with db.market_conn() as con:
        d = db.resolve_as_of(con, as_of)
        if d is None or not db.table_exists(con, "group_daily"):
            return d, {}
        return d, states_on(con, d, level)


def group_state(as_of: date | None, level: str = "industry", groups: list[str] | None = None) -> Result:
    """Public service behind GET /api/v2/pulse/group-state."""
    lv = level_key(level)
    with db.market_conn() as con:
        d = db.resolve_as_of(con, as_of)
        if d is None:
            return no_session(as_of)
        if not db.table_exists(con, "group_daily"):
            return unavailable(d, "group_daily missing", SOURCES, level=lv)
        gd = frame(con, d, lv)
    t = gd[gd.d == pd.Timestamp(d)] if not gd.empty else gd
    if t.empty:
        return unavailable(d, f"no {LEVELS[lv]} rows in group_daily on {d.isoformat()}", SOURCES, level=lv)
    if groups:
        want = set(groups)
        t = t[t.n.isin(want)]
    rows = []
    for r in t.itertuples():
        rows.append({
            "id": f"{lv}:{r.n}", "level": lv, "group_name": r.n, "state": r.state, "reason": r.why,
            "members": None if pd.isna(r.members) else int(r.members),
            "pct_above_50ema": db.num(r.a50, 1), "vs_median_21d": db.num(r.x21, 2), "vs_median_63d": db.num(r.x63, 2),
            "ret_5d_pct": db.num(r.r5, 2), "share_5d_pct": db.num(r.sh5, 3), "share_20d_pct": db.num(r.sh20, 3),
            "ew_above_ema50": None if _f(r.ew) is None or _f(r.ew50) is None else bool(r.ew > r.ew50),
            "sessions_in_state": int(r.in_state), "state_since": pd.Timestamp(r.state_since).date().isoformat(),
        })
    rows.sort(key=lambda x: (STATE_ORDER[x["state"]], x["group_name"]))
    split = {s: sum(1 for x in rows if x["state"] == s) for s in STATES}
    return Result(as_of=d, rows=rows, sources=SOURCES, notes=[RULE],
                  extra={"level": lv, "level_label": LEVELS[lv], "floor": FLOOR, "split": split, "rule": RULE,
                         "owner": "pulse"})
