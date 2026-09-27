"""Today endpoints (Desk "Today" / Groups "Today"): market strip, movers + quality of move, breakouts,
groups today + fact-only "why" — against a small fixture DuckDB."""
from __future__ import annotations

from datetime import timedelta

import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from test_api_v2_helpers import LAST, build_market_db, sessions

# symbol: (change today %, rvol, delivery % today, avg delivery %, delivered qty today, avg delivered qty, mcap, band)
PHARMA = {
    "P1": (10.0, 2.0, 60.0, 40.0, 3_000_000, 1_000_000, 2000.0, 20.0),   # Real + delivery spike
    "P2": (3.0, 1.8, 30.0, 40.0, 900_000, 1_000_000, 2000.0, 20.0),      # Churn
    "P3": (1.0, 0.5, 40.0, 40.0, 1_000_000, 1_000_000, 2000.0, 20.0),    # Thin
    "P4": (-1.0, 1.2, 40.0, 40.0, 1_000_000, 1_000_000, 2000.0, 20.0),   # Normal
    "TINY": (5.0, 3.0, 20.0, 40.0, 500_000, 1_000_000, 300.0, 5.0),      # Operator-ish (tiny cap at its 5% band)
}


def _add_pharma(path) -> None:
    days = sessions()
    con = duckdb.connect(str(path))
    con.execute("ALTER TABLE indicators_daily ADD COLUMN new_20d_high BOOLEAN")
    con.execute("ALTER TABLE indicators_daily ADD COLUMN avg_delivery_qty_20d DOUBLE")
    rows = []
    for d in days:
        last = d == days[-1]
        for sym, (chg, rvol, dp, adp, dq, adq, _m, _b) in PHARMA.items():
            close = 100.0 * (1 + chg / 100) if last else 100.0
            rows.append({
                "symbol": sym, "series": "EQ", "trade_date": pd.Timestamp(d), "prev_close": 100.0,
                "open_price": 100.5 if last else 100.0, "high_price": max(close, 100.5), "low_price": min(close, 99.0),
                "close_price": close, "volume": 1_000_000, "turnover_cr": 10.0 * (rvol if last else 1.0),
                "delivery_qty": dq if last else adq, "delivery_pct": dp if last else adp,
                "avg_volume_20d": 1_000_000, "rvol": rvol if last else 1.0, "avg_delivery_pct_20d": adp,
                "avg_delivery_qty_20d": adq, "avg_traded_value_cr_20d": 10.0,
                "rs_percentile": 70.0, "away_52w_high_pct": 0.0 if (last and sym == "P1") else -10.0,
                "high_52w": 110.0 if sym == "P1" else 200.0, "low_52w": 50.0,
                "delivery_spike": bool(last and dq > 2 * adq), "new_20d_high": bool(last and chg > 0),
                "return_1m_pct": 5.0,
            })
    con.register("_p", pd.DataFrame(rows))
    con.execute("INSERT INTO indicators_daily BY NAME SELECT * FROM _p")
    con.unregister("_p")
    con.register("_m", pd.DataFrame([{
        "symbol": s, "security_name": f"{s} Ltd", "broad_sector": "Healthcare", "sector": "Healthcare",
        "broad_industry": "Pharmaceuticals & Biotechnology", "industry": "Pharma", "market_cap_cr": v[6], "band": v[7],
    } for s, v in PHARMA.items()]))
    con.execute("INSERT INTO stocks_master BY NAME SELECT * FROM _m")
    con.unregister("_m")
    con.execute("""CREATE TABLE deal_session_net (trade_date TIMESTAMP, symbol VARCHAR, n_prints INTEGER,
                   net_value_cr DOUBLE, net_value_cr_ex_prop DOUBLE, buying_houses DOUBLE, selling_houses DOUBLE,
                   event_type VARCHAR)""")
    con.execute("INSERT INTO deal_session_net VALUES (?, 'P1', 2, 5.0, 5.0, 1, 0, 'accumulate')", [pd.Timestamp(days[-1])])
    con.execute("""CREATE TABLE setup_daily (trade_date TIMESTAMP, queue VARCHAR, symbol VARCHAR, trigger_price DOUBLE,
                   stop_price DOUBLE, status VARCHAR)""")
    con.execute("INSERT INTO setup_daily VALUES (?, 'darvas_squeeze', 'P2', 101.0, 95.0, 'active')", [pd.Timestamp(days[-2])])
    con.execute("INSERT INTO setup_daily VALUES (?, 'vcp', 'P1', 112.0, 104.0, 'new')", [pd.Timestamp(days[-1])])
    con.execute("INSERT INTO security_events VALUES ('P1', ?, 'financial_results', 'Q2 results')",
                [pd.Timestamp(days[-3])])
    con.execute("INSERT INTO security_events VALUES ('P2', ?, 'order_or_contract', 'Order win')", [pd.Timestamp(days[-1])])
    con.execute("INSERT INTO security_events VALUES ('P3', ?, 'other', 'Noise')", [pd.Timestamp(days[-1])])
    con.close()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    market = build_market_db(tmp_path / "market.duckdb")
    _add_pharma(market)
    monkeypatch.setenv("MP_DB_PATH", str(market))
    monkeypatch.setenv("MP_USER_DB_PATH", str(tmp_path / "user.duckdb"))
    monkeypatch.setenv("MP_STATUS_PATH", str(tmp_path / "status.json"))
    monkeypatch.setenv("MP_HOLIDAYS_PATH", str(tmp_path / "no_holidays.json"))
    from App.services import common, db

    db.clear_cache()
    monkeypatch.setattr(common, "expected_session", lambda now=None, holidays=None: LAST)
    from App.api.v2 import create_app

    yield TestClient(create_app())
    db.clear_cache()


