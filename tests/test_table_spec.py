from __future__ import annotations

from App.ui.table import SCREENER_COLUMNS, SWING_COLUMNS, SYMBOL_CELL_SLOT, ColumnSpec, fixed_table_css
from App.ui.styles import STYLES_HTML


def test_table_specs_have_explicit_widths_and_approved_totals() -> None:
    assert sum(column.width_px for column in SWING_COLUMNS) == 768
    assert sum(column.width_px for column in SCREENER_COLUMNS) == 1040
    assert all(isinstance(column, ColumnSpec) and column.width_px > 0 for column in [*SWING_COLUMNS, *SCREENER_COLUMNS])


def test_fixed_table_css_removes_auto_layout_and_why_now_column() -> None:
    css = fixed_table_css()

    assert "table-layout: fixed" in css
    assert "why_now" not in css


def test_symbol_name_opens_tradingview_and_arrow_opens_drawer() -> None:
    slot = SYMBOL_CELL_SLOT
    assert "tradingview.com/chart/?symbol=NSE:" in slot
    assert "mp-symbol-open" in slot
    assert "$parent.$emit('stock360'" in slot
    assert 'class="mp-symbol"' in slot
    name_pos = slot.find('class="mp-symbol"')
    arrow_pos = slot.find("$parent.$emit('stock360'")
    assert 0 <= name_pos < arrow_pos
    app = __import__("pathlib").Path("App/app.py").read_text(encoding="utf-8")
    assert 'table.add_slot("body-cell-symbol", SYMBOL_CELL_SLOT)' in app


def test_active_theme_uses_dark_terminal_tokens() -> None:
    assert "--mp-bg:" in STYLES_HTML
    assert "mp-up" in STYLES_HTML
    assert "mp-down" in STYLES_HTML
    assert "table-layout: fixed !important" in STYLES_HTML
    assert "width: 100% !important" in STYLES_HTML
    assert "table-layout: auto !important" not in STYLES_HTML
    assert "width: max-content !important" not in STYLES_HTML
    assert "linear-gradient(90deg" not in STYLES_HTML


def test_canonical_global_column_registry_coverage() -> None:
    from App.ui.columns import GLOBAL_COLUMNS, get_column_label, get_quasar_column_def, table_min_width_px

    # Standardized abbreviations
    assert get_column_label("close_price") == "CMP"
    assert get_column_label("cmp") == "CMP"
    assert get_column_label("day_pct") == "1D %"
    assert get_column_label("return_1d_pct") == "1D %"
    assert get_column_label("return_5d_pct") == "5D %"
    assert get_column_label("week_pct") == "5D %"
    assert get_column_label("return_1m_pct") == "1M %"
    assert get_column_label("month_pct") == "1M %"
    assert get_column_label("market_cap_cr") == "MCAP"
    assert get_column_label("turnover_1d_cr") == "TURNOVER"
    assert get_column_label("turnover_cr") == "TURNOVER"
    assert get_column_label("rs_percentile") == "RS"
    assert get_column_label("above_50ema_pct") == ">50 EMA"
    assert get_column_label("above_200ema_pct") == ">200 EMA"
    assert get_column_label("top_leaders") == "LEADERS"
    assert get_column_label("group_name") == "SECTOR / GROUP"

    # get_quasar_column_def generates full Quasar styling
    col = get_quasar_column_def("group_name")
    assert col["name"] == "group_name"
    assert col["label"] == "SECTOR / GROUP"
    assert "mp-sticky-col" in col["classes"]
    assert "width:210px" in col["style"]
    assert "min-width:180px" in col["style"]

    # Leaders column has generous width contract
    leaders_col = get_quasar_column_def("top_leaders", width_override=280)
    assert leaders_col["label"] == "LEADERS"
    assert "width:280px" in leaders_col["style"]
    assert "min-width:240px" in leaders_col["style"]

    # Minimum width helper
    min_w = table_min_width_px(["rotation_rank", "group_name", "top_leaders"])
    assert min_w >= 48 + 180 + 240
