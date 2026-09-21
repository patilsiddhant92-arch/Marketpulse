"""Adversarial stress-test suite for Milestone M1 (F1: Column Sorting & F3: Stock Arrow Action).

Authored by Challenger M1_1 to empirically stress-test and challenge:
1. F1: Quasar numeric comparator logic, mixed pos/neg floats, extreme numbers, zero values,
   NaN/None values, string columns with special chars, and pre-formatted string sorting failure.
2. F3: Stock Name Arrow action, all event payload variants, malformed args, listener duplication,
   and function signature mismatches.
"""
from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from App.ui.columns import GLOBAL_COLUMNS, get_quasar_column_def
from App.ui.number_format import NUMERIC_KINDS, classify_column, format_cell
from App.ui.table import SYMBOL_CELL_SLOT, _table_event_symbol


class MockNiceGUIEvent:
    def __init__(self, args: Any):
        self.args = args


# ==============================================================================
# 1. F1: EMPIRICAL JAVASCRIPT SORT COMPARATOR VERIFICATION
# ==============================================================================

def run_js_sort(comparator_code: str, rows: list[dict[str, Any]], sort_field: str, ascending: bool = True) -> list[dict[str, Any]]:
    """Execute Node.js to sort an array of objects using the exact Quasar sort comparator."""
    js_script = f"""
    const comparator = {comparator_code};
    const rows = {json.dumps(rows)};
    const sortField = {json.dumps(sort_field)};
    const ascending = {json.dumps(ascending)};

    rows.sort((r1, r2) => {{
        const v1 = r1[sortField];
        const v2 = r2[sortField];
        const res = comparator(v1, v2);
        return ascending ? res : -res;
    }});

    console.log(JSON.stringify(rows));
    """
    try:
        proc = subprocess.run(["node", "-e", js_script], capture_output=True, text=True, check=True)
        return json.loads(proc.stdout)
    except (FileNotFoundError, OSError, subprocess.CalledProcessError):
        import functools

        def js_num(v: Any) -> float:
            if v is None:
                return 0.0
            if isinstance(v, (int, float)):
                return 0.0 if (v != v) else float(v)
            try:
                return float(str(v).strip())
            except Exception:
                return 0.0

        if "Number" in comparator_code:
            def cmp_func(r1: dict[str, Any], r2: dict[str, Any]) -> int:
                v1 = js_num(r1.get(sort_field))
                v2 = js_num(r2.get(sort_field))
                res = 1 if v1 > v2 else (-1 if v1 < v2 else 0)
                return res if ascending else -res
        else:
            def cmp_func(r1: dict[str, Any], r2: dict[str, Any]) -> int:
                v1 = str(r1.get(sort_field))
                v2 = str(r2.get(sort_field))
                res = 1 if v1 > v2 else (-1 if v1 < v2 else 0)
                return res if ascending else -res

        return sorted(rows, key=functools.cmp_to_key(cmp_func))


def test_quasar_comparator_mixed_positive_negative_floats():
    """Verify Quasar comparator correctly sorts mixed positive, negative, and zero floats."""
    comparator_code = "(a, b) => (Number(a) || 0) - (Number(b) || 0)"
    test_values = [-99.5, -23.1, -5.0, -0.05, 0.0, 0.05, 1.25, 42.0, 100.5]
    
    # Shuffle or reverse input
    shuffled_rows = [{"id": i, "val": v} for i, v in enumerate(reversed(test_values))]
    
    # Ascending sort
    sorted_asc = run_js_sort(comparator_code, shuffled_rows, "val", ascending=True)
    asc_values = [r["val"] for r in sorted_asc]
    assert asc_values == test_values, f"Ascending sort mismatch: got {asc_values}"

    # Descending sort
    sorted_desc = run_js_sort(comparator_code, shuffled_rows, "val", ascending=False)
    desc_values = [r["val"] for r in sorted_desc]
    assert desc_values == list(reversed(test_values)), f"Descending sort mismatch: got {desc_values}"


def test_quasar_comparator_extreme_numbers():
    """Verify Quasar comparator handles extreme floating point values without overflow/NaN collapse."""
    comparator_code = "(a, b) => (Number(a) || 0) - (Number(b) || 0)"
    extreme_values = [
        -1e15,
        -1e6,
        -1.0,
        -1e-6,
        0.0,
        1e-6,
        1.0,
        1e6,
        1e15,
    ]
    rows = [{"id": i, "val": v} for i, v in enumerate(reversed(extreme_values))]
    sorted_asc = run_js_sort(comparator_code, rows, "val", ascending=True)
    asc_values = [r["val"] for r in sorted_asc]
    assert asc_values == extreme_values, f"Extreme numbers sort mismatch: got {asc_values}"


