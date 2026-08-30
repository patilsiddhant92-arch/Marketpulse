from pathlib import Path


def test_stock_360_header_contains_decision_context_and_action_summary():
    source = Path("App/ui/stock_drawer.py").read_text(encoding="utf-8")

    assert "Market Regime" in source
    assert "Action State" in source
    assert "Event Risk" in source
    assert "Data As Of" in source
    assert "Invalid geometry" in source
    assert "SMA template" in source
    assert "render_t_panel" in source
