"""How a number is shown — meaning first, color only when the number is P&L.

Green/red is for signed returns and net buy/sell. Delivery 52%, distance from a
52-week high, and rupee turnover are levels, not a down-day.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

SIGNED_RETURN = frozenset(
    {
        "day_pct",
        "week_pct",
        "month_pct",
        "day_change_pct",
        "return_1d_pct",
        "return_5d_pct",
        "return_1m_pct",
        "return_3m_pct",
        "return_6m_pct",
        "return_9m_pct",
        "return_12m_pct",
        "avg_1d_pct",
        "avg_1w_pct",
        "avg_1m_pct",
        "avg_day_pct",
        "pnl_pct",
        "avg_pnl_pct",
        "unrealized_pct",
        "realized_pct",
        "forward_return_pct",
        "cmp_vs_inst_entry_pct",
        "deal_price_vs_close_pct",
    }
)
LEVEL_PCT = frozenset(
    {
        "delivery_pct",
        "advance_pct",
        "advance_count_pct",
        "above_10ema_pct",
        "above_50ema_pct",
        "above_200ema_pct",
        "above_50",
        "weight_pct",
        "deal_pct_volume",
        "deal_volume_pct",
        "close_location_pct",
        "risk_pct",
        "reward_pct",
        "initial_risk_pct",
        "turnover_share_pct",
        "volume_dryup_pct",
        "atr_pct",
        "range_5d_pct",
        "range_10d_pct",
        "range_20d_pct",
    }
)
DISTANCE = frozenset(
    {
        "away_52w_high_pct",
        "away_52w_low_pct",
        "away_10ema_pct",
        "away_10wema_pct",
        "away_10mema_pct",
        "away_database_high_pct",
        "distance_to_high_pct",
        "distance_to_trigger_pct",
        "distance_below_52w",
    }
)
SIGNED_MONEY = frozenset(
    {
        "net_value_cr",
        "net_deal_cr",
        "pnl_amount",
        "profit_inr",
        "unrealized_pnl_inr",
        "realized_pnl_inr",
    }
)
BUY_MONEY = frozenset({"buy_value_cr", "buy_deal_cr", "buy_cr", "total_buy_cr"})
SELL_MONEY = frozenset({"sell_value_cr", "sell_deal_cr", "sell_cr"})
RVOL = frozenset({"rvol", "vs_20d", "vol_shock"})
SCORES = frozenset(
    {
        "rs",
        "rs_percentile",
        "rs_1y_percentile",
        "rs_3m_percentile",
        "rs_rank",
        "vcp_score",
        "trend_score",
        "contraction_score",
        "volume_dryup_score",
        "pivot_proximity_score",
        "focus_score",
        "rotation_score",
    }
)
MONEY_HINTS = ("_cr", "mcap", "turnover", "value_cr", "t_o_")
TONE_UP = "mp-up"
TONE_DOWN = "mp-down"

NUMERIC_KINDS = frozenset(
    {
        "signed_return",
        "level_pct",
        "distance",
        "signed_money",
        "buy_money",
        "sell_money",
        "money",
        "rvol",
        "score",
        "signed_delta",
        "number",
    }
)


def classify_column(col: str) -> str:
    name = str(col).lower()
    if name in SIGNED_RETURN or _looks_like_return(name):
        return "signed_return"
    if name in DISTANCE or name.startswith("away_") or name.startswith("distance_"):
        return "distance"
    if "rank_change" in name or name in {"score_change_5d"}:
        return "signed_delta"
    if name in LEVEL_PCT:
        return "level_pct"
    if name.endswith("_pct") or name.endswith("pct"):
        return "level_pct"
    if name in SIGNED_MONEY:
        return "signed_money"
    if name in BUY_MONEY:
        return "buy_money"
    if name in SELL_MONEY:
        return "sell_money"
    if name in RVOL:
        return "rvol"
    if name in SCORES:
        return "score"
    if any(h in name for h in MONEY_HINTS):
        return "money"
    return "other"


def _looks_like_return(name: str) -> bool:
    return any(
        token in name
        for token in ("return_", "pnl", "day_pct", "week_pct", "month_pct", "change_pct", "vs_inst")
    )


def format_cell(col: str, value: Any) -> tuple[str, str]:
    """Return (display_text, css_tone). css_tone is mp-up, mp-down, or empty."""
    if _missing(value):
        return "—", ""
    kind = classify_column(col)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value), ""
    name = str(col).lower()
    if kind == "signed_return":
        return f"{number:+.2f}%", _signed_tone(number)
    if kind == "level_pct":
        return f"{number:.1f}%", ""
    if kind == "distance":
        return _format_distance(name, number), ""
    if kind == "signed_money":
        return _format_money(number, signed=True), _signed_tone(number)
    if kind == "buy_money":
        return _format_money(number, signed=False), TONE_UP if number > 0 else ""
    if kind == "sell_money":
        return _format_money(number, signed=False), TONE_DOWN if number > 0 else ""
    if kind == "money":
        return _format_money(number, signed=False), ""
    if kind == "rvol":
        return f"{number:.2f}x", ""
    if kind == "score":
        return f"{number:.0f}", ""
    if kind == "signed_delta":
        if number == 0:
            return "0", ""
        return f"{number:+.0f}", _signed_tone(number)
    if kind == "number" or isinstance(value, (int, float)) and not isinstance(value, bool):
        if abs(number - round(number)) < 1e-9 and abs(number) >= 1:
            return f"{number:,.0f}", ""
        return f"{number:,.2f}", ""
    return str(value), ""


def _signed_tone(number: float) -> str:
    if number > 0:
        return TONE_UP
    if number < 0:
        return TONE_DOWN
    return ""


def _format_money(number: float, *, signed: bool) -> str:
    body = f"{abs(number):,.1f}"
    if signed:
        if number > 0:
            return f"+{body}"
        if number < 0:
            return f"-{body}"
    return body if number >= 0 else f"-{body}"


def _format_distance(_name: str, number: float) -> str:
    """Plain signed percent. 2.0% = through/above, -2.0% = below."""
    if abs(number) < 0.05:
        return "0.0%"
    if number > 0:
        return f"{number:.1f}%"
    return f"{number:.1f}%"


def _missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


__all__ = ["NUMERIC_KINDS", "classify_column", "format_cell"]
