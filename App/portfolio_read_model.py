"""Pure portfolio heat, concentration, and sizing calculations for the UI."""

from __future__ import annotations

from math import floor
from typing import Any

import pandas as pd


def _number(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame.get(column, pd.Series(index=frame.index, dtype=float)), errors="coerce").fillna(0.0)


def suggested_quantity(
    *,
    entry_price: float,
    stop_price: float,
    account_equity: float,
    max_risk_pct: float,
) -> int:
    """Return whole shares allowed by the configured per-trade risk budget."""

    try:
        entry = float(entry_price)
        stop = float(stop_price)
        equity = max(0.0, float(account_equity))
        risk_pct = max(0.0, float(max_risk_pct))
    except (TypeError, ValueError):
        return 0
    risk_per_share = entry - stop
    if entry <= 0 or risk_per_share <= 0 or equity <= 0 or risk_pct <= 0:
        return 0
    return max(0, floor((equity * risk_pct / 100.0) / risk_per_share))


def portfolio_summary(
    positions: pd.DataFrame | None,
    *,
    account_equity: float = 100_000.0,
    max_risk_pct: float = 1.0,
) -> dict[str, Any]:
    """Summarize portfolio heat and concentration without writing user data."""

    frame = positions.copy() if positions is not None else pd.DataFrame()
    equity = max(1.0, float(account_equity or 0.0))
    budget_pct = max(0.0, float(max_risk_pct or 0.0))
    market_value = _number(frame, "market_value_inr").sum()
    initial_risk = _number(frame, "initial_risk_inr").sum()
    current_risk = _number(frame, "current_open_risk_inr").sum()
    sector_weights = pd.DataFrame()
    if not frame.empty and "sector" in frame.columns:
        sector_weights = frame.assign(_market_value=_number(frame, "market_value_inr")).groupby("sector", dropna=False)["_market_value"].sum()
    largest_sector = str(sector_weights.idxmax()) if not sector_weights.empty else "—"
    largest_sector_value = float(sector_weights.max()) if not sector_weights.empty else 0.0
    missing_stop_count = int((_number(frame, "stop_price") <= 0).sum())
    return {
        "market_value_inr": round(float(market_value), 2),
        "initial_risk_inr": round(float(initial_risk), 2),
        "current_open_risk_inr": round(float(current_risk), 2),
        "initial_heat_pct": round(float(initial_risk / equity * 100.0), 2),
        "current_heat_pct": round(float(current_risk / equity * 100.0), 2),
        "largest_sector": largest_sector,
        "largest_sector_weight_pct": round(float(largest_sector_value / market_value * 100.0), 2) if market_value else 0.0,
        "missing_stop_count": missing_stop_count,
        "risk_budget_pct": round(budget_pct, 2),
        "over_budget": bool(current_risk > equity * budget_pct / 100.0),
        "account_equity": round(equity, 2),
    }


__all__ = ["portfolio_summary", "suggested_quantity"]
