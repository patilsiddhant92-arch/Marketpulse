"""Point-in-time forward outcome and expectancy calculations."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd


def future_session_values(prices: pd.DataFrame, symbol: str, as_of, horizons: Iterable[int] = (5, 10, 20, 60)) -> dict[int, dict]:
    frame = prices.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce").dt.normalize()
    as_of = pd.Timestamp(as_of).normalize()
    frame = frame[(frame["symbol"].astype(str).str.upper() == str(symbol).upper()) & (frame["trade_date"] > as_of)].sort_values("trade_date")
    out = {}
    for horizon in horizons:
        window = frame.head(int(horizon))
        out[int(horizon)] = {"resolved": len(window) >= int(horizon), "window": window}
    return out


def calculate_outcome(prices: pd.DataFrame, signal: dict, horizons: Iterable[int] = (5, 10, 20, 60)) -> list[dict]:
    symbol = str(signal["symbol"]).upper()
    as_of = pd.Timestamp(signal["first_seen_date"]).normalize()
    base = prices.copy()
    base["trade_date"] = pd.to_datetime(base["trade_date"], errors="coerce").dt.normalize()
    base_row = base[(base["symbol"].astype(str).str.upper() == symbol) & (base["trade_date"] == as_of)]
    entry = float(base_row.iloc[0]["close_price"]) if not base_row.empty else float(signal.get("trigger_price") or np.nan)
    result = []
    for horizon, values in future_session_values(prices, symbol, as_of, horizons).items():
        window = values["window"]
        resolved = bool(values["resolved"])
        if not resolved or not np.isfinite(entry) or window.empty:
            result.append({"signal_id": signal["signal_id"], "horizon_sessions": horizon, "as_of_date": as_of.date(), "forward_return_pct": None, "max_favourable_excursion_pct": None, "max_adverse_excursion_pct": None, "trigger_to_invalidation_return_pct": None, "time_to_trigger_sessions": None, "time_to_failure_sessions": None, "resolved": False})
            continue
        high = pd.to_numeric(window["high_price"], errors="coerce")
        low = pd.to_numeric(window["low_price"], errors="coerce")
        close = float(window.iloc[-1]["close_price"])
        invalidation = signal.get("invalidation_price")
        failure = window[low <= float(invalidation)] if invalidation is not None and pd.notna(invalidation) else pd.DataFrame()
        result.append({
            "signal_id": signal["signal_id"], "horizon_sessions": horizon, "as_of_date": as_of.date(),
            "forward_return_pct": round((close / entry - 1) * 100, 6),
            "max_favourable_excursion_pct": round((high.max() / entry - 1) * 100, 6),
            "max_adverse_excursion_pct": round((low.min() / entry - 1) * 100, 6),
            "trigger_to_invalidation_return_pct": round((float(invalidation) / float(signal.get("trigger_price")) - 1) * 100, 6) if invalidation and signal.get("trigger_price") else None,
            "time_to_trigger_sessions": None,
            "time_to_failure_sessions": int(failure.index[0] - window.index[0] + 1) if not failure.empty else None,
            "resolved": True,
        })
    return result


def summarize_outcomes(outcomes: pd.DataFrame, group_fields: list[str]) -> pd.DataFrame:
    if outcomes is None or outcomes.empty:
        return pd.DataFrame()
    resolved = outcomes[outcomes["resolved"].fillna(False)].copy()
    if resolved.empty:
        return pd.DataFrame()
    return resolved.groupby(group_fields, dropna=False).agg(
        observations=("signal_id", "count"),
        average_forward_return_pct=("forward_return_pct", "mean"),
        median_forward_return_pct=("forward_return_pct", "median"),
        average_mfe_pct=("max_favourable_excursion_pct", "mean"),
        average_mae_pct=("max_adverse_excursion_pct", "mean"),
    ).reset_index()
