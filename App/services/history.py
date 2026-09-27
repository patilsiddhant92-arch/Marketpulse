"""Trend over time: Desk "vs last week" and the Groups rotation grid.

compare(sessions=5)
  Now vs N sessions ago (both real stored sessions): Desk queue counts (setup_daily), breadth and
  the verdict (regime_daily), and the top industry groups by Health (group_daily / live frame):
  which entered and which left the top list. Nothing is interpolated: a missing session or table
  leaves that line NULL.

rotation(level, floor, weeks=12)
  Groups × the last `weeks` week-ends (the last stored session of each ISO week), each cell the
  group's Health, Health rank and RRG quadrant on that session. Ranked groups only (>= 3 members
  on the latest week), healthiest first.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from App.services import db, desk, groups, universe
from App.services.common import STATUS_PARTIAL, Result, no_session, unavailable

TOP_GROUPS = 10
MAX_WEEKS = 52
BREADTH = [
    ("above_50ema_pct", "Above 50 EMA", "pct", "up"),
    ("above_200ema_pct", "Above 200 EMA", "pct", "up"),
    ("net_new_highs", "Net new highs", "int", "up"),
    ("advancers", "Advancers", "int", "up"),
]


def _regime(con: Any, d: date) -> dict[str, Any]:
    if not db.table_exists(con, "regime_daily"):
        return {}
    cols = set(db.table_columns(con, "regime_daily"))
    want = [c for c in ("verdict", "verdict_guidance", *(b[0] for b in BREADTH)) if c in cols]
    if not want:
        return {}
    r = db.records(con, f"SELECT {', '.join(want)} FROM regime_daily WHERE trade_date = ?", [d])
    return r[0] if r else {}


def _queue_counts(con: Any, d: date) -> dict[str, int] | None:
    if not db.table_exists(con, "setup_daily"):
        return None
    rows = con.execute("SELECT queue, count(DISTINCT symbol) FROM setup_daily WHERE trade_date = ? GROUP BY 1", [d]).fetchall()
    if not rows and not con.execute("SELECT 1 FROM setup_daily WHERE trade_date = ? LIMIT 1", [d]).fetchone():
        return None
    got = {str(q): int(n) for q, n in rows}
    return {q: got.get(q, 0) for q in desk.QUEUES}


def _top_groups(long: pd.DataFrame | None, d: date, n: int = TOP_GROUPS) -> list[dict[str, Any]]:
    if long is None or long.empty or "health_rank" not in long.columns:
        return []
    day = long[long["trade_date"] == pd.Timestamp(d)]
    day = day[pd.to_numeric(day["health_rank"], errors="coerce").notna()].sort_values("health_rank").head(n)
    return [{"id": groups.group_id("industry", str(r["group_name"])), "group_name": str(r["group_name"]),
             "health": db.num(r.get("health"), 1), "health_rank": db.integer(r.get("health_rank")),
             "rrg_quadrant": db.text(r.get("rrg_quadrant"))} for r in day.to_dict("records")]


def _row(key: str, label: str, unit: str, better: str | None, now: Any, then: Any, group: str) -> dict[str, Any]:
    now_v, then_v = db.num(now, 2), db.num(then, 2)
    return {"key": key, "label": label, "group": group, "unit": unit, "better": better, "now": now_v, "then": then_v,
            "delta": db.num(now_v - then_v, 2) if now_v is not None and then_v is not None else None}


def compare(as_of: date | None, sessions: int = 5) -> Result:
    sessions = max(1, min(int(sessions), 60))
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        then = db.session_back(con, resolved, sessions)
        if then is None:
            return unavailable(resolved, f"no session {sessions} back from {resolved.isoformat()}", ["indicators_daily"])
        rn, rt = _regime(con, resolved), _regime(con, then)
        qn, qt = _queue_counts(con, resolved), _queue_counts(con, then)
        long = groups._long(con, resolved, "industry", "1000") if db.table_exists(con, "group_daily") else None
    rows: list[dict[str, Any]] = []
    for name, meta in desk.QUEUES.items():
        rows.append(_row(f"queue_{name}", meta["label"], "int", None, (qn or {}).get(name), (qt or {}).get(name), "Queues"))
    for key, label, unit, better in BREADTH:
        rows.append(_row(key, label, unit, better, rn.get(key), rt.get(key), "Breadth"))
    top_now, top_then = _top_groups(long, resolved), _top_groups(long, then)
    ids_now, ids_then = {g["id"] for g in top_now}, {g["id"] for g in top_then}
    then_rank = {}
    if long is not None and not long.empty and "health_rank" in long.columns:
        d0 = long[long["trade_date"] == pd.Timestamp(then)]
        then_rank = {groups.group_id("industry", str(r["group_name"])): db.integer(r["health_rank"]) for r in d0.to_dict("records")}
    for g in top_now:
        g["health_rank_then"] = then_rank.get(g["id"])
        g["new"] = g["id"] not in ids_then
    missing = [s for s, ok in (("regime_daily", bool(rn and rt)), ("setup_daily", qn is not None and qt is not None),
                               ("group_daily", bool(top_now and top_then))) if not ok]
    return Result(
        as_of=resolved, rows=rows, status=STATUS_PARTIAL if missing else "ok",
        reason=f"missing on one of the two sessions: {', '.join(missing)}" if missing else None,
        sources=["setup_daily", "regime_daily", "group_daily"],
        extra={"sessions": sessions, "then_date": then,
               "verdict_now": db.text(rn.get("verdict")), "verdict_then": db.text(rt.get("verdict")),
               "top_groups_now": top_now, "top_groups_then": top_then,
               "groups_entered": [g for g in top_now if g["id"] not in ids_then],
               "groups_left": [g for g in top_then if g["id"] not in ids_now]},
        notes=[f"Top {TOP_GROUPS} industry groups by Health at the ₹1,000 Cr floor on each session."],
        metric_keys=["group_health"])


def week_ends(dates: list[pd.Timestamp], weeks: int) -> list[pd.Timestamp]:
    """Last available session of each ISO week, the most recent `weeks` of them, oldest first. Pure."""
    if not dates:
        return []
    s = pd.Series(sorted(set(dates)))
    iso = s.dt.isocalendar()
    key = iso["year"].astype(int) * 100 + iso["week"].astype(int)
    last = s.groupby(key.to_numpy()).max().sort_values()
    return list(last.tail(weeks))


def rotation(as_of: date | None, level: str = "industry", floor: str = "1000", weeks: int = 12) -> Result:
    level_key = universe.level_key(level)
    if level_key is None:
        raise ValueError(f"unknown level {level!r}")
    groups.floor_value(floor)
    weeks = max(2, min(int(weeks), MAX_WEEKS))
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        long = groups._long(con, resolved, level_key, floor) if db.table_exists(con, "group_daily") else None
        members = None
        if long is not None and not long.empty:
            df, _ = groups._frame(con, resolved, level_key, floor)
            last, _ = groups._last_rows(df, resolved)
            members = {str(r["group_name"]): db.integer(r.get("stocks")) for r in last.to_dict("records")}
    if long is None or long.empty or "health" not in long.columns:
        return unavailable(resolved, "group_daily (with Health history) is needed for the rotation grid", ["group_daily"],
                           weeks=[])
    long = long[long["trade_date"] <= pd.Timestamp(resolved)]
    ends = week_ends(list(long["trade_date"].unique()), weeks)
    grid = long[long["trade_date"].isin(ends)]
    latest = grid[grid["trade_date"] == ends[-1]]
    ranked = latest[pd.to_numeric(latest["health_rank"], errors="coerce").notna()]
    order = ranked.sort_values("health_rank")["group_name"].astype(str).tolist()
    by = {(str(r["group_name"]), pd.Timestamp(r["trade_date"])): r for r in grid.to_dict("records")}
    rows = []
    for name in order:
        cells = []
        for d in ends:
            r = by.get((name, pd.Timestamp(d)))
            cells.append({"week_end": db.to_date(d), "health": db.num(r.get("health"), 1) if r else None,
                          "health_rank": db.integer(r.get("health_rank")) if r else None,
                          "rrg_quadrant": db.text(r.get("rrg_quadrant")) if r else None})
        hs = [c["health"] for c in cells if c["health"] is not None]
        rows.append({"id": groups.group_id(level_key, name), "group_name": name, "level": level_key,
                     "stocks": (members or {}).get(name), "health_now": cells[-1]["health"],
                     "health_change": db.num(hs[-1] - hs[0], 1) if len(hs) >= 2 else None, "cells": cells})
    return Result(as_of=resolved, rows=rows, sources=["group_daily"],
                  extra={"level": level_key, "floor": floor, "weeks": [db.to_date(d) for d in ends],
                         "rule": "cell = Health on the last stored session of each week; ranked groups (>= 3 members)"},
                  metric_keys=["group_health"])
