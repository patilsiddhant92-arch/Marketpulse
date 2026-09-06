from __future__ import annotations

from pathlib import Path

import pytest


APP_TEXT = Path("App/app.py").read_text(encoding="utf-8")


def test_app_shell_owns_navigation_and_page_canvas() -> None:
    assert "mp-app-shell" in APP_TEXT
    assert "mp-page-canvas" in APP_TEXT
    assert "aria-label=\"Primary navigation\"" in APP_TEXT


def test_app_header_uses_semantic_brand_and_status_classes() -> None:
    assert "mp-brand-mark" in APP_TEXT
    assert "mp-header-status-good" in APP_TEXT
    assert "mp-header-status-warn" in APP_TEXT


def test_primary_navigation_rerenders_content_from_tabs_value_changes() -> None:
    assert "tabs.on_value_change" in APP_TEXT
    assert "tab_el.on(\"click\"" not in APP_TEXT


def test_main_keeps_nicegui_header_as_a_top_level_layout(monkeypatch, tmp_path) -> None:
    from App import app as app_module

    database = tmp_path / "market.duckdb"
    database.touch()
    monkeypatch.setattr(app_module, "DB_PATH", database)
    monkeypatch.setattr(app_module, "STATUS_PATH", tmp_path / "status.json")
    monkeypatch.setattr(app_module, "add_styles", lambda: None)
    monkeypatch.setattr(app_module.ui, "run", lambda **_: None)
    monkeypatch.setattr(app_module, "desk_page", lambda: None)
    monkeypatch.setattr(app_module, "special_watchlist_page", lambda: None)
    monkeypatch.setattr(app_module, "sma_template_page", lambda: None)
    monkeypatch.setattr(app_module, "sector_rotation_page", lambda: None)
    monkeypatch.setattr(app_module, "deals_page", lambda: None)
    monkeypatch.setattr(app_module, "portfolio_page", lambda: None)
    monkeypatch.setattr(app_module, "data_health_page", lambda: None)

    try:
        app_module.main()
    except RuntimeError as exc:
        pytest.fail(f"main assembled an invalid nested NiceGUI layout: {exc}")
