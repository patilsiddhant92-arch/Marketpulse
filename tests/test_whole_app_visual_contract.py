from __future__ import annotations

from pathlib import Path

from App.ui.styles import STYLES_HTML


def test_momentum_filter_groups_have_a_narrow_layout_contract() -> None:
    source = Path("App/app.py").read_text(encoding="utf-8")
    css = STYLES_HTML.lower()
    assert "mp-momentum-filters" in source
    assert "mp-filter-check-row" in source
    assert ".mp-momentum-filters" in css
    assert ".mp-filter-check-row" in css
    assert "grid-template-columns: minmax(0, 1fr)" in css
    row_start = css.index(".mp-momentum-filters > .mp-filter-check-row")
    assert "grid-column: 1 / -1" in css[row_start : row_start + 420]


def test_market_health_chart_helper_uses_shared_visual_primitive() -> None:
    source = Path("App/app.py").read_text(encoding="utf-8")
    assert "chart_panel" in source
    assert "line_chart" in source
    assert '"smooth": True' not in source


def test_sector_board_uses_bounded_chart_and_heatmap_sections() -> None:
    source = Path("App/pages/research/sector_board.py").read_text(encoding="utf-8")
    assert "chart_panel" in source
    assert "mp-sector-visuals w-full" in source


def test_metric_cards_keep_semantic_surface_classes() -> None:
    source = Path("App/app.py").read_text(encoding="utf-8")
    assert "mp-kpi-tile mp-signal-tile tone-" in source
