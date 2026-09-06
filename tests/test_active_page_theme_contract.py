from __future__ import annotations

from pathlib import Path


def test_active_page_modules_use_shared_page_roots() -> None:
    app_text = Path("App/app.py").read_text(encoding="utf-8")
    for marker in (
        "mp-page-desk",
        "mp-page-momentum",
        "mp-page-template",
        "mp-page-research",
        "mp-page-deals",
        "mp-page-portfolio",
        "mp-page-health",
    ):
        assert marker in app_text


def test_sector_research_does_not_emit_legacy_light_gradient_surfaces() -> None:
    text = Path("App/pages/research/sector_intel.py").read_text(encoding="utf-8")
    assert "bg-gradient-to-r" not in text
    assert "shadow-md" not in text


def test_active_ui_code_does_not_emit_the_old_light_palette_literals() -> None:
    for path in ("App/app.py", "App/pages/research/sector_intel.py"):
        text = Path(path).read_text(encoding="utf-8").lower()
        assert "#01696f" not in text
        assert "#28251d" not in text
        assert "#a12c7b" not in text
