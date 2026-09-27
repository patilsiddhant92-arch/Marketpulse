"""SQL column-selection helpers for readers that compare prices across dates.

Task 6 (price adjustment) adds `adj_open_price`, `adj_high_price`,
`adj_low_price`, `adj_close_price`, `adj_last_price`, `adj_avg_price`,
`adj_prev_close`, `adj_volume`, `adj_delivery_qty`, and `price_factor` to
`prices_daily` once it is rebuilt/appended. Any reader that compares or
aggregates prices/volumes *across different dates* (returns, highs/lows,
swing points, forward returns, moving averages, ranges) must use the
adjusted columns when they exist, so a split/bonus event doesn't show up as
a fake price discontinuity.

The live DB does not have these columns yet, so `ohlcv_columns` checks for
them at query-build time (via `PRAGMA table_info`) and falls back to the raw
column names when they are absent -- callers work unmodified against both
the current live DB and a rebuilt one.
"""

from __future__ import annotations

from typing import Any

# Raw column name -> its adjusted counterpart in prices_daily.
_RAW_TO_ADJ = {
    "open_price": "adj_open_price",
    "high_price": "adj_high_price",
    "low_price": "adj_low_price",
    "close_price": "adj_close_price",
    "prev_close": "adj_prev_close",
    "volume": "adj_volume",
    "delivery_qty": "adj_delivery_qty",
}


def _prices_daily_columns(con: Any) -> set[str]:
    """Best-effort column set for `prices_daily`; empty set if unavailable."""
    try:
        rows = con.execute("PRAGMA table_info('prices_daily')").fetchall()
    except Exception:
        return set()
    return {str(row[1]) for row in rows}


def ohlcv_columns(con: Any, alias: str = "") -> dict[str, str]:
    """SQL expressions for `prices_daily` OHLCV columns, adjusted when present.

    Returns a dict keyed `open_price, high_price, low_price, close_price,
    prev_close, volume, delivery_qty, price_factor` mapping to SQL
    expressions suitable for a SELECT list:

    - `COALESCE({alias}adj_<col>, {alias}<col>)` when `prices_daily` carries
      that adjusted column (checked via `PRAGMA table_info`), else just
      `{alias}<col>`.
    - `price_factor`: `COALESCE({alias}price_factor, 1.0)` when the column
      exists, else the literal `1.0`.

    `alias`, when given, is prepended verbatim to every column reference
    (pass e.g. `"p."` for a query that joins `prices_daily` as `p`). Safe to
    call on a read-only connection and against a database that predates the
    adjustment columns (today's live DB) -- it just returns raw column
    names in that case.
    """
    cols = _prices_daily_columns(con)
    exprs: dict[str, str] = {}
    for raw, adj in _RAW_TO_ADJ.items():
        if adj in cols:
            exprs[raw] = f"COALESCE({alias}{adj}, {alias}{raw})"
        else:
            exprs[raw] = f"{alias}{raw}"
    if "price_factor" in cols:
        exprs["price_factor"] = f"COALESCE({alias}price_factor, 1.0)"
    else:
        exprs["price_factor"] = "1.0"
    return exprs
