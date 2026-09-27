"""Point-in-time equity universe built from the bhavcopies themselves (no survivorship filter)."""
from __future__ import annotations

import pandas as pd

SERIES_WHITELIST = frozenset({"EQ", "BE", "BZ"})


def apply_symbol_changes(prices: pd.DataFrame, changes: pd.DataFrame) -> pd.DataFrame:
    """Rename symbols using the parsed symbolchange history, respecting each change's date.

    Rows are only renamed if they predate the change (or the change has no date), so a
    ticker later reused by an unrelated company keeps its post-reuse rows under the old
    symbol. Changes are applied in chronological order so chains (A->B, B->C) resolve
    correctly regardless of row order in ``changes``.
    """
    if changes is None or changes.empty or prices.empty:
        return prices
    # Vectorised rename (same sequential, date-aware semantics) shared with price_adjustment:
    # one full-frame comparison per change is far too slow on the full price history.
    from price_adjustment import _rename_symbols

    out = _rename_symbols(prices, changes, "trade_date")
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
