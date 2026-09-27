"""Automated test suite verifying F1 (Quasar Table Sorting) and F2 (Numeric Column Classification)."""
from __future__ import annotations

import pandas as pd
import pytest

from App.ui.columns import GLOBAL_COLUMNS, get_quasar_column_def
from App.ui.number_format import NUMERIC_KINDS, classify_column, format_cell


def test_numeric_columns_have_custom_js_sort_comparator():
    """Verify numeric columns receive custom JavaScript sort comparator in get_quasar_column_def."""
    numeric_keys = [
        "close_price",
        "cmp",
        "return_1d_pct",
        "return_5d_pct",
        "turnover_cr",
        "market_cap_cr",
        "pe",
        "roe",
        "debt_to_equity",
        "rsi_14",
        "rank",
        "stocks",
        "qty",
        "active_days",
    ]
    for key in numeric_keys:
        col = get_quasar_column_def(key)
        assert col["sortable"] is True, f"{key} must be sortable"
        assert col.get(":sort") == "(a, b) => (Number(a) || 0) - (Number(b) || 0)", f"{key} missing :sort"
        assert col.get("sort") == "(a, b) => (Number(a) || 0) - (Number(b) || 0)", f"{key} missing sort"


def test_text_columns_do_not_have_numeric_sort_comparator():
    """Verify non-numeric string columns do not receive numeric sort comparator."""
    text_keys = ["symbol", "group_name", "sector", "industry", "status", "role_desc", "notes"]
    for key in text_keys:
        col = get_quasar_column_def(key)
        assert ":sort" not in col, f"{key} should not have numeric :sort"
        assert "sort" not in col, f"{key} should not have numeric sort"


def test_zero_unclassified_numeric_columns_in_global_registry():
    """Verify all columns in GLOBAL_COLUMNS with numeric/currency/pct/multiple formats are in NUMERIC_KINDS."""
    unclassified = [
        k
        for k, c in GLOBAL_COLUMNS.items()
        if c.format_type in ("numeric", "currency", "pct", "multiple")
        and classify_column(k) not in NUMERIC_KINDS
    ]
    assert unclassified == [], f"Found unclassified numeric columns: {unclassified}"


def test_classification_of_38_financial_columns():
    """Verify all 38 financial columns evaluate to valid financial kinds."""
    expected_kinds = {
        "close_price": "price",
        "cmp": "price",
        "sell_price": "price",
        "avg_buy_price": "price",
        "inst_vwap": "price",
        "exit_price": "price",
        "trigger_price": "price",
        "invalidation_price": "price",
        "stop_loss": "price",
        "first_resistance": "price",
        "pivot": "price",
        "low": "price",
        "high": "price",
        "pe": "multiple",
        "debt_to_equity": "multiple",
        "reward_to_risk": "multiple",
        "pct_change": "signed_return",
        "rs_vs_nifty_21d": "signed_return",
        "rs_vs_nifty_63d": "signed_return",
        "delivery_delta": "signed_return",
        "roe": "level_pct",
        "revenue_cagr_3y": "level_pct",
        "rsi_14": "score",
        "total_score": "score",
        "quality_score": "score",
        "rank": "number",
        "rotation_rank": "number",
        "stocks": "number",
        "near_52w_highs": "number",
        "vcp_candidates": "number",
        "new_20d_highs": "number",
        "deal_count": "number",
        "client_count": "number",
        "inst_count": "number",
        "institutions_count": "number",
        "active_days": "number",
        "qty": "number",
        "days_held": "number",
    }
    for col_name, expected_kind in expected_kinds.items():
        actual_kind = classify_column(col_name)
        assert actual_kind == expected_kind, f"Column '{col_name}' expected kind '{expected_kind}', got '{actual_kind}'"


def test_table_from_df_numeric_null_preservation():
    """Verify table_from_df in app.py does not convert nulls to empty string."""
    from pathlib import Path
    app_code = Path("App/app.py").read_text(encoding="utf-8")
    assert 'view.astype(object).where(pd.notna(view), None)' in app_code, (
        "table_from_df must use None for missing values to avoid coercing nulls to 0"
    )
    assert 'col_def[":sort"] = "(a, b) => (Number(a) || 0) - (Number(b) || 0)"' in app_code
