from __future__ import annotations

import duckdb
import pandas as pd

from price_adjustment import ADJUSTMENT_COLUMNS, drop_stale_adjustment_columns, empty_adjustments_frame


def test_empty_adjustments_frame_round_trips_through_duckdb():
    # write_database (and refresh_deals' fallback) hand an empty price_adjustments frame
    # straight to duckdb with no real rows to infer types from; a plain
    # pd.DataFrame(columns=ADJUSTMENT_COLUMNS) leaves every column `object` dtype, which duckdb
    # can resolve to the wrong SQL type (observed: INTEGER) -- breaking a later typed query like
    # `WHERE ex_date >= DATE '...'` once real rows exist. The explicitly-typed frame must not.
    frame = empty_adjustments_frame()
    assert list(frame.columns) == ADJUSTMENT_COLUMNS
    assert frame.empty

    con = duckdb.connect(":memory:")
    try:
        con.register("price_adjustments_df", frame)
        con.execute("CREATE TABLE price_adjustments AS SELECT * FROM price_adjustments_df")
        result = con.execute(
            "SELECT * FROM price_adjustments WHERE ex_date >= DATE '2026-01-01'"
        ).fetchdf()
        assert result.empty
        assert list(result.columns) == ADJUSTMENT_COLUMNS
    finally:
        con.close()


def test_drop_stale_adjustment_columns_removes_adj_and_price_factor():
    df = pd.DataFrame({
        "symbol": ["A"],
        "trade_date": pd.to_datetime(["2026-01-01"]),
        "close_price": [10.0],
        "adj_close_price": [10.0],
        "adj_volume": [100.0],
        "price_factor": [1.0],
    })

    out = drop_stale_adjustment_columns(df)

    assert "close_price" in out.columns and "trade_date" in out.columns and "symbol" in out.columns
    assert "adj_close_price" not in out.columns
    assert "adj_volume" not in out.columns
    assert "price_factor" not in out.columns
    # Non-destructive: doesn't mutate the caller's frame or crash when there's nothing stale.
    assert "adj_close_price" in df.columns
    untouched = drop_stale_adjustment_columns(out)
    assert list(untouched.columns) == list(out.columns)


def test_load_extra_actions_warns_and_returns_none_when_corporate_actions_missing(monkeypatch, capsys):
    import append_database as ad

    def boom(name):
        raise RuntimeError("no such table: corporate_actions")

    monkeypatch.setattr(ad, "_load_table", boom)

    result = ad._load_extra_actions()

    assert result is None
    captured = capsys.readouterr()
    assert "Warning" in captured.out
    assert "corporate_actions" in captured.out
    assert "no such table: corporate_actions" in captured.out
