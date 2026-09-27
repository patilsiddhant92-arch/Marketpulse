"""build_derived_tables / write_derived_tables: isolation, DuckDB round trip (in-memory)."""
from __future__ import annotations

import duckdb
import pandas as pd

import Scripts.derived as derived
from Scripts.derived import LAST_RUN, TABLES, build_derived_tables, write_derived_tables
from tests.test_derived_group_daily import universe


def _inputs():
    ind, master, idx = universe()
    deals = pd.DataFrame([dict(trade_date=ind.trade_date.max(), symbol="UP1", client_name="F", side="BUY",
                               quantity=1000, price=100.0, clientele="FII", deal_type="Bulk")])
    prices = ind[["symbol", "trade_date", "close_price", "turnover_cr"]].assign(volume=1e6)
    return dict(prices=prices, indicators=ind, index_daily=idx, master=master, deals=deals)


def test_builds_all_four_and_writes_to_duckdb():
    tables = build_derived_tables(**_inputs())
    assert set(tables) == set(TABLES)
    assert not LAST_RUN["errors"] and set(LAST_RUN["timings_s"]) == set(TABLES)
    con = duckdb.connect(":memory:")
    written = write_derived_tables(con, tables)
    assert written == {k: len(v) for k, v in tables.items()}
    for name, frame in tables.items():
        n = con.execute(f"select count(*) from {name}").fetchone()[0]
        assert n == len(frame)
    # JSON columns and booleans survive
    js = con.execute("select connected_readings, alerts, alert_any from regime_daily limit 1").fetchone()
    assert js[0].startswith("[") and js[1].startswith("[") and isinstance(js[2], bool)
    # re-running replaces (not appends) and keeps indexes creatable
    write_derived_tables(con, tables)
    assert con.execute("select count(*) from group_daily").fetchone()[0] == len(tables["group_daily"])


def test_one_failing_builder_is_isolated(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("kaput")
    monkeypatch.setattr(derived, "build_group_daily", boom)
    tables = build_derived_tables(**_inputs())
    assert "group_daily" not in tables
    assert {"regime_daily", "setup_daily", "deal_session_net"} <= set(tables)
    assert "kaput" in LAST_RUN["errors"]["group_daily"]
