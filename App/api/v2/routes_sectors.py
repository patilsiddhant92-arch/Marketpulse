"""Sector Intel endpoints (HarkPro/07-tab-sector-intel.md). Thin: validate -> App.services.sectors -> envelope.

Mounted on the v2 router at import (App/api/v2/__init__.py imports this module). Group ids travel as a query
parameter (`id=<level>:<name>`) because taxonomy names can contain '/' and ','.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from fastapi import APIRouter, Query

from App.api.v2.routes import AsOf, Limit, Offset, V2Route, _call, envelope, router as v2_router
from App.services import sectors

router = APIRouter(prefix="/sectors", route_class=V2Route, tags=["sectors"])

BoardLevel = Literal["sector", "broad_industry", "industry", "index"]
TaxLevel = Literal["sector", "broad_industry", "industry"]


@router.get("/board", description="Sector Intel leadership board at one level (Sector / Broad Industry / Industry / Index). "
            "Rows carry every window (1D/1W/2W/1M) and each reading's percentile vs the group's own ~2 years; "
            "meta.context carries the Pulse mood, the 'working now' gauge and the verdict.")
def sectors_board(as_of: Optional[date] = AsOf, level: BoardLevel = "broad_industry", offset: int = Offset,
                  limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(sectors.board, as_of, level), offset, limit)


@router.get("/context", description="Pulse mood + 'Is group ranking working now?' gauge + plain-English verdict.")
def sectors_context(as_of: Optional[date] = AsOf, level: BoardLevel = "broad_industry") -> dict[str, Any]:
    return envelope(_call(sectors.context, as_of, level))


@router.get("/charts", description="Equal-weight group candles, RS line vs the equal-weight market and % near 52W high "
            "for up to 12 groups (the 9-card chart grid and the group panel).")
def sectors_charts(as_of: Optional[date] = AsOf, id: list[str] = Query(..., max_length=160),
                   bars: int = Query(sectors.CHART_BARS, ge=20, le=400)) -> dict[str, Any]:
    return envelope(_call(sectors.charts, as_of, id, bars))


@router.get("/members", description="Members of one group (>= Rs 1,000 Cr) by RS, with 52W-high distance and deals 10D.")
def sectors_members(as_of: Optional[date] = AsOf, id: str = Query(..., max_length=160), offset: int = Offset,
                    limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(sectors.members, as_of, id), offset, limit)


@router.get("/heatmap", description="TradingView-style stock heatmap rows: every stock with its size and colour metrics.")
def sectors_heatmap(as_of: Optional[date] = AsOf, offset: int = Offset, limit: int = Query(5000, ge=1, le=5000)) -> dict[str, Any]:
    return envelope(_call(sectors.heatmap, as_of), offset, limit)


@router.get("/group-studies", description="Group studies (moved here from Research): evidence-engine tables when built, "
            "plus the local Sector Intel readings / market-state evidence in meta.context.")
def sectors_group_studies(as_of: Optional[date] = AsOf, level: TaxLevel = "broad_industry", offset: int = Offset,
                          limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(sectors.group_studies, as_of, level), offset, limit)


v2_router.include_router(router)
