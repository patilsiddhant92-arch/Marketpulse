"""Setups tab endpoints (HarkPro/06-tab2-setups.md, locked). Thin: validate -> service -> envelope.

GET /api/v2/setups/board          one row per stock, screener tags, decision columns, read-out in meta.context
GET /api/v2/setups/near-miss      Squeeze candidates failing exactly one strict gate
GET /api/v2/setups/dropped        stocks that left a screener since the previous session, with the reason
GET /api/v2/setups/detail/{sym}   board row + peers + deal markers + stored RSI divergences
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from fastapi import APIRouter, Path, Query
from pydantic import BaseModel

from App.api.v2 import models as m
from App.api.v2.routes import AsOf, Limit, Offset, V2Route, _call, envelope, symbol_param
from App.services import setups



# --------------------------------------------------------------------------- row models (typed for the UI)
class SetupChip(BaseModel):
    kind: str
    label: str
    title: Optional[str] = None


class SetupBaseRate(BaseModel):
    n: Optional[int] = None
    win: Optional[float] = None
    median: Optional[float] = None
    scope: Optional[str] = None
    horizon: Optional[int] = None
    insufficient: Optional[bool] = None


class SetupTenEma(BaseModel):
    case: str
    tier: Optional[int] = None
    flavor: Optional[str] = None


class SetupBoardRow(BaseModel):
    symbol: str
    name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap_cr: Optional[float] = None
    tags: list[str]
    screeners: list[str]
    status: str
    age: Optional[int] = None
    close: Optional[float] = None
    change_1d_pct: Optional[float] = None
    trigger: Optional[float] = None
    stop: Optional[float] = None
    risk_pct: Optional[float] = None
    adr_pct: Optional[float] = None
    risk_adr: Optional[float] = None
    away_52w_high_pct: Optional[float] = None
    away_10ema_pct: Optional[float] = None
    away_50ema_pct: Optional[float] = None
    rs_21d: Optional[float] = None
    rs_63d: Optional[float] = None
    rs_percentile: Optional[float] = None
    rs_delta_5d: Optional[float] = None
    range_10d_pct: Optional[float] = None
    atr_x: Optional[float] = None
    volume_dryup_pct: Optional[float] = None
    squeeze_pct: Optional[float] = None
    vcp_footprint: Optional[str] = None
    ten_ema: Optional[SetupTenEma] = None
    delivery_pct: Optional[float] = None
    delivery_avg_20d: Optional[float] = None
    delivery_streak: int = 0
    delivery_5d: list[Optional[float]] = []
    turnover_cr: Optional[float] = None
    turnover_1d_x: Optional[float] = None
    turnover_1w_x: Optional[float] = None
    turnover_1m_x: Optional[float] = None
    turnover_3m_avg_cr: Optional[float] = None
    group_state: str
    group_reason: str
    group_share_chg_1d: Optional[float] = None
    group_share_chg_1w: Optional[float] = None
    group_share_chg_1m: Optional[float] = None
    group_rank: Optional[float] = None
    group_rank_n: Optional[int] = None
    group_rank_chg_5d: Optional[float] = None
    room_to_run_pct: Optional[float] = None
    blue_sky: bool = False
    breakouts_held_6m: int = 0
    breakouts_failed_6m: int = 0
    weekly_above_10w: Optional[bool] = None
    weekly_tight: Optional[bool] = None
    weekly_spread_3w_pct: Optional[float] = None
    chips: list[SetupChip] = []
    results_date: Optional[date] = None
    results_soon: bool = False
    base_rate: Optional[SetupBaseRate] = None
    data_warning: Optional[str] = None
    peer_note: Optional[str] = None


class SetupNearMissRow(BaseModel):
    symbol: str
    industry: Optional[str] = None
    gate: str
    squeeze_pct: Optional[float] = None
    close: Optional[float] = None
    box_top: Optional[float] = None
    ema_10: Optional[float] = None
    rvol: Optional[float] = None


class SetupDroppedRow(BaseModel):
    screener: str
    screener_name: str
    symbol: str
    code: str
    why: str
    industry: Optional[str] = None
    close: Optional[float] = None


router = APIRouter(route_class=V2Route, tags=["setups"])  # included into the /api/v2 router

Template = Query("ema", description="Momentum template: 'ema' (EMA 10>20>50>100>200) or 'sma' (SMA 50>150>200, rising 200)")
VolumeMode = Query("day", description="Momentum volume gate: 'day' (session volume) or 'avg20d' (20D average volume)")
MinVolume = Query(1_000_000.0, ge=0, description="Momentum volume threshold (shares)")
ResultsN = Query(setups.RESULTS_N_DEFAULT, ge=1, le=60, description="Highlight rows with results within N sessions")


def _params(template: str, volume_mode: str, min_volume: float, results_n: int) -> setups.BoardParams:
    return setups.BoardParams(template=template, volume_mode=volume_mode, min_volume=float(min_volume),
                              results_n=int(results_n))


@router.get("/setups/board", response_model=m.Envelope[SetupBoardRow], description="Setups board: every stock in Darvas Squeeze, Darvas 10 EMA, VCP or Momentum, "
                                         "one row each with screener tags, group state + reason and decision columns. "
                                         "meta.context carries counts, read-out, base rates and data gaps.")
def setups_board(
    as_of: Optional[date] = AsOf,
    template: Literal["ema", "sma"] = Template,
    volume_mode: Literal["day", "avg20d"] = VolumeMode,
    min_volume: float = MinVolume,
    results_n: int = ResultsN,
    offset: int = Offset,
    limit: int = Limit,
) -> dict[str, Any]:
    return envelope(_call(setups.board, as_of, _params(template, volume_mode, min_volume, results_n)), offset, limit)


@router.get("/setups/near-miss", response_model=m.Envelope[SetupNearMissRow], description="Darvas Squeeze near-miss: close in the zone, exactly one strict gate failed.")
def setups_near_miss(as_of: Optional[date] = AsOf, limit: int = Query(60, ge=1, le=500)) -> dict[str, Any]:
    return envelope(_call(setups.near_miss, as_of, limit))


@router.get("/setups/dropped", response_model=m.Envelope[SetupDroppedRow], description="Why dropped: stocks that left a screener since the previous session.")
def setups_dropped(
    as_of: Optional[date] = AsOf,
    template: Literal["ema", "sma"] = Template,
    volume_mode: Literal["day", "avg20d"] = VolumeMode,
    min_volume: float = MinVolume,
) -> dict[str, Any]:
    return envelope(_call(setups.dropped, as_of, _params(template, volume_mode, min_volume, setups.RESULTS_N_DEFAULT)))


@router.get("/setups/detail/{sym}", response_model=m.Envelope[SetupBoardRow], description="Detail panel: board row, top-RS peers in the industry, deal markers, "
                                                "stored RSI divergences.")
def setups_detail(
    sym: str = Path(..., description="NSE symbol"),
    as_of: Optional[date] = AsOf,
    template: Literal["ema", "sma"] = Template,
    volume_mode: Literal["day", "avg20d"] = VolumeMode,
    min_volume: float = MinVolume,
    results_n: int = ResultsN,
) -> dict[str, Any]:
    return envelope(_call(setups.detail, symbol_param(sym), as_of, _params(template, volume_mode, min_volume, results_n)))
