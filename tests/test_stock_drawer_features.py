from pathlib import Path
from App.ui.stock_drawer import (
    query_stock_candlestick_data,
    load_stock_note,
    save_stock_note,
    toggle_watchlist_symbol,
    is_in_watchlist,
)

DB_PATH = Path("Database/marketpulse.duckdb")
USER_DB = Path("Database/marketpulse_user.duckdb")


def test_stock_candlestick_query_returns_expected_structure():
    data = query_stock_candlestick_data(DB_PATH, "RELIANCE", limit=60)
    assert bool(data) is True
    assert len(data["dates"]) == 60
    assert len(data["ohlc"]) == 60
    assert len(data["volume"]) == 60
    assert len(data["ema10"]) == 60
    assert len(data["ema200"]) == 60
    assert len(data["rsi"]) == 60
    # verify OHLC values are floats
    o, c, l, h = data["ohlc"][-1]
    assert h >= l


def test_user_notes_roundtrip():
    test_symbol = "TEST_STOCK"
    test_note = "Testing local setup breakout thesis at 1450"
    save_stock_note(USER_DB, test_symbol, test_note)
    loaded = load_stock_note(USER_DB, test_symbol)
    assert loaded == test_note


def test_user_watchlist_toggle():
    test_symbol = "TEST_WL_STOCK"
    # Ensure initially false or toggle to known state
    if is_in_watchlist(USER_DB, 1, test_symbol):
        toggle_watchlist_symbol(USER_DB, 1, test_symbol)

    assert is_in_watchlist(USER_DB, 1, test_symbol) is False
    added = toggle_watchlist_symbol(USER_DB, 1, test_symbol)
    assert added is True
    assert is_in_watchlist(USER_DB, 1, test_symbol) is True
    removed = toggle_watchlist_symbol(USER_DB, 1, test_symbol)
    assert removed is False
    assert is_in_watchlist(USER_DB, 1, test_symbol) is False
