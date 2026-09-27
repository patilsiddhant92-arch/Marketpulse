"""True relative strength: stock excess return vs index benchmarks.

rs_vs_idx_Nd = (stock_ret_N - index_ret_N) * 100  (percentage points)
Fail closed: NaN when either leg lacks N prior sessions or dates don't align.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

# Exact index_daily.index_name spellings (assert in tests against live DB).
BENCH_NIFTY50 = "Nifty 50"
BENCH_MIDSML400 = "NIFTY MIDSML 400"

BENCH_COLUMNS = {
    BENCH_NIFTY50: ("rs_vs_nifty50_21d", "rs_vs_nifty50_63d"),
    BENCH_MIDSML400: ("rs_vs_midsml400_21d", "rs_vs_midsml400_63d"),
}

TRUE_RS_COLUMNS = (
    "rs_vs_nifty50_21d",
    "rs_vs_nifty50_63d",
    "rs_vs_midsml400_21d",
    "rs_vs_midsml400_63d",
)


def excess_vs_index(
    stock_close: pd.DataFrame,
    index_close: pd.DataFrame,
    sessions: int,
) -> pd.Series:
    """Return excess % pts (stock_ret - index_ret) * 100 aligned to stock rows.

    stock_close: columns symbol, trade_date, close_price
    index_close: columns trade_date, close_price (single index series)
    """
    if sessions < 1:
        raise ValueError("sessions must be >= 1")
    if stock_close is None or stock_close.empty:
        return pd.Series(dtype=float)
    if index_close is None or index_close.empty:
        out = pd.Series(np.nan, index=stock_close.index, dtype=float)
        return out

    stocks = stock_close.copy()
    stocks["trade_date"] = pd.to_datetime(stocks["trade_date"], errors="coerce").dt.normalize()
    stocks["close_price"] = pd.to_numeric(stocks["close_price"], errors="coerce")
    stocks = stocks.dropna(subset=["symbol", "trade_date", "close_price"])
    stocks = stocks.sort_values(["symbol", "trade_date"])

    idx = index_close.copy()
    idx["trade_date"] = pd.to_datetime(idx["trade_date"], errors="coerce").dt.normalize()
    idx["close_price"] = pd.to_numeric(idx["close_price"], errors="coerce")
    idx = idx.dropna(subset=["trade_date", "close_price"]).drop_duplicates("trade_date")
    idx = idx.sort_values("trade_date")
    idx["idx_prior"] = idx["close_price"].shift(sessions)
    idx["idx_ret"] = idx["close_price"] / idx["idx_prior"] - 1.0
    idx_map = idx.set_index("trade_date")["idx_ret"]

    out = pd.Series(np.nan, index=stock_close.index, dtype=float)
    for _sym, group in stocks.groupby("symbol", sort=False):
        prior = group["close_price"].shift(sessions)
        stock_ret = group["close_price"] / prior - 1.0
        index_ret = group["trade_date"].map(idx_map)
        excess = (stock_ret - index_ret) * 100.0
        out.loc[group.index] = excess.astype(float)
    return out


def index_closes(index_daily: pd.DataFrame, index_name: str) -> pd.DataFrame:
    if index_daily is None or index_daily.empty:
        return pd.DataFrame(columns=["trade_date", "close_price"])
    frame = index_daily.loc[index_daily["index_name"] == index_name, ["trade_date", "close_price"]].copy()
    return frame.reset_index(drop=True)


def attach_true_rs_columns(
    indicators: pd.DataFrame,
    index_daily: pd.DataFrame,
    *,
    sessions: Iterable[int] = (21, 63),
) -> pd.DataFrame:
    """Return indicators copy with TRUE_RS_COLUMNS populated (NaN when fail-closed)."""
    out = indicators.copy()
    for col in TRUE_RS_COLUMNS:
        if col not in out.columns:
            out[col] = np.nan

    stock = out[["symbol", "trade_date", "close_price"]].copy()
    session_set = tuple(sessions)

    for index_name, col_pair in BENCH_COLUMNS.items():
        idx = index_closes(index_daily, index_name)
        for sessions_n, col in zip((21, 63), col_pair):
            if sessions_n not in session_set:
                continue
            out[col] = excess_vs_index(stock, idx, sessions_n).to_numpy()
    return out


def bench_session_counts(index_daily: pd.DataFrame) -> dict[str, int]:
    if index_daily is None or index_daily.empty:
        return {BENCH_NIFTY50: 0, BENCH_MIDSML400: 0}
    counts = (
        index_daily.groupby("index_name")["trade_date"]
        .nunique()
        .to_dict()
    )
    return {
        BENCH_NIFTY50: int(counts.get(BENCH_NIFTY50, 0)),
        BENCH_MIDSML400: int(counts.get(BENCH_MIDSML400, 0)),
    }
