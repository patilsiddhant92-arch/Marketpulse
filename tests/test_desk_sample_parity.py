from __future__ import annotations

from pathlib import Path


DESK_SOURCE = Path("App/pages/desk.py").read_text(encoding="utf-8")


def test_desk_first_viewport_uses_sample_parity_composition() -> None:
    """The Desk must be composed from the approved regime/leadership/chart hierarchy."""
    for token in (
        "signal_tile",
        "leadership_tile",
        "chart_panel",
        "mp-regime-strip",
        "mp-leadership-strip",
        "mp-movers-grid",
    ):
        assert token in DESK_SOURCE


def test_desk_keeps_positive_negative_chart_semantics_visible() -> None:
    assert "series_tones" in DESK_SOURCE
    assert "tone=\"good\"" in DESK_SOURCE
    assert "tone=signal_tone" in DESK_SOURCE
    assert "flow_spark" in DESK_SOURCE


def test_desk_chart_sections_are_bounded_panels_not_loose_headings() -> None:
    assert "with chart_panel(" in DESK_SOURCE
    assert "Participation" in DESK_SOURCE
    assert "Sector rotation" in DESK_SOURCE
    assert "Buy / sell flow" in DESK_SOURCE
