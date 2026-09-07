from __future__ import annotations

import json
from pathlib import Path
import duckdb
import pandas as pd
import pytest

from App.ui.terminal_bar import fetch_market_indices, load_stocks_master_cache
from App.ui.watchlist_hub import (
    load_watchlist_symbols,
    clear_watchlist_symbols,
    fetch_watchlist_table_data,
)
from App.trade_analytics import calculate_trade_metrics, log_trade_entry, query_journal_records
from App.ui.stock_drawer import toggle_watchlist_symbol


def test_market_indices_query_returns_benchmarks(tmp_path: Path) -> None:
    db = tmp_path / "test_indices.duckdb"
    with duckdb.connect(str(db)) as con:
        con.execute(
            """
            CREATE TABLE index_daily (
                trade_date DATE, index_name TEXT, close_price DOUBLE,
                return_1d_pct DOUBLE, previous_close DOUBLE
            )
            """
        )
        con.execute(
            """
            INSERT INTO index_daily VALUES
            ('2026-09-02', 'Nifty 50', 23914.45, -0.58, 24055.8),
            ('2026-09-02', 'Nifty Bank', 57172.0, -0.41, 57409.6),
            ('2026-09-02', 'NIFTY MIDCAP 100', 63001.6, 0.52, 62675.0),
            ('2026-09-02', 'India VIX', 11.59, -1.2, 11.73)
            """
        )

    results = fetch_market_indices(db)
    assert len(results) == 4
    names = [r["name"] for r in results]
    assert "Nifty 50" in names
    assert "MIDCAP 100" in names
    assert "India VIX" in names
    vix = next(r for r in results if r["name"] == "India VIX")
    # For VIX, down (-1.2%) is good
    assert vix["tone"] == "good"


def test_global_search_loads_stocks_master_cache(tmp_path: Path) -> None:
    db = tmp_path / "test_stocks.duckdb"
    with duckdb.connect(str(db)) as con:
        con.execute(
            """
            CREATE TABLE stocks_master (
                symbol TEXT, security_name TEXT, sector TEXT, industry TEXT,
                latest_close DOUBLE, market_cap_cr DOUBLE
            )
            """
        )
        con.execute(
            """
            INSERT INTO stocks_master VALUES
            ('RELIANCE', 'Reliance Industries', 'Energy', 'Refineries', 1313.1, 1776958.0),
            ('TCS', 'Tata Consultancy Services', 'IT', 'Software', 2348.0, 849526.0)
            """
        )

    import App.ui.terminal_bar as tb
    tb._STOCKS_CACHE = []
    stocks = load_stocks_master_cache(db)
    assert len(stocks) == 2
    symbols = [s["symbol"] for s in stocks]
    assert "RELIANCE" in symbols
    assert "TCS" in symbols


def test_watchlist_hub_crud_and_formatting(tmp_path: Path) -> None:
    user_db = tmp_path / "test_user.duckdb"
    db_path = tmp_path / "test_market.duckdb"

    with duckdb.connect(str(user_db)) as con:
        con.execute("CREATE TABLE portfolio_settings (setting_key VARCHAR PRIMARY KEY, setting_value VARCHAR, updated_at TIMESTAMP)")

    with duckdb.connect(str(db_path)) as con:
        con.execute(
            """
            CREATE TABLE indicators_daily (
                symbol TEXT, trade_date DATE, close_price DOUBLE, return_5d_pct DOUBLE,
                rs_percentile DOUBLE, away_10ema_pct DOUBLE, away_52w_high_pct DOUBLE,
                turnover_cr DOUBLE, rvol DOUBLE, ema_stack_bullish BOOLEAN
            )
            """
        )
        con.execute("CREATE TABLE stocks_master (symbol TEXT, security_name TEXT, sector TEXT)")
        con.execute("INSERT INTO indicators_daily VALUES ('TRENT', '2026-09-02', 7200.0, 4.2, 98.0, 1.5, -0.8, 450.0, 1.8, true)")
        con.execute("INSERT INTO stocks_master VALUES ('TRENT', 'Trent Ltd', 'Retail')")

    # Add to WL1
    assert toggle_watchlist_symbol(user_db, 1, "TRENT") is True
    syms = load_watchlist_symbols(user_db, 1)
    assert syms == ["TRENT"]

    # Query table data
    table_df = fetch_watchlist_table_data(db_path, syms)
    assert not table_df.empty
    assert table_df.iloc[0]["symbol"] == "TRENT"
    assert table_df.iloc[0]["trend_state"] == "Bullish"

    # Clear WL1
    clear_watchlist_symbols(user_db, 1)
    assert load_watchlist_symbols(user_db, 1) == []