def _get(client, url):
    r = client.get(url)
    assert r.status_code == 200, (url, r.text[:500])
    body = r.json()
    assert body["returned"] == len(body["rows"])
    return body


def test_market_strip(client):
    body = _get(client, "/api/v2/today/market")
    row = body["rows"][0]
    assert body["as_of"] == LAST.isoformat()
    assert row["advancers"] == 60 and row["decliners"] == 40
    idx = {i["name"]: i for i in row["indices"]}
    assert idx["Nifty 50"]["close"] is not None and idx["Nifty 50"]["return_1d_pct"] is not None
    assert idx["NIFTY SMLCAP 250"]["close"] is None  # not in the fixture: NULL, never invented
    assert row["india_vix"] is not None
    assert row["turnover_vs_20d"] is not None and row["turnover_vs_20d"] > 1  # pharma volume burst today
    assert row["delivery_pct"] is not None


def test_movers_quality_traits_and_context(client):
    body = _get(client, "/api/v2/today/movers")
    rows = {r["symbol"]: r for r in body["rows"]}
    assert "TINY" not in rows and "SMALL" not in rows  # ₹1,000 Cr floor
    p1 = rows["P1"]
    assert p1["side"] == "gainer" and p1["rank"] == 1
    assert p1["quality"] == "Real" and p1["delivery_vs_20d"] == 1.5
    assert set(p1["traits"]) == {"delivery_spike", "rvol_1_5", "results_5"}
    assert p1["deal_net_cr_today"] == 5.0 and p1["deal_event_type"] == "accumulate"
    assert p1["queues"] == ["vcp"]
    assert p1["results_nearby"]["when"] == "past"
    assert rows["P2"]["quality"] == "Churn"
    assert [n["label"] for n in rows["P2"]["news_today"]] == ["order/contract"]
    assert rows["P3"]["quality"] == "Thin" and rows["P3"]["news_today"] == []  # 'other' is not news
    assert rows["P4"]["side"] == "loser" and rows["P4"]["quality"] == "Normal"
    ctx = body["meta"]["context"]
    assert [r["id"] for r in ctx["quality_rules"]][:2] == ["operator", "real"]
    assert "rvol" in body["meta"]["metric_keys"] and "move_quality" in body["meta"]["metric_keys"]


def test_movers_all_caps_flags_operator(client):
    rows = {r["symbol"]: r for r in _get(client, "/api/v2/today/movers?min_mcap_cr=0")["rows"]}
    assert rows["TINY"]["at_upper_circuit"] is True
    assert rows["TINY"]["quality"] == "Operator-ish"


def test_breakouts(client):
    body = _get(client, "/api/v2/today/breakouts")
    rows = {r["symbol"]: r for r in body["rows"]}
    assert "setup_trigger" in rows["P2"]["kinds"] and rows["P2"]["setup_trigger"] == 101.0
    assert rows["P2"]["setup_queue"] == "darvas_squeeze"
    assert {"new_52w_high", "accumulation", "high_20d_rvol"} <= set(rows["P1"]["kinds"])
    assert body["meta"]["context"]["counts"]["setup_trigger"] == 1


