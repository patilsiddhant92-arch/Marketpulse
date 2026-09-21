import re
from pathlib import Path

import duckdb
import pandas as pd

from App.ui.stock_drawer import (
    query_stock_candlestick_data,
    query_stock_rs_delivery_history,
    load_stock_note,
    save_stock_note,
    toggle_watchlist_symbol,
    is_in_watchlist,
)

DB_PATH = Path("Database/marketpulse.duckdb")
USER_DB = Path("Database/marketpulse_user.duckdb")


def test_stock_candlestick_query_limits_400_then_reverses(tmp_path):
    src = Path("App/ui/stock_drawer.py").read_text(encoding="utf-8")
    fn = src.split("def query_stock_candlestick_data", 1)[1].split("def query_stock_360_data", 1)[0]
    assert "ORDER BY trade_date DESC" in fn
    assert re.search(r"LIMIT\s+(?:400\b|\?)", fn)
    assert "iloc[::-1]" in fn
    assert "ORDER BY trade_date ASC" not in fn

    db_path = tmp_path / "chart.duckdb"
    dates = pd.bdate_range("2024-01-02", periods=450)
    frame = pd.DataFrame({
        "trade_date": dates,
        "open_price": 100.0,
        "close_price": 101.0,
        "low_price": 99.0,
        "high_price": 102.0,
        "volume": 1000,
        "ema_10": 100.0,
        "ema_20": 100.0,
        "ema_50": 100.0,
        "ema_200": 100.0,
        "rsi_14": 50.0,
        "symbol": "AAA",
    })
    with duckdb.connect(str(db_path)) as db:
        db.register("frame", frame)
        db.execute("CREATE TABLE indicators_daily AS SELECT * FROM frame")

    from Scripts.desk_contract import DARVAS
    expected_cap = int(DARVAS["box_lookback_sessions"])
    capped = query_stock_candlestick_data(db_path, "AAA", limit=500)
    assert len(capped["dates"]) == expected_cap
    assert capped["dates"] == [d.strftime("%Y-%m-%d") for d in dates[-expected_cap:]]

    data = query_stock_candlestick_data(db_path, "AAA", limit=5)
    assert data["dates"] == [d.strftime("%Y-%m-%d") for d in dates[-5:]]


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


def test_stock_rs_delivery_history_query():
    hist = query_stock_rs_delivery_history(DB_PATH, "RELIANCE", limit=60)
    assert bool(hist) is True
    assert len(hist["dates"]) == 60
    assert len(hist["rs"]) == 60
    assert len(hist["delivery_pct"]) == 60
    assert len(hist["volume"]) == 60
    assert len(hist["delivery_qty"]) == 60
    # Chronological ascending
    assert hist["dates"][-1] > hist["dates"][0]
    # Check types
    assert isinstance(hist["rs"][-1], float)
    assert isinstance(hist["delivery_pct"][-1], float)
    assert isinstance(hist["volume"][-1], (int, float))

    # Graceful handling for non-existent stock
    empty_hist = query_stock_rs_delivery_history(DB_PATH, "NON_EXISTENT_SYMBOL_XYZ", limit=60)
    assert empty_hist == {"dates": [], "rs": [], "delivery_pct": [], "volume": [], "delivery_qty": [], "close": []}

    # Empty and None symbol guards
    assert query_stock_rs_delivery_history(DB_PATH, "", limit=60) == {"dates": [], "rs": [], "delivery_pct": [], "volume": [], "delivery_qty": [], "close": []}
    assert query_stock_rs_delivery_history(DB_PATH, None, limit=60) == {"dates": [], "rs": [], "delivery_pct": [], "volume": [], "delivery_qty": [], "close": []}

