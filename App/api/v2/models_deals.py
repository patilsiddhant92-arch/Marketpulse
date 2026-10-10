"""Response rows of the Deals tab endpoints (App/api/v2/routes_deals.py, services in App/services/deals_tab.py).

Shapes come from Scripts/derived/deal_desk.py (shared with the Telegram digest). Field nullability mirrors what the
services emit: every key is always present (Optional = may be null), except `earlier` (Today / Watch / stock
drawer rows only) and `verdict` on an earlier deal (stock drawer only). `extra="allow"` keeps
any field a later service adds on the wire until it is typed here (the response model never silently drops it).
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Verdict = Literal["confirm", "watch", "place", "absorbed", "supply", "none", "churn", "avoid", "ignore"]
Side = Literal["B", "S", "P", "T", "C"]
EventType = Literal["fresh", "accumulate", "placement", "distribute", "churn", "transfer_interse"]
Grade = Literal["good", "mixed", "poor", "ungraded"]
PatternKey = Literal["repeat_buy", "single_buy", "selling_only", "mixed", "churn_only", "transfers_only"]


class _Row(BaseModel):
    model_config = ConfigDict(extra="allow")


class DealParty(_Row):
    """A buyer or seller of the deal session (non-PROP), with its house record."""
    name: str
    house: str
    buyer_class: str
    value_cr: float
    grade: Grade
    record_n: int


class DealEarlier(_Row):
    """An earlier deal session of the same stock inside the watch window."""
    deal_date: str
    event_type: EventType
    side: Optional[Side]
    net_cr: float
    deal_price: Optional[float]
    verdict: Optional[Verdict] = None


class DealTabRow(_Row):
    """One stock-session with its evidence verdict (Today, Deal watch, stock drawer)."""
    symbol: str
    name: str
    deal_date: str
    sessions_since: int
    event_type: EventType
    side: Optional[Side]
    event_label: str
    verdict: Verdict
    verdict_title: str
    why: str
    next_action: str
    net_cr: float = Field(description="Net ₹ Cr ex-PROP")
    bought_cr: float
    gross_cr: Optional[float]
    prop_cr: Optional[float]
    deal_price: Optional[float] = Field(description="Buy VWAP (sell VWAP for net sells); the deal level")
    close: float
    vs_deal_pct: Optional[float]
    status: Optional[str] = Field(description="day 0 / holding / lost / reclaimed / below seller")
    strong_chart: bool
    rs: Optional[float]
    from_high_pct: Optional[float]
    month_pct: Optional[float]
    rvol: Optional[float]
    mcap_cr: Optional[float]
    industry: Optional[str]
    sector: Optional[str]
    buyers: list[DealParty]
    sellers: list[DealParty]
    chips: list[str]
    earlier: Optional[list[DealEarlier]] = None


class DealHistoryRow(_Row):
    symbol: str
    industry: Optional[str]
    pattern: PatternKey
    pattern_label: str
    buy_sessions: int
    sell_sessions: int
    churn_sessions: int
    net_cr: float
    prop_cr: float
    avg_deal_price: Optional[float]
    close: float
    vs_deal_pct: Optional[float]
    cells: list[Optional[Side]] = Field(description="One cell per deal session, oldest first")


class DealSpreadItem(_Row):
    industry: str
    value_cr: float
    share_pct: float
    symbols: list[str]


class DealHouseRow(_Row):
    house: str
    name: str
    buyer_class: str
    bought_cr: Optional[float]
    symbols: list[str]
    grade: Grade
    record_n: int
    record_avg_pct: Optional[float]
    record_beat_pct: Optional[float]
    spread: list[DealSpreadItem]


class DealGroupRow(_Row):
    industry: str
    sector: Optional[str]
    buying_names: int
    selling_names: int
    flow_cr: float
    symbols: list[str]
    three_plus_buyers: bool


class DealTelegramRow(_Row):
    text: str
    chars: int
    max_chars: int


class DealCandle(_Row):
    date: str
    open: Optional[float]
    high: Optional[float]
    low: Optional[float]
    close: Optional[float]


class DealMarker(_Row):
    date: str
    side: Optional[Side]
    event_type: EventType
    price: Optional[float]
    net_cr: Optional[float]
    gross_cr: Optional[float]


class DealStockDetail(_Row):
    symbol: str
    deal: Optional[DealTabRow]
    candles: list[DealCandle]
    markers: list[DealMarker]
    price_lines: list[DealMarker]


class DealHousePosition(_Row):
    symbol: str
    deal_date: str
    bought_cr: Optional[float]
    deal_price: Optional[float]
    buyer_class: str
    entry_date: Optional[str]
    since_entry_pct: Optional[float]
    market_pct: Optional[float]
    vs_market_pct: Optional[float]
    verdict: Optional[Verdict]
    verdict_title: Optional[str]
    status: Optional[str]


class DealFlagRow(_Row):
    symbol: str
    has_recent_deal: bool
    last_deal_date: Optional[str]
    deal_sessions_ago: Optional[int]
    side: Optional[Side]
    event_type: Optional[EventType]
    deal_sessions_in_window: int
    verdict: Optional[Verdict]
    verdict_title: Optional[str]
    deal_price: Optional[float]
    status: Optional[str]
    vs_deal_pct: Optional[float]
