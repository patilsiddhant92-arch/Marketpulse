"""API v2 contract tests against a small fixture DuckDB (spec §6.3, §8, §11)."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from test_api_v2_helpers import LAST, build_market_db, sessions

ROOT = Path(__file__).resolve().parents[1]
ENVELOPE_KEYS = {"as_of", "freshness", "total", "returned", "rows", "meta"}
FABRICATED = {50.0, 45.0, 2.0}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    market = build_market_db(tmp_path / "market.duckdb")
    monkeypatch.setenv("MP_DB_PATH", str(market))
    monkeypatch.setenv("MP_USER_DB_PATH", str(tmp_path / "user.duckdb"))
    monkeypatch.setenv("MP_STATUS_PATH", str(tmp_path / "status.json"))
    monkeypatch.setenv("MP_HOLIDAYS_PATH", str(tmp_path / "no_holidays.json"))
    from App.services import common, db

    db.clear_cache()
    # Freeze "now" so the fixture's last session is the expected one (fresh).
    monkeypatch.setattr(common, "expected_session", lambda now=None, holidays=None: LAST)
    yield tmp_path
    db.clear_cache()


@pytest.fixture()
def client(env):
    from App.api.v2 import create_app

    return TestClient(create_app())


def _ok(client, url, status=200):
    r = client.get(url)
    assert r.status_code == status, (url, r.status_code, r.text[:500])
    body = r.json()
    assert ENVELOPE_KEYS <= set(body), url
    assert body["returned"] == len(body["rows"]) <= body["total"]
    assert body["meta"]["status"] in ("ok", "partial", "unavailable")
    return body


# --------------------------------------------------------------------------
# Envelope shape on every read endpoint
# --------------------------------------------------------------------------
READ_URLS = [
    "/api/v2/market/regime", "/api/v2/market/health", "/api/v2/desk/queues", "/api/v2/desk/queue/darvas_squeeze",
    "/api/v2/desk/queue/darvas_10ema", "/api/v2/desk/queue/vcp", "/api/v2/desk/diff", "/api/v2/screener/presets",
    "/api/v2/screener/run?preset=minervini_8of8", "/api/v2/screener/debug?symbol=AAA&preset=minervini_8of8",
    "/api/v2/groups/board", "/api/v2/groups/rrg", "/api/v2/groups/industry:Heavy Electrical",
    "/api/v2/groups/industry:Heavy Electrical/members", "/api/v2/deals/session", "/api/v2/deals/house/GOOD FUND LP",
    "/api/v2/deals/followthrough", "/api/v2/deals/prints", "/api/v2/deals/window?min_mcap_cr=0",
    "/api/v2/deals/leaderboard", "/api/v2/deals/star-radar", "/api/v2/stock/AAA", "/api/v2/stock/AAA/bars", "/api/v2/stock/AAA/bars?tf=W",
    "/api/v2/stock/AAA/bars?tf=M", "/api/v2/stock/AAA/rs", "/api/v2/stock/AAA/events", "/api/v2/stock/AAA/deals",
    "/api/v2/stock/AAA/analogs", "/api/v2/evidence/vcp", "/api/v2/research/analogs", "/api/v2/research/big-moves",
    "/api/v2/research/big-moves/abc", "/api/v2/research/pre-move", "/api/v2/metrics/dictionary", "/api/v2/watchlist",
    "/api/v2/notes/AAA", "/api/v2/context/stocks?symbols=AAA,SMALL", "/api/v2/context/groups", "/api/v2/desk/compare",
    "/api/v2/groups/rotation", "/api/v2/stock/AAA/why", "/api/v2/stock/AAA/profile", "/api/v2/stock/AAA/peers",
    "/api/v2/market/accumulators",
]


@pytest.mark.parametrize("url", READ_URLS)
def test_envelope_shape(client, url):
    body = _ok(client, url)
    assert set(body["freshness"]) >= {"status", "latest_session", "history_mode"}
    assert isinstance(body["meta"]["sources"], list)


def test_freshness_and_as_of_on_latest(client):
    body = _ok(client, "/api/v2/market/health")
    assert body["as_of"] == LAST.isoformat()
    assert body["freshness"]["status"] == "fresh"
    assert body["freshness"]["history_mode"] is False


# --------------------------------------------------------------------------
# NULL stays NULL / no fabricated defaults
# --------------------------------------------------------------------------
def test_null_stays_null_in_stock_header(client):
    row = _ok(client, "/api/v2/stock/NULLRS")["rows"][0]
    assert row["rs_percentile"] is None  # never 50
    assert row["delivery_pct"] is None  # never 45
    assert row["deliv_pct_x"] is None
    assert row["ema_200"] is None
    assert row["excess_vs_midsml400_63d"] is None


def test_screener_fails_closed_on_null_and_keeps_null(client):
    rows = _ok(client, "/api/v2/screener/run?preset=minervini_8of8")["rows"]
    syms = {r["symbol"] for r in rows}
    assert "AAA" in syms
    assert "NULLRS" not in syms  # NULL RS fails the RS >= 70 rule (fail-closed)
    rules = json.dumps([{"field": "close", "op": "gt", "value": 0}])
    rows = _ok(client, f"/api/v2/screener/run?rules={rules}")["rows"]
    nullrs = next(r for r in rows if r["symbol"] == "NULLRS")
    assert nullrs["rs_percentile"] is None and nullrs["delivery_pct"] is None
    assert nullrs["rs_is_ipo_rank"] is False


def test_include_ipos_uses_badged_ipo_rank(client):
    rules = json.dumps([{"field": "rs_percentile", "op": "gte", "value": 70}])
    rows = _ok(client, f"/api/v2/screener/run?rules={rules}&include_ipos=true")["rows"]
    nullrs = next(r for r in rows if r["symbol"] == "NULLRS")
    assert nullrs["rs_percentile"] == 77.0 and nullrs["rs_is_ipo_rank"] is True


def test_ema200_null_fails_close_gt_ema200_rule(client):
    rules = json.dumps([{"field": "close", "op": "gt", "ref": "ema_200"}])
    syms = {r["symbol"] for r in _ok(client, f"/api/v2/screener/run?rules={rules}")["rows"]}
    assert "NULLRS" not in syms and "AAA" in syms


def test_queue_shaping_never_fabricates_geometry(env):
    import pandas as pd

    from App.services import db, desk

    frame = pd.DataFrame([{"symbol": "AAA", "close": 100.0, "trigger_price": float("nan"), "stop_price": None,
                           "rs_percentile": None, "delivery_pct": None, "vdu_ratio": None}])
    with db.market_conn() as con:
        row = desk._shape(frame, "vcp", "D", LAST, con, None)[0]
    assert row["trigger_price"] is None and row["stop_price"] is None
    assert row["risk_pct"] is None and row["distance_to_trigger_pct"] is None
    assert row["vdu_ratio"] is None and row["rs_percentile"] is None and row["delivery_pct"] is None
    assert row["is_new"] is None


def test_no_fabricated_defaults_in_queue_rows(client):
    for q in ("darvas_squeeze", "darvas_10ema", "vcp"):
        for row in _ok(client, f"/api/v2/desk/queue/{q}")["rows"]:
            close = row["close"]
            for k in (1.02, 0.96, 1.025, 0.965, 1.005, 0.95):
                assert row["trigger_price"] != round(close * k, 2)
                assert row["stop_price"] != round(close * k, 2)
            assert row["vdu_ratio"] not in (0.65, 0.85, 0.72)
            assert "reward_to_risk" not in row


def test_market_health_values_are_real(client):
    row = _ok(client, "/api/v2/market/health")["rows"][0]
    assert row["pct_above_50ema"] == 51.0 and row["advance_pct"] == 60.0
    # 30 sessions of history: 25-session rolling measure exists, VIX 5d change computed
    assert row["distribution_days_25"] is not None


# --------------------------------------------------------------------------
# Paging
# --------------------------------------------------------------------------
def test_paging_total_and_returned(client):
    full = _ok(client, "/api/v2/market/health")
    assert full["total"] == len(sessions())
    page = _ok(client, "/api/v2/market/health?offset=2&limit=3")
    assert page["total"] == full["total"] and page["returned"] == 3
    assert page["rows"][0]["trade_date"] == full["rows"][2]["trade_date"]
    assert page["meta"]["offset"] == 2 and page["meta"]["limit"] == 3
    beyond = _ok(client, "/api/v2/market/health?offset=500")
    assert beyond["returned"] == 0 and beyond["total"] == full["total"]


def test_limit_bounds_validated(client):
    assert client.get("/api/v2/market/health?limit=0").status_code == 422
    assert client.get("/api/v2/market/health?limit=999999").status_code == 422
    assert client.get("/api/v2/market/health?offset=-1").status_code == 422


# --------------------------------------------------------------------------
# as_of bounding (time travel)
# --------------------------------------------------------------------------
def test_as_of_bounds_every_series(client):
    days = sessions()
    mid = days[10]
    health = _ok(client, f"/api/v2/market/health?as_of={mid}")
    assert health["as_of"] == mid.isoformat()
    assert all(r["trade_date"] <= mid.isoformat() for r in health["rows"])
    assert health["freshness"]["history_mode"] is True
    bars = _ok(client, f"/api/v2/stock/AAA/bars?as_of={mid}")
    assert bars["rows"][-1]["trade_date"] == mid.isoformat()
    events = _ok(client, f"/api/v2/stock/AAA/events?as_of={mid}&days_ahead=0")
    assert all(r["event_date"] <= mid.isoformat() for r in events["rows"])
    header = _ok(client, f"/api/v2/stock/AAA?as_of={mid}")["rows"][0]
    assert header["close"] == 100.0 + 10
    board = _ok(client, f"/api/v2/groups/board?as_of={mid}")
    assert board["as_of"] == mid.isoformat()


def test_as_of_on_weekend_resolves_to_prior_session(client):
    sunday = LAST + timedelta(days=2)
    assert _ok(client, f"/api/v2/market/health?as_of={sunday}")["as_of"] == LAST.isoformat()


def test_as_of_before_history_is_unavailable_not_500(client):
    body = _ok(client, "/api/v2/market/health?as_of=2000-01-01")
    assert body["rows"] == [] and body["meta"]["status"] == "unavailable" and body["meta"]["reason"]


def test_deals_as_of_before_deal_session_flags_no_records(client):
    body = _ok(client, f"/api/v2/deals/session?as_of={sessions()[-2]}")
    assert body["rows"] == []
    assert body["meta"]["context"]["no_records_for_session"] is True


def test_bad_as_of_is_422(client):
    assert client.get("/api/v2/market/health?as_of=yesterday").status_code == 422


# --------------------------------------------------------------------------
# Symbol validation
# --------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["A;DROP", "a b", "X" * 21, "AAA'--", "%27"])
def test_symbol_validation_rejects(client, bad):
    assert client.get(f"/api/v2/stock/{bad}").status_code == 422
    assert client.get(f"/api/v2/stock/{bad}/bars").status_code == 422
    assert client.put(f"/api/v2/notes/{bad}", json={"body": "x"}).status_code == 422


def test_symbol_normalised_and_allowed_chars(client):
    assert _ok(client, "/api/v2/stock/aaa")["rows"][0]["symbol"] == "AAA"
    assert client.get("/api/v2/stock/M&M-X_1.A/events").status_code == 200
    assert client.get("/api/v2/screener/debug?symbol=bad;sym").status_code == 422
    r = client.put("/api/v2/watchlist", json={"symbols": ["AAA", "bad sym"]})
    assert r.status_code == 422


# --------------------------------------------------------------------------
# Unavailable tables
# --------------------------------------------------------------------------
@pytest.mark.parametrize("url", [
    "/api/v2/market/regime", "/api/v2/groups/rrg", "/api/v2/evidence/vcp",
    "/api/v2/research/analogs", "/api/v2/research/big-moves", "/api/v2/research/big-moves/1",
    "/api/v2/research/pre-move", "/api/v2/stock/AAA/analogs",
])
def test_missing_tables_return_unavailable_envelope(client, url):
    body = _ok(client, url)
    assert body["rows"] == [] and body["total"] == 0
    assert body["meta"]["status"] == "unavailable" and body["meta"]["reason"]


def test_legacy_fallbacks_are_labelled_partial(client):
    board = _ok(client, "/api/v2/groups/board")
    assert board["meta"]["status"] == "partial" and "computed live" in board["meta"]["reason"]
    # 30 fixture sessions < the 50 needed for EMA50 of the RS line: RS-Ratio stays NULL, never defaulted.
    assert all(r["rs_ratio"] is None and r["rrg_quadrant"] is None for r in board["rows"])
    assert all(r["rank"] is None for r in board["rows"])  # < 3 members or no 63d excess -> unranked, not 0
    assert "TOTAL" not in {r["group_name"] for r in board["rows"]}
    assert _ok(client, "/api/v2/deals/session")["meta"]["status"] == "partial"
    assert _ok(client, "/api/v2/desk/queue/vcp")["meta"]["status"] == "partial"


def test_followthrough_small_sample_shows_no_numbers(client):
    body = _ok(client, "/api/v2/deals/followthrough?min_mcap_cr=0")
    assert body["meta"]["status"] == "partial"
    assert {r["event_type"] for r in body["rows"]} >= {"accumulate", "fresh", "distribute", "baseline"}
    for r in body["rows"]:
        assert r["insufficient_sample"] is True and r["avg_fwd_t20_pct"] is None and r["hit_rate_t20"] is None


def test_live_group_board_matches_hand_computed_return(client):
    body = _ok(client, "/api/v2/groups/board?level=industry&floor=all")
    heavy = next(r for r in body["rows"] if r["group_name"] == "Heavy Electrical")
    # Members AAA (100+i), NULLRS (50+i), SMALL (20+i); 21d EW return on the last of 30 sessions (i=29 vs i=8).
    expected = ((129 / 108 - 1) + (79 / 58 - 1) + (49 / 28 - 1)) / 3 * 100
    assert abs(heavy["return_ew_21d"] - expected) < 1e-3
    assert heavy["stocks"] == 3 and heavy["leader_symbols"][0] == "AAA"


def test_deal_session_live_event_types(client):
    rows = _ok(client, "/api/v2/deals/session")["rows"]
    aaa = next(r for r in rows if r["symbol"] == "AAA")
    assert aaa["event_type"] == "fresh" and aaa["persistence_days"] == 1 and aaa["net_ex_prop_cr"] == 1.28
    houses = _ok(client, "/api/v2/deals/houses")["rows"]
    good = next(h for h in houses if h["house"] == "GOOD FUND LP")
    assert good["prints"] == 1 and good["ranked"] is False and good["avg_fwd_t20_pct"] is None


def test_groups_and_deals_switch_to_derived_tables(tmp_path, monkeypatch):
    """When group_daily / deal_session_net exist (Scripts/derived/SCHEMA.md names) they are the source."""
    market = build_market_db(tmp_path / "m3.duckdb")
    con = duckdb.connect(str(market))
    days = sessions()
    con.execute("""CREATE TABLE group_daily (trade_date TIMESTAMP, level VARCHAR, floor VARCHAR, group_name VARCHAR,
                   members BIGINT, ret_ew_1d DOUBLE, ret_ew_21d DOUBLE, excess_midsml_21d DOUBLE, excess_midsml_63d DOUBLE,
                   rs_ratio DOUBLE, rs_momentum DOUBLE, rrg_quadrant VARCHAR, days_in_quadrant DOUBLE, rank DOUBLE,
                   rank_n DOUBLE, rank_chg_5d DOUBLE, pct_above_50ema DOUBLE, turnover_share_delta DOUBLE,
                   top1_turnover_share_pct DOUBLE, concentration_flag BOOLEAN, deliv_acc_10d_pct DOUBLE,
                   rs_ratio_self DOUBLE, rs_momentum_self DOUBLE, ew_index DOUBLE, ew_index_ema50 DOUBLE,
                   ew_index_ema200 DOUBLE, abs_trend VARCHAR, quadrant_note VARCHAR, health DOUBLE, health_rank DOUBLE)""")
    for i, d in enumerate(days):
        for fl in ("all", "1000cr"):
            con.execute("INSERT INTO group_daily VALUES (?, 'Industry', ?, 'Heavy Electrical', 3, 0.5, 7.5, 2.0, 4.0, "
                        "101.5, 100.4, 'Leading', ?, 1, 1, 2, 66.7, 0.1, 40, FALSE, 12.5, "
                        "103.0, 100.9, ?, NULL, NULL, 'Up', NULL, 71.5, 1)", [d, fl, i + 1, 100 + i])
    con.execute("""CREATE TABLE deal_session_net (trade_date TIMESTAMP, symbol VARCHAR, n_prints BIGINT,
                   buy_value_cr DOUBLE, sell_value_cr DOUBLE, net_value_cr DOUBLE, net_value_cr_ex_prop DOUBLE,
                   buying_houses DOUBLE, net_vs_adv DOUBLE, net_buy_sessions_10 DOUBLE, event_type VARCHAR)""")
    con.execute("INSERT INTO deal_session_net VALUES (?, 'AAA', 1, 1.28, 0, 1.28, 1.28, 1, 0.07, 2, 'accumulate')", [days[-1]])
    con.close()
    monkeypatch.setenv("MP_DB_PATH", str(market))
    monkeypatch.setenv("MP_HOLIDAYS_PATH", str(tmp_path / "none.json"))
    from App.api.v2 import create_app
    from App.services import db

    db.clear_cache()
    c = TestClient(create_app())
    board = _ok(c, "/api/v2/groups/board?level=industry")
    assert board["meta"]["status"] == "ok" and board["meta"]["context"]["source"] == "group_daily"
    row = board["rows"][0]
    assert row["rrg_quadrant"] == "Leading" and row["rank_delta_5"] == 2 and row["excess_vs_midsml400_63d"] == 4.0
    assert row["delivery_accumulation"] == 12.5 and row["days_in_quadrant"] == len(days)
    assert row["health"] == 71.5 and row["health_rank"] == 1 and row["abs_trend"] == "Up" and row["rs_ratio_self"] == 103.0
    idx = _ok(c, "/api/v2/groups/industry:Heavy Electrical/index")
    assert idx["meta"]["status"] == "ok" and idx["rows"][-1]["ew_index"] == 100 + len(days) - 1
    tree = _ok(c, "/api/v2/groups/treemap")
    assert any(r["id"] == "industry:Heavy Electrical" and r["health"] == 71.5 for r in tree["rows"])
    rrg = _ok(c, "/api/v2/groups/rrg?level=industry")
    assert rrg["meta"]["status"] == "ok" and rrg["rows"][0]["tail"][-1]["rs_ratio"] == 101.5
    watch = _ok(c, "/api/v2/groups/board?level=industry&floor=watch")  # not in group_daily -> live, labelled
    assert watch["meta"]["status"] == "partial"
    deals_body = _ok(c, "/api/v2/deals/session")
    assert deals_body["meta"]["status"] == "ok"
    aaa = deals_body["rows"][0]
    assert aaa["event_type"] == "accumulate" and aaa["persistence_days"] == 2 and aaa["vs_adv"] == 0.07
    db.clear_cache()


def test_legacy_group_daily_gets_peer_rrg_and_health_on_the_fly(tmp_path, monkeypatch):
    """A group_daily built before the peer-relative columns: the API derives them from the stored self RS-Ratio."""
    market = build_market_db(tmp_path / "m4.duckdb")
    con = duckdb.connect(str(market))
    days = sessions()
    con.execute("""CREATE TABLE group_daily (trade_date TIMESTAMP, level VARCHAR, floor VARCHAR, group_name VARCHAR,
                   members BIGINT, ret_ew_1d DOUBLE, ret_ew_21d DOUBLE, rs_ratio DOUBLE, rs_momentum DOUBLE,
                   rrg_quadrant VARCHAR, pct_above_50ema DOUBLE, pct_above_200ema DOUBLE)""")
    for i, d in enumerate(days):
        for k in range(6):  # every group's self ratio > 100 (falling benchmark), stored quadrant all 'Leading'
            con.execute("INSERT INTO group_daily VALUES (?, 'Industry', '1000cr', ?, 3, -0.2, ?, ?, ?, 'Leading', 40, 30)",
                        [d, f"G{k}", -2.0 + k, 101.0 + k, 100.1 + 0.1 * k])
    con.close()
    monkeypatch.setenv("MP_DB_PATH", str(market))
    monkeypatch.setenv("MP_HOLIDAYS_PATH", str(tmp_path / "none.json"))
    from App.api.v2 import create_app
    from App.services import db

    db.clear_cache()
    c = TestClient(create_app())
    board = _ok(c, "/api/v2/groups/board?level=industry")
    rows = {r["group_name"]: r for r in board["rows"]}
    assert board["meta"]["status"] == "ok"
    assert rows["G5"]["rs_ratio_self"] == 106.0 and abs(sum(r["rs_ratio"] for r in rows.values()) / 6 - 100) < 1e-3
    assert sum(1 for r in rows.values() if r["rrg_quadrant"] == "Leading") == 3  # was 6 of 6
    assert rows["G5"]["rrg_quadrant"] == "Leading" and rows["G5"]["quadrant_note"] == "Leading, narrow breadth"
    assert rows["G3"]["quadrant_note"] == "Leading, narrow breadth" and rows["G0"]["rrg_quadrant"] == "Lagging"
    assert board["rows"][0]["group_name"] == "G5" and rows["G5"]["health_rank"] == 1
    market_ctx = board["meta"]["context"]["market"]
    assert market_ctx["quadrants"]["Leading"] == 3 and market_ctx["groups"] == 6
    rrg = _ok(c, "/api/v2/groups/rrg?level=industry")
    assert {r["group_name"] for r in rrg["rows"] if r["rrg_quadrant"] == "Leading"} == {"G3", "G4", "G5"}
    db.clear_cache()


def test_regime_read_from_regime_daily_when_present(tmp_path, monkeypatch):
    market = build_market_db(tmp_path / "m2.duckdb", with_regime=True)
    monkeypatch.setenv("MP_DB_PATH", str(market))
    monkeypatch.setenv("MP_HOLIDAYS_PATH", str(tmp_path / "none.json"))
    from App.api.v2 import create_app
    from App.services import db

    db.clear_cache()
    body = _ok(TestClient(create_app()), "/api/v2/market/regime?days=5")
    assert body["meta"]["status"] == "ok" and body["returned"] == 5
    row = body["rows"][0]
    assert row["verdict"] == "Constructive" and row["rule_id"] == "R2"
    assert row["pillars"]["trend"]["status"] == "Healthy"
    assert row["pillars"]["follow_through"]["status"] is None
    assert row["pillars"]["trend"]["inputs"] == {"midsml400_vs_50ema_pct": None}


def test_unknown_queue_and_bad_params(client):
    assert client.get("/api/v2/desk/queue/nope").status_code == 422
    assert client.get("/api/v2/groups/board?level=galaxy").status_code == 422
    assert client.get("/api/v2/groups/nonsense").status_code == 422
    assert client.get("/api/v2/evidence/not_a_setup").status_code == 404


# --------------------------------------------------------------------------
# Screener rules are data, never SQL
# --------------------------------------------------------------------------
@pytest.mark.parametrize("rules", [
    '[{"field": "close; DROP TABLE x", "op": "gt", "value": 1}]',
    '[{"field": "close", "op": "gt", "value": "1 OR 1=1"}]',
    '[{"field": "close", "op": "like", "value": 1}]',
    '[{"field": "close", "op": "gt", "ref": "(SELECT 1)"}]',
    '{"field": "close"}',
    'not json',
])
def test_screener_rejects_bad_rules(client, rules):
    assert client.get("/api/v2/screener/run", params={"rules": rules}).status_code == 422


def test_screener_presets_are_editable_chips(client):
    rows = _ok(client, "/api/v2/screener/presets")["rows"]
    mm = next(p for p in rows if p["id"] == "minervini_8of8")
    assert {"field": "rs_percentile", "op": "gte", "value": 70.0} .items() <= mm["rules"][1].items()
    run = _ok(client, "/api/v2/screener/run?preset=minervini_8of8")
    assert run["meta"]["context"]["applied_rules"][1]["field"] == "rs_percentile"
    assert client.get("/api/v2/screener/run?preset=nope").status_code == 422


def test_screener_debug_explains_each_rule(client):
    body = _ok(client, "/api/v2/screener/debug?symbol=NULLRS&preset=minervini_8of8")
    rules = [r for r in body["rows"] if r["kind"] == "rule"]
    rs_rule = next(r for r in rules if r["field"] == "rs_percentile")
    assert rs_rule["passed"] is False and rs_rule["missing_input"] is True and rs_rule["actual"] is None
    assert body["meta"]["context"]["passes_all"] is False


def test_floor_and_total_exclusion(client):
    rules = json.dumps([{"field": "close", "op": "gt", "value": 0}])
    syms = {r["symbol"] for r in _ok(client, f"/api/v2/screener/run?rules={rules}")["rows"]}
    assert "TOTAL" not in syms and "SMALL" not in syms
    syms_all = {r["symbol"] for r in _ok(client, f"/api/v2/screener/run?rules={rules}&min_mcap_cr=0")["rows"]}
    assert "SMALL" in syms_all and "TOTAL" not in syms_all
    members = _ok(client, "/api/v2/groups/industry:Heavy Electrical/members?floor=all")["rows"]
    assert {r["symbol"] for r in members} == {"AAA", "NULLRS", "SMALL"}


# --------------------------------------------------------------------------
# Deals: duplicate prints collapsed
# --------------------------------------------------------------------------
def test_duplicate_bulk_block_print_counted_once(client):
    rows = _ok(client, "/api/v2/deals/session")["rows"]
    aaa = next(r for r in rows if r["symbol"] == "AAA")
    assert aaa["prints"] == 1 and aaa["buy_cr"] == 1.28 and aaa["net_cr"] == 1.28
    assert "TOTAL" not in {r["symbol"] for r in rows}
    prints = _ok(client, "/api/v2/stock/AAA/deals")["rows"]
    assert len(prints) == 1 and set(prints[0]["deal_types"].split("+")) == {"Bulk", "Block"}


def test_deals_desk_views_restored(client):
    """Today prints, the multi-session window and the house leaderboard (old desk features) on the fixture."""
    prints = _ok(client, "/api/v2/deals/prints")
    assert prints["total"] == 1 and prints["rows"][0]["symbol"] == "AAA"  # bulk+block duplicate once, TOTAL dropped
    assert prints["rows"][0]["house"] == "GOOD FUND LP" and prints["rows"][0]["event_type"] == "fresh"
    win = _ok(client, "/api/v2/deals/window?min_mcap_cr=0&lookback=10")
    aaa = next(r for r in win["rows"] if r["symbol"] == "AAA")
    assert aaa["deal_days"] == 1 and aaa["net_buy_days"] == 1 and aaa["flow_net_cr"] == 1.28
    assert aaa["tier"] == "fresh" and aaa["play_reason"] == "Single" and aaa["n_buy_houses"] == 1
    assert win["meta"]["context"]["lookback"] == 10 and len(aaa["net_by_session"]) == len(win["meta"]["context"]["window_dates"])
    # A ₹1.28 Cr print is below the ₹5 Cr bet floor: no house is ranked, no star radar rows (never fabricated).
    assert _ok(client, "/api/v2/deals/leaderboard?include_individuals=true")["total"] == 0
    assert _ok(client, "/api/v2/deals/star-radar")["total"] == 0
    assert client.get("/api/v2/deals/window?setup=BOGUS").status_code == 422


def test_house_page_forward_returns_never_look_past_as_of(client):
    body = _ok(client, "/api/v2/deals/house/good fund lp")
    assert body["total"] == 1
    assert body["rows"][0]["fwd_t20_pct"] is None  # no 20 sessions after the deal inside the data
    assert body["meta"]["context"]["summary"]["ranked"] is False


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------
def test_health_200_when_fresh(client):
    r = client.get("/api/v2/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy" and body["version"] and body["build"]


def test_health_503_when_stale(tmp_path, monkeypatch):
    market = build_market_db(tmp_path / "stale.duckdb", last=date(2026, 8, 3))
    monkeypatch.setenv("MP_DB_PATH", str(market))
    monkeypatch.setenv("MP_HOLIDAYS_PATH", str(tmp_path / "none.json"))
    monkeypatch.setenv("MP_STATUS_PATH", str(tmp_path / "status.json"))
    from App.api.v2 import create_app
    from App.services import common

    monkeypatch.setattr(common, "expected_session", lambda now=None, holidays=None: date(2026, 8, 5))
    r = TestClient(create_app()).get("/api/v2/health")
    assert r.status_code == 503
    assert r.json()["status"] == "stale" and r.json()["freshness"]["sessions_behind"] == 2


def test_health_503_when_degraded(env, client):
    (env / "status.json").write_text(json.dumps({"ok": True, "steps": [{"step": "append", "ok": False}]}))
    r = client.get("/api/v2/health")
    assert r.status_code == 503 and r.json()["status"] == "degraded"
    assert _ok(client, "/api/v2/market/health")["freshness"]["status"] == "degraded"


def test_health_503_when_db_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("MP_DB_PATH", str(tmp_path / "missing.duckdb"))
    from App.api.v2 import create_app

    r = TestClient(create_app()).get("/api/v2/health")
    assert r.status_code == 503 and r.json()["status"] == "unavailable"
    assert TestClient(create_app()).get("/api/v2/market/health").status_code == 503


def test_db_lock_maps_to_503_with_retry_after(client, monkeypatch):
    from App.services import db

    def locked(*a, **k):
        raise duckdb.IOException('IO Error: Could not set lock on file "market.duckdb": Conflicting lock is held')

    monkeypatch.setattr(db.duckdb, "connect", locked)
    r = client.get("/api/v2/market/health")
    assert r.status_code == 503 and r.headers.get("Retry-After")
    # user endpoints do not depend on the market DB for freshness, but still honour a user-DB lock
    assert client.get("/api/v2/watchlist").status_code == 503


def test_market_connection_is_read_only_and_cannot_write_files(env):
    from App.services import db

    with db.market_conn() as con:
        with pytest.raises(duckdb.Error):
            con.execute("CREATE TABLE x (a INT)")
        with pytest.raises(duckdb.Error):
            con.execute(f"COPY (SELECT 1) TO '{(env / 'leak.csv').as_posix()}'")
    assert not (env / "leak.csv").exists()


# --------------------------------------------------------------------------
# User data
# --------------------------------------------------------------------------
def test_watchlist_and_notes_round_trip(client):
    r = client.put("/api/v2/watchlist", json={"symbols": ["aaa", "NULLRS", "AAA"]})
    assert r.status_code == 200
    assert [x["symbol"] for x in r.json()["rows"]] == ["AAA", "NULLRS"]
    assert [x["symbol"] for x in _ok(client, "/api/v2/watchlist")["rows"]] == ["AAA", "NULLRS"]
    assert client.put("/api/v2/notes/AAA", json={"body": "base forming"}).status_code == 200
    assert _ok(client, "/api/v2/notes/AAA")["rows"][0]["body"] == "base forming"
    client.put("/api/v2/notes/AAA", json={"body": "  "})
    assert _ok(client, "/api/v2/notes/AAA")["rows"] == []


# --------------------------------------------------------------------------
# Hygiene
# --------------------------------------------------------------------------
def test_v2_never_imports_nicegui():
    code = ("import sys; import App.api.v2, App.services.desk, App.services.stock, App.services.screener; "
            "sys.exit(1 if any(m == 'nicegui' or m.startswith('nicegui.') for m in sys.modules) else 0)")
    res = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stderr[-2000:]


def test_metric_keys_used_by_services_exist_in_dictionary():
    from App.services import deals, desk, groups, market, metrics, screener, stock

    keys = set(metrics.by_key())
    used = set(market.HEALTH_METRICS + market.REGIME_METRICS + desk.QUEUE_METRICS + screener.SCREENER_METRICS
               + groups.GROUP_METRICS + groups.MEMBER_METRICS + deals.DEAL_METRICS + stock.STOCK_METRICS)
    assert used - keys == set()


def test_metric_dictionary_is_complete_and_consistent():
    from App.services import metrics

    entries = metrics.load()
    keys = {e["key"] for e in entries}
    assert len(keys) == len(entries) >= 60
    for e in entries:
        for f in ("plain_name", "measures", "zones", "read_with", "definition_sql_ref"):
            assert e.get(f), (e["key"], f)
        assert len(e["zones"]) >= 2 and all({"range", "label", "why"} <= set(z) for z in e["zones"])
        assert set(e["read_with"]) <= keys and e["key"] not in e["read_with"]


def test_openapi_export_matches_app():
    from App.api.v2 import create_app

    exported = json.loads((ROOT / "frontend" / "openapi.json").read_text(encoding="utf-8"))
    assert exported == json.loads(json.dumps(create_app().openapi())), "run Scripts/export_openapi.py"


# --------------------------------------------------------------------------
# Screener tab (t2): rule catalog, dropped-since-yesterday, queue debugger
# --------------------------------------------------------------------------
def test_screener_presets_carry_rule_catalog_and_categories(client):
    body = _ok(client, "/api/v2/screener/presets")
    fields = {f["field"]: f for f in body["meta"]["context"]["fields"]}
    assert fields["rs_percentile"]["kind"] == "num" and fields["rs_percentile"]["metric_key"] == "rs_percentile"
    assert fields["trend_template_pass"]["kind"] == "bool"
    assert {p["id"]: p["category"] for p in body["rows"]}["vcp"] == "Setups"


def test_screener_run_reports_new_and_dropped(client):
    body = _ok(client, "/api/v2/screener/run?preset=minervini_8of8")
    ctx = body["meta"]["context"]
    assert isinstance(ctx["dropped"], list) and isinstance(ctx["new_count"], int)
    today = {r["symbol"] for r in body["rows"]}
    assert not today & {d["symbol"] for d in ctx["dropped"]}


def test_screener_debug_explains_queue_presets(client):
    body = _ok(client, "/api/v2/screener/debug?symbol=AAA&preset=vcp")
    rows = body["rows"]
    assert rows and rows[-1]["kind"] == "result"
    assert any(r["kind"] == "floor" for r in rows)
    assert body["meta"]["context"]["passes_all"] == rows[-1]["passed"]
    assert body["meta"]["context"]["queue"] == "vcp"


def test_screener_queue_preset_group_filter(client):
    body = _ok(client, "/api/v2/screener/run?preset=darvas&level=industry&group=__nope__")
    assert body["total"] == 0 and body["meta"]["context"]["delegated_to"] == "desk/queue/darvas_squeeze"