def test_groups_today_why_is_built_from_facts(client):
    body = _get(client, "/api/v2/today/groups?level=industry")
    assert body["meta"]["status"] == "partial"  # no group_daily in the fixture: 5d / rank unavailable
    g = next(r for r in body["rows"] if r["group_name"] == "Pharma")
    assert g["stocks"] == 4 and g["return_1d"] == 3.25
    assert g["pct_up"] == 75.0 and g["pct_up_2"] == 50.0
    assert g["top_contributors"][0]["symbol"] == "P1"
    assert g["top_contributors"][0]["share_of_move_pct"] == 77.0
    assert g["top_contributors"][0]["weight_pct"] == 25.0
    assert g["top_detractors"][0]["symbol"] == "P4"
    assert g["breadth_label"] == "one-stock"
    assert g["deal_buyers"] == 1 and g["deal_net_cr"] == 5.0
    assert g["results_nearby_n"] == 1 and g["news_types"] == {"order/contract": 1}
    assert g["return_5d"] is None and g["rank"] is None
    why = g["why"]
    assert why.startswith("Pharma +3.")
    assert "P1 +10.0% = 77% of the move" in why
    assert "1 net buyer" in why and "results within 5 sessions" in why and "order/contract" in why
    assert "5d" not in why  # no 5d fact -> no persistence clause
    heavy = next(r for r in body["rows"] if r["group_name"] == "Heavy Electrical")
    assert heavy["breadth_label"] == "thin" and heavy["rank_1d"] is None


def test_first_rule_fails_closed_on_null():
    from App.services import today

    assert today.first_rule({"rvol": None, "delivery_vs_20d": 2.0}, today.QUALITY_RULES) is None
    assert today.first_rule({"rvol": 1.6, "delivery_vs_20d": None}, today.QUALITY_RULES)["id"] == "normal"
    assert today.first_rule({"rvol": 1.6, "delivery_vs_20d": 1.3, "market_cap_cr": 100, "at_circuit": True},
                            today.QUALITY_RULES)["id"] == "operator"
    assert today.first_rule({"return_1d": 1, "return_5d": -1, "return_21d": 4}, today.PERSISTENCE_RULES)["id"] == "resume_up"
    assert today.first_rule({"return_1d": 1, "return_5d": 1, "return_21d": -4}, today.PERSISTENCE_RULES)["id"] == "bounce"


def test_why_sentence_persistence_clause():
    from App.services import today

    g = {"group_name": "Pharma", "return_1d": 2.1, "stocks": 23, "pct_up": 78.0, "breadth_label": "broad",
         "top_contributors": [{"symbol": "X", "change_1d_pct": 6.0}, {"symbol": "Y", "change_1d_pct": 5.0}],
         "turnover_vs_20d": 1.8, "delivery_vs_20d": 1.3, "participation": "real participation",
         "deal_buyers": 2, "deal_sellers": 0, "deal_net_cr": 12.0, "return_5d": 4.0, "return_21d": 9.0,
         "persistence_phrase": "part of an up-trend"}
    s = today.why_sentence(g)
    assert s == ("Pharma +2.1% today, broad (78% of 23 stocks up), led by X +6.0%, Y +5.0%. Turnover 1.80× normal "
                 "with delivery 1.30× — real participation. Deals: 2 net buyers (net +₹12.0 Cr, PROP excluded). "
                 "5d +4.0%, 21d +9.0% — part of an up-trend.")


def test_today_metric_keys_exist():
    from App.services import metrics, today

    keys = set(metrics.by_key())
    assert set(today.TODAY_METRICS + today.MARKET_METRICS + today.GROUP_TODAY_METRICS) - keys == set()


def test_as_of_time_travel_bounds_session(client):
    prev = sessions()[-2]
    body = _get(client, f"/api/v2/today/movers?as_of={prev.isoformat()}")
    assert body["as_of"] == prev.isoformat()
    assert all(r["symbol"] not in {"P1", "P2", "P3", "P4"} for r in body["rows"])  # pharma was flat before today
    assert (prev + timedelta(days=1)) <= LAST


def test_why_sentence_flat_group_lists_biggest_moves_not_shares():
    from App.services import today

    g = {"group_name": "Power", "return_1d": 0.01, "stocks": 31, "pct_up": 39.0, "breadth_label": "flat",
         "top_contributors": [{"symbol": "JNPR", "change_1d_pct": 3.2}], "top_detractors": [{"symbol": "UEL", "change_1d_pct": -4.0}],
         "top1_share_pct": None}
    s = today.why_sentence(g)
    assert s == "Power +0.01% today — flat overall (39% of 31 stocks up), biggest moves UEL -4.0%, JNPR +3.2%."
