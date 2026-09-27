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
    delivery_vs_20d: Optional[float] = None
    rs_percentile: Optional[float] = None
    rs_delta_5: Optional[float] = None
    excess_vs_midsml400_63d: Optional[float] = None
    market_cap_cr: Optional[float] = None
    adv_cr_20d: Optional[float] = None


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
    tail: list[RrgPoint]


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
