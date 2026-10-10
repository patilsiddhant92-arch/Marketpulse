"""Deals tab endpoints (HarkPro/08-tab-deals.md, mockup v1.2). Thin: validate -> App/services/deals_tab -> envelope.

Tab views live under /api/v2/deals/tab/*. Two read-only cross-tab feeds for the integration pass:
  GET /api/v2/deals/markers/{sym}   per-symbol deal markers (date, side B/S/P/T/C, price) for chart deal candles
  GET /api/v2/deals/flags           per-symbol "has recent deal" flag (+ verdict) for the cross-tab deal icon
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Path, Query

from App.api.v2 import models_deals as md
from App.api.v2.models import Envelope
from App.api.v2.routes import AsOf, Limit, Offset, V2Route, _call, envelope, symbol_param
from App.services import deals_tab

# No prefix: App/api/v2/__init__.py includes this router into the /api/v2 router.
router = APIRouter(route_class=V2Route, tags=["deals-tab"])
MAX_FLAG_SYMBOLS = 500


@router.get("/deals/tab/today", response_model=Envelope[md.DealTabRow],
            description="Every deal stock (>= ₹1,000 Cr) of the latest deal session with its evidence "
            "verdict, 'what usually follows', deal price, status and chips. Sorted by verdict. meta.context: summary, skipped.")
def tab_today(as_of: Optional[date] = AsOf, offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(deals_tab.today, as_of), offset, limit)


@router.get("/deals/tab/watch", response_model=Envelope[md.DealTabRow],
            description="Deal watch: one row per stock with a deal in the last 10 deal sessions (no churn / "
            "transfers): holding / lost / reclaimed vs the deal price, verdict upgraded after day 3.")
def tab_watch(as_of: Optional[date] = AsOf, status: Literal["all", "best", "holding", "lost", "reclaimed"] = "all",
              offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(deals_tab.watch, as_of, status), offset, limit)


@router.get("/deals/tab/history", response_model=Envelope[md.DealHistoryRow],
            description="Every stock >= ₹1,000 Cr with a deal in the last 5 / 10 / 20 deal sessions incl. "
            "churn, prop desks and transfers: pattern, one cell per session, net, prop, avg deal price, now vs deal.")
def tab_history(as_of: Optional[date] = AsOf, sessions: int = Query(10, description="5, 10 or 20 deal sessions"),
                pattern: Literal["all", "repeat_buy", "single_buy", "selling_only", "mixed", "churn_only", "transfers_only"] = "all",
                offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(deals_tab.history, as_of, sessions, pattern), offset, limit)


@router.get("/deals/tab/houses", response_model=Envelope[md.DealHouseRow],
            description="Houses buying in the last 10 deal sessions: class, out-of-sample grade (FII/DII), "
            "spread across groups. meta.context: class_evidence, fund_groups (FII/DII money by industry).")
def tab_houses(as_of: Optional[date] = AsOf, offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(deals_tab.houses, as_of), offset, limit)


@router.get("/deals/tab/groups", response_model=Envelope[md.DealGroupRow],
            description="Deals by industry over the last 10 deal sessions (transfers and churn out): "
            "buying / selling names, net ₹ Cr, symbols. Context only.")
def tab_groups(as_of: Optional[date] = AsOf, offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(deals_tab.groups, as_of), offset, limit)


@router.get("/deals/tab/telegram", response_model=Envelope[md.DealTelegramRow],
            description="Preview of the one-message Telegram digest (same text the sender posts).")
def tab_telegram(as_of: Optional[date] = AsOf) -> dict[str, Any]:
    return envelope(_call(deals_tab.telegram, as_of))


@router.get("/deals/tab/stock/{sym}", response_model=Envelope[md.DealStockDetail],
            description="Stock drawer: latest deal verdict (last 10 deal sessions, null if none), "
            "candles from 45 days before the deal, deal markers and the 3 latest deal-price lines.")
def tab_stock(sym: str, as_of: Optional[date] = AsOf) -> dict[str, Any]:
    return envelope(_call(deals_tab.stock, as_of, symbol_param(sym)))


@router.get("/deals/tab/house/{house}", response_model=Envelope[md.DealHousePosition],
            description="House drawer: class, grade, spread, and its buys over the last 20 deal "
            "sessions vs the equal-weight market since the next-open entry.")
def tab_house(house: str = Path(..., min_length=1, max_length=200), as_of: Optional[date] = AsOf) -> dict[str, Any]:
    return envelope(_call(deals_tab.house, as_of, house))


@router.get("/deals/markers/{sym}", response_model=Envelope[md.DealMarker],
            description="Cross-tab: per-symbol deal markers for chart deal candles. Rows: date, side "
            "(B net buy, S net sell, P placement, T transfer, C churn), price (deal level), event_type, net_cr, gross_cr.")
def deal_markers(sym: str, as_of: Optional[date] = AsOf, lookback: int = Query(250, ge=1, le=2000)) -> dict[str, Any]:
    return envelope(_call(deals_tab.markers, as_of, symbol_param(sym), lookback))


@router.get("/deals/flags", response_model=Envelope[md.DealFlagRow],
            description="Cross-tab: per-symbol 'has recent deal' flag (a deal within the last 10 deal sessions) "
            "with side and verdict, for the deal icon. symbols=A,B,C (max 500); omit for every flagged symbol.")
def deal_flags(as_of: Optional[date] = AsOf, symbols: Optional[str] = Query(None, max_length=12000),
               offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    syms = [symbol_param(s) for s in (symbols or "").split(",") if s.strip()] or None
    if syms and len(syms) > MAX_FLAG_SYMBOLS:
        raise HTTPException(status_code=422, detail=f"at most {MAX_FLAG_SYMBOLS} symbols")
    return envelope(_call(deals_tab.flags, as_of, syms), offset, limit)
