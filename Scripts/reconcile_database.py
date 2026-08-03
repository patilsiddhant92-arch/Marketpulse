"""Compare incremental and rebuilt DuckDB tables."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd


def _frame(path: Path, table: str) -> pd.DataFrame:
    with duckdb.connect(str(path), read_only=True) as db:
        return db.execute(f'SELECT * FROM "{table}"').fetchdf()


def reconcile_databases(incremental_db: Path, rebuilt_db: Path, tables: list[str], tolerance: float = 1e-9) -> list[str]:
    differences = []
    for table in tables:
        left = _frame(incremental_db, table)
        right = _frame(rebuilt_db, table)
        if set(left.columns) != set(right.columns):
            differences.append(f"{table}: columns differ")
            continue
        columns = sorted(left.columns)
        left = left[columns].sort_values(columns, kind="stable").reset_index(drop=True)
        right = right[columns].sort_values(columns, kind="stable").reset_index(drop=True)
        if len(left) != len(right):
            differences.append(f"{table}: row counts {len(left)} != {len(right)}")
            continue
        for column in columns:
            a, b = left[column], right[column]
            if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
                equal = (a.fillna(0) - b.fillna(0)).abs().le(tolerance) | (a.isna() & b.isna())
            else:
                equal = a.astype("string").fillna("<NULL>").eq(b.astype("string").fillna("<NULL>"))
            if not bool(equal.all()):
                differences.append(f"{table}.{column}: values differ")
    return differences
