"""Wiring of Scripts/derived into the build / append: inputs read from DuckDB, fail-soft."""
from __future__ import annotations

import sys
import types

import duckdb
import pandas as pd
import pytest

import derived_tables_step as dts


def _db(tmp_path):
    con = duckdb.connect(str(tmp_path / "m.duckdb"))
    con.execute("CREATE TABLE prices_daily AS SELECT 'A' AS symbol, TIMESTAMP '2026-09-25' AS trade_date, 1.0 AS close_price, 10 AS volume, 0.1 AS turnover_cr, 'EQ' AS series")
    con.execute("CREATE TABLE indicators_daily AS SELECT 'A' AS symbol, TIMESTAMP '2026-09-25' AS trade_date, 1.0 AS close_price, 2.0 AS ema_50, 3.0 AS avg_traded_value_cr_20d, 9.0 AS unused")
    for t in ("index_daily", "stocks_master", "deals", "breadth_daily", "security_reference_daily"):
        con.execute(f"CREATE TABLE {t} AS SELECT 1 AS x")
    return con


@pytest.fixture()
def fake_package(monkeypatch):
    calls = {}
    pkg = types.ModuleType("derived")
    pkg.LAST_RUN = {"errors": {}}
    pkg.regime = types.SimpleNamespace(INDICATOR_COLUMNS=("close_price",))
    pkg.group_daily = types.SimpleNamespace(INDICATOR_COLUMNS=("ema_50",))
    pkg.setup_daily = types.SimpleNamespace(INDICATOR_COLUMNS=("close_price",))

    def build_derived_tables(**kw):
        calls["build"] = kw
        return {"regime_daily": pd.DataFrame({"trade_date": [pd.Timestamp("2026-09-25")], "verdict": ["Mixed"]})}

    def write_derived_tables(con, tables):
        for name, frame in tables.items():
            con.register("_f", frame)
            con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _f")
            con.unregister("_f")
        return {k: len(v) for k, v in tables.items()}

    pkg.build_derived_tables = build_derived_tables
    pkg.write_derived_tables = write_derived_tables
    pkg.incremental_setup_args = lambda con: {"setup_since": pd.Timestamp("2026-09-20"), "setup_previous": pd.DataFrame()}
    monkeypatch.setitem(sys.modules, "derived", pkg)
    return calls


def test_full_build_reads_only_needed_columns_and_uses_workers(tmp_path, fake_package):
    con = _db(tmp_path)
    written = dts.rebuild_in_place(con, incremental=False, own_transaction=False, quiet=True)
    assert written == {"regime_daily": 1}
    kw = fake_package["build"]
    assert list(kw["indicators"].columns) == ["symbol", "trade_date", "close_price", "ema_50", "avg_traded_value_cr_20d"]
    assert list(kw["prices"].columns) == ["symbol", "trade_date", "close_price", "volume", "turnover_cr"]
    assert kw["setup_workers"] == dts.FULL_SETUP_WORKERS
    assert "setup_since" not in kw
    assert con.execute("SELECT verdict FROM regime_daily").fetchone()[0] == "Mixed"


def test_append_uses_incremental_setup_args(tmp_path, fake_package):
    con = _db(tmp_path)
    dts.rebuild_in_place(con, incremental=True, quiet=True)
    kw = fake_package["build"]
    assert kw["setup_workers"] == 1
    assert kw["setup_since"] == pd.Timestamp("2026-09-20")


def test_failure_is_soft(tmp_path, fake_package, capsys):
    con = _db(tmp_path)
    sys.modules["derived"].build_derived_tables = lambda **kw: (_ for _ in ()).throw(RuntimeError("boom"))
    assert dts.rebuild_in_place(con, incremental=True) == {}
    assert "DERIVED TABLES NOT REBUILT" in capsys.readouterr().out


def test_missing_package_is_soft(tmp_path, monkeypatch, capsys):
    con = _db(tmp_path)
    monkeypatch.setitem(sys.modules, "derived", None)  # import raises ImportError
    assert dts.rebuild_in_place(con, incremental=False) == {}
    assert "not available" in capsys.readouterr().out
