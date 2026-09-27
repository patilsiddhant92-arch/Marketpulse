"""Pydantic response models for API v2 (source for frontend/openapi.json → types.gen.ts).

Every data endpoint returns `Envelope[Row]`:
    {as_of, freshness, total, returned, rows, meta}
Numeric fields are Optional: NULL stays NULL (the UI renders "—").
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Freshness(BaseModel):
    status: Literal["fresh", "stale", "degraded", "unavailable"]
    latest_session: Optional[date] = None
    expected_session: Optional[date] = None
    sessions_behind: Optional[int] = None
    history_mode: bool = False
    reason: Optional[str] = None


class Meta(BaseModel):
    status: Literal["ok", "partial", "unavailable"] = "ok"
    reason: Optional[str] = None
    sources: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    offset: int = 0
    limit: int = 0
    metric_keys: list[str] = Field(default_factory=list, description="Keys into /api/v2/metrics/dictionary")
    context: dict[str, Any] = Field(default_factory=dict, description="Endpoint-specific context (applied rules, floor, …)")


class Envelope(BaseModel, Generic[T]):
    as_of: Optional[date] = None
    freshness: Freshness
    total: int
    returned: int
    rows: list[T]
    meta: Meta


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------
class HealthCheck(BaseModel):
    name: str
    ok: bool
    detail: Optional[str] = None


class HealthResponse(BaseModel):
    status: Literal["healthy", "stale", "degraded", "unavailable"]
    version: str
    build: str
    freshness: Freshness
    checks: list[HealthCheck]


# --------------------------------------------------------------------------
# Market
# --------------------------------------------------------------------------
class Pillar(BaseModel):
    status: Optional[str] = None
    sentence: Optional[str] = None
    dir_1d: Optional[str] = None
    dir_1w: Optional[str] = None
    dir_1m: Optional[str] = None
    inputs: dict[str, Any] = Field(default_factory=dict)


class Pillars(BaseModel):
    trend: Pillar
    participation: Pillar
    leadership: Pillar
    follow_through: Pillar
    stress: Pillar


class RegimeRow(BaseModel):
    trade_date: Optional[date] = None
    verdict: Optional[str] = Field(None, description="Favourable | Constructive | Mixed | Weak | Danger")
    previous_verdict: Optional[str] = None
    rule_id: Optional[str] = None
    days_in_state: Optional[int] = None
    changed_on: Optional[date] = None
    readings: Optional[Any] = None
    verdict_evidence: Optional[str] = Field(None, description="descriptive_only when the verdict failed the out-of-sample ship gate (spec §6.1.5)")
    verdict_evidence_note: Optional[str] = None
    pillars: Pillars
    inputs: dict[str, Any] = Field(default_factory=dict)


class MarketHealthRow(BaseModel):
    trade_date: Optional[date] = None
    stocks: Optional[int] = None
    advancers: Optional[int] = None
    decliners: Optional[int] = None
    advance_pct: Optional[float] = None
    net_advancers: Optional[int] = None
    ad_line_10d: Optional[int] = None
    pct_above_10ema: Optional[float] = None
    pct_above_20ema: Optional[float] = None
    pct_above_50ema: Optional[float] = None
    pct_above_200ema: Optional[float] = None
    new_52w_highs: Optional[int] = None
    new_52w_lows: Optional[int] = None
    net_new_highs: Optional[int] = None
    near_52w_highs: Optional[int] = None
    stage2_count: Optional[int] = None
    nifty50_close: Optional[float] = None
    nifty50_return_1d_pct: Optional[float] = None
    midsml400_close: Optional[float] = None
    midsml400_return_1d_pct: Optional[float] = None
    india_vix: Optional[float] = None
    vix_change_1d_pct: Optional[float] = None
    vix_change_5d_pct: Optional[float] = None
    distribution_day: Optional[bool] = None
    distribution_days_25: Optional[int] = None
    breadth_state: Optional[str] = None


# --------------------------------------------------------------------------
# Common stock columns
# --------------------------------------------------------------------------
class StockBase(BaseModel):
    symbol: Optional[str] = None
    security_name: Optional[str] = None
    broad_sector: Optional[str] = None
    sector: Optional[str] = None
    broad_industry: Optional[str] = None
    industry: Optional[str] = None
    close: Optional[float] = None
    change_1d_pct: Optional[float] = Field(None, description="Close vs previous close, %")
    rvol: Optional[float] = None
    delivery_pct: Optional[float] = None
    deliv_pct_x: Optional[float] = Field(
        None, description="Delivery % ×20d: today's delivery % ÷ the stock's own 20-day average delivery % (its delivery habit)")
    rs_percentile: Optional[float] = None
    rs_delta_5: Optional[float] = None
    excess_vs_midsml400_63d: Optional[float] = None
    market_cap_cr: Optional[float] = None
    adv_cr_20d: Optional[float] = None
    data_warning: Optional[str] = Field(
        None, description="Unexplained price gap inside a metric window; those metrics are served NULL")


# --------------------------------------------------------------------------
# Desk
# --------------------------------------------------------------------------
class QueueSummaryRow(BaseModel):
    name: str
    label: str
    description: str
    timeframes: list[str]
    counts: dict[str, Optional[int]]
    count: Optional[int] = None


class Contraction(BaseModel):
    label: str
    start_date: Optional[date] = None
    trough_date: Optional[date] = None
    end_date: Optional[date] = None
    peak: Optional[float] = None
    trough: Optional[float] = None
    depth_pct: Optional[float] = None
    bars: Optional[int] = None
    volume_ratio: Optional[float] = None


class NextEvent(BaseModel):
    event_type: Optional[str] = None
    event_date: Optional[date] = None


class QueueRow(StockBase):
    queue: str
    timeframe: str
    trigger_price: Optional[float] = None
    stop_price: Optional[float] = None
    distance_to_trigger_pct: Optional[float] = None
    risk_pct: Optional[float] = None
    risk_flag: bool = False
    first_seen: Optional[date] = None
    setup_age_sessions: Optional[int] = None
    is_new: Optional[bool] = None
    industry_quadrant: Optional[str] = None
    results_within_10: Optional[bool] = None
    next_event: Optional[NextEvent] = None
    deal_net_10s_cr: Optional[float] = None
    squeeze_pct: Optional[float] = None
    candle_range_pct: Optional[float] = None
    darvas_box_top: Optional[float] = None
    darvas_box_bottom: Optional[float] = None
    darvas_10ema_flavor: Optional[str] = None
    signal_date: Optional[date] = None
    vcp_contractions: Optional[list[Contraction]] = None
    vcp_depth_pct: Optional[float] = None
    vdu_ratio: Optional[float] = None
    status: Optional[str] = None


class DeskWatchRow(StockBase):
    trade_date: Optional[date] = None
    has_data: bool = False
    queues: list[str] = Field(default_factory=list, description="Daily Desk queues the stock is in on as_of")
    primary_queue: Optional[str] = None
    trigger_price: Optional[float] = None
    stop_price: Optional[float] = None
    distance_to_trigger_pct: Optional[float] = None
    risk_pct: Optional[float] = None
    away_52w_high_pct: Optional[float] = None
    results_within_10: Optional[bool] = None
    next_event: Optional[NextEvent] = None


class DiffRow(BaseModel):
    queue: str
    timeframe: str
    change: Literal["new", "dropped"]
    symbol: Optional[str] = None
    session: Optional[date] = None
    close: Optional[float] = None
    rs_percentile: Optional[float] = None
    industry: Optional[str] = None


# --------------------------------------------------------------------------
# Screener
# --------------------------------------------------------------------------
class Rule(BaseModel):
    field: str
    op: Literal["gt", "gte", "lt", "lte", "eq", "is_true", "is_false"]
    value: Optional[float] = None
    ref: Optional[str] = None
    label: Optional[str] = None


class PresetRow(BaseModel):
    id: str
    label: str
    description: str
    kind: Literal["rules", "queue", "lab"]
    queue: Optional[str] = None
    category: Optional[str] = Field(None, description="Picker group: Trend | Highs | Coil | Momentum | Setups | Lab")
    rules: list[Rule]
    available: bool


class ScreenerRow(StockBase):
    model_config = ConfigDict(extra="allow")
    rs_is_ipo_rank: bool = False
    rs_delta_20: Optional[float] = None
    rs_rank_t5: Optional[float] = None
    rs_rank_t15: Optional[float] = None
    rs_rank_t30: Optional[float] = None
    trend_template_pass_n: Optional[int] = None
    away_52w_high_pct: Optional[float] = None
    days_since_52w_high: Optional[int] = None
    days_in_stage2: Optional[int] = None
    days_in_stage2_capped: Optional[bool] = None
    return_1m_pct: Optional[float] = None
    return_3m_pct: Optional[float] = None
    return_6m_pct: Optional[float] = None
    last_pass_date: Optional[date] = None
    is_new: Optional[bool] = None


class DebugRow(BaseModel):
    kind: Literal["floor", "rule", "check", "result"]
    label: str
    field: Optional[str] = None
    op: Optional[str] = None
    value: Optional[float] = None
    ref: Optional[str] = None
    actual: Optional[Any] = None
    ref_actual: Optional[float] = None
    passed: bool
    missing_input: Optional[bool] = None
    detail: Optional[str] = None


class MomentumRow(BaseModel):
    """One Momentum-scanner candidate (parity port of the old /api/screener/momentum row; NULL stays NULL)."""

    symbol: Optional[str] = None
    security_name: Optional[str] = None
    broad_sector: Optional[str] = None
    sector: Optional[str] = None
    broad_industry: Optional[str] = None
    industry: Optional[str] = None
    trigger_date: Optional[date] = Field(None, description="Latest session in the lookback on which every trigger condition held")
    bucket: Optional[Literal["0_2%", "2_5%", "5_10%", "10%+", "Below 10EMA"]] = Field(
        None, description="Coil bucket by % above the 10 EMA")
    bucket_rank: Optional[int] = None
    close: Optional[float] = None
    change_1d_pct: Optional[float] = None
    return_5d_pct: Optional[float] = None
    return_1m_pct: Optional[float] = None
    return_3m_pct: Optional[float] = None
    rs_percentile: Optional[float] = None
    away_10ema_pct: Optional[float] = None
    away_52w_high_pct: Optional[float] = None
    away_52w_low_pct: Optional[float] = None
    volume: Optional[int] = None
    avg_volume_20d: Optional[int] = None
    rvol: Optional[float] = None
    delivery_pct: Optional[float] = None
    market_cap_cr: Optional[float] = None
    bullish_stack: Optional[bool] = Field(None, description="10 > 20 > 50 > 200 EMA; NULL when any EMA is missing")
    delivery_spike: Optional[bool] = Field(None, description="Delivery spike today or on a trigger session")
    coiling: Optional[bool] = Field(None, description="NR7 or inside bar today")
    is_new: Optional[bool] = Field(None, description="Listed today but not on the previous session")
    data_warning: Optional[str] = None


class MomentumEvidenceRow(BaseModel):
    """Forward returns of past Momentum-scanner hits (default settings) per coil bucket."""

    bucket: str
    sessions: Optional[int] = None
    stocks: Optional[int] = None
    n_5: int = 0
    hit_rate_5: Optional[float] = None
    avg_5: Optional[float] = None
    median_5: Optional[float] = None
    n_10: int = 0
    hit_rate_10: Optional[float] = None
    avg_10: Optional[float] = None
    median_10: Optional[float] = None
    n_20: int = 0
    hit_rate_20: Optional[float] = None
    avg_20: Optional[float] = None
    median_20: Optional[float] = None
    insufficient_sample: bool = True


# --------------------------------------------------------------------------
# Groups
# --------------------------------------------------------------------------
class GroupRow(BaseModel):
    id: str
    level: str
    group_name: Optional[str] = None
    trade_date: Optional[date] = None
    stocks: Optional[int] = None
    rrg_quadrant: Optional[str] = None
    days_in_quadrant: Optional[int] = None
    rs_ratio: Optional[float] = None
    rs_momentum: Optional[float] = None
    rs_ratio_self: Optional[float] = Field(
        None, description="Self-normalised RS trend: 100 x EMA10/EMA50 of (EW group index / MidSml400); the pre-2026-09-27 RS-Ratio")
    rs_momentum_self: Optional[float] = Field(None, description="100 x rs_ratio_self / rs_ratio_self 10 sessions ago")
    health: Optional[float] = Field(
        None, description="Group Health 0-100 = 0.40 relative (peer RRG) + 0.35 absolute trend + 0.25 breadth")
    health_rank: Optional[int] = Field(None, description="Rank by Health among groups with >= 3 members, 1 = healthiest")
    abs_trend: Optional[str] = Field(None, description="Up / Flat / Down: EW index vs its 50/200 EMA and the EMA50 slope")
    quadrant_note: Optional[str] = Field(None, description="e.g. 'Leading but falling' (21d EW return < 0)")
    ew_index: Optional[float] = Field(None, description="Equal-weight group index, start of history = 100")
    ew_index_ema50: Optional[float] = None
    ew_index_ema200: Optional[float] = None
    turnover_cr: Optional[float] = Field(None, description="Group turnover that session, ₹ Cr")
    rank: Optional[int] = None
    rank_delta_5: Optional[int] = None
    rank_delta_20: Optional[int] = None
    rank_delta_63: Optional[int] = None
    rank_n: Optional[int] = Field(None, description="Groups ranked at this level and floor that session")
    rank_score: Optional[float] = Field(None, description="mean(excess vs MidSml400 21d, 63d), points")
    return_ew_1d: Optional[float] = None
    return_ew_5d: Optional[float] = None
    return_ew_21d: Optional[float] = None
    return_ew_63d: Optional[float] = None
    return_cw_21d: Optional[float] = None
    excess_vs_midsml400_21d: Optional[float] = None
    excess_vs_midsml400_63d: Optional[float] = None
    excess_vs_nifty50_21d: Optional[float] = None
    excess_vs_nifty50_63d: Optional[float] = None
    breadth_50: Optional[float] = None
    breadth_200: Optional[float] = None
    trend_template_pct: Optional[float] = None
    new_highs: Optional[int] = None
    pct_new_highs: Optional[float] = None
    turnover_share_5d: Optional[float] = None
    turnover_share_20d: Optional[float] = None
    turnover_share_delta: Optional[float] = None
    turnover_share_pct: Optional[float] = None
    delivery_accumulation: Optional[float] = Field(
        None, description="(delivery value on up days - on down days) / delivery value over 10 sessions, % (-100..100)")
    acc_day_members_pct: Optional[float] = Field(None, description="% of members with an accumulation day today")
    deal_net_10s_cr: Optional[float] = None
    concentration_top3: Optional[float] = None
    top1_turnover_share_pct: Optional[float] = Field(None, description="Largest member's share of group turnover, %")
    concentration_flag: Optional[bool] = Field(None, description="Top member >= 50% of group turnover (>= 3 members)")
    flow_up_days_10: Optional[int] = Field(None, description="Sessions of the last 10 with turnover_share_delta > 0")
    rank_spark_60: Optional[list[Optional[int]]] = None
    rs_line_60: Optional[list[Optional[float]]] = Field(
        None, description="Equal-weight group index / MidSml400, last 60 sessions, rebased to 100")
    legacy_rotation_state: Optional[str] = Field(None, description="Legacy sector_rotation label (not an RRG quadrant)")
    legacy_median_rs_percentile: Optional[float] = None
    leader_symbols: Optional[list[str]] = None
    health_spark_21: Optional[list[Optional[float]]] = Field(None, description="Health over the last 21 sessions, oldest first")
    index_spark_1y: Optional[list[Optional[float]]] = Field(
        None, description="Equal-weight group index over ~1 year (every 5th session, oldest first), rebased to 100")


class RrgPoint(BaseModel):
    trade_date: Optional[date] = None
    rs_ratio: Optional[float] = None
    rs_momentum: Optional[float] = None


class RrgRow(BaseModel):
    id: str
    group_name: str
    level: str
    rs_ratio: Optional[float] = None
    rs_momentum: Optional[float] = None
    rrg_quadrant: Optional[str] = None
    days_in_quadrant: Optional[int] = None
    stocks: Optional[int] = None
    rank: Optional[int] = None
    health: Optional[float] = None
    health_rank: Optional[int] = None
    abs_trend: Optional[str] = None
    quadrant_note: Optional[str] = None
    return_ew_21d: Optional[float] = None
    tail: list[RrgPoint]


class GroupIndexRow(BaseModel):
    trade_date: Optional[date] = None
    ew_index: Optional[float] = Field(None, description="Equal-weight group index, start of history = 100")
    ema_50: Optional[float] = None
    ema_200: Optional[float] = None
    abs_trend: Optional[str] = None
    health: Optional[float] = None


class GroupTreeRow(BaseModel):
    id: str
    level: str
    group_name: str
    parent_id: Optional[str] = Field(None, description="Parent group id (most common parent in today's mapping)")
    stocks: Optional[int] = None
    turnover_20d_cr: Optional[float] = Field(None, description="Average daily turnover over 20 sessions, ₹ Cr (tile size)")
    health: Optional[float] = None
    return_ew_21d: Optional[float] = None
    rrg_quadrant: Optional[str] = None
    quadrant_note: Optional[str] = None
    abs_trend: Optional[str] = None


class MemberRow(StockBase):
    rs_vs_sector_index_63d: Optional[float] = None
    sector_index_name: Optional[str] = None
    rs_rank_t5: Optional[float] = None
    rs_rank_t15: Optional[float] = None
    rs_rank_t30: Optional[float] = None
    trend_template_pass_n: Optional[int] = None
    trend_template_pass: Optional[bool] = None
    return_1m_pct: Optional[float] = None
    return_3m_pct: Optional[float] = None
    excess_vs_midsml400_21d: Optional[float] = None
    away_52w_high_pct: Optional[float] = None
    delivery_accumulation_days: Optional[int] = None
    deal_net_10s_cr: Optional[float] = Field(None, description="Bulk/block net over 10 sessions, PROP excluded, Rs Cr")
    active_setups: Optional[list[str]] = None


# --------------------------------------------------------------------------
# Deals
# --------------------------------------------------------------------------
class DealSessionRow(BaseModel):
    symbol: Optional[str] = None
    security_name: Optional[str] = None
    industry: Optional[str] = None
    trade_date: Optional[date] = None
    close: Optional[float] = None
    market_cap_cr: Optional[float] = None
    rs_percentile: Optional[float] = None
    buy_cr: Optional[float] = None
    sell_cr: Optional[float] = None
    net_cr: Optional[float] = None
    net_ex_prop_cr: Optional[float] = Field(None, description="Net excluding PROP desks (drives events and ADV ratio)")
    institutional_net_cr: Optional[float] = None
    fii_net_cr: Optional[float] = None
    dii_net_cr: Optional[float] = None
    prop_net_cr: Optional[float] = None
    corporate_net_cr: Optional[float] = None
    buying_houses: Optional[int] = None
    selling_houses: Optional[int] = None
    prints: Optional[int] = None
    deal_types: Optional[str] = None
    vwap: Optional[float] = None
    buy_vwap: Optional[float] = None
    vwap_vs_cmp_pct: Optional[float] = Field(None, description="Close on as_of vs buy VWAP (else VWAP), %")
    adv_cr: Optional[float] = None
    vs_adv: Optional[float] = None
    deal_price_vs_close_pct: Optional[float] = None
    deal_qty_pct_volume: Optional[float] = None
    round_trip_value_cr: Optional[float] = None
    prop_value_cr: Optional[float] = None
    matched_value_cr: Optional[float] = None
    all_prop: Optional[bool] = None
    event_type: Optional[str] = None
    event_rule: Optional[str] = None
    persistence_days: Optional[int] = None
    net_10s: Optional[list[Optional[float]]] = Field(
        None, description="Net ex-PROP Rs Cr on each of the last 10 sessions (dates in meta.context.net_10s_dates); NULL = no deal")
    above_200ema: Optional[bool] = None
    rs_ge_70: Optional[bool] = None
    within_15pct_of_high: Optional[bool] = None


class HousePrintRow(BaseModel):
    trade_date: Optional[date] = None
    symbol: Optional[str] = None
    side: Optional[str] = None
    quantity: Optional[int] = None
    price: Optional[float] = None
    value_cr: Optional[float] = None
    deal_types: Optional[str] = None
    clientele: Optional[str] = None
    is_prop: Optional[bool] = None
    entry_open: Optional[float] = None
    fwd_t5_pct: Optional[float] = None
    fwd_t20_pct: Optional[float] = None
    excess_t20_pct: Optional[float] = None


class HouseRow(BaseModel):
    house: str
    clientele: Optional[str] = None
    prints: int
    buy_prints: int
    sell_prints: int
    buy_value_cr: Optional[float] = None
    sell_value_cr: Optional[float] = None
    net_cr: Optional[float] = None
    symbols: int
    first_date: Optional[date] = None
    last_date: Optional[date] = None
    buy_bets_t20: int
    avg_fwd_t20_pct: Optional[float] = None
    avg_excess_t20_pct: Optional[float] = None
    hit_rate_t20: Optional[float] = None
    ranked: bool
    round_trip_pct: Optional[float] = None
    churner: bool
    active_in_session: bool
    session_net_cr: Optional[float] = None
    session_symbols: Optional[list[str]] = None


class FollowThroughRow(BaseModel):
    event_type: Optional[str] = None
    label: Optional[str] = None
    rule: Optional[str] = None
    is_baseline: bool = False
    n: int
    n_t5: Optional[int] = None
    insufficient_sample: bool
    avg_fwd_t5_pct: Optional[float] = None
    avg_fwd_t20_pct: Optional[float] = None
    median_fwd_t20_pct: Optional[float] = None
    hit_rate_t20: Optional[float] = None
    avg_excess_t5_pct: Optional[float] = None
    avg_excess_t20_pct: Optional[float] = None


class _DealStock(BaseModel):
    security_name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    close: Optional[float] = None
    ema_200: Optional[float] = None
    above_200ema: Optional[bool] = None
    away_52w_high_pct: Optional[float] = None
    rs_percentile: Optional[float] = None
    market_cap_cr: Optional[float] = None
    circuit_band: Optional[float] = None


class DealPrintRow(_DealStock):
    """One collapsed print of the deal session (Today)."""

    trade_date: Optional[date] = None
    symbol: Optional[str] = None
    client: Optional[str] = None
    house: Optional[str] = Field(None, description="Fund house (entity suffixes such as -FPI / -ODI / PVT LTD stripped)")
    side: Optional[str] = None
    quantity: Optional[int] = None
    price: Optional[float] = None
    value_cr: Optional[float] = None
    deal_types: Optional[str] = None
    clientele: Optional[str] = None
    is_prop: Optional[bool] = None
    price_vs_close_pct: Optional[float] = None
    event_type: Optional[str] = Field(None, description="The stock's event label for the session")


class DealWindowRow(_DealStock):
    """One stock over the last N deal sessions (repeated deals, Play tiers, churn, transfers)."""

    symbol: str
    deal_days: int = Field(..., description="Sessions in the window with any collapsed print")
    net_buy_days: int
    net_sell_days: int
    transfer_days: int
    churn_days: int
    buy_cr: Optional[float] = None
    sell_cr: Optional[float] = None
    net_ex_prop_cr: Optional[float] = None
    flow_net_cr: Optional[float] = Field(None, description="Net ex-PROP on accumulate / fresh / distribute sessions only")
    flow_buy_cr: Optional[float] = None
    transfer_cr: Optional[float] = None
    prop_value_cr: Optional[float] = None
    fii_net_cr: Optional[float] = None
    dii_net_cr: Optional[float] = None
    first_deal_date: Optional[date] = None
    last_deal_date: Optional[date] = None
    last_event_type: Optional[str] = None
    net_by_session: list[Optional[float]] = Field(
        default_factory=list, description="Flow net per window session (dates in meta.context.window_dates); 0 = transfer/churn, NULL = no deal")
    n_houses: int = 0
    n_buy_houses: int = 0
    n_sell_houses: int = 0
    repeat_house: bool = False
    top_buyers: list[str] = Field(default_factory=list)
    top_sellers: list[str] = Field(default_factory=list)
    adv_cr: Optional[float] = None
    net_vs_adv: Optional[float] = None
    tier: str = Field(..., description="quarantined | transfer | churn | conviction | fresh | distribution")
    play_reason: Optional[str] = None


class DealHolding(BaseModel):
    symbol: str
    buy_cr: Optional[float] = None
    sell_cr: Optional[float] = None
    net_cr: Optional[float] = None
    prints: int
    last_date: Optional[date] = None
    last_side: Optional[str] = None
    last_price: Optional[float] = None


class DealLeaderRow(BaseModel):
    house: str
    clientele: Optional[str] = None
    individual: bool
    clients: list[str] = Field(default_factory=list)
    bets: int
    bets_t20: int
    names: int
    total_cr: Optional[float] = None
    win_rate_20d: Optional[float] = None
    hit_rate_20d: Optional[float] = None
    avg_ret_20d: Optional[float] = None
    avg_excess_20d: Optional[float] = None
    avg_peak_runup: Optional[float] = None
    avg_days_to_peak: Optional[float] = None
    baggers: int = 0
    best_gain: Optional[float] = None
    latest_buy_date: Optional[date] = None
    catalyst_score: Optional[float] = None
    tier: str
    ranked: bool
    names_in_window: int = 0
    net_long_count: int = 0
    holdings: list[DealHolding] = Field(default_factory=list)


class DealStarRow(BaseModel):
    symbol: str
    house: str
    client: Optional[str] = None
    clientele: Optional[str] = None
    tier: Optional[str] = None
    catalyst_score: Optional[float] = None
    win_rate_20d: Optional[float] = None
    deal_date: Optional[date] = None
    deal_price: Optional[float] = None
    entry_open: Optional[float] = None
    cmp: Optional[float] = None
    gain_pct: Optional[float] = None
    peak_runup_pct: Optional[float] = None
    holding_days: Optional[int] = None
    deal_cr: Optional[float] = None
    rs_percentile: Optional[float] = None
    away_52w_high_pct: Optional[float] = None
    market_cap_cr: Optional[float] = None
    sector: Optional[str] = None


# --------------------------------------------------------------------------
# Stock
# --------------------------------------------------------------------------
class TaxonomyNode(BaseModel):
    level: str
    name: Optional[str] = None
    id: Optional[str] = None


class Adjustment(BaseModel):
    ex_date: Optional[date] = None
    kind: Optional[str] = None
    factor: Optional[float] = None
    source: Optional[str] = None
    confidence: Optional[str] = None
    description: Optional[str] = None


class StockHeaderRow(StockBase):
    trade_date: Optional[date] = None
    stale_vs_as_of: bool = False
    isin: Optional[str] = None
    series: Optional[str] = None
    prev_close: Optional[float] = None
    high_52w: Optional[float] = None
    low_52w: Optional[float] = None
    away_52w_high_pct: Optional[float] = None
    away_52w_low_pct: Optional[float] = None
    circuit_band: Optional[float] = None
    band_remarks: Optional[str] = None
    mcap_point_in_time: Optional[bool] = None
    excess_vs_midsml400_21d: Optional[float] = None
    excess_vs_nifty50_21d: Optional[float] = None
    excess_vs_nifty50_63d: Optional[float] = None
    rs_vs_sector_index_63d: Optional[float] = None
    sector_index_name: Optional[str] = None
    rs_rank_t5: Optional[float] = None
    rs_rank_t15: Optional[float] = None
    rs_rank_t30: Optional[float] = None
    rs_percentile_ipo: Optional[float] = None
    trend_template_pass_n: Optional[int] = None
    trend_template_pass: Optional[bool] = None
    adr_20_pct: Optional[float] = None
    atr_pct: Optional[float] = None
    ema_10: Optional[float] = None
    ema_20: Optional[float] = None
    ema_50: Optional[float] = None
    ema_200: Optional[float] = None
    return_1m_pct: Optional[float] = None
    return_3m_pct: Optional[float] = None
    return_6m_pct: Optional[float] = None
    taxonomy: list[TaxonomyNode]
    adjustments: list[Adjustment]
    prices_adjusted: bool = False
    next_event: Optional[NextEvent] = None
    delivery_spark_60: list[Optional[float]]
    setups: dict[str, Optional[QueueRow]]


class BarRow(BaseModel):
    trade_date: Optional[date] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    raw_close: Optional[float] = None
    volume: Optional[int] = None
    delivery_pct: Optional[float] = None
    ema_10: Optional[float] = None
    ema_20: Optional[float] = None
    ema_50: Optional[float] = None
    ema_200: Optional[float] = None
    partial: bool = False


class DarvasBoxRow(BaseModel):
    start_date: Optional[date] = None
    formed_date: Optional[date] = None
    end_date: Optional[date] = None
    top: Optional[float] = None
    bottom: Optional[float] = None
    status: Literal["active", "broken_up", "broken_down", "superseded"] = "active"
    break_date: Optional[date] = None
    break_close: Optional[float] = None
    bars: Optional[int] = None


class RsRow(BaseModel):
    trade_date: Optional[date] = None
    close: Optional[float] = None
    midsml400_close: Optional[float] = None
    nifty50_close: Optional[float] = None
    rs_midsml400: Optional[float] = None
    rs_nifty50: Optional[float] = None
    rs_midsml400_new_high: Optional[bool] = None
    rs_nifty50_new_high: Optional[bool] = None


class EventRow(BaseModel):
    event_date: Optional[date] = None
    event_type: Optional[str] = None
    headline: Optional[str] = None
    source: str
    upcoming: bool = False


class TrendCriterion(BaseModel):
    key: str
    label: str
    passed: Optional[bool] = Field(None, description="NULL when an input is missing or the 252-session window spans a price gap")


class TrailPoint(BaseModel):
    trade_date: Optional[date] = None
    change_pct: Optional[float] = None
    rvol: Optional[float] = None
    delivery_pct: Optional[float] = None
    turnover_cr: Optional[float] = None


class StockProfileRow(StockBase):
    """Old Inspector sidecar blocks: Minervini checklist, institutional footprint, 5-session trail."""
    trade_date: Optional[date] = None
    trend_template_pass_n: Optional[int] = None
    trend_template_pass: Optional[bool] = None
    criteria: list[TrendCriterion]
    turnover_cr: Optional[float] = Field(None, description="Traded value that session, ₹ Cr")
    turnover_surge_pct: Optional[float] = Field(None, description="Turnover vs its 20-day average traded value, % above (+) / below (-)")
    avg_delivery_pct_20d: Optional[float] = None
    ticket_ratio: Optional[float] = Field(None, description="Average trade size ÷ its 20-day average")
    whale_ticket: Optional[bool] = Field(None, description="ticket_ratio >= 1.25")
    delivery_spike: Optional[bool] = None
    price_up_delivery_up: Optional[bool] = None
    nr7: Optional[bool] = None
    trail: list[TrailPoint]


class PeerRow(StockBase):
    rank: Optional[int] = Field(None, description="Rank by strength rank within the industry (1 = strongest); NULL = no rank")
    away_10ema_pct: Optional[float] = None
    is_target: bool = False
    stronger_near_10ema: bool = Field(False, description="Higher strength rank than the target and within ±3% of its 10 EMA")


class AccumulatorRow(StockBase):
    turnover_cr: Optional[float] = None
    turnover_surge_pct: Optional[float] = Field(None, description="Turnover vs its 20-day average traded value, % above")
    ticket_ratio: Optional[float] = None
    whale_ticket: Optional[bool] = None
    delivery_spike: Optional[bool] = None
    price_up_delivery_up: Optional[bool] = None


class StockDealRow(BaseModel):
    trade_date: Optional[date] = None
    client: Optional[str] = None
    side: Optional[str] = None
    quantity: Optional[int] = None
    price: Optional[float] = None
    value_cr: Optional[float] = None
    deal_types: Optional[str] = None
    clientele: Optional[str] = None
    is_prop: Optional[bool] = None
    institutional: Optional[bool] = None


class StockAnalogRow(BaseModel):
    """Final shape (stub until the evidence engine)."""

    trade_date: Optional[date] = None
    symbol: Optional[str] = None
    queue: Optional[str] = None
    distance: Optional[float] = None
    features: dict[str, Optional[float]] = Field(default_factory=dict)
    r_multiple: Optional[float] = None
    hit_2r: Optional[bool] = None
    days_held: Optional[int] = None


# --------------------------------------------------------------------------
# Evidence / research (final shapes; tables arrive with the evidence engine)
# --------------------------------------------------------------------------
class EvidenceRow(BaseModel):
    bucket: str
    n: int
    insufficient_sample: bool
    label: Optional[str] = None
    hit_rate_2r: Optional[float] = None
    avg_r: Optional[float] = None
    median_r: Optional[float] = None
    mae_pct: Optional[float] = None
    mfe_pct: Optional[float] = None


class MarketAnalogRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    analog_date: Optional[date] = None
    distance: Optional[float] = None
    fwd_midsml400_5d_pct: Optional[float] = None
    fwd_midsml400_20d_pct: Optional[float] = None
    fwd_midsml400_60d_pct: Optional[float] = None
    next_month_follow_through_pct: Optional[float] = None
    verdict_then: Optional[str] = None


class BigMoveRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    event_id: Optional[str] = None
    symbol: Optional[str] = None
    event_date: Optional[date] = None
    trigger: Optional[str] = Field(None, description="upper_circuit | up30_20d | up50_60d")
    mcap_cr_at_event: Optional[float] = None
    move_pct: Optional[float] = None
    catalyst: Optional[str] = Field(None, description="results | deal | sector | corporate_action | unexplained")
    industry: Optional[str] = None


class PreMoveRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    symbol: Optional[str] = None
    trade_date: Optional[date] = None
    matched_traits: Optional[list[str]] = None
    precision_20d: Optional[float] = None
    base_rate_20d: Optional[float] = None
    n: Optional[int] = None


class GroupStudyRow(BaseModel):
    """Big movers by taxonomy level (evidence engine, spec §7.6)."""

    model_config = ConfigDict(extra="allow")
    level: Optional[str] = None
    group_name: Optional[str] = None
    n_events: Optional[int] = None
    eligible_stock_days: Optional[int] = None
    events_per_1000_days: Optional[float] = None
    lift_vs_all: Optional[float] = None
    median_move_pct: Optional[float] = None
    label: Optional[str] = None


class MetricZone(BaseModel):
    model_config = ConfigDict(extra="allow")
    range: str
    label: str
    tone: Optional[str] = None
    why: Optional[str] = None


class MetricEntry(BaseModel):
    model_config = ConfigDict(extra="allow")
    key: str
    plain_name: str
    unit: Optional[str] = None
    measures: str
    zones: list[MetricZone]
    read_with: list[str]
    read_with_why: Optional[str] = None
    caveats: Optional[str] = None
    definition_sql_ref: str


# --------------------------------------------------------------------------
# User data
# --------------------------------------------------------------------------
class WatchlistItem(BaseModel):
    symbol: str
    position: Optional[int] = None
    added_at: Optional[datetime] = None


class WatchlistPut(BaseModel):
    symbols: list[str] = Field(..., max_length=1000)


class Note(BaseModel):
    symbol: str
    body: Optional[str] = None
    updated_at: Optional[datetime] = None


class NotePut(BaseModel):
    body: str = Field(..., max_length=20000)


# --------------------------------------------------------------------------
# Today (what moved, breakouts, groups today + why)
# --------------------------------------------------------------------------
class TodayIndex(BaseModel):
    name: str
    label: str
    close: Optional[float] = None
    return_1d_pct: Optional[float] = None
    return_5d_pct: Optional[float] = None
    return_20d_pct: Optional[float] = None


class TodayMarketRow(BaseModel):
    trade_date: Optional[date] = None
    indices: list[TodayIndex] = Field(default_factory=list)
    india_vix: Optional[float] = None
    vix_change_1d_pct: Optional[float] = None
    advancers: Optional[int] = None
    decliners: Optional[int] = None
    unchanged: Optional[int] = None
    advance_pct: Optional[float] = None
    new_52w_highs: Optional[int] = None
    new_52w_lows: Optional[int] = None
    new_52w_highs_5d_avg: Optional[float] = Field(None, description="Average of the prior 5 sessions")
    new_52w_lows_5d_avg: Optional[float] = None
    up_5pct: Optional[int] = Field(None, description="Stocks up >= 5% on the session")
    down_5pct: Optional[int] = None
    turnover_cr: Optional[float] = Field(None, description="Sum of every stock's traded value, ₹ Cr")
    turnover_20d_avg_cr: Optional[float] = Field(None, description="Average of the prior 20 sessions, ₹ Cr")
    turnover_vs_20d: Optional[float] = None
    delivery_pct: Optional[float] = Field(None, description="Delivered value ÷ traded value (EQ series), %")
    delivery_pct_20d_avg: Optional[float] = None
    deliv_pct_x: Optional[float] = Field(None, description="Market delivery % ÷ its prior 20-session average")


class TodayEvent(BaseModel):
    event_type: Optional[str] = None
    event_date: Optional[date] = None
    when: Optional[Literal["past", "today", "upcoming"]] = None
    headline: Optional[str] = None


class TodayNews(BaseModel):
    event_type: str
    label: str
    headline: Optional[str] = None


class TodayStockRow(StockBase):
    turnover_cr: Optional[float] = None
    turnover_vs_20d: Optional[float] = Field(None, description="Turnover ÷ average traded value of the prior 20 sessions")
    deliv_qty_x: Optional[float] = Field(
        None, description="Delivered qty ×20d: delivered shares ÷ average delivered shares of the prior 20 sessions (drives quality / footprints)")
    delivery_spike: Optional[bool] = Field(None, description="Delivered shares > 2 × their 20-day average")
    away_52w_high_pct: Optional[float] = None
    is_52w_high: Optional[bool] = None
    circuit_band: Optional[float] = Field(None, description="Price band %, point-in-time where available")
    at_upper_circuit: Optional[bool] = None
    at_lower_circuit: Optional[bool] = None
    gap_pct: Optional[float] = Field(None, description="Open vs previous close, %")
    queues: list[str] = Field(default_factory=list, description="Daily Desk queues the stock is in on as_of")
    deal_prints_today: Optional[int] = None
    deal_net_cr_today: Optional[float] = Field(None, description="Bulk/block net today, PROP excluded, ₹ Cr")
    deal_event_type: Optional[str] = Field(None, description="deal_session_net event type (accumulate / distribute / churn …)")
    results_nearby: Optional[TodayEvent] = Field(None, description="Results board meeting / financial results within ±5 sessions")
    corp_action_nearby: Optional[TodayEvent] = None
    news_today: list[TodayNews] = Field(default_factory=list)
    quality: Optional[str] = Field(None, description="Quality of move label (meta.context.quality_rules)")
    quality_id: Optional[str] = None
    quality_tone: Optional[str] = None
    traits: list[str] = Field(default_factory=list, description="Evidence pre-move traits present: delivery_spike, rvol_1_5, results_5")


class TodayMoverRow(TodayStockRow):
    side: Literal["gainer", "loser"]
    rank: int


class TodayBreakoutRow(TodayStockRow):
    kinds: list[str] = Field(default_factory=list, description="Rule ids from meta.context.rules")
    setup_queue: Optional[str] = None
    setup_trigger: Optional[float] = Field(None, description="Trigger carried on the previous session that the close crossed")


class TodayContributor(BaseModel):
    symbol: str
    change_1d_pct: Optional[float] = None
    contribution: Optional[float] = Field(None, description="Points of the equal-weight group return")
    share_of_move_pct: Optional[float] = None
    weight_pct: Optional[float] = None
    rvol: Optional[float] = None
    deliv_qty_x: Optional[float] = Field(None, description="Delivered qty ×20d: delivered shares ÷ prior 20-session average")


class TodayGroupRow(BaseModel):
    id: str
    level: str
    group_name: str
    stocks: int
    stocks_with_return: int
    return_1d: Optional[float] = Field(None, description="Equal-weight mean 1D change of members, %")
    advancers: Optional[int] = None
    decliners: Optional[int] = None
    pct_up: Optional[float] = None
    pct_down: Optional[float] = None
    pct_up_2: Optional[float] = Field(None, description="% of members up more than 2%")
    pct_down_2: Optional[float] = None
    turnover_cr: Optional[float] = None
    turnover_vs_20d: Optional[float] = None
    deliv_qty_x: Optional[float] = Field(None, description="Members' delivered shares ÷ their prior 20-session average (Delivered qty ×20d)")
    top_contributors: list[TodayContributor] = Field(default_factory=list)
    top_detractors: list[TodayContributor] = Field(default_factory=list)
    top1_share_pct: Optional[float] = Field(None, description="Largest contributor's share of the group move, %")
    breadth_label: Optional[str] = Field(None, description="broad | mixed | one-stock | flat | thin")
    participation_id: Optional[str] = None
    participation: Optional[str] = None
    deal_stocks: Optional[int] = None
    deal_buyers: Optional[int] = None
    deal_sellers: Optional[int] = None
    deal_net_cr: Optional[float] = None
    results_nearby_n: Optional[int] = None
    news_today_n: Optional[int] = None
    news_types: dict[str, int] = Field(default_factory=dict)
    return_5d: Optional[float] = None
    return_21d: Optional[float] = None
    rank: Optional[int] = Field(None, description="group_daily rank (mean 21d/63d excess vs MidSml400)")
    rank_delta_5: Optional[int] = None
    rank_n: Optional[int] = None
    rank_1d: Optional[int] = Field(None, description="Rank by today's return among groups with >= 3 members")
    rank_1d_n: Optional[int] = None
    context_source: Optional[str] = None
    persistence_id: Optional[str] = None
    persistence: Optional[str] = None
    persistence_phrase: Optional[str] = None
    symbols: list[str] = Field(default_factory=list, description="Members in move order (for charts / copy)")
    why: Optional[str] = Field(None, description="Plain-language sentence built only from the facts in this row")


# --------------------------------------------------------------------------
# Cross-tab context (connect the dots) and history views
# --------------------------------------------------------------------------
class GroupContext(BaseModel):
    id: str
    group_name: Optional[str] = None
    level: str
    stocks: Optional[int] = None
    thin: bool = Field(False, description="Fewer than 3 members: listed, not ranked")
    health: Optional[float] = None
    health_zone: Optional[Literal["Healthy", "Mixed", "Weak"]] = None
    health_rank: Optional[int] = None
    rrg_quadrant: Optional[str] = None
    quadrant_note: Optional[str] = Field(None, description="'falling' / 'narrow' caveat on a Leading / Improving group")
    abs_trend: Optional[str] = None
    return_ew_21d: Optional[float] = None
    health_spark_21: Optional[list[Optional[float]]] = Field(None, description="Health over the last 21 sessions, oldest first")


class ContextSetup(BaseModel):
    queue: str
    label: str
    trigger_price: Optional[float] = None
    stop_price: Optional[float] = None
    distance_to_trigger_pct: Optional[float] = None
    risk_pct: Optional[float] = None
    setup_age_sessions: Optional[int] = None
    first_seen: Optional[date] = None
    flavor: Optional[str] = None


class ContextEvent(BaseModel):
    event_type: Optional[str] = None
    event_date: Optional[date] = None
    headline: Optional[str] = None


class StockContextRow(BaseModel):
    symbol: str
    security_name: Optional[str] = None
    in_session: bool = Field(False, description="The symbol has an indicators_daily row on as_of")
    industry: Optional[str] = None
    group: Optional[GroupContext] = Field(None, description="Its industry group at the ₹1,000 Cr floor")
    deal_net_10s_cr: Optional[float] = Field(None, description="Bulk/block net over 10 sessions, PROP excluded, ₹ Cr")
    deal_prints_10s: int = 0
    deal_last_date: Optional[date] = None
    setups: list[ContextSetup] = Field(default_factory=list, description="Desk queues the stock is in on as_of")
    data_warning: Optional[str] = None
    next_results: Optional[ContextEvent] = Field(None, description="Results / board meeting within 14 days")
    next_corp_action: Optional[ContextEvent] = Field(None, description="Split / bonus / dividend … ex-date within 14 days")


class WhyBullet(BaseModel):
    kind: Literal["setup", "trigger", "evidence", "group", "deals", "footprint", "event", "data", "environment"]
    tone: Literal["positive", "negative", "neutral", "warn", "info", "accent"]
    text: str = Field(..., description="Plain-language sentence restating stored facts")
    link: Optional[str] = Field(None, description="In-app path for the underlying view")
    facts: dict[str, Any] = Field(default_factory=dict)


class CompareRow(BaseModel):
    key: str
    label: str
    group: Literal["Queues", "Breadth"]
    unit: str
    better: Optional[Literal["up", "down"]] = None
    now: Optional[float] = None
    then: Optional[float] = None
    delta: Optional[float] = None


class RotationCell(BaseModel):
    week_end: Optional[date] = None
    health: Optional[float] = None
    health_rank: Optional[int] = None
    rrg_quadrant: Optional[str] = None


class RotationRow(BaseModel):
    id: str
    group_name: str
    level: str
    stocks: Optional[int] = None
    health_now: Optional[float] = None
    health_change: Optional[float] = Field(None, description="Health, last week minus first week of the grid")
    cells: list[RotationCell] = Field(default_factory=list, description="One per week_end in meta.context.weeks")
