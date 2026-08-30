from pathlib import Path
import os
import pytest


def test_app_exposes_candidates_health_and_loopback_default():
    source = Path("App/app.py").read_text(encoding="utf-8")
    assert '("Desk", desk_page, "desk", True)' in source
    assert '("Health", data_health_page, "data-health", False)' in source
    assert '("Sectors", sector_rotation_page, "rotation", False)' in source
    assert '("Deals", deals_page, "deals", False)' in source
    assert '("Portfolio", portfolio_page, "portfolio", False)' in source
    assert 'show_page("Desk")' in source
    assert 'host = (os.environ.get("MP_HOST") or "127.0.0.1").strip() or "127.0.0.1"' in source
    assert "MP_ALLOW_REMOTE" in source
    assert "build_today_decision_panel" in source


def test_momentum_is_a_first_class_active_tab():
    source = Path("App/app.py").read_text(encoding="utf-8")

    assert '("Momentum", special_watchlist_page, "scanner", False)' in source
    assert '("Template", sma_template_page, "sma-template", False)' in source
    assert '("Minervini", minervini_page, "minervini", False)' not in source
    assert "build_sma_template_block" not in source
    assert '("Momentum (legacy)", special_watchlist_page, "scanner-legacy", False)' not in source


def test_navigation_scrolls_inside_the_chrome_without_page_overflow():
    styles = Path("App/ui/styles.py").read_text(encoding="utf-8")

    assert "body {" in styles and "overflow-x: hidden" in styles
    assert ".mp-sticky-nav" in styles and "overflow: hidden" in styles
    assert ".mp-tabs .q-tabs__content" in styles
    assert "overflow-x: auto" in styles


def test_sector_page_uses_dark_tokens_and_keeps_long_rationale_out_of_tables():
    page = Path("App/pages/research/sector_board.py").read_text(encoding="utf-8")
    styles = Path("App/ui/styles.py").read_text(encoding="utf-8")
    app = Path("App/app.py").read_text(encoding="utf-8")

    assert "mp-sector-page" in page
    assert "Why Now Rationale" not in page
    assert "build_sector_board_page" in app
    assert "group_tape" in page
    assert ".mp-sector-page .bg-white" in styles
    assert ".mp-sector-page .text-slate-800" in styles


def test_header_groups_brand_and_status_meta_for_small_screens():
    app = Path("App/app.py").read_text(encoding="utf-8")
    styles = Path("App/ui/styles.py").read_text(encoding="utf-8")

    assert "mp-header-brand" in app
    assert "mp-header-meta" in app
    assert ".mp-header-meta" in styles


def test_production_today_uses_decision_panel_not_stub_snapshot():
    app_source = Path("App/app.py").read_text(encoding="utf-8")
    stub = Path("App/pages/today.py").read_text(encoding="utf-8")
    assert "build_today_decision_panel" in app_source
    assert "load_app_snapshot" not in stub
    assert "NotImplementedError" in stub
    assert "quarantined" in stub.lower()


def test_ui_run_kwargs_refuses_remote_without_allow_flag(monkeypatch):
    import importlib
    import sys

    # Import after path is project-root relative for pytest.
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    # app.py expects Scripts on path
    scripts = root / "Scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))

    # Avoid importing full NiceGUI app UI construction; load module attributes only.
    # app imports nicegui at top level — skip if environment lacks it? project has it.
    monkeypatch.setenv("MP_HOST", "0.0.0.0")
    monkeypatch.delenv("MP_ALLOW_REMOTE", raising=False)

    from App import app as app_module

    importlib.reload(app_module)
    with pytest.raises(RuntimeError, match="MP_ALLOW_REMOTE"):
        app_module._ui_run_kwargs()

    monkeypatch.setenv("MP_ALLOW_REMOTE", "1")
    kwargs = app_module._ui_run_kwargs()
    assert kwargs["host"] == "0.0.0.0"


def test_ui_run_kwargs_uses_non_conflicting_local_port_by_default(monkeypatch):
    import importlib
    import sys

    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    scripts = root / "Scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))

    monkeypatch.delenv("MP_PORT", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("MP_HOST", raising=False)
    from App import app as app_module

    importlib.reload(app_module)
    kwargs = app_module._ui_run_kwargs()

    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8081


def test_launch_batch_selects_a_free_port_for_repeatable_startups():
    launch = Path("Launch_MarketPulse.bat").read_text(encoding="utf-8")

    assert "netstat -ano" in launch
    assert "findstr" in launch
    assert 'set "MP_PORT=%PORT%"' in launch
    assert 'set "URL=http://localhost:%PORT%"' in launch


def test_app_market_db_connects_are_read_only():
    source = Path("App/app.py").read_text(encoding="utf-8")
    # No market write helpers remain.
    assert "def write_execute" not in source
    assert "def write_query" not in source
    assert "def ensure_portfolio_tables" not in source
    # Market DB open path is read_only=True on the default con().
    assert 'duckdb.connect(str(DB_PATH), read_only=True)' in source


def test_screener_page_reads_focused_v2_without_fundamentals():
    source = Path("App/pages/screener.py").read_text(encoding="utf-8")
    assert "load_decision_snapshot" in source
    assert "screener_daily" not in source
    assert "technofunda_score" not in source
