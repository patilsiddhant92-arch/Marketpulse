"""build_derived_tables / write_derived_tables: isolation, DuckDB round trip (in-memory)."""
from __future__ import annotations

import duckdb
import pandas as pd

import Scripts.derived as derived
from Scripts.derived import LAST_RUN, TABLES, build_derived_tables, incremental_setup_args, write_derived_tables
from tests.test_derived_group_daily import universe
from tests.test_derived_setup_daily import ema_pullback_stock, squeeze_stock


def _inputs():
    ind, master, idx = universe()
    extra = pd.concat([squeeze_stock("SQA", seed=1), squeeze_stock("SQB", n_up=35, n_flat=20, seed=2),
                       ema_pullback_stock("PBK")], ignore_index=True)
    ind = pd.concat([ind, extra.drop(columns=["ema_200"]).assign(turnover_cr=20.0)], ignore_index=True)
    master = pd.concat([master, pd.DataFrame({"symbol": ["SQA", "SQB", "PBK"], "broad_sector": "BS", "sector": "S3",
                                              "broad_industry": "BI3", "industry": "SqInd", "market_cap_cr": 9000.0,
                                              "market_cap_date": master["market_cap_date"].iloc[0]})], ignore_index=True)
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


def test_incremental_setup_args_round_trip():
    con = duckdb.connect(":memory:")
    assert incremental_setup_args(con) == {}  # no table yet -> full build
    inputs = _inputs()
    tables = build_derived_tables(**inputs)
    write_derived_tables(con, tables)
    args = incremental_setup_args(con, lookback_sessions=5)
    assert len(tables["setup_daily"]) > 0
    stored = sorted(tables["setup_daily"]["trade_date"].unique())
    assert args["setup_since"] == pd.Timestamp(stored[-5] if len(stored) >= 5 else stored[0])
    assert (args["setup_previous"]["trade_date"] < args["setup_since"]).all()
    again = build_derived_tables(**inputs, **args)
    pd.testing.assert_frame_equal(again["setup_daily"].reset_index(drop=True),
                                  tables["setup_daily"].reset_index(drop=True), check_dtype=False)
