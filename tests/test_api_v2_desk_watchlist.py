"""Contract tests for GET /api/v2/desk/watchlist (Desk watchlist panel, spec §7.2)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from test_api_v2_helpers import LAST, build_market_db, sessions

ENVELOPE_KEYS = {"as_of", "freshness", "total", "returned", "rows", "meta"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    market = build_market_db(tmp_path / "market.duckdb")
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


def _get(client, url, status=200):
    r = client.get(url)
    assert r.status_code == status, (url, r.status_code, r.text[:500])
    return r.json()


def test_watchlist_snapshot_keeps_order_and_nulls(client):
    body = _get(client, "/api/v2/desk/watchlist?symbols=nullrs,AAA,ZZZNODATA,AAA")
    assert ENVELOPE_KEYS <= set(body)
    syms = [r["symbol"] for r in body["rows"]]
    assert syms == ["NULLRS", "AAA", "ZZZNODATA"]  # caller order, de-duplicated, nothing dropped
    by = {r["symbol"]: r for r in body["rows"]}
    assert by["AAA"]["has_data"] is True and by["AAA"]["close"] is not None
    # A symbol with no data stays NULL — never filled.
    missing = by["ZZZNODATA"]
    assert missing["has_data"] is False
    assert missing["close"] is None and missing["rs_percentile"] is None and missing["queues"] == []
    # NULL rank stays NULL (no 50 default).
    assert by["NULLRS"]["rs_percentile"] is None
    for r in body["rows"]:
        assert isinstance(r["queues"], list)
        if not r["queues"]:
            assert r["trigger_price"] is None and r["stop_price"] is None and r["risk_pct"] is None


def test_watchlist_queue_membership_matches_desk_queues(client):
    queued = {}
    for q in ("darvas_squeeze", "darvas_10ema", "vcp"):
        for row in _get(client, f"/api/v2/desk/queue/{q}")["rows"]:
            queued.setdefault(row["symbol"], set()).add(q)
    body = _get(client, "/api/v2/desk/watchlist?symbols=AAA,NULLRS,SMALL")
    for r in body["rows"]:
        assert set(r["queues"]) == queued.get(r["symbol"], set())


def test_watchlist_empty_and_validation(client):
    body = _get(client, "/api/v2/desk/watchlist")
    assert body["rows"] == [] and body["total"] == 0
    _get(client, "/api/v2/desk/watchlist?symbols=BAD;SYM", status=422)


def test_watchlist_respects_as_of(client):
    days = sessions()
    earlier = days[-5]
    body = _get(client, f"/api/v2/desk/watchlist?symbols=AAA&as_of={earlier.isoformat()}")
    assert body["as_of"] == earlier.isoformat()
    assert body["rows"][0]["trade_date"] == earlier.isoformat()
