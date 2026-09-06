"""Canonical Global Column Registry for MarketPulse.

Enforces a single, professional financial terminal standard (TradingView / Koyfin style)
for column names, widths, min-widths, alignments, and Quasar/NiceGUI table specifications
across all pages in MarketPulse.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ColumnContract:
    key: str
    label: str
    width_px: int
    min_width_px: int
    align: str = "left"
    format_type: str = "text"
    wrap: bool = False
    sticky: bool = False
    group: str = ""


# Global Canonical Dictionary mapping every system field to its professional standard
GLOBAL_COLUMNS: dict[str, ColumnContract] = {
    # Identity & Hierarchy
    "symbol": ColumnContract("symbol", "SYMBOL", 112, 100, align="left", sticky=True, group="Identity"),
    "security_name": ColumnContract("security_name", "COMPANY", 180, 150, align="left", wrap=True, group="Identity"),
    "group_name": ColumnContract("group_name", "SECTOR / GROUP", 210, 180, align="left", sticky=True, wrap=True, group="Identity"),
    "sector": ColumnContract("sector", "SECTOR", 176, 150, align="left", wrap=True, group="Identity"),
    "broad_sector": ColumnContract("broad_sector", "BROAD SECTOR", 176, 150, align="left", wrap=True, group="Identity"),
    "industry": ColumnContract("industry", "INDUSTRY", 176, 150, align="left", wrap=True, group="Identity"),
    "broad_industry": ColumnContract("broad_industry", "BROAD INDUSTRY", 176, 150, align="left", wrap=True, group="Identity"),
    "client_name": ColumnContract("client_name", "CLIENT", 220, 180, align="left", wrap=True, group="Flow"),
    "index_name": ColumnContract("index_name", "INDEX", 180, 150, align="left", group="Identity"),
    "pillar": ColumnContract("pillar", "PILLAR", 130, 110, align="left", group="Identity"),
    "role_desc": ColumnContract("role_desc", "ROLE IN THEME", 200, 160, align="left", wrap=True, group="Identity"),
    "theme": ColumnContract("theme", "MACRO THEME", 160, 130, align="left", wrap=True, group="Identity"),
    "clean_name": ColumnContract("clean_name", "INDEX", 210, 170, align="left", sticky=True, group="Identity"),
    "ema_stack": ColumnContract("ema_stack", "EMA STACK", 130, 110, align="center", group="Setup"),
    "rs_trail": ColumnContract("rs_trail", "RS TRAIL (4W)", 170, 140, align="center", group="Setup"),
    "rsi_14": ColumnContract("rsi_14", "RS", 66, 56, align="right", format_type="numeric", group="Setup"),

    # Rank & Status
    "rank": ColumnContract("rank", "RANK", 56, 48, align="center", format_type="numeric", group="Setup"),
    "rotation_rank": ColumnContract("rotation_rank", "RANK", 56, 48, align="center", format_type="numeric", group="Setup"),
    "rs_rank": ColumnContract("rs_rank", "RS RANK", 64, 56, align="center", format_type="numeric", group="Setup"),
    "rank_change_5d": ColumnContract("rank_change_5d", "RANK Δ", 68, 58, align="center", format_type="numeric", group="Setup"),
    "rotation_state": ColumnContract("rotation_state", "STATE", 96, 88, align="center", format_type="badge", group="Setup"),
    "state": ColumnContract("state", "STATE", 96, 88, align="center", format_type="badge", group="Setup"),
    "candidate_state": ColumnContract("candidate_state", "STATE", 96, 88, align="center", format_type="badge", group="Setup"),
    "setup_class": ColumnContract("setup_class", "STATE", 96, 88, align="center", format_type="badge", group="Setup"),
    "status": ColumnContract("status", "STATUS", 96, 80, align="center", group="Context"),
    "vcp_state": ColumnContract("vcp_state", "VCP", 104, 90, align="center", format_type="badge", group="Setup"),
    "sector_state": ColumnContract("sector_state", "SECTOR STATE", 110, 96, align="center", format_type="badge", group="Setup"),
    "industry_state": ColumnContract("industry_state", "INDUSTRY STATE", 110, 96, align="center", format_type="badge", group="Setup"),
    "side": ColumnContract("side", "SIDE", 70, 60, align="center", format_type="badge", group="Flow"),
    "band": ColumnContract("band", "BAND", 70, 60, align="center", group="Risk"),

    # Prices & Levels
    "close_price": ColumnContract("close_price", "CMP", 90, 80, align="right", format_type="currency", group="Market"),
    "cmp": ColumnContract("cmp", "CMP", 90, 80, align="right", format_type="currency", group="Market"),
    "sell_price": ColumnContract("sell_price", "SELL PX", 92, 84, align="right", format_type="currency", group="Action"),
    "avg_buy_price": ColumnContract("avg_buy_price", "AVG BUY", 92, 84, align="right", format_type="currency", group="Action"),
    "inst_vwap": ColumnContract("inst_vwap", "AVG BUY", 92, 84, align="right", format_type="currency", group="Flow"),
    "exit_price": ColumnContract("exit_price", "EXIT PX", 92, 84, align="right", format_type="currency", group="Action"),
    "trigger_price": ColumnContract("trigger_price", "TRIGGER", 88, 80, align="right", format_type="currency", group="Action"),
    "invalidation_price": ColumnContract("invalidation_price", "STOP", 84, 76, align="right", format_type="currency", group="Risk"),
    "stop_loss": ColumnContract("stop_loss", "STOP", 84, 76, align="right", format_type="currency", group="Risk"),
    "first_resistance": ColumnContract("first_resistance", "RESISTANCE", 92, 84, align="right", format_type="currency", group="Risk"),
    "pivot": ColumnContract("pivot", "PIVOT", 88, 80, align="right", format_type="currency", group="Setup"),
    "low": ColumnContract("low", "LOW", 88, 80, align="right", format_type="currency", group="Market"),
    "high": ColumnContract("high", "HIGH", 88, 80, align="right", format_type="currency", group="Market"),

    # Returns & Performance
    "day_pct": ColumnContract("day_pct", "1D %", 78, 68, align="right", format_type="pct", group="Market"),
    "return_1d_pct": ColumnContract("return_1d_pct", "1D %", 78, 68, align="right", format_type="pct", group="Market"),
    "day_change_pct": ColumnContract("day_change_pct", "1D %", 78, 68, align="right", format_type="pct", group="Market"),
    "pct_change": ColumnContract("pct_change", "1D %", 78, 68, align="right", format_type="pct", group="Market"),
    "week_pct": ColumnContract("week_pct", "5D %", 78, 68, align="right", format_type="pct", group="Market"),
    "return_5d_pct": ColumnContract("return_5d_pct", "5D %", 78, 68, align="right", format_type="pct", group="Market"),
    "month_pct": ColumnContract("month_pct", "1M %", 78, 68, align="right", format_type="pct", group="Market"),
    "return_1m_pct": ColumnContract("return_1m_pct", "1M %", 78, 68, align="right", format_type="pct", group="Market"),
    "return_3m_pct": ColumnContract("return_3m_pct", "3M %", 78, 68, align="right", format_type="pct", group="Market"),
    "return_6m_pct": ColumnContract("return_6m_pct", "6M %", 78, 68, align="right", format_type="pct", group="Market"),
    "return_12m_pct": ColumnContract("return_12m_pct", "12M %", 78, 68, align="right", format_type="pct", group="Market"),
    "unrealized_pct": ColumnContract("unrealized_pct", "U/R %", 80, 70, align="right", format_type="pct", group="Performance"),
    "realized_pct": ColumnContract("realized_pct", "RLZ %", 80, 70, align="right", format_type="pct", group="Performance"),
    "weight_pct": ColumnContract("weight_pct", "WT %", 72, 64, align="right", format_type="pct", group="Performance"),

    # Relative Strength & Scores
    "rs_percentile": ColumnContract("rs_percentile", "RS", 62, 54, align="right", format_type="numeric", group="Setup"),
    "rs": ColumnContract("rs", "RS", 62, 54, align="right", format_type="numeric", group="Setup"),
    "rs_5d_trail": ColumnContract("rs_5d_trail", "RS 5D TRAIL", 160, 140, align="center", format_type="text", group="Setup"),
    "rs_vs_nifty_63d": ColumnContract("rs_vs_nifty_63d", "VS NIFTY 63D", 96, 88, align="right", format_type="numeric", group="Setup"),
    "total_score": ColumnContract("total_score", "SCORE", 68, 60, align="right", format_type="numeric", group="Setup"),
    "quality_score": ColumnContract("quality_score", "FUNDA", 68, 60, align="right", format_type="numeric", group="Quality"),
    "focus_score": ColumnContract("focus_score", "FOCUS", 68, 60, align="right", format_type="numeric", group="Setup"),

    # Moving Average Distances & Breadth
    "away_10ema_pct": ColumnContract("away_10ema_pct", "VS 10EMA", 82, 74, align="right", format_type="pct", group="Setup"),
    "away_20ema_pct": ColumnContract("away_20ema_pct", "VS 20EMA", 82, 74, align="right", format_type="pct", group="Setup"),
    "away_50ema_pct": ColumnContract("away_50ema_pct", "VS 50EMA", 82, 74, align="right", format_type="pct", group="Setup"),
    "away_52w_high_pct": ColumnContract("away_52w_high_pct", "52W %", 76, 68, align="right", format_type="pct", group="Setup"),
    "distance_below_52w": ColumnContract("distance_below_52w", "52W %", 76, 68, align="right", format_type="pct", group="Setup"),
    "away_52w_low_pct": ColumnContract("away_52w_low_pct", "52W LOW %", 76, 68, align="right", format_type="pct", group="Setup"),
    "above_50": ColumnContract("above_50", ">50 EMA", 84, 74, align="right", format_type="pct", group="Breadth"),
    "above_50ema_pct": ColumnContract("above_50ema_pct", ">50 EMA", 84, 74, align="right", format_type="pct", group="Breadth"),
    "above_200ema_pct": ColumnContract("above_200ema_pct", ">200 EMA", 88, 78, align="right", format_type="pct", group="Breadth"),
    "advance_pct": ColumnContract("advance_pct", "ADVANCE %", 88, 78, align="right", format_type="pct", group="Breadth"),
    "near_52w_highs": ColumnContract("near_52w_highs", "NEAR 52W", 82, 72, align="center", format_type="numeric", group="Breadth"),
    "new_20d_highs": ColumnContract("new_20d_highs", "NEW 20D", 80, 70, align="center", format_type="numeric", group="Breadth"),

    # Turnover, Volume & Deals
    "market_cap_cr": ColumnContract("market_cap_cr", "MCAP", 98, 88, align="right", format_type="currency", group="Identity"),
    "turnover_cr": ColumnContract("turnover_cr", "TURNOVER", 102, 90, align="right", format_type="currency", group="Flow"),
    "turnover_1d_cr": ColumnContract("turnover_1d_cr", "TURNOVER", 102, 90, align="right", format_type="currency", group="Flow"),
    "t_o_today": ColumnContract("t_o_today", "TURNOVER", 102, 90, align="right", format_type="currency", group="Flow"),
    "turnover_share_pct": ColumnContract("turnover_share_pct", "SHARE %", 78, 68, align="right", format_type="pct", group="Flow"),
    "turnover_expansion": ColumnContract("turnover_expansion", "VS 20D", 80, 70, align="right", format_type="multiple", group="Flow"),
    "vs_20d": ColumnContract("vs_20d", "VS 20D", 80, 70, align="right", format_type="multiple", group="Flow"),
    "rvol": ColumnContract("rvol", "RVOL", 68, 60, align="right", format_type="multiple", group="Flow"),
    "vol_shock": ColumnContract("vol_shock", "VOL SHOCK", 88, 78, align="right", format_type="multiple", group="Flow"),
    "delivery_pct": ColumnContract("delivery_pct", "DELIV %", 78, 68, align="right", format_type="pct", group="Flow"),
    "delivery_delta": ColumnContract("delivery_delta", "DELIV Δ", 78, 68, align="right", format_type="pct", group="Flow"),
    "deal_value_cr": ColumnContract("deal_value_cr", "DEAL CR", 92, 82, align="right", format_type="currency", group="Flow"),
    "buy_deal_cr": ColumnContract("buy_deal_cr", "BUY CR", 92, 82, align="right", format_type="currency", group="Flow"),
    "buy_value_cr": ColumnContract("buy_value_cr", "BUY CR", 92, 82, align="right", format_type="currency", group="Flow"),
    "total_buy_cr": ColumnContract("total_buy_cr", "BUY CR", 92, 82, align="right", format_type="currency", group="Flow"),
    "sell_deal_cr": ColumnContract("sell_deal_cr", "SELL CR", 92, 82, align="right", format_type="currency", group="Flow"),
    "sell_value_cr": ColumnContract("sell_value_cr", "SELL CR", 92, 82, align="right", format_type="currency", group="Flow"),
    "net_deal_cr": ColumnContract("net_deal_cr", "NET CR", 92, 82, align="right", format_type="currency", group="Flow"),
    "net_value_cr": ColumnContract("net_value_cr", "NET CR", 92, 82, align="right", format_type="currency", group="Flow"),
    "deal_net_10s_cr": ColumnContract("deal_net_10s_cr", "NET 10S", 88, 78, align="right", format_type="currency", group="Flow"),
    "deal_count": ColumnContract("deal_count", "DEALS", 70, 60, align="center", format_type="numeric", group="Flow"),
    "client_count": ColumnContract("client_count", "INST", 64, 56, align="center", format_type="numeric", group="Flow"),
    "inst_count": ColumnContract("inst_count", "INST", 64, 56, align="center", format_type="numeric", group="Flow"),
    "institutions_count": ColumnContract("institutions_count", "INST", 64, 56, align="center", format_type="numeric", group="Flow"),
    "active_days": ColumnContract("active_days", "DAYS", 64, 56, align="center", format_type="numeric", group="Flow"),
    "clientele": ColumnContract("clientele", "CLIENTELE", 110, 96, align="left", wrap=True, group="Flow"),
    "deal_when": ColumnContract("deal_when", "DATE", 100, 90, align="center", group="Flow"),
    "latest_deal_date": ColumnContract("latest_deal_date", "DATE", 100, 90, align="center", group="Flow"),
    "trade_date": ColumnContract("trade_date", "DATE", 100, 90, align="center", group="Market"),
    "exit_date": ColumnContract("exit_date", "DATE", 100, 90, align="center", group="Action"),

    # Multi-Symbol & Informational
    "top_leaders": ColumnContract("top_leaders", "LEADERS", 280, 240, align="left", format_type="chips", group="Context"),
    "leaders": ColumnContract("leaders", "LEADERS", 280, 240, align="left", format_type="chips", group="Context"),
    "symbol_preview": ColumnContract("symbol_preview", "SYMBOLS", 260, 200, align="left", wrap=True, group="Identity"),
    "symbol_list": ColumnContract("symbol_list", "SYMBOL LIST", 260, 200, align="left", wrap=True, group="Identity"),
    "symbols": ColumnContract("symbols", "SYMBOLS", 260, 200, align="left", wrap=True, group="Identity"),
    "why_focus": ColumnContract("why_focus", "THESIS", 260, 200, align="left", wrap=True, group="Context"),
    "why_now": ColumnContract("why_now", "THESIS", 260, 200, align="left", wrap=True, group="Context"),
    "notes": ColumnContract("notes", "NOTES", 220, 160, align="left", wrap=True, group="Context"),
    "tags": ColumnContract("tags", "TAGS", 160, 120, align="left", wrap=True, group="Context"),
    "copy_symbols": ColumnContract("copy_symbols", "COPY", 64, 56, align="center", group="Action"),
    "close_position": ColumnContract("close_position", "CLOSE", 68, 60, align="center", group="Action"),
    "actions": ColumnContract("actions", "ACTIONS", 84, 72, align="center", group="Action"),

    # Financial Ratios & Fundamentals
    "pe": ColumnContract("pe", "P/E", 64, 56, align="right", format_type="multiple", group="Quality"),
    "roe": ColumnContract("roe", "ROE", 68, 60, align="right", format_type="pct", group="Quality"),
    "revenue_cagr_3y": ColumnContract("revenue_cagr_3y", "REV 3Y", 78, 68, align="right", format_type="pct", group="Quality"),
    "debt_to_equity": ColumnContract("debt_to_equity", "D/E", 64, 56, align="right", format_type="multiple", group="Quality"),
    "promoter_pledge_pct": ColumnContract("promoter_pledge_pct", "PLEDGE", 76, 68, align="right", format_type="pct", group="Quality"),

    # Portfolio & Risk
    "qty": ColumnContract("qty", "QTY", 76, 68, align="right", format_type="numeric", group="Action"),
    "unrealized_pnl_inr": ColumnContract("unrealized_pnl_inr", "U/R ₹", 98, 88, align="right", format_type="currency", group="Performance"),
    "realized_pnl_inr": ColumnContract("realized_pnl_inr", "RLZ ₹", 98, 88, align="right", format_type="currency", group="Performance"),
    "market_value_inr": ColumnContract("market_value_inr", "MKT ₹", 102, 90, align="right", format_type="currency", group="Performance"),
    "cost_value_inr": ColumnContract("cost_value_inr", "COST ₹", 102, 90, align="right", format_type="currency", group="Performance"),
    "profit_inr": ColumnContract("profit_inr", "P&L ₹", 98, 88, align="right", format_type="currency", group="Performance"),
    "days_held": ColumnContract("days_held", "DAYS", 64, 56, align="center", format_type="numeric", group="Performance"),
    "reward_to_risk": ColumnContract("reward_to_risk", "R:R", 60, 54, align="right", format_type="multiple", group="Risk"),
    "initial_risk_pct": ColumnContract("initial_risk_pct", "RISK %", 76, 68, align="right", format_type="pct", group="Risk"),
    "risk_pct": ColumnContract("risk_pct", "RISK %", 76, 68, align="right", format_type="pct", group="Risk"),
    "distance_to_trigger_pct": ColumnContract("distance_to_trigger_pct", "DIST %", 74, 64, align="right", format_type="pct", group="Risk"),
    "dist_to_trigger_pct": ColumnContract("dist_to_trigger_pct", "DIST %", 74, 64, align="right", format_type="pct", group="Risk"),
    "deal_flow": ColumnContract("deal_flow", "DEAL FLOW", 110, 95, align="center", format_type="text", group="Flow"),
    "setup_type": ColumnContract("setup_type", "SETUP", 120, 100, align="center", format_type="badge", group="Setup"),
    "event_risk": ColumnContract("event_risk", "EVENT", 96, 80, align="center", group="Action"),
    "event_date": ColumnContract("event_date", "EVENT DATE", 104, 90, align="center", group="Action"),
}


def get_column_contract(key: str) -> ColumnContract:
    """Retrieve the canonical contract for a column, with a robust auto-fallback."""
    clean_key = str(key).strip().lower()
    contract = GLOBAL_COLUMNS.get(clean_key)
    if contract is not None:
        return contract

    # Fallback for dynamic / unknown fields
    label = str(key).replace("_", " ").upper()
    return ColumnContract(
        key=key,
        label=label,
        width_px=96,
        min_width_px=80,
        align="left",
    )


def get_column_label(key: str) -> str:
    """Return the global standard label for a column key."""
    return get_column_contract(key).label


def get_quasar_column_def(
    key: str,
    *,
    field: str | None = None,
    label_override: str | None = None,
    sortable: bool = True,
    width_override: int | None = None,
    min_width_override: int | None = None,
) -> dict[str, Any]:
    """Generate a fully-styled Quasar/NiceGUI column definition dictionary.

    Guarantees consistent width, min-width, alignment, and wrapping styling
    so columns never collapse or clip unexpectedly.
    """
    contract = get_column_contract(key)
    field_name = field or contract.key
    label = label_override if label_override is not None else contract.label
    width = width_override or contract.width_px
    min_width = min_width_override or contract.min_width_px

    # CSS classes
    classes = []
    if contract.align == "right":
        classes.append("numeric")
    elif contract.align == "center":
        classes.append("action-col")
    elif contract.key == "symbol":
        classes.append("symbol-col")
    elif contract.key in {"symbols", "symbol_list", "symbol_preview", "top_leaders", "leaders"}:
        classes.append("symbols-col")
    else:
        classes.append("text-col")

    if contract.sticky:
        classes.append("mp-sticky-col")

    width_decl = f"width:{width}px;min-width:{min_width}px;"
    if contract.wrap:
        classes.append("mp-wrap-col")
        style = f"{width_decl}max-width:{width + 80}px;white-space:normal;word-break:break-word;vertical-align:middle;"
        header_style = f"{width_decl}white-space:normal;line-height:1.2;"
    else:
        style = f"{width_decl}white-space:nowrap;overflow:hidden;text-overflow:ellipsis;"
        header_style = f"{width_decl}white-space:normal;line-height:1.2;"

    cls_str = " ".join(classes)
    return {
        "name": field_name,
        "label": label,
        "field": field_name,
        "sortable": sortable,
        "align": contract.align,
        "style": style,
        "headerStyle": header_style,
        "classes": cls_str,
        "headerClasses": f"{cls_str} mp-th",
    }


def table_min_width_px(keys: list[str] | tuple[str, ...]) -> int:
    """Return the cumulative minimum width required by an ordered list of columns."""
    return sum(get_column_contract(k).min_width_px for k in keys)


__all__ = [
    "ColumnContract",
    "GLOBAL_COLUMNS",
    "get_column_contract",
    "get_column_label",
    "get_quasar_column_def",
    "table_min_width_px",
]
