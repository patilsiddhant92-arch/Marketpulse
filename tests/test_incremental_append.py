"""Incremental append == full recompute (synthetic history, no input files).

A base DB is built by the streaming full build from all sessions but the last; the last
session is then appended incrementally and the result is compared, table by table, with a full
recompute over every session. Also: a split applied on the appended day (the symbol is
rewritten over its whole history), and fail-closed behaviour.
"""
from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd
import pytest

import build_database as bd
import incremental_append as ia
import reference_history
import streaming_build as sb

from test_streaming_build import synthetic_prices

LAST = None  # set per test


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("MP_DISABLE_MULTIPROCESSING", "1")
    empty = pd.DataFrame()
    no_index = pd.DataFrame(columns=["index_name", "trade_date", "close_price"])
    master_sector = pd.DataFrame({
        "symbol": [f"S{i:02d}" for i in range(7)],
        "broad_sector": ["A", "A", "B", "B", "C", "C", "C"],
        "sector": ["A1", "A2", "B1", "B1", "C1", "C2", "C2"],
        "broad_industry": ["x"] * 7,
        "industry": ["i1", "i2", "i1", "i2", "i1", "i2", "i3"],
    })
    mcap = pd.DataFrame({
        "symbol": [f"S{i:02d}" for i in range(7)], "security_name": "N",
        "market_cap_cr": [5000.0, 800.0, 20000.0, 1500.0, 999.0, 3000.0, 100.0],
        "market_cap_date": pd.Timestamp("2025-09-01"), "issue_size": 1e6,
    })
    monkeypatch.setattr(bd, "read_sector", lambda: master_sector)
    monkeypatch.setattr(bd, "read_market_cap", lambda: mcap)
    monkeypatch.setattr(bd, "read_price_band", lambda: pd.DataFrame(columns=["symbol", "band", "band_remarks"]))
    monkeypatch.setattr(bd, "read_pe", lambda: pd.DataFrame(columns=["symbol", "pe", "adjusted_pe"]))
    monkeypatch.setattr(bd, "read_52_week", lambda: pd.DataFrame(columns=["symbol", "high_52w", "low_52w"]))
    def deals():
        # make_screener_results needs at least one deal (pre-existing behaviour of the build)
        days = pd.bdate_range("2024-01-01", periods=420)
        return pd.DataFrame({
            "deal_type": ["Bulk", "Block"], "trade_date": [days[-30], days[-1]], "symbol": ["S00", "S03"],
            "security_name": ["N", "N"], "client_name": ["FUND A", "FUND B"], "side": ["BUY", "SELL"],
            "quantity": [100000.0, 50000.0], "price": [100.0, 90.0], "source_file": ["t", "t"],
            "deal_value_cr": [1.0, 0.45],
        })

    monkeypatch.setattr(bd, "read_all_deals", deals)
    monkeypatch.setattr(bd, "read_equity_symbols", lambda: pd.DataFrame({"symbol": [f"S{i:02d}" for i in range(7)]}))
    monkeypatch.setattr(bd, "load_reference_history", lambda root: empty)
    monkeypatch.setattr(reference_history, "load_reference_history", lambda root: empty)
    monkeypatch.setattr(bd, "load_all_index_history", lambda root: no_index)
    monkeypatch.setattr(bd, "load_benchmark_inputs", lambda: (no_index, RuntimeError("no membership in tests")))
    monkeypatch.setattr(bd, "load_symbol_changes", lambda: None)
    monkeypatch.setattr(bd, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(bd, "ensure_folders", lambda: None)
    import derived_tables_step
    monkeypatch.setattr(derived_tables_step, "rebuild_in_place", lambda con, **k: {})
    return tmp_path


def _full_db(path, raw, extra_actions=None):
    # metric_reference: what the append uses when there is no reference history (the empty
    # security_reference_daily table), so base, append and full recompute agree.
    frames = bd.compute_full_build(quiet=True, db_path=path, raw_prices=raw, extra_actions=extra_actions,
                                   metric_reference=pd.DataFrame())
    temp = bd.build_temp_database(**frames, db_path=path)
    import os
    os.replace(temp, path)
    return path


def _corporate_actions(con, rows):
    con.execute("CREATE TABLE IF NOT EXISTS corporate_actions (symbol VARCHAR, ex_date TIMESTAMP, action_type VARCHAR, "
                "ratio_from DOUBLE, ratio_to DOUBLE, cash_amount DOUBLE, description VARCHAR, source_checksum VARCHAR)")
    for sym, day, desc in rows:
        con.execute("INSERT INTO corporate_actions VALUES (?, ?, 'split', NULL, NULL, NULL, ?, 'test')", [sym, day, desc])


def _compare(a_path, b_path, tables, rel=1e-9):
    con = duckdb.connect()
    con.execute(f"ATTACH '{a_path}' AS a (READ_ONLY)")
    con.execute(f"ATTACH '{b_path}' AS b (READ_ONLY)")
    problems = []
    for t in tables:
        cols = [r[0] for r in con.execute(f"SELECT column_name FROM duckdb_columns() WHERE database_name='a' AND table_name='{t}' ORDER BY column_index").fetchall()]
        types = dict(con.execute(f"SELECT column_name, data_type FROM duckdb_columns() WHERE database_name='a' AND table_name='{t}'").fetchall())
        na = con.execute(f"SELECT count(*) FROM a.{t}").fetchone()[0]
        nb = con.execute(f"SELECT count(*) FROM b.{t}").fetchone()[0]
        if na != nb:
            problems.append(f"{t}: rows {na} vs {nb}")
            continue
        exact = [c for c in cols if types[c] not in ("DOUBLE",)]
        floats = [c for c in cols if types[c] == "DOUBLE"]
        keys = ", ".join(f'"{c}"' for c in exact)
        la = con.execute(f"SELECT * FROM a.{t} ORDER BY {keys}").fetchdf()
        lb = con.execute(f"SELECT {', '.join(chr(34) + c + chr(34) for c in cols)} FROM b.{t} ORDER BY {keys}").fetchdf()
        for c in exact:
            x = [None if pd.isna(v) else v for v in la[c]]
            y = [None if pd.isna(v) else v for v in lb[c]]
            if x != y:
                problems.append(f"{t}.{c} differs")
        for c in floats:
            x = la[c].to_numpy(float)
            y = lb[c].to_numpy(float)
            ok = np.isclose(x, y, rtol=rel, atol=1e-12, equal_nan=True) | (x == y)
            if not ok.all():
                problems.append(f"{t}.{c}: {int((~ok).sum())} values beyond {rel}")
    return problems


CORE = ("prices_daily", "indicators_daily", "breadth_daily", "sector_rotation", "sector_metrics_daily", "screener_results", "stocks_master")


def test_incremental_equals_full_recompute(sandbox):
    raw = synthetic_prices()
    last = raw["trade_date"].max()
    base = _full_db(sandbox / "inc" / "marketpulse.duckdb", raw[raw["trade_date"] < last])
    full = _full_db(sandbox / "full" / "marketpulse.duckdb", raw)
    summary = ia.incremental_append(base, raw[raw["trade_date"] == last], root=sandbox, equity=bd.read_equity_symbols(), quiet=True)
    assert summary["full_symbols"] == []
    assert summary["backup"] is not None and summary["backup"].exists()
    assert _compare(full, base, CORE) == []


def test_split_on_appended_day_rewrites_symbol(sandbox):
    raw = synthetic_prices()
    last = raw["trade_date"].max()
    m = (raw["symbol"] == "S02") & (raw["trade_date"] == last)
    for c in ("open_price", "high_price", "low_price", "last_price", "close_price", "avg_price"):
        raw.loc[m, c] = raw.loc[m, c] / 2
    raw.loc[m, "volume"] = raw.loc[m, "volume"] * 2
    action = [("S02", last, "FACE VALUE SPLIT (SUB-DIVISION) - FROM RS 10/- PER SHARE TO RS 5/- PER SHARE")]
    base = _full_db(sandbox / "inc" / "marketpulse.duckdb", raw[raw["trade_date"] < last])
    with duckdb.connect(str(base)) as con:
        _corporate_actions(con, action)
    extra = pd.DataFrame({"symbol": ["S02"], "ex_date": [last], "description": [action[0][2]]})
    from price_adjustment import actions_from_corporate_actions_table
    full = _full_db(sandbox / "full" / "marketpulse.duckdb", raw, extra_actions=actions_from_corporate_actions_table(extra))
    summary = ia.incremental_append(base, raw[raw["trade_date"] == last], root=sandbox, equity=bd.read_equity_symbols(), quiet=True)
    assert summary["full_symbols"] == ["S02"]
    with duckdb.connect(str(base), read_only=True) as con:
        factors = con.execute("SELECT DISTINCT price_factor FROM prices_daily WHERE symbol='S02' AND trade_date < ?", [last]).fetchall()
    assert factors == [(0.5,)]
    assert _compare(full, base, CORE) == []


def test_failure_inside_transaction_leaves_db_unchanged(sandbox, monkeypatch):
    raw = synthetic_prices()
    last = raw["trade_date"].max()
    base = _full_db(sandbox / "inc" / "marketpulse.duckdb", raw[raw["trade_date"] < last])
    before = sandbox / "before.duckdb"
    import shutil
    shutil.copy2(base, before)

    def boom(*a, **k):
        raise RuntimeError("injected failure after the first writes")

    monkeypatch.setattr(ia, "_update_breadth", boom)
    with pytest.raises(RuntimeError, match="injected"):
        ia.incremental_append(base, raw[raw["trade_date"] == last], root=sandbox, equity=bd.read_equity_symbols(), quiet=True)
    assert _compare(before, base, CORE) == []


def test_old_schema_requires_full_recompute(sandbox):
    db = sandbox / "old.duckdb"
    with duckdb.connect(str(db)) as con:
        for t in ("prices_daily", "indicators_daily", "breadth_daily", "sector_rotation", "stocks_master", "sector_metrics_daily"):
            con.execute(f"CREATE TABLE {t} AS SELECT 'A' AS symbol, TIMESTAMP '2026-01-01' AS trade_date, 1.0 AS close_price")
    with pytest.raises(ia.FullRecomputeRequired, match="price-adjustment"):
        ia.incremental_append(db, pd.DataFrame({"symbol": ["A"], "trade_date": [pd.Timestamp("2026-01-02")]}), root=sandbox, equity=pd.DataFrame(), quiet=True)


def test_month_window_start():
    assert ia.month_window_start(pd.Timestamp("2026-09-25")) == pd.Timestamp("2026-09-01")
    # first session of a month: the previous week (a holiday Friday completes late) is included
    assert ia.month_window_start(pd.Timestamp("2026-10-01")) == pd.Timestamp("2026-09-21")
