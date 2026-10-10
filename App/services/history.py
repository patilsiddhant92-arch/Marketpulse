"""Trend over time: the Groups rotation grid. (The legacy Desk "vs last week" compare strip was removed
with the legacy Pulse Setups view in sprint 2.)

rotation(level, floor, weeks=12)
  Groups × the last `weeks` week-ends (the last stored session of each ISO week), each cell the
  group's Health, Health rank and RRG quadrant on that session. Ranked groups only (>= 3 members
  on the latest week), healthiest first.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from App.services import db, groups, universe
from App.services.common import Result, no_session, unavailable

MAX_WEEKS = 52


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
