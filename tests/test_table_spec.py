from __future__ import annotations

from App.ui.table import SCREENER_COLUMNS, SWING_COLUMNS, ColumnSpec, fixed_table_css
from App.ui.styles import STYLES_HTML


def test_table_specs_have_explicit_widths_and_approved_totals() -> None:
    assert sum(column.width_px for column in SWING_COLUMNS) == 768
    assert sum(column.width_px for column in SCREENER_COLUMNS) == 1040
    assert all(isinstance(column, ColumnSpec) and column.width_px > 0 for column in [*SWING_COLUMNS, *SCREENER_COLUMNS])


def test_fixed_table_css_removes_auto_layout_and_why_now_column() -> None:
    css = fixed_table_css()

    assert "table-layout: fixed" in css
    assert "why_now" not in css


def test_active_theme_uses_dark_terminal_tokens() -> None:
    assert "--mp-bg:" in STYLES_HTML
    assert "mp-up" in STYLES_HTML
    assert "mp-down" in STYLES_HTML
    assert "table-layout: auto !important" in STYLES_HTML
    assert "linear-gradient(90deg" not in STYLES_HTML
