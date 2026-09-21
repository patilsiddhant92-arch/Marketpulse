"""Automated regression suite verifying F3 Stock Name Arrow Action across all MarketPulse tables."""
from __future__ import annotations

from pathlib import Path
import pytest
from App.ui.table import SYMBOL_CELL_SLOT, _table_event_symbol


class MockNiceGUIEvent:
    def __init__(self, args):
        self.args = args


def test_table_event_symbol_normalizes_all_payload_variants():
    """Verify _table_event_symbol handles every NiceGUI/Quasar event shape without error."""
    # 1. Standard string
    assert _table_event_symbol("TCS") == "TCS"
    assert _table_event_symbol(MockNiceGUIEvent("TCS")) == "TCS"

    # 2. List containing string (NiceGUI default)
    assert _table_event_symbol(["INFY"]) == "INFY"
    assert _table_event_symbol(MockNiceGUIEvent(["INFY"])) == "INFY"
    assert _table_event_symbol(MockNiceGUIEvent(["INFY", "extra_arg"])) == "INFY"

    # 3. List containing dict
    assert _table_event_symbol([{"symbol": "RELIANCE"}]) == "RELIANCE"
    assert _table_event_symbol(MockNiceGUIEvent([{"symbol": "RELIANCE"}])) == "RELIANCE"
    assert _table_event_symbol(MockNiceGUIEvent([{"value": "HDFCBANK"}])) == "HDFCBANK"

    # 4. Direct dict
    assert _table_event_symbol({"symbol": "ITC"}) == "ITC"
    assert _table_event_symbol(MockNiceGUIEvent({"symbol": "ITC"})) == "ITC"
    assert _table_event_symbol(MockNiceGUIEvent({"value": "LT"})) == "LT"

    # 5. Stringified python list
    assert _table_event_symbol(MockNiceGUIEvent("['SBIN']")) == "SBIN"
    assert _table_event_symbol(MockNiceGUIEvent('["SBIN"]')) == "SBIN"

    # 6. Whitespace and lowercase normalization
    assert _table_event_symbol("  tatamotors  ") == "TATAMOTORS"
    assert _table_event_symbol(MockNiceGUIEvent(["  tatamotors  "])) == "TATAMOTORS"

    # 7. None and empty collections
    assert _table_event_symbol(None) == ""
    assert _table_event_symbol("") == ""
    assert _table_event_symbol([]) == ""
    assert _table_event_symbol({}) == ""
    assert _table_event_symbol(MockNiceGUIEvent(None)) == ""
    assert _table_event_symbol(MockNiceGUIEvent([])) == ""


def test_symbol_cell_slot_contains_arrow_and_stock360():
    """Verify SYMBOL_CELL_SLOT contract remains exact."""
    assert "mp-symbol-open" in SYMBOL_CELL_SLOT
    assert "stock360" in SYMBOL_CELL_SLOT
    assert "quick_wl" in SYMBOL_CELL_SLOT
    assert "tradingview.com/chart/?symbol=NSE:" in SYMBOL_CELL_SLOT
    assert "Open Stock 360" in SYMBOL_CELL_SLOT


def test_action_desk_has_no_duplicate_stock360_listener():
    """Verify action_desk.py does not attach a redundant stock360 listener."""
    content = Path("App/pages/action_desk.py").read_text(encoding="utf-8")
    assert 'tbl.on("stock360"' not in content, (
        "Duplicate stock360 listener detected in action_desk.py! table_from_df already wires it."
    )


def test_sector_intel_uses_table_event_symbol_safe_parsing():
    """Verify sector_intel.py parses stock360 events safely without calling .get() on list."""
    content = Path("App/pages/research/sector_intel.py").read_text(encoding="utf-8")
    assert ".get(\"symbol\")" not in content, (
        "Unsafe event.args.get('symbol') found in sector_intel.py! Must use _table_event_symbol."
    )
    assert "_table_event_symbol" in content
    assert 'table.on("quick_wl"' in content


def test_sector_board_emits_stock360_and_supports_open_stock():
    """Verify sector_board.py emits stock360 on all symbol buttons and supports both event names."""
    content = Path("App/pages/research/sector_board.py").read_text(encoding="utf-8")
    # All .mp-symbol-open buttons must emit 'stock360'
    assert "$parent.$emit('stock360', props.value)" in content
    # Standard title on button
    assert 'title="Open Stock 360"' in content
    # Both events wired for backward compatibility
    assert 't.on("stock360"' in content
    assert 't.on("open_stock"' in content