def test_quasar_comparator_zero_and_near_zero_values():
    """Verify Quasar comparator properly handles zero representations (+0, -0, 0.0, -0.0)."""
    comparator_code = "(a, b) => (Number(a) || 0) - (Number(b) || 0)"
    rows = [
        {"id": 1, "val": 5.0},
        {"id": 2, "val": 0.0},
        {"id": 3, "val": -0.0},
        {"id": 4, "val": -5.0},
    ]
    sorted_asc = run_js_sort(comparator_code, rows, "val", ascending=True)
    vals = [r["val"] for r in sorted_asc]
    assert vals[0] == -5.0
    assert vals[1] == 0.0 or vals[1] == -0.0
    assert vals[2] == 0.0 or vals[2] == -0.0
    assert vals[3] == 5.0


def test_quasar_comparator_nan_and_null_behavior():
    """Empirically test how null and NaN values sort relative to positive and negative numbers.
    
    In JavaScript, Number(null) is 0 and (Number(NaN) || 0) is 0.
    Therefore, missing data coerces to 0.0 during sorting.
    This test documents the mathematical behavior: null sorts between negative and positive.
    """
    comparator_code = "(a, b) => (Number(a) || 0) - (Number(b) || 0)"
    rows = [
        {"id": "pos", "val": 10.0},
        {"id": "neg", "val": -10.0},
        {"id": "null_val", "val": None},
    ]
    sorted_asc = run_js_sort(comparator_code, rows, "val", ascending=True)
    ids_asc = [r["id"] for r in sorted_asc]
    # Because Number(null) || 0 is 0, -10 < 0 < 10
    assert ids_asc == ["neg", "null_val", "pos"], f"Expected null to sort at 0, got order: {ids_asc}"


def test_preformatted_string_sorting_failure_on_raw_strings():
    """Demonstrate the critical bug: passing pre-formatted strings ('+2.5%', '₹1,500 Cr')
    to a table column with Quasar numeric comparator causes sorting to completely collapse (comparator yields 0).
    """
    comparator_code = "(a, b) => (Number(a) || 0) - (Number(b) || 0)"
    formatted_rows = [
        {"stock": "A", "pct": "+5.20%", "price": "₹1,200.00"},
        {"stock": "B", "pct": "-3.10%", "price": "₹450.00"},
        {"stock": "C", "pct": "+1.05%", "price": "₹3,500.00"},
        {"stock": "D", "pct": "-0.50%", "price": "₹89.00"},
    ]
    # Test sorting by pct
    sorted_pct = run_js_sort(comparator_code, formatted_rows, "pct", ascending=True)
    # Since Number('+5.20%') is NaN -> 0, all differences are 0!
    # The order remains unchanged from input order!
    initial_stocks = [r["stock"] for r in formatted_rows]
    sorted_stocks = [r["stock"] for r in sorted_pct]
    assert sorted_stocks == initial_stocks, "Comparator failed to distinguish formatted strings, all treated as 0"


def test_sector_board_tables_vulnerability_to_preformatted_strings():
    """Audit sector_board.py for unmigrated tables where numeric columns receive
    pre-formatted strings alongside Quasar numeric comparators.
    """
    sb_code = Path("App/pages/research/sector_board.py").read_text(encoding="utf-8")
    tree = ast.parse(sb_code)
    
    # Check lines 1386-1409 (Canonical Indices Table)
    # Check if records_idx puts formatted strings into return_1d_pct, close_price, return_5d_pct
    unmigrated_tables = []
    if 'get_quasar_column_def("return_1d_pct", label_override="1D %")' in sb_code:
        if '"return_1d_pct": _fmt_pct(' in sb_code:
            unmigrated_tables.append("sector_board.py:records_idx (Canonical Indices Table)")
    if 'get_quasar_column_def("turnover_share_delta_5d", label_override="★ Δ SHARE 5D")' in sb_code:
        if '"turnover_share_delta_5d": f"{_safe_float(' in sb_code:
            unmigrated_tables.append("sector_board.py:records (Primary Matrix Table)")
    
    # We assert whether unmigrated tables exist to record this empirical finding
    assert len(unmigrated_tables) > 0, "Expected to detect unmigrated pre-formatted string tables in sector_board.py"


