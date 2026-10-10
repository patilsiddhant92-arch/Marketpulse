"""Pulse tab endpoints (HarkPro/02-tab1-pulse.md §11). Mounted under /api/v2 by App/api/v2/__init__.py.

Thin: validate -> App.services.pulse -> v2 envelope (rows + meta.context).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from fastapi import APIRouter, Query

from App.api.v2 import models as m
from App.api.v2.routes import AsOf, V2Route, _call, envelope
from App.services import pulse

router = APIRouter(prefix="/pulse", route_class=V2Route, tags=["pulse"])

Row = m.Envelope[dict[str, Any]]
Lookback = Query(5, description="Compare with: 5, 10, 20 (1M), 60 (3M) or 250 (1Y) sessions")
Sessions = Query(None, ge=2, le=2000, description="Sessions of series to return (default depends on lookback)")


@router.get("/summary", response_model=Row,
            description="Mood score (0-100, average archive percentile of six readings), label, direction qualifier, "
                        "commentary sentences, the What-to-do action, History Lab line and breadth flags.")
def pulse_summary(as_of: Optional[date] = AsOf, lookback: int = Lookback) -> dict[str, Any]:
    return envelope(_call(pulse.summary, as_of, lookback))


@router.get("/breadth", response_model=Row,
            description="Per session: % and count of stocks above the 10/20/50/100/200 EMA, daily change, 60-day sigma, "
                        "unusual-move and expansion/contraction flags, point-in-time percentile. meta.context.stats: "
                        "archive min/max/p10/p90, lookback delta and the flag thresholds.")
def pulse_breadth(as_of: Optional[date] = AsOf, sessions: Optional[int] = Sessions,
                  lookback: int = Lookback) -> dict[str, Any]:
    return envelope(_call(pulse.breadth, as_of, sessions, lookback))


@router.get("/internals", response_model=Row,
            description="Six market internals cards: value, change vs lookback average, archive percentile, series.")
def pulse_internals(as_of: Optional[date] = AsOf, sessions: Optional[int] = Sessions,
                    lookback: int = Lookback) -> dict[str, Any]:
    return envelope(_call(pulse.internals, as_of, sessions, lookback))


@router.get("/expansions", response_model=Row,
            description="Latest breadth expansion / contraction days with next 10/20-session equal-weight returns; "
                        "meta.context.stats per 20/50/200 EMA.")
def pulse_expansions(as_of: Optional[date] = AsOf, limit: int = Query(8, ge=1, le=200)) -> dict[str, Any]:
    return envelope(_call(pulse.expansions, as_of, limit))


@router.get("/flow", response_model=Row,
            description="Market turnover / delivered value per session (all stocks) with 20-day average; "
                        "meta.context.headline and meta.context.sectors (share, change in share, returns).")
def pulse_flow(as_of: Optional[date] = AsOf, sessions: Optional[int] = Query(None, ge=2, le=250),
               lookback: int = Lookback) -> dict[str, Any]:
    return envelope(_call(pulse.flow, as_of, sessions, lookback))


@router.get("/groups", response_model=Row,
            description="Groups table: sector / industry (group_daily, all stocks, equal weight) or the official NSE "
                        "sectoral / thematic indices (index_daily).")
def pulse_groups(as_of: Optional[date] = AsOf,
                 level: Literal["sector", "industry", "sectoral", "thematic"] = "sector") -> dict[str, Any]:
    return envelope(_call(pulse.groups, as_of, level))


@router.get("/movers", response_model=Row,
            description="Top 20 stocks that moved (market cap >= min_mcap on the as-of date) with event chips.")
def pulse_movers(as_of: Optional[date] = AsOf,
                 kind: Literal["gainers", "losers", "turnover", "delivered", "rvol"] = "gainers",
                 min_mcap: float = Query(1000.0, ge=0)) -> dict[str, Any]:
    return envelope(_call(pulse.movers, as_of, kind, min_mcap))


@router.get("/analogs", response_model=Row,
            description="Days like today: nearest past sessions (excluding the latest 25) and their next 10/20-session "
                        "equal-weight returns. Shared with History Lab.")
def pulse_analogs(as_of: Optional[date] = AsOf, k: int = Query(8, ge=1, le=30)) -> dict[str, Any]:
    return envelope(_call(pulse.analogs, as_of, k))
