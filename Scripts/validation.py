"""Leakage checks and date-grouped validation utilities."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

import numpy as np
import pandas as pd


def walk_forward_splits(dates: Iterable, min_train_dates: int, test_dates: int) -> Iterator[tuple[list[pd.Timestamp], list[pd.Timestamp]]]:
    unique = sorted(pd.to_datetime(pd.Series(list(dates)), errors="coerce").dropna().dt.normalize().drop_duplicates().tolist())
    if min_train_dates <= 0 or test_dates <= 0:
        raise ValueError("min_train_dates and test_dates must be positive")
    for start in range(min_train_dates, len(unique), test_dates):
        train = unique[:start]
        test = unique[start:start + test_dates]
        if test:
            yield train, test


def future_high_label(prices: pd.DataFrame, index: int, horizon: int, threshold: float) -> bool:
    if index < 0 or index >= len(prices) or horizon <= 0:
        return False
    entry = pd.to_numeric(prices.iloc[index].get("high_price"), errors="coerce")
    future = pd.to_numeric(prices.iloc[index + 1:index + 1 + horizon]["high_price"], errors="coerce")
    return bool(np.isfinite(entry) and len(future) == horizon and future.max() >= entry * float(threshold))


def assert_point_in_time(rows: pd.DataFrame, reference_date_column="effective_date", trade_date_column="trade_date") -> None:
    if rows.empty or reference_date_column not in rows.columns or trade_date_column not in rows.columns:
        return
    reference = pd.to_datetime(rows[reference_date_column], errors="coerce")
    trade = pd.to_datetime(rows[trade_date_column], errors="coerce")
    bad = reference.notna() & trade.notna() & (reference > trade)
    if bool(bad.any()):
        raise AssertionError(f"future reference data detected in {int(bad.sum())} rows")
