from pathlib import Path
import os
import pytest


def test_app_exposes_candidates_health_and_loopback_default():
    source = Path("App/app.py").read_text(encoding="utf-8")
    assert '("Candidates", candidates_page, "candidates", False)' in source
    assert '("Data Health", data_health_page, "data-health", False)' in source
    assert 'host = (os.environ.get("MP_HOST") or "127.0.0.1").strip() or "127.0.0.1"' in source
    assert "MP_ALLOW_REMOTE" in source
    assert "build_today_decision_panel" in source


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


def test_app_market_db_connects_are_read_only():
    source = Path("App/app.py").read_text(encoding="utf-8")
    # No market write helpers remain.
    assert "def write_execute" not in source
    assert "def write_query" not in source
    assert "def ensure_portfolio_tables" not in source
    # Market DB open path is read_only=True on the default con().
    assert 'duckdb.connect(str(DB_PATH), read_only=True)' in source
