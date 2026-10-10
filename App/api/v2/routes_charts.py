"""Charts tab endpoints (HarkPro/09-tab-charts.md). Read-only; registered from App/api/v2/__init__.py."""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from App.api.v2 import models as m
from App.api.v2.routes import AsOf, V2Route, _call, envelope, symbol_param
from App.api.v2.routes import router as v2_router
from App.services import charts

# No prefix: included into the /api/v2 router below.
router = APIRouter(route_class=V2Route)


class DealCandleRow(BaseModel):
    trade_date: Optional[date] = None
    letter: Optional[str] = None
    kind: Optional[str] = None
    label: Optional[str] = None
    event_type: Optional[str] = None
    event_rule: Optional[str] = None
    net_cr: Optional[float] = None
    buy_cr: Optional[float] = None
    sell_cr: Optional[float] = None
    gross_cr: Optional[float] = None
    prop_cr: Optional[float] = None
    fii_net_cr: Optional[float] = None
    dii_net_cr: Optional[float] = None
    buying_houses: Optional[int] = None
    selling_houses: Optional[int] = None
    deal_types: Optional[str] = None
    deal_price: Optional[float] = None
    deal_price_adj: Optional[float] = None
    top_buyer: Optional[str] = None
    top_buyer_class: Optional[str] = None
    top_buyer_cr: Optional[float] = None
    top_seller: Optional[str] = None
    top_seller_class: Optional[str] = None
    top_seller_cr: Optional[float] = None
    close_as_of: Optional[float] = None
    status: Optional[str] = None
    show_line: Optional[bool] = None


@router.get("/charts/{sym}/deal-candles", response_model=m.Envelope[DealCandleRow],
            description="Deal-day candles for one stock: one row per deal session (B/S/P/T/C letter from "
                        "deal_session_net.event_type), deal price (raw and adjusted), top non-PROP buyer / seller, "
                        "and holding / lost status for the 3 latest B/S/P deal-price lines.")
def chart_deal_candles(sym: str, as_of: Optional[date] = AsOf,
                       limit: int = Query(2000, ge=1, le=5000)) -> dict[str, Any]:
    res = _call(charts.deal_candles, as_of, symbol_param(sym))
    # Newest sessions matter most: page from the end, keep oldest-first order.
    if res.rows and len(res.rows) > limit:
        res.rows = res.rows[-limit:]
    return envelope(res, 0, limit)


class SymbolSearchRow(BaseModel):
    symbol: Optional[str] = None
    security_name: Optional[str] = None
    industry: Optional[str] = None
    market_cap_cr: Optional[float] = None


@router.get("/charts/search", response_model=m.Envelope[SymbolSearchRow],
            description="Symbol / company-name search for the chart symbol box (exact symbol, symbol prefix, "
                        "name prefix, then contains; ties by market cap).")
def chart_search(q: str = Query(..., min_length=1, max_length=40), as_of: Optional[date] = AsOf,
                 limit: int = Query(12, ge=1, le=charts.SEARCH_MAX)) -> dict[str, Any]:
    return envelope(_call(charts.search_symbols, as_of, q, limit), 0, limit)


# Mounted on the main v2 router when App.api.v2 imports this module (one line in __init__.py).
v2_router.include_router(router)
