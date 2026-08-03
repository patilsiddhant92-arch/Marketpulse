"""Corporate-action normalization and historical price adjustment factors."""

from __future__ import annotations

import pandas as pd


def _normalized_actions(actions: pd.DataFrame) -> pd.DataFrame:
    if actions is None or actions.empty:
        return pd.DataFrame(columns=["symbol", "ex_date", "action_type", "ratio_from", "ratio_to"])
    result = actions.copy()
    result["symbol"] = result["symbol"].astype(str).str.strip().str.upper()
    result["ex_date"] = pd.to_datetime(result["ex_date"], errors="coerce").dt.normalize()
    result["action_type"] = result["action_type"].astype(str).str.strip().str.lower()
    for col in ("ratio_from", "ratio_to"):
        result[col] = pd.to_numeric(result.get(col, 1), errors="coerce").fillna(1.0)
    return result[result["ex_date"].notna() & (result["ratio_to"] > 0)]


def build_adjustment_factors(actions: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Return factors that back-adjust pre-ex-date rows for splits/bonuses."""

    columns = ["symbol", "trade_date", "price_factor", "volume_factor"]
    if prices is None or prices.empty:
        return pd.DataFrame(columns=columns)
    price_rows = prices[["symbol", "trade_date"]].copy()
    price_rows["symbol"] = price_rows["symbol"].astype(str).str.strip().str.upper()
    price_rows["trade_date"] = pd.to_datetime(price_rows["trade_date"], errors="coerce").dt.normalize()
    normalized = _normalized_actions(actions)
    factors = []
    for row in price_rows.itertuples(index=False):
        price_factor = 1.0
        volume_factor = 1.0
        for action in normalized[normalized["symbol"] == row.symbol].itertuples(index=False):
            if row.trade_date < action.ex_date and action.action_type in {"split", "bonus", "rights issue", "rights"}:
                factor = float(action.ratio_from) / float(action.ratio_to)
                price_factor *= factor
                volume_factor *= 1.0 / factor
        factors.append((row.symbol, row.trade_date, price_factor, volume_factor))
    return pd.DataFrame(factors, columns=columns)


def apply_adjustment_factors(prices: pd.DataFrame, factors: pd.DataFrame) -> pd.DataFrame:
    if prices is None or prices.empty:
        return prices.copy()
    result = prices.copy()
    factor_frame = factors.copy()
    factor_frame["symbol"] = factor_frame["symbol"].astype(str).str.strip().str.upper()
    factor_frame["trade_date"] = pd.to_datetime(factor_frame["trade_date"], errors="coerce").dt.normalize()
    result["symbol"] = result["symbol"].astype(str).str.strip().str.upper()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce").dt.normalize()
    result = result.merge(factor_frame, on=["symbol", "trade_date"], how="left", validate="one_to_one")
    result["price_factor"] = result["price_factor"].fillna(1.0)
    result["volume_factor"] = result["volume_factor"].fillna(1.0)
    for col in ("open_price", "high_price", "low_price", "last_price", "close_price", "avg_price"):
        if col in result.columns:
            result[f"{col}_adjusted"] = pd.to_numeric(result[col], errors="coerce") * result["price_factor"]
    if "volume" in result.columns:
        result["volume_adjusted"] = pd.to_numeric(result["volume"], errors="coerce") * result["volume_factor"]
    return result
