"""Unit tests verifying Milestone M1 features and invariants (F4, F5, F6, F7)."""
from __future__ import annotations

from pathlib import Path
import pytest

from App.app import copy_text_to_clipboard
from App.ui.columns import GLOBAL_COLUMNS, get_column_label, get_functional_header_group, get_quasar_column_def
from App.ui.number_format import _format_money, format_cell
from App.ui.styles import STYLES_HTML


def test_f4_styles_contrast_and_font_size():
    """F4: Verify --mp-faint contrast token and badge 12px font size enforcement."""
    assert "--mp-faint:           #7888a0;" in STYLES_HTML
    assert "font-size: 12px !important;" in STYLES_HTML
    assert "body.body--light .mp-badge.mp-good" in STYLES_HTML
    assert "body.body--light .mp-badge.mp-bad" in STYLES_HTML
    assert "body.body--light .mp-badge.mp-warn" in STYLES_HTML
    assert "body.body--light .mp-badge.mp-info" in STYLES_HTML
    assert "body.body--light .mp-deal-badge" in STYLES_HTML
    assert "body.body--light .mp-sector-badge" in STYLES_HTML


def test_f5_rsi_label_collision_resolved():
    """F5: Verify rsi_14 displays 'RSI' and does not collide with 'RS'."""
    assert GLOBAL_COLUMNS["rsi_14"].label == "RSI"
    assert get_column_label("rsi_14") == "RSI"
    assert GLOBAL_COLUMNS["rs_percentile"].label == "RS"
    q_col = get_quasar_column_def("rsi_14")
    assert q_col["label"] == "RSI"
    assert "mp-th-momentum" in q_col["headerClasses"]


def test_f5_functional_header_groups():
    """F5: Verify table header functional groups assign correct CSS classes."""
    assert get_functional_header_group("cmp", "Market") == "price-return"
    assert get_functional_header_group("return_1d_pct", "Market") == "price-return"
    assert get_functional_header_group("turnover_cr", "Flow") == "volume"
    assert get_functional_header_group("rvol", "Setup") == "volume"
    assert get_functional_header_group("rs_percentile", "Setup") == "rs"
    assert get_functional_header_group("pe", "Quality") == "valuation"
    assert get_functional_header_group("rsi_14", "Momentum") == "momentum"
    assert get_functional_header_group("stop_loss", "Risk") == "risk"
    assert get_functional_header_group("symbol", "Identity") == "identity"

    # Header styles in STYLES_HTML
    assert "mp-th-price-return" in STYLES_HTML
    assert "mp-th-volume" in STYLES_HTML
    assert "mp-th-rs" in STYLES_HTML
    assert "mp-th-valuation" in STYLES_HTML
    assert "mp-th-momentum" in STYLES_HTML
    assert "mp-th-risk" in STYLES_HTML


def test_f6_clipboard_dual_signature_flexibility():
    """F6 / Invariant 2: Verify clipboard helper supports single and dual arguments without error."""
    # Single argument (string of symbols)
    copy_text_to_clipboard("NSE:TCS,NSE:INFY")
    # Dual argument (label, text)
    copy_text_to_clipboard("My Watchlist", "NSE:TCS,NSE:INFY")
    # Missing / None
    copy_text_to_clipboard(None)

    # Verify app.py passes copy_text_to_clipboard directly without rigid lambdas
    app_code = Path("App/app.py").read_text(encoding="utf-8")
    assert "copy_text=copy_text_to_clipboard" in app_code
    assert "copy_text=lambda label, text:" not in app_code


def test_f7_float_deadband_invariant():
    """F7 / Invariant 4: Verify near-zero float deadband eliminates -0.0 and -0."""
    # Net value near-zero negative values
    text, tone = format_cell("net_value_cr", -0.02)
    assert text == "+0.0"
    assert tone == ""

    text, tone = format_cell("net_value_cr", 0.02)
    assert text == "+0.0"
    assert tone == ""

    text, tone = format_cell("net_value_cr", -0.001)
    assert text == "+0.0"
    assert tone == ""

    # Significant negative numbers retain negative sign and tone
    text, tone = format_cell("net_value_cr", -12.5)
    assert text == "-12.5"
    assert tone == "mp-down"

    # Significant positive numbers retain positive sign and tone
    text, tone = format_cell("net_value_cr", 12.5)
    assert text == "+12.5"
    assert tone == "mp-up"

    # Rupee INR deadband
    text, tone = format_cell("profit_inr", -0.01)
    assert text == "+₹0"
    assert tone == ""
