from __future__ import annotations

from pathlib import Path

import App.ui.widgets as widgets_module
from App.ui.styles import STYLES_HTML


def test_shared_signal_and_leadership_tiles_exist() -> None:
    assert callable(getattr(widgets_module, "signal_tile", None))
    assert callable(getattr(widgets_module, "leadership_tile", None))
    assert callable(getattr(widgets_module, "chart_panel", None))

    source = Path("App/ui/widgets.py").read_text(encoding="utf-8")
    for token in ("mp-signal-tile", "mp-leadership-tile", "mp-chart-panel"):
        assert token in source


def test_line_primitives_support_explicit_semantic_tones_and_area_context() -> None:
    source = Path("App/ui/widgets.py").read_text(encoding="utf-8")
    assert "series_tones" in source
    assert "areaStyle" in source
    assert '"smooth": False' in source
    assert '"animation": False' in source


def test_sample_parity_surface_tokens_make_semantics_visible() -> None:
    css = STYLES_HTML.lower()
    for token in (
        ".mp-regime-strip",
        ".mp-leadership-strip",
        ".mp-chart-panel",
        ".mp-signal-tile.tone-good",
        ".mp-signal-tile.tone-bad",
        ".mp-heat-up-1 { background: var(--mp-good-bg)",
        ".mp-heat-down-1 { background: var(--mp-bad-bg)",
    ):
        assert token in css


def test_signal_tile_tone_mapping_is_data_semantic() -> None:
    assert widgets_module.signal_tone(70, midpoint=50) == "good"
    assert widgets_module.signal_tone(30, midpoint=50) == "bad"
    assert widgets_module.signal_tone(50, midpoint=50) == "neutral"