def test_trade_analytics_metrics_calculation(tmp_path: Path) -> None:
    mock_journal = pd.DataFrame([
        {"status": "Closed", "entry_price": 100, "exit_price": 120, "quantity": 100, "stop_loss": 90},  # +2000, +2R
        {"status": "Closed", "entry_price": 200, "exit_price": 190, "quantity": 50, "stop_loss": 190},   # -500, -1R
        {"status": "Closed", "entry_price": 500, "exit_price": 600, "quantity": 10, "stop_loss": 475},   # +1000, +4R
        {"status": "Open", "entry_price": 300, "exit_price": None, "quantity": 30, "stop_loss": 285},     # Open (skipped)
    ])

    metrics = calculate_trade_metrics(mock_journal)
    assert metrics["total_trades"] == 3
    assert metrics["wins"] == 2
    assert metrics["losses"] == 1
    assert metrics["win_rate"] == 66.7
    assert metrics["total_pnl_inr"] == 2500.0
    assert metrics["profit_factor"] == 6.0
    assert metrics["avg_win_r"] == 3.0
    assert metrics["avg_loss_r"] == 1.0
    assert metrics["expectancy_r"] == pytest.approx(1.67, rel=1e-2)


def test_log_trade_entry_and_query(tmp_path: Path) -> None:
    user_db = tmp_path / "test_journal.duckdb"
    with duckdb.connect(str(user_db)) as con:
        con.execute(
            """
            CREATE TABLE trade_journal (
                id BIGINT PRIMARY KEY, created_at TIMESTAMP, updated_at TIMESTAMP, trade_date DATE,
                symbol VARCHAR, trade_type VARCHAR, setup_type VARCHAR, entry_price DOUBLE,
                quantity DOUBLE, stop_loss DOUBLE, target DOUBLE, position_size DOUBLE,
                risk_amount DOUBLE, risk_pct DOUBLE, reward_pct DOUBLE, r_multiple_target DOUBLE,
                status VARCHAR, exit_date DATE, exit_price DOUBLE, exit_reason VARCHAR, notes VARCHAR,
                mistake_tag VARCHAR
            )
            """
        )

    ok = log_trade_entry(
        user_db,
        symbol="HAL",
        entry_price=4500.0,
        quantity=20.0,
        stop_loss=4300.0,
        exit_price=4800.0,
        setup_type="VCP",
        mistake_tag=None,
        notes="Clean volume dryup entry",
    )
    assert ok is True

    journal_df = query_journal_records(user_db)
    assert len(journal_df) == 1
    assert journal_df.iloc[0]["symbol"] == "HAL"
    assert journal_df.iloc[0]["status"] == "Closed"
    assert journal_df.iloc[0]["setup_type"] == "VCP"


def test_symbol_cell_slot_has_quick_wl_and_clean_contract() -> None:
    from App.ui.table import SYMBOL_CELL_SLOT
    assert "mp-symbol-star" in SYMBOL_CELL_SLOT
    assert "quick_wl" in SYMBOL_CELL_SLOT
    assert "mp-symbol-open" in SYMBOL_CELL_SLOT
    assert "stock360" in SYMBOL_CELL_SLOT
    assert "tradingview.com/chart/?symbol=NSE:" in SYMBOL_CELL_SLOT


def test_group_trend_weekly_query(tmp_path: Path) -> None:
    from App.market_summary import group_trend
    db = tmp_path / "test_group_trend.duckdb"
    with duckdb.connect(str(db)) as con:
        con.execute("CREATE TABLE indicators_daily (symbol TEXT, trade_date DATE, close_price DOUBLE, prev_close DOUBLE, return_5d_pct DOUBLE, turnover_cr DOUBLE)")
        con.execute("CREATE TABLE stocks_master (symbol TEXT, sector TEXT)")
        con.execute("INSERT INTO indicators_daily VALUES ('INFY', '2026-09-02', 1800.0, 1780.0, 3.5, 500.0)")
        con.execute("INSERT INTO stocks_master VALUES ('INFY', 'IT')")

    res = group_trend(db, "sector", top_n=5, days=10)
    assert not res.empty
    assert "day_pct" in res.columns
    assert "week_pct" in res.columns
    assert res.iloc[0]["week_pct"] == pytest.approx(3.5, rel=1e-2)


def test_telegram_deals_persistence_and_clientele_structure() -> None:
    from Scripts.telegram_deals import build_deals_telegram_report, notify_deals
    report = build_deals_telegram_report(lookback_days=5, min_mcap_cr=500.0)
    assert "as_of" in report
    assert "messages" in report
    assert len(report["messages"]) == 2

    msg1, msg2 = report["messages"]
    # Message 1: 3-Tier Swing Radar (Alpha & Action)
    assert "TIER 1: CONVICTION ACCUMULATION" in msg1
    assert "TIER 2: FRESH WHALE RADAR" in msg1
    assert "TRADINGVIEW MASTER PASTE" in msg1

    # Message 2: Risk & Context
    assert "INSTITUTIONAL EXITS / DISTRIBUTION" in msg2
    assert "TIER 3A: PROP DESK CHURN" in msg2
    assert "TIER 3B: QUARANTINED" in msg2
    assert "<1000 CR" not in msg2
    assert "<900 CR" not in msg2

    # Dry-run execution
    res = notify_deals(dry_run=True, lookback_days=5)
    assert res["sent"] is False
    assert res["dry_run"] is True
    assert res["message_count"] == 2

