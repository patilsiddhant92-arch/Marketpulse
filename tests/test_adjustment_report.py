from __future__ import annotations

import duckdb
import pandas as pd


def _seed_db(db_path):
    prices = pd.DataFrame({
        "symbol": ["GOODLUCK", "GOODLUCK", "GOODLUCK"],
        "trade_date": pd.to_datetime(["2026-08-19", "2026-08-20", "2026-08-21"]),
        "open_price": [1340.0, 1385.0, 493.2],
        "high_price": [1370.0, 1445.0, 494.4],
        "low_price": [1330.0, 1380.0, 469.8],
        "close_price": [1363.3, 1439.4, 490.9],
        "volume": [100.0, 120.0, 646400.0],
    })
    corporate_actions = pd.DataFrame({
        "symbol": ["GOODLUCK"],
        "ex_date": pd.to_datetime(["2026-08-21"]),
        "action_type": ["bonus"],
        "ratio_from": [1.0],
        "ratio_to": [2.0],
        "cash_amount": [None],
        "description": ["BONUS 2:1"],
        "source_checksum": ["x"],
    })
    with duckdb.connect(str(db_path)) as con:
        con.register("prices_df", prices)
        con.execute("CREATE TABLE prices_daily AS SELECT * FROM prices_df")
        con.register("ca_df", corporate_actions)
        con.execute("CREATE TABLE corporate_actions AS SELECT * FROM ca_df")


def test_main_runs_read_only_dry_run_against_tmp_db(tmp_path, capsys):
    from adjustment_report import main

    db_path = tmp_path / "tiny.duckdb"
    _seed_db(db_path)

    rc = main(["--db", str(db_path), "--root", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "READ-ONLY" in out
    assert "Counts by confidence" in out
    assert "Applied events" in out
    assert "unexplained_gap rows" in out
    assert "Runtime" in out

    # A read-only dry run must not create or modify the DB file's tables.
    with duckdb.connect(str(db_path), read_only=True) as con:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    assert tables == {"prices_daily", "corporate_actions"}


def test_main_returns_nonzero_when_db_missing(tmp_path):
    from adjustment_report import main

    rc = main(["--db", str(tmp_path / "does_not_exist.duckdb")])

    assert rc == 1
