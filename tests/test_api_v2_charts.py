"""Charts tab: GET /api/v2/charts/{sym}/deal-candles and the deal-candle mapping (09-tab-charts §5, 08-tab-deals §5.5)."""
from __future__ import annotations

import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from App.services import charts
from test_api_v2_helpers import LAST, build_market_db, sessions


# ------------------------------------------------------------------ pure mapping
@pytest.mark.parametrize("event_type,net,letter", [
    ("accumulate", 5.0, "B"), ("fresh", 1.0, "B"), ("distribute", -3.0, "S"), ("placement", 0.0, "P"),
    ("transfer_interse", 0.0, "T"), ("churn", 2.0, "C"),
    # The stored type wins over the net sign (a churn day with a positive net is still churn).
    ("churn", -9.0, "C"),
    # Unknown / NULL type: fall back on the net sign; nothing at all -> None (never invented).
    (None, 4.0, "B"), ("weird", -4.0, "S"), (None, 0.0, "C"), (None, None, None),
])
def test_classify(event_type, net, letter):
    assert charts.classify(event_type, net) == letter


def test_deal_price_and_status():
    assert charts.deal_price("B", 100.0, 90.0, 95.0) == 100.0
    assert charts.deal_price("S", 100.0, 90.0, 95.0) == 90.0
    assert charts.deal_price("P", 100.0, 90.0, 95.0) == 95.0
    assert charts.deal_price("B", None, 90.0, 95.0) == 95.0
    assert charts.line_status("B", 100.0, 101.0) == "holding"
    assert charts.line_status("P", 100.0, 99.0) == "lost"
    assert charts.line_status("S", 100.0, 101.0) == "reclaimed"
    assert charts.line_status("S", 100.0, 100.0) == "below"
    assert charts.line_status("C", 100.0, 101.0) is None
    assert charts.line_status("B", None, 101.0) is None


def test_mark_lines_keeps_three_latest_levels():
    rows = [{"letter": l, "deal_price": 1.0} for l in ("B", "S", "C", "P", "T", "B", "C")]
    charts.mark_lines(rows)
    assert [r["show_line"] for r in rows] == [False, True, False, True, False, True, False]


# ------------------------------------------------------------------ endpoint
@pytest.fixture()
def client(tmp_path, monkeypatch):
    market = build_market_db(tmp_path / "market.duckdb")
    days = sessions(LAST)
    con = duckdb.connect(str(market))
    sess = pd.DataFrame([
        {"trade_date": pd.Timestamp(days[-5]), "symbol": "AAA", "event_type": "accumulate", "event_rule": "r",
         "net_value_cr_ex_prop": 12.5, "buy_value_cr": 12.5, "sell_value_cr": 0.0, "gross_value_cr": 12.5,
         "prop_value_cr": 0.0, "buying_houses": 1.0, "selling_houses": 0.0, "buy_vwap": 124.0, "sell_vwap": None,
         "vwap": 124.0, "close_price": 125.0, "deal_types": "Bulk", "net_value_cr_fii": 12.5, "net_value_cr_dii": 0.0},
        {"trade_date": pd.Timestamp(days[-3]), "symbol": "AAA", "event_type": "churn", "event_rule": "r",
         "net_value_cr_ex_prop": 0.0, "buy_value_cr": 3.0, "sell_value_cr": 3.0, "gross_value_cr": 6.0,
         "prop_value_cr": 6.0, "buying_houses": 0.0, "selling_houses": 0.0, "buy_vwap": 126.0, "sell_vwap": 126.0,
         "vwap": 126.0, "close_price": 126.0, "deal_types": "Bulk", "net_value_cr_fii": 0.0, "net_value_cr_dii": 0.0},
        {"trade_date": pd.Timestamp(days[-1]), "symbol": "AAA", "event_type": "distribute", "event_rule": "r",
         "net_value_cr_ex_prop": -4.0, "buy_value_cr": 0.0, "sell_value_cr": 4.0, "gross_value_cr": 4.0,
         "prop_value_cr": 0.0, "buying_houses": 0.0, "selling_houses": 1.0, "buy_vwap": None, "sell_vwap": 131.0,
         "vwap": 131.0, "close_price": 129.0, "deal_types": "Block", "net_value_cr_fii": 0.0, "net_value_cr_dii": 0.0},
    ])
    con.register("_s", sess)
    con.execute("CREATE TABLE deal_session_net AS SELECT * FROM _s")
    con.close()
    monkeypatch.setenv("MP_DB_PATH", str(market))
    monkeypatch.setenv("MP_USER_DB_PATH", str(tmp_path / "user.duckdb"))
    monkeypatch.setenv("MP_STATUS_PATH", str(tmp_path / "status.json"))
    from App.services import common, db

    db.clear_cache()
    monkeypatch.setattr(common, "expected_session", lambda now=None, holidays=None: LAST)
    from App.api.v2 import create_app

    yield TestClient(create_app()), days
    db.clear_cache()


def test_deal_candles_endpoint(client):
    c, days = client
    r = c.get("/api/v2/charts/AAA/deal-candles")
    assert r.status_code == 200
    body = r.json()
    rows = body["rows"]
    assert [x["letter"] for x in rows] == ["B", "C", "S"]
    assert [x["trade_date"] for x in rows] == [days[-5].isoformat(), days[-3].isoformat(), days[-1].isoformat()]
    b, ch, s = rows
    assert b["deal_price"] == 124.0 and b["deal_price_adj"] == 124.0
    assert b["show_line"] is True and ch["show_line"] is False and s["show_line"] is True
    # As-of close is 129 (AAA close = 100 + 29): above the buy price, below the sell price.
    assert b["status"] == "holding" and s["status"] == "below"
    # The fixture print (one FII buy stored as Bulk and Block) counts once.
    assert s["top_buyer"] == "GOOD FUND LP" and s["top_buyer_cr"] == 1.28 and s["top_buyer_class"] == "FII"
    assert body["meta"]["status"] == "ok"


def test_deal_candles_time_travel_and_bad_symbol(client):
    c, days = client
    r = c.get("/api/v2/charts/AAA/deal-candles", params={"as_of": days[-4].isoformat()})
    assert [x["letter"] for x in r.json()["rows"]] == ["B"]
    assert c.get("/api/v2/charts/bad sym!/deal-candles").status_code == 422
    assert c.get("/api/v2/charts/SMALL/deal-candles").json()["rows"] == []


def test_deal_candles_unavailable_without_table(tmp_path, monkeypatch):
    market = build_market_db(tmp_path / "m.duckdb")
    monkeypatch.setenv("MP_DB_PATH", str(market))
    monkeypatch.setenv("MP_STATUS_PATH", str(tmp_path / "status.json"))
    from App.services import db

    db.clear_cache()
    res = charts.deal_candles(None, "AAA")
    assert res.status == "unavailable" and res.rows == []
