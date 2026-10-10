"""RSI divergence endpoints (HarkPro/12-sprint2-plan.md "Divergence API contract"). Read-only.

GET /api/v2/charts/{sym}/divergences?tf=D|W|M&as_of=          every divergence of one stock (chart lines)
GET /api/v2/setups/divergences?tf=&side=&types=&window=&as_of=  recently confirmed, >= Rs 1,000 Cr universe
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from fastapi import APIRouter, Path, Query
from pydantic import BaseModel

from App.api.v2 import models as m
from App.api.v2.routes import AsOf, Limit, Offset, V2Route, _call, envelope, symbol_param
from App.api.v2.routes import router as v2_router
from App.services import divergence

Side = Literal["bull", "bear"]
DivType = Literal["Strong", "Medium", "Weak", "Hidden"]
DivStatus = Literal["watching", "triggered", "failed"]
Tf = Literal["D", "W", "M"]


class DivergenceRow(BaseModel):
    side: Side
    type: DivType
    p1_date: date
    p2_date: date
    p1_price: float
    p2_price: float
    p1_rsi: float
    p2_rsi: float
    confirm_date: date
    trigger_price: float
    stop_price: float
    status: DivStatus
    status_date: Optional[date] = None
    bars_apart: int
    tf: Tf


class DivergenceScanRow(DivergenceRow):
    symbol: str
    name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    group: Optional[str] = None
    market_cap_cr: Optional[float] = None
    bars_since_confirm: int
    close: Optional[float] = None
    distance_to_trigger_pct: Optional[float] = None
    risk_pct: Optional[float] = None
    rsi: Optional[float] = None
    group_state: Optional[str] = None
    group_reason: Optional[str] = None


router = APIRouter(route_class=V2Route, tags=["divergences"])

TfQ = Query("D", description="Bar timeframe: D (daily), W (W-FRI weeks), M (calendar months); W/M use completed bars only")


@router.get("/charts/{sym}/divergences", response_model=m.Envelope[DivergenceRow],
            description="RSI(14) divergences of one stock on D/W/M bars up to as_of, oldest confirm first: 8 types "
                        "(Strong/Medium/Weak/Hidden x bull/bear), 3-bar pivots confirmed 3 bars later (no look-ahead), "
                        "trigger / stop and status (watching / triggered / failed) as of the date. meta.context.rules "
                        "spells out the rules.")
def chart_divergences(sym: str = Path(..., description="NSE symbol"), tf: Tf = TfQ,
                      as_of: Optional[date] = AsOf) -> dict[str, Any]:
    return envelope(_call(divergence.chart_divergences, as_of, symbol_param(sym), tf))


@router.get("/setups/divergences", response_model=m.Envelope[DivergenceScanRow],
            description="Divergences confirmed in the last `window` bars (default 5; 1 = on the as-of bar) across the "
                        ">= Rs 1,000 Cr universe, with industry group + Pulse group state, distance to trigger and RSI. "
                        "meta.context.counts has the count per side:type before the side/types/status filters.")
def setups_divergences(
    tf: Tf = TfQ,
    side: Optional[Side] = Query(None, description="bull or bear (default both)"),
    types: Optional[str] = Query(None, description="Comma list of Strong, Medium, Weak, Hidden (default all)"),
    status: Optional[str] = Query(None, description="Comma list of watching, triggered, failed (default all)"),
    window: int = Query(divergence.WINDOW_DEFAULT, ge=1, le=60, description="Confirmed within the last N bars of tf"),
    as_of: Optional[date] = AsOf,
    offset: int = Offset,
    limit: int = Limit,
) -> dict[str, Any]:
    tlist = [t for t in (types or "").split(",") if t.strip()]
    slist = [s for s in (status or "").split(",") if s.strip()]
    return envelope(_call(divergence.scan, as_of, tf, side, tlist, window, slist), offset, limit)


# Mounted on the main v2 router when App.api.v2 imports this module (one line in __init__.py).
v2_router.include_router(router)
