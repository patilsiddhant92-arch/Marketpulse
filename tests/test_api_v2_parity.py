"""Parity restorations (audit 2026-09-27): stock profile, industry peers, capital accumulators."""
from __future__ import annotations

import duckdb
import pytest
from fastapi.testclient import TestClient

from test_api_v2_helpers import LAST, build_market_db


@pytest.fixture()
def client(tmp_path, monkeypatch):
    market = build_market_db(tmp_path / "market.duckdb")
    con = duckdb.connect(str(market))
    # A surge day for AAA: turnover 30 Cr vs 18 Cr 20-day ADV (+66.7 %), on an up close.
    con.execute("UPDATE indicators_daily SET turnover_cr = 30 WHERE symbol = 'AAA' AND trade_date = ?", [LAST])
    con.close()
    monkeypatch.setenv("MP_DB_PATH", str(market))
    monkeypatch.setenv("MP_USER_DB_PATH", str(tmp_path / "user.duckdb"))
    monkeypatch.setenv("MP_HOLIDAYS_PATH", str(tmp_path / "none.json"))
    from App.api.v2 import create_app
    from App.services import db

    db.clear_cache()
    yield TestClient(create_app())
    db.clear_cache()


def _get(c, url):
    r = c.get(url)
    assert r.status_code == 200, (url, r.text[:400])
    body = r.json()
    assert body["returned"] == len(body["rows"]) <= body["total"]
    return body


def test_profile_checklist_matches_stored_count(client):
    body = _get(client, "/api/v2/stock/AAA/profile")
    row = body["rows"][0]
    passed = [c["passed"] for c in row["criteria"]]
    assert len(passed) == 8
    assert sum(1 for p in passed if p) == row["trend_template_pass_n"] == 8
    assert row["turnover_cr"] == 30.0
    assert row["turnover_surge_pct"] == pytest.approx(66.7, abs=0.1)
    assert len(row["trail"]) == 5
    assert row["trail"][-1]["trade_date"] == LAST.isoformat()


def test_profile_null_stays_null(client):
    row = _get(client, "/api/v2/stock/NULLRS/profile")["rows"][0]
    rs = next(c for c in row["criteria"] if c["key"] == "rs_at_least_70")
    assert rs["passed"] is None  # NULL rank is not "failed", never a default
    # the fixture has no avg_trade_size columns: ticket stays NULL, no whale guess
    assert row["ticket_ratio"] is None and row["whale_ticket"] is None
    assert row["delivery_pct"] is None


def test_peers_rank_target_and_unranked_last(client):
    body = _get(client, "/api/v2/stock/AAA/peers")
    ctx = body["meta"]["context"]
    assert ctx["industry"] == "Heavy Electrical"
    syms = [r["symbol"] for r in body["rows"]]
    assert "TOTAL" not in syms and "AAA" in syms
    target = next(r for r in body["rows"] if r["is_target"])
    assert target["symbol"] == "AAA" and ctx["target_rank"] == target["rank"]
    null = next(r for r in body["rows"] if r["symbol"] == "NULLRS")
    assert null["rank"] is None and syms[-1] == "NULLRS"


def test_peers_unknown_symbol_is_unavailable_not_500(client):
    body = _get(client, "/api/v2/stock/NOPE/peers")
    assert body["meta"]["status"] == "unavailable" and body["rows"] == []


def test_accumulators_filters_and_no_silent_cap(client):
    body = _get(client, "/api/v2/market/accumulators")
    syms = [r["symbol"] for r in body["rows"]]
    assert syms == ["AAA"]  # SMALL is below the floor; others have no surge; TOTAL never appears
    row = body["rows"][0]
    assert row["turnover_surge_pct"] == pytest.approx(66.7, abs=0.1)
    assert body["total"] == len(body["rows"])
    looser = _get(client, "/api/v2/market/accumulators?min_mcap_cr=0&min_surge_pct=0&min_turnover_cr=0")
    assert "SMALL" in [r["symbol"] for r in looser["rows"]]
    assert "TOTAL" not in [r["symbol"] for r in looser["rows"]]


def test_accumulators_as_of_bounded(client):
    body = _get(client, "/api/v2/market/accumulators?as_of=2026-09-24")
    assert body["as_of"] == "2026-09-24" and body["rows"] == []
