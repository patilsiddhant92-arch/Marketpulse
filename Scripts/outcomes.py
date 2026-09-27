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


def _ledger_price_scale(symbol_rows: pd.DataFrame, signal: dict) -> float:
    """Factor putting the signal's ledger prices onto the scale of `symbol_rows`.

    `signal_ledger.trigger_price` / `invalidation_price` are written on the price scale of the
    signal's `last_seen_date` session. When `prices` carries a `price_factor` column (adjusted
    prices, see `price_views.ohlcv_columns`), a split/bonus after that session back-adjusts
    the price rows but not the ledger, so the ledger prices must be multiplied by the
    `price_factor` in force on `last_seen_date` (falling back to `first_seen_date`) -- the
    factor of the latest price row on or before that date. 1.0 when there is no factor column
    or no such row.
    """
    if "price_factor" not in symbol_rows.columns or symbol_rows.empty:
        return 1.0
    for key in ("last_seen_date", "first_seen_date"):
        value = signal.get(key)
        if value is None or pd.isna(value):
            continue
        on_or_before = symbol_rows[symbol_rows["trade_date"] <= pd.Timestamp(value).normalize()]
        if on_or_before.empty:
            continue
        factor = pd.to_numeric(on_or_before.sort_values("trade_date")["price_factor"], errors="coerce").iloc[-1]
        return float(factor) if pd.notna(factor) and factor > 0 else 1.0
    return 1.0


def _scaled(value, scale: float):
    if value is None or pd.isna(value):
        return None
    return float(value) * scale


def calculate_outcome(prices: pd.DataFrame, signal: dict, horizons: Iterable[int] = (5, 10, 20, 60)) -> list[dict]:
    symbol = str(signal["symbol"]).upper()
    as_of = pd.Timestamp(signal["first_seen_date"]).normalize()
    base = prices.copy()
    base["trade_date"] = pd.to_datetime(base["trade_date"], errors="coerce").dt.normalize()
    symbol_rows = base[base["symbol"].astype(str).str.upper() == symbol]
    scale = _ledger_price_scale(symbol_rows, signal)
    trigger_price = _scaled(signal.get("trigger_price"), scale)
    invalidation = _scaled(signal.get("invalidation_price"), scale)
    base_row = symbol_rows[symbol_rows["trade_date"] == as_of]
    entry = float(base_row.iloc[0]["close_price"]) if not base_row.empty else float(trigger_price or np.nan)
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
        # Positional (1-based session count into the window): the index labels of `prices`
        # need not be contiguous per symbol (e.g. a multi-symbol SQL fetch).
        failed_at = np.flatnonzero((low <= invalidation).to_numpy()) if invalidation is not None else np.array([], dtype=int)
        result.append({
            "signal_id": signal["signal_id"], "horizon_sessions": horizon, "as_of_date": as_of.date(),
            "forward_return_pct": round((close / entry - 1) * 100, 6),
            "max_favourable_excursion_pct": round((high.max() / entry - 1) * 100, 6),
            "max_adverse_excursion_pct": round((low.min() / entry - 1) * 100, 6),
            "trigger_to_invalidation_return_pct": round((invalidation / trigger_price - 1) * 100, 6) if invalidation and trigger_price else None,
            "time_to_trigger_sessions": None,
            "time_to_failure_sessions": int(failed_at[0]) + 1 if len(failed_at) else None,
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
