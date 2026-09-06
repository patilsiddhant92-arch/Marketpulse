from __future__ import annotations

from App.ui.styles import STYLES_HTML


def test_institutional_midnight_tokens_are_centralized() -> None:
    expected = {
        "--mp-bg:#080c12",
        "--mp-surface:#101721",
        "--mp-surface-raised:#151f2b",
        "--mp-primary:#d8ac3d",
        "--mp-good:#45d483",
        "--mp-bad:#f27c84",
        "--mp-warn:#f0be58",
        "--mp-cyan:#5ad3d0",
    }
    css = STYLES_HTML.lower().replace(" ", "")
    assert all(token in css for token in expected)


def test_shared_surface_contract_has_responsive_canvas_and_focus_rules() -> None:
    css = STYLES_HTML.lower()
    assert ".mp-app-shell" in css
    assert ".mp-page-canvas" in css
    assert ".mp-panel" in css
    assert ".mp-status-banner" in css
    assert ":focus-visible" in css
    assert "prefers-reduced-motion" in css
    assert "linear-gradient" not in css


def test_sticky_chrome_does_not_reserve_an_extra_fixed_header_gap() -> None:
    assert "#app > .q-layout > .q-page-container { padding-top: 0 !important; }" in STYLES_HTML
    assert "#app > .q-layout > .q-page-container > .q-page > .nicegui-content { padding: 0 !important; }" in STYLES_HTML


def test_standard_table_contract_is_fixed_and_fluid() -> None:
    css = STYLES_HTML.lower()
    assert "table-layout: fixed !important" in css
    assert "width: 100% !important" in css
    assert "width: max-content !important" not in css


def test_checkbox_states_are_visible_on_the_midnight_surface() -> None:
    css = STYLES_HTML.lower()
    assert ".q-checkbox__inner--falsy .q-checkbox__bg" in css
    assert "border-color: var(--mp-muted) !important" in css
    assert ".q-checkbox__inner--truthy .q-checkbox__bg" in css
    assert "background-color: var(--mp-primary) !important" in css
    assert ".q-checkbox__svg { color: var(--mp-inverse) !important; }" in css
