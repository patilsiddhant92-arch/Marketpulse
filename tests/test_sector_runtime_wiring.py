from __future__ import annotations

from pathlib import Path


def test_sector_intel_runtime_is_taxonomy_only() -> None:
    source = (Path(__file__).parents[1] / "App" / "pages" / "research" / "sector_intel.py").read_text(encoding="utf-8")

    assert "thematic_read_model" not in source
    assert '"view_mode": "Thematic"' not in source
    assert "NEXTGEN_TECH_UNIVERSE" not in source
    assert '"selected_level": "Sector"' in source
    assert "_render_taxonomy_tree_workspace" in source
