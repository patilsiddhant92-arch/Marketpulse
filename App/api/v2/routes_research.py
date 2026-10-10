"""Research tab endpoints (HarkPro/10-tab-research.md §§3-13): regime quadrant, days like today, setup
scorecard, big-mover case studies, before the big moves, index study.

Registered on the shared v2 router (one import line in App/api/v2/__init__.py). Heavy parts are
precomputed by Scripts/research_lab.py; see App/services/research_lab.py. Every response carries
meta.context.caveat ("retrospective research, not advice").
"""
from __future__ import annotations

from datetime import date
from typing import Any, Callable, Literal, Optional

from fastapi import Query
from pydantic import BaseModel, ConfigDict

from App.api.v2 import models as m
from App.api.v2.routes import AsOf, Limit, Offset, _call, envelope, router, symbol_param
from App.services import research_bigmove, research_lab, research_premove, research_regime
from App.services.common import Result


class RegimeDayRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    trade_date: Optional[date] = None
    ew_index: Optional[float] = None
    drawdown_pct: Optional[float] = None
    chop: Optional[float] = None
    er: Optional[float] = None
    adx: Optional[float] = None
    ft_pct: Optional[float] = None
    ft_n: Optional[float] = None
    chop_pctile: Optional[float] = None
    er_pctile: Optional[float] = None
    ft_pctile: Optional[float] = None
    index_axis: Optional[str] = None
    breakout_axis: Optional[str] = None
    quadrant: Optional[str] = None
    next10_ft_pct: Optional[float] = None
    fwd20_pct: Optional[float] = None


class AnalogDayRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    analog_date: Optional[date] = None
    distance: Optional[float] = None
    quadrant: Optional[str] = None
    quadrant_label: Optional[str] = None
    fwd5_pct: Optional[float] = None
    fwd10_pct: Optional[float] = None
    fwd20_pct: Optional[float] = None
    fwd60_pct: Optional[float] = None
    next10_ft_pct: Optional[float] = None


class ScorecardRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    preset_id: str
    preset: str
    letter: Optional[str] = None
    category: Optional[str] = None
    early: bool = False
    description: Optional[str] = None
    movers: Optional[int] = None
    caught: Optional[int] = None
    caught_pct: Optional[float] = None
    entry_vs_low_pct: Optional[float] = None
    to_peak_pct: Optional[float] = None
    trail20_pct: Optional[float] = None
    fires_per_mover: Optional[float] = None
    fires: Optional[int] = None
    hit_pct: Optional[float] = None
    false_alarm_pct: Optional[float] = None
    lift: Optional[float] = None
    fires_rs80: Optional[int] = None
    hit_rs80_pct: Optional[float] = None


class CaseMoverRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    symbol: str
    security_name: Optional[str] = None
    industry: Optional[str] = None
    mcap_cr: Optional[float] = None
    low_date: Optional[date] = None
    low: Optional[float] = None
    peak_date: Optional[date] = None
    peak: Optional[float] = None
    gain_pct: Optional[float] = None
    ladder_pct: Optional[float] = None
    trades: Optional[int] = None
    first_early_fire: Optional[date] = None
    first_early_preset: Optional[str] = None
    first_early_vs_low_pct: Optional[float] = None


class CaseBarRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    time: date
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[float] = None
    ema_20: Optional[float] = None


class EarlyLiftRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    symbol: str
    security_name: Optional[str] = None
    industry: Optional[str] = None
    mcap_cr: Optional[float] = None
    lift_date: Optional[date] = None
    close: Optional[float] = None
    score: int = 0
    score_max: int = 0
    bucket: Optional[str] = None
    bucket_runner_pct: Optional[float] = None
    bucket_events: Optional[int] = None
    traits_on: list[str] = []
    quadrant: Optional[str] = None
    quadrant_label: Optional[str] = None
    regime_multiplier: Optional[float] = None
    above_200ema_pct: Optional[float] = None
    range_50d_pct: Optional[float] = None
    rs_percentile: Optional[float] = None


class DrawdownRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    peak_date: Optional[date] = None
    trough_date: Optional[date] = None
    depth_pct: Optional[float] = None
    sessions_down: Optional[int] = None
    recovered_date: Optional[date] = None
    sessions_to_recover: Optional[int] = None
    breadth_above_50ema_at_low: Optional[float] = None
    ongoing: bool = False


def _research(fn: Callable[..., Result], *args: Any) -> Result:
    """Call a research service and make its rows / context JSON-safe (numpy, NaN, timestamps)."""
    res = _call(fn, *args)
    res.rows = research_lab.deep_clean(res.rows)
    res.extra = research_lab.deep_clean(res.extra)
    res.extra.setdefault("caveat", research_lab.CAVEAT)
    return res


@router.get("/research/regime", response_model=m.Envelope[RegimeDayRow],
            description="Two-axis regime quadrant per session (index range/trend x breakouts paying/failing), "
                        "today's reading, the quadrant record, episodes and durations (10-tab-research §11).")
def research_regime_route(as_of: Optional[date] = AsOf, days: int = Query(600, ge=1, le=5000),
                          offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_research(research_regime.regime, as_of, days), offset, limit)


@router.get("/research/days-like-today", response_model=m.Envelope[AnalogDayRow],
            description="The k nearest past sessions to today by breadth, regime and follow-through readings, "
                        "with what the equal-weight market did next vs all days (§§3-4).")
def research_days_like_today(as_of: Optional[date] = AsOf, k: int = Query(10, ge=3, le=30)) -> dict[str, Any]:
    return envelope(_research(research_regime.analogs, as_of, k))


@router.get("/research/scorecard", response_model=m.Envelope[ScorecardRow],
            description="Setup scorecard: each screener preset's catch rate on the year's big movers, how early it "
                        "fired, and its precision / false alarms on all fresh fires (§12).")
def research_scorecard(as_of: Optional[date] = AsOf) -> dict[str, Any]:
    return envelope(_research(research_bigmove.scorecard, as_of))


@router.get("/research/case-study", response_model=m.Envelope[CaseMoverRow],
            description="Big movers of the 12 months to the study end (low -> peak >= +100%), with the 20 EMA ladder.")
def research_case_movers(as_of: Optional[date] = AsOf, min_gain_pct: float = Query(100.0, ge=100.0, le=10000.0),
                         offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_research(research_bigmove.case_movers, as_of, min_gain_pct), offset, limit)


@router.get("/research/case-study/{sym}", response_model=m.Envelope[CaseBarRow],
            description="Case study of one stock: daily bars (rows), the low -> peak move, every preset's fresh "
                        "fire, the first-fire table, the 20 EMA ladder and the precision context (meta.context).")
def research_case_study(sym: str, as_of: Optional[date] = AsOf) -> dict[str, Any]:
    return envelope(_research(research_bigmove.case_study, as_of, symbol_param(sym)))


@router.get("/research/before-moves", response_model=m.Envelope[EarlyLiftRow],
            description="Before the big moves: runner vs fizzle trait profile per family (trend / turnaround "
                        "lifts), today's early lifts scored by trait count, and the regime multiplier (§13).")
def research_before_moves(as_of: Optional[date] = AsOf, family: Literal["trend", "turnaround"] = "trend",
                          days: int = Query(10, ge=1, le=60), offset: int = Offset,
                          limit: int = Limit) -> dict[str, Any]:
    return envelope(_research(research_premove.before_moves, as_of, family, days), offset, limit)


@router.get("/research/index-study", response_model=m.Envelope[DrawdownRow],
            description="Index study on the equal-weight market: every fall > 8% (depth, time down, time to "
                        "recover, breadth at the low), size leadership and the EW series (§6).")
def research_index_study(as_of: Optional[date] = AsOf) -> dict[str, Any]:
    return envelope(_research(research_regime.index_study, as_of))
