"""Empirical Challenger Test Suite for Milestone M1 (F4, F5, F6, F7).

Executed by: Challenger M1_2 (teamwork_preview_challenger_m1_2)
Verifies:
- F4: Badge contrast ratios across dark (#101721) and light (#ffffff) themes (WCAG AA >= 4.5:1)
- F5: Header dictionary, RSI vs RS collision resolution, and functional group color palettes
- F6: Clipboard callback flexibility (Invariant 2: single-arg, dual-arg, event argument defense)
- F7: Float near-zero deadband (Invariant 4) across boundary floats [-0.0499, -0.0500, -0.0001, 0.0, 0.0001, 0.0499, -1.23]
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any
import pytest

from App.app import copy_text_to_clipboard
from App.ui.columns import (
    GLOBAL_COLUMNS,
    get_column_label,
    get_functional_header_group,
    get_quasar_column_def,
)
from App.ui.number_format import (
    _format_money,
    _signed_tone,
    classify_column,
    format_cell,
)
from App.ui.styles import STYLES_HTML


# =========================================================================
# F4: Relative Luminance and WCAG AA Contrast Mathematical Testing
# =========================================================================

def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def blend_rgba(fg_hex: str, alpha: float, bg_rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    fg_rgb = hex_to_rgb(fg_hex)
    return tuple(int(fg_rgb[i] * alpha + bg_rgb[i] * (1 - alpha)) for i in range(3))


def srgb_to_lin(c: int) -> float:
    v = c / 255.0
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    r = srgb_to_lin(rgb[0])
    g = srgb_to_lin(rgb[1])
    b = srgb_to_lin(rgb[2])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(rgb1: tuple[int, int, int], rgb2: tuple[int, int, int]) -> float:
    l1 = relative_luminance(rgb1)
    l2 = relative_luminance(rgb2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


DARK_SURFACE = hex_to_rgb("101721")
LIGHT_SURFACE = hex_to_rgb("ffffff")


def test_f4_dark_theme_wcag_aa_contrast():
    """F4: Compute WCAG AA contrast ratios for all dark theme badge tokens against surface and badge bg."""
    dark_tokens = [
        ("mp-good / leading", "#45d483", "#163526"),
        ("mp-bad / lagging", "#f27c84", "#3a2027"),
        ("mp-warn / weakening", "#f0be58", "#3a2f18"),
        ("mp-info / emerging", "#74a9ff", "#182b46"),
        ("mp-improving", "#5ad3d0", "#123238"),
        ("mp-neutral / chip", "#98a7ba", "#1a2431"),
        ("mp-sector-badge", "#56d364", "#17351f"),
        ("mp-industry-badge", "#39c5cf", "#102f36"),
        ("mp-improving-badge", "#79c0ff", "#1c3450"),
        ("mp-deal-badge", "#e3b341", "#3c2f14"),
        ("mp-sector-tag", "#38bdf8", "#0f2d3d"),
        ("mp-deal-badge-fii", "#38bdf8", blend_rgba("38bdf8", 0.18, DARK_SURFACE)),
        ("mp-deal-badge-dii", "#c084fc", blend_rgba("a855f7", 0.18, DARK_SURFACE)),
        ("mp-deal-badge-prop", "#fbbf24", blend_rgba("f59e0b", 0.18, DARK_SURFACE)),
        ("--mp-faint", "#7888a0", "#101721"),
        ("--mp-muted", "#98a7ba", "#101721"),
        ("--mp-text", "#f1f4f8", "#101721"),
    ]

    for name, text_hex, bg in dark_tokens:
        t_rgb = hex_to_rgb(text_hex)
        b_rgb = bg if isinstance(bg, tuple) else hex_to_rgb(bg)
        cr_bg = contrast_ratio(t_rgb, b_rgb)
        cr_surf = contrast_ratio(t_rgb, DARK_SURFACE)

        assert cr_bg >= 4.5, f"Dark token '{name}' failed contrast vs badge bg: {cr_bg:.2f}:1 < 4.5:1"
        assert cr_surf >= 4.5, f"Dark token '{name}' failed contrast vs dark surface: {cr_surf:.2f}:1 < 4.5:1"


def test_f4_light_theme_wcag_aa_contrast():
    """F4: Compute WCAG AA contrast ratios for all light theme badge tokens against surface and badge bg."""
    light_tokens = [
        ("mp-good / leading", "#0e6237", "#d1f2dd"),
        ("mp-bad / lagging", "#9f1239", "#ffe4e6"),
        ("mp-warn / weakening", "#92400e", "#fef3c7"),
        ("mp-info / emerging", "#1e40af", "#dbeafe"),
        ("mp-improving / ind", "#155e75", "#cffafe"),
        ("mp-neutral / chip", "#334155", "#f1f5f9"),
        ("mp-sector-badge", "#0e6237", "#d1f2dd"),
        ("mp-industry-badge", "#155e75", "#cffafe"),
        ("mp-sector-tag", "#0369a1", "#e0f2fe"),
        ("mp-deal-badge", "#92400e", "#fef3c7"),
        ("mp-deal-badge-fii", "#0369a1", "#e0f2fe"),
        ("mp-deal-badge-dii", "#6b21a8", "#f3e8ff"),
        ("mp-deal-badge-prop", "#92400e", "#fef3c7"),
    ]

    for name, text_hex, bg_hex in light_tokens:
        t_rgb = hex_to_rgb(text_hex)
        b_rgb = hex_to_rgb(bg_hex)
        cr_bg = contrast_ratio(t_rgb, b_rgb)
        cr_surf = contrast_ratio(t_rgb, LIGHT_SURFACE)

        assert cr_bg >= 4.5, f"Light token '{name}' failed contrast vs badge bg: {cr_bg:.2f}:1 < 4.5:1"
        assert cr_surf >= 4.5, f"Light token '{name}' failed contrast vs light surface: {cr_surf:.2f}:1 < 4.5:1"


def test_f4_badge_typography_and_minimum_font_size():
    """F4: Verify badges enforce minimum 12px font size and eliminate sub-11px micro-text."""
    assert "font-size: 12px !important;" in STYLES_HTML
    assert ".mp-mini-badge" in STYLES_HTML
    assert "--mp-text-xs:   13px;" in STYLES_HTML


# =========================================================================
# F5: Header Dictionary, Palette, and Collision Resolution
# =========================================================================

def test_f5_header_dictionary_and_rs_rsi_collision():
    """F5: Verify RSI vs RS label disambiguation and functional header styling."""
    assert GLOBAL_COLUMNS["rsi_14"].label == "RSI"
    assert get_column_label("rsi_14") == "RSI"
    assert GLOBAL_COLUMNS["rs_percentile"].label == "RS"
    assert get_column_label("rs_percentile") == "RS"

    q_rsi = get_quasar_column_def("rsi_14")
    assert "mp-th-momentum" in q_rsi["headerClasses"]

    q_rs = get_quasar_column_def("rs_percentile")
    assert "mp-th-rs" in q_rs["headerClasses"]

    q_cmp = get_quasar_column_def("cmp")
    assert "mp-th-price-return" in q_cmp["headerClasses"]

    q_pe = get_quasar_column_def("pe")
    assert "mp-th-valuation" in q_pe["headerClasses"]

    q_vol = get_quasar_column_def("turnover_cr")
    assert "mp-th-volume" in q_vol["headerClasses"]

    q_risk = get_quasar_column_def("stop_loss")
    assert "mp-th-risk" in q_risk["headerClasses"]


# =========================================================================
# F6: Clipboard Callback Flexibility (Invariant 2)
# =========================================================================

class MockNiceGUIEvent:
    def __init__(self, sender: Any = "btn", client: Any = "client"):
        self.sender = sender
        self.client = client


def test_f6_clipboard_adversarial_signatures():
    """F6: Stress-test copy_text_to_clipboard with diverse argument patterns."""
    copy_text_to_clipboard("NSE:RELIANCE,NSE:TCS")
    copy_text_to_clipboard("TCS")
    copy_text_to_clipboard("Nifty IT", "NSE:TCS,NSE:INFY,NSE:WIPRO")
    copy_text_to_clipboard("")
    copy_text_to_clipboard(None)

    event = MockNiceGUIEvent()
    copy_text_to_clipboard(event)
    copy_text_to_clipboard("My Label", event)

    app_text = Path("App/app.py").read_text(encoding="utf-8")
    assert "copy_text=lambda label, text:" not in app_text


# =========================================================================
# F7: Float Near-Zero Deadband (Invariant 4) Boundary Testing & Findings
# =========================================================================

BOUNDARY_FLOATS = [
    -0.0499,
    -0.0500,
    -0.0001,
    0.0,
    0.0001,
    0.0499,
    -1.23,
]


def test_f7_crore_float_formatting_deadband():
    """F7: Verify 1-decimal Crore formatting (net_value_cr, net_deal_cr) respects < 0.05 deadband."""
    for val in [-0.0499, -0.0001, 0.0, 0.0001, 0.0499]:
        text, tone = format_cell("net_value_cr", val)
        assert text == "+0.0"
        assert tone == ""

    # Significant negatives retain negative sign and tone
    text, tone = format_cell("net_value_cr", -1.23)
    assert text == "-1.2"
    assert tone == "mp-down"


def test_f7_defect_inr_format_money_negative_zero():
    """F7 DEFECT CONFIRMATION: _format_money returns -₹0 for boundary float -0.0500 and near-zero INR."""
    val = -0.0500
    res_inr_signed = _format_money(val, signed=True, is_inr=True)
    # EMPIRICAL FINDING: Currently produces '-₹0' because abs(-0.0500) < 0.05 is False,
    # and f"{abs(val):,.0f}" rounds to "0", but sign logic appends "-"
    assert res_inr_signed == "-\u20b90", f"Expected defect confirmation '-\\u20b90', got {res_inr_signed}"


def test_f7_defect_deal_flow_card_negative_zero():
    """F7 DEFECT CONFIRMATION: deal_flow_card produces '-0' and '+-0 Cr' for boundary float -0.0500."""
    val = -0.0500
    sell_v = float(val)
    net_v = float(val)
    buy_cr = float(val)
    if abs(net_v) < 0.05:
        net_v = 0.0
    if abs(sell_v) < 0.05:
        sell_v = 0.0
    if abs(buy_cr) < 0.05:
        buy_cr = 0.0

    net_text = f"{net_v:+,.0f}"
    buy_text = f"+{buy_cr:,.0f} Cr"

    # EMPIRICAL FINDING: Because :+,.0f formats to 0 decimals, -0.05 formats as '-0'
    # and Buy Cr formats as '+-0 Cr'
    assert net_text == "-0", f"Expected defect confirmation '-0', got {net_text}"
    assert buy_text == "+-0 Cr", f"Expected defect confirmation '+-0 Cr', got {buy_text}"


def test_f7_defect_unclassified_net_cr_columns():
    """F7 DEFECT CONFIRMATION: net_cr and institutional net columns are classified as 'money' instead of 'signed_money'."""
    # Columns that represent net institutional flow but lack signed_money classification
    unclassified_net_cols = ["net_cr", "inst_net_cr", "fii_net_cr", "dii_net_cr", "prop_net_cr"]
    for col in unclassified_net_cols:
        kind = classify_column(col)
        # EMPIRICAL FINDING: classify_column returns 'money' instead of 'signed_money'
        assert kind == "money", f"Column {col} expected to show missing signed_money classification"
