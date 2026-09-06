from __future__ import annotations

from pathlib import Path

import App.ui.widgets as widgets_module
from App.ui.styles import STYLES_HTML


def test_chart_theme_matches_institutional_midnight_semantics() -> None:
    theme_builder = getattr(widgets_module, "chart_theme", None)
    assert callable(theme_builder), "chart_theme must centralize ECharts visual tokens"
    theme = theme_builder()
    assert theme["text"] == "#98A7BA"
    assert theme["grid"] == "#263447"
    assert theme["series"][0] == "#D8AC3D"
    assert theme["series"][1] == "#74A9FF"
    assert theme["good"] == "#45D483"
    assert theme["bad"] == "#F27C84"


def test_shared_primitives_have_compact_spacing_and_focus_rules() -> None:
    css = STYLES_HTML.lower()
    assert ".mp-status-banner" in css
    assert ".mp-kpi-tile" in css
    assert ":focus-visible" in css
    assert "prefers-reduced-motion" in css


def test_vcp_chart_consumes_the_shared_chart_theme() -> None:
    source = Path("App/ui/vcp_chart.py").read_text(encoding="utf-8")
    assert "chart_theme" in source
    assert "#2a261c" not in source
    assert "#d8d0c0" not in source
