"""Tests for Scripts/price_views.ohlcv_columns."""

from __future__ import annotations

import duckdb
import pytest

from Scripts import price_views


def _make_db(path, with_adj: bool) -> None:
    con = duckdb.connect(str(path))
    try:
        if with_adj:
            con.execute(
                """
                CREATE TABLE prices_daily (
                    symbol VARCHAR, trade_date DATE,
                    open_price DOUBLE, high_price DOUBLE, low_price DOUBLE,
                    close_price DOUBLE, prev_close DOUBLE, volume BIGINT,
                    delivery_qty BIGINT,
                    adj_close_price DOUBLE, price_factor DOUBLE
                )
                """
            )
        else:
            con.execute(
                """
                CREATE TABLE prices_daily (
                    symbol VARCHAR, trade_date DATE,
                    open_price DOUBLE, high_price DOUBLE, low_price DOUBLE,
                    close_price DOUBLE, prev_close DOUBLE, volume BIGINT,
                    delivery_qty BIGINT
                )
                """
            )
    finally:
        con.close()


def test_no_adj_columns_returns_raw_names(tmp_path):
    db_path = tmp_path / "raw.duckdb"
    _make_db(db_path, with_adj=False)
    con = duckdb.connect(str(db_path))
    try:
        cols = price_views.ohlcv_columns(con)
        assert cols["close_price"] == "close_price"
        assert cols["open_price"] == "open_price"
        assert cols["high_price"] == "high_price"
        assert cols["low_price"] == "low_price"
        assert cols["prev_close"] == "prev_close"
        assert cols["volume"] == "volume"
        assert cols["delivery_qty"] == "delivery_qty"
        assert cols["price_factor"] == "1.0"
    finally:
        con.close()


def test_adj_columns_present_uses_coalesce(tmp_path):
    db_path = tmp_path / "adj.duckdb"
    _make_db(db_path, with_adj=True)
    con = duckdb.connect(str(db_path))
    try:
        cols = price_views.ohlcv_columns(con)
        assert cols["close_price"] == "COALESCE(adj_close_price, close_price)"
        assert cols["price_factor"] == "COALESCE(price_factor, 1.0)"
        # Column not adjusted in this minimal fixture stays raw.
        assert cols["open_price"] == "open_price"
    finally:
        con.close()


def test_alias_prefixes_expressions(tmp_path):
    db_path = tmp_path / "adj_alias.duckdb"
    _make_db(db_path, with_adj=True)
    con = duckdb.connect(str(db_path))
    try:
        cols = price_views.ohlcv_columns(con, alias="p.")
        assert cols["close_price"] == "COALESCE(p.adj_close_price, p.close_price)"
        assert cols["price_factor"] == "COALESCE(p.price_factor, 1.0)"
        assert cols["open_price"] == "p.open_price"
    finally:
        con.close()


def test_works_on_read_only_connection(tmp_path):
    db_path = tmp_path / "readonly.duckdb"
    _make_db(db_path, with_adj=True)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        cols = price_views.ohlcv_columns(con)
        assert cols["close_price"] == "COALESCE(adj_close_price, close_price)"
    finally:
        con.close()


def test_missing_table_falls_back_to_raw_names(tmp_path):
    db_path = tmp_path / "empty.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        cols = price_views.ohlcv_columns(con)
        assert cols["close_price"] == "close_price"
        assert cols["price_factor"] == "1.0"
    finally:
        con.close()