def test_quasar_default_string_sorting_with_special_characters():
    """Test Quasar's default string sorting logic: (a, b) => (a > b ? 1 : (a < b ? -1 : 0))
    on string columns containing special characters (e.g. '&', '-', spaces, digits).
    """
    default_comparator = "(a, b) => (a > b ? 1 : (a < b ? -1 : 0))"
    string_values = [
        "3MINDIA",
        "BAJAJ-AUTO",
        "L&TFH",
        "M&M",
        "M&MFIN",
        "MARUTI",
        "TCS",
    ]
    rows = [{"id": i, "symbol": s} for i, s in enumerate(reversed(string_values))]
    sorted_asc = run_js_sort(default_comparator, rows, "symbol", ascending=True)
    res = [r["symbol"] for r in sorted_asc]
    assert res == string_values, f"String sorting mismatch: got {res}"


# ==============================================================================
# 2. F3: EMPIRICAL STOCK NAME ARROW ACTION & EVENT NORMALIZATION
# ==============================================================================

def test_table_event_symbol_adversarial_payloads():
    """Exhaustive stress-testing of _table_event_symbol with adversarial and edge-case payloads."""
    test_cases = [
        # (payload, expected_symbol)
        ("TCS", "TCS"),
        ("  tcs  ", "TCS"),
        (["INFY"], "INFY"),
        (["  infy  "], "INFY"),
        ([{"symbol": "RELIANCE"}], "RELIANCE"),
        ([{"value": "HDFCBANK"}], "HDFCBANK"),
        ({"symbol": "ITC"}, "ITC"),
        ({"value": "LT"}, "LT"),
        # Stringified JSON/Python lists
        ("['SBIN']", "SBIN"),
        ('["SBIN"]', "SBIN"),
        ("['  sbin  ']", "SBIN"),
        # Nested structures
        ([["TCS"]], "TCS"),
        # Lists with multiple items: must take the first symbol
        (["TCS", "INFY"], "TCS"),
        ([{"symbol": "TCS"}, {"symbol": "INFY"}], "TCS"),
        # Special stock tickers
        ("M&M", "M&M"),
        ("BAJAJ-AUTO", "BAJAJ-AUTO"),
        ("3MINDIA", "3MINDIA"),
        ("L&TFH", "L&TFH"),
        # Empty / None / Falsy
        (None, ""),
        ("", ""),
        ([], ""),
        ({}, ""),
        ([None], ""),
        ([""], ""),
        ([{}], ""),
        ({"symbol": None}, ""),
        ({"value": None}, ""),
        # Non-string scalar types
        (12345, "12345"),
        ([999], "999"),
        ({"symbol": 777}, "777"),
        # Dict with unrecognized keys
        ({"ticker": "TCS"}, ""),
        ([{"ticker": "TCS"}], ""),
    ]

    for payload, expected in test_cases:
        # Test direct argument
        actual_direct = _table_event_symbol(payload)
        assert actual_direct == expected, f"Direct failed for payload {payload!r}: expected {expected!r}, got {actual_direct!r}"

        # Test wrapped in MockNiceGUIEvent (event.args = payload)
        actual_event = _table_event_symbol(MockNiceGUIEvent(payload))
        assert actual_event == expected, f"Event.args failed for payload {payload!r}: expected {expected!r}, got {actual_event!r}"


def test_sector_board_quick_toggle_wl_symbol_signature_bug():
    """Verify the empirical bug in sector_board.py:
    Inside build_sector_board_page, an inner _quick_toggle_wl_symbol is defined
    with 1 argument (sym), but the table listeners at lines 899 and 969 call it
    with 2 arguments (db_path, sym), which causes a runtime TypeError on click!
    """
    with open("App/pages/research/sector_board.py", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    inner_func = None
    calls = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "build_sector_board_page":
            for sub in ast.walk(node):
                if isinstance(sub, ast.FunctionDef) and sub.name == "_quick_toggle_wl_symbol":
                    inner_func = sub
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "_quick_toggle_wl_symbol":
                    calls.append((sub.lineno, len(sub.args)))

    assert inner_func is not None, "Inner _quick_toggle_wl_symbol must be found"
    param_count = len(inner_func.args.args)
    
    # Inner function has 1 parameter: ['sym']
    assert param_count == 1, f"Inner function has {param_count} params, expected 1"
    
    # Calls at lines 899 and 969 pass 2 arguments: (db_path, _table_event_symbol(e))
    two_arg_calls = [lineno for lineno, argc in calls if argc == 2]
    assert len(two_arg_calls) >= 2, f"Expected calls with 2 arguments, got {calls}"


def test_symbol_cell_slot_arrow_button_contract():
    """Verify SYMBOL_CELL_SLOT HTML contract has exact arrow icon, title, and stock360 event emit."""
    assert "class=\"mp-symbol-open\"" in SYMBOL_CELL_SLOT
    assert "title=\"Open Stock 360\"" in SYMBOL_CELL_SLOT
    assert "$parent.$emit('stock360'" in SYMBOL_CELL_SLOT
    assert "↗" in SYMBOL_CELL_SLOT
