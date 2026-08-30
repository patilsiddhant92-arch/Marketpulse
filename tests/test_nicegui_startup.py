from __future__ import annotations


def test_client_javascript_is_skipped_until_nicegui_loop_exists(monkeypatch):
    import nicegui.core as nicegui_core
    from App import app as app_module

    calls: list[str] = []
    monkeypatch.setattr(nicegui_core, "loop", None)
    monkeypatch.setattr(app_module.ui, "run_javascript", lambda code, **_: calls.append(code))

    result = app_module._run_client_javascript("window.__marketpulse_test = true;")

    assert result is None
    assert calls == []


def test_client_javascript_is_forwarded_after_nicegui_loop_starts(monkeypatch):
    import nicegui.core as nicegui_core
    from App import app as app_module

    class ActiveLoop:
        def is_closed(self):
            return False

    sentinel = object()
    monkeypatch.setattr(nicegui_core, "loop", ActiveLoop())
    monkeypatch.setattr(app_module.ui, "run_javascript", lambda code, **_: sentinel)

    assert app_module._run_client_javascript("window.__marketpulse_test = true;") is sentinel
