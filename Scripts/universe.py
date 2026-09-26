"""Point-in-time equity universe built from the bhavcopies themselves (no survivorship filter)."""
from __future__ import annotations

import pandas as pd

SERIES_WHITELIST = frozenset({"EQ", "BE", "BZ"})


def apply_symbol_changes(prices: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    if not mapping or prices.empty:
        return prices
    out = prices.copy()
    out["symbol"] = out["symbol"].map(lambda s: mapping.get(s, s))
    out["_pri"] = (out.get("series", pd.Series("EQ", index=out.index)) != "EQ").astype(int)
    out = out.sort_values(["symbol", "trade_date", "_pri"]).drop_duplicates(["symbol", "trade_date"], keep="first")
    return out.drop(columns="_pri").reset_index(drop=True)


def build_universe_history(prices: pd.DataFrame, active_symbols: set[str]) -> pd.DataFrame:
    p = prices.sort_values(["symbol", "trade_date"])
    g = p.groupby("symbol")
    out = pd.DataFrame({
        "first_date": g["trade_date"].min(),
        "last_date": g["trade_date"].max(),
        "last_series": g["series"].last(),
        "sessions": g["trade_date"].nunique(),
    }).reset_index()
    out["status"] = out["symbol"].map(lambda s: "active" if s in active_symbols else "inactive")
    return out
