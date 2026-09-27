"""Momentum scanner v2 (parity port of the old /api/screener/momentum) against the fixture DB."""
from __future__ import annotations

import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from test_api_v2_helpers import LAST, build_market_db, sessions

URL = "/api/v2/screener/momentum"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    market = build_market_db(tmp_path / "market.duckdb")
    monkeypatch.setenv("MP_DB_PATH", str(market))
    monkeypatch.setenv("MP_USER_DB_PATH", str(tmp_path / "user.duckdb"))
    monkeypatch.setenv("MP_STATUS_PATH", str(tmp_path / "status.json"))
    monkeypatch.setenv("MP_HOLIDAYS_PATH", str(tmp_path / "no_holidays.json"))
    from App.services import common, db

    db.clear_cache()
    monkeypatch.setattr(common, "expected_session", lambda now=None, holidays=None: LAST)
    yield market
    db.clear_cache()


@pytest.fixture()
def client(env):
    from App.api.v2 import create_app

    return TestClient(create_app())


def _get(client, url, **params):
    r = client.get(url, params=params)
    assert r.status_code == 200, r.text[:500]
    return r.json()


def test_defaults_match_old_endpoint_semantics(client):
    body = _get(client, URL)
    syms = [r["symbol"] for r in body["rows"]]
    # AAA passes everything; NULLRS has no 200 EMA, which the old filter lets through ("unknown passes");
    # SMALL is below ₹1,000 Cr; TOTAL (aggregate row) never appears.
    assert syms == ["AAA", "NULLRS"]
    ctx = body["meta"]["context"]
    assert ctx["params"]["lookback_days"] == 20 and ctx["params"]["min_volume"] == 1_000_000
    assert ctx["is_default"] is True
    assert ctx["buckets_tv"] == "###0_2%,NSE:AAA,NSE:NULLRS"
    assert [b["bucket"] for b in ctx["buckets"]] == ["0_2%", "2_5%", "5_10%", "10%+", "Below 10EMA"]
    assert ctx["buckets"][0]["count"] == 2
    assert ctx["top_sectors"][0]["sector"] == "Capital Goods" and ctx["top_sectors"][0]["stock_count"] == 2
    assert ctx["top_sectors"][0]["tv_str"] == "NSE:AAA,NSE:NULLRS"
    assert ctx["top_industries"][0]["industry"] == "Heavy Electrical"
    aaa = body["rows"][0]
    assert aaa["bucket"] == "0_2%" and aaa["away_10ema_pct"] == 1.0
    assert aaa["trigger_date"] == LAST.isoformat()
    assert aaa["bullish_stack"] is True and aaa["coiling"] is False


def test_null_stays_null(client):
    rows = {r["symbol"]: r for r in _get(client, URL)["rows"]}
    n = rows["NULLRS"]
    assert n["rs_percentile"] is None and n["delivery_pct"] is None
    assert n["bullish_stack"] is None  # 200 EMA unknown: not "False", not "True"
    assert n["return_5d_pct"] is None  # column absent in the fixture -> NULL, never 0


def test_filters_are_bound_parameters(client):
    assert _get(client, URL, min_mcap_cr=4000)["total"] == 1  # only AAA (5000 Cr)
    assert _get(client, URL, min_volume=3_000_000)["total"] == 0
    # Volume gate off + mcap off: SMALL (500 Cr) joins.
    syms = {r["symbol"] for r in _get(client, URL, min_volume=0, min_mcap_cr=0)["rows"]}
    assert syms == {"AAA", "NULLRS", "SMALL"}
    # 20D-average gate (old behaviour: also needs that session's volume >= threshold).
    assert _get(client, URL, min_volume=0, min_avg_volume_20d=1_000_000)["total"] == 2
    assert _get(client, URL, min_volume=0, min_avg_volume_20d=1_600_000)["total"] == 0
    assert _get(client, URL, weekly_rsi_60=True)["total"] == 2
    assert _get(client, URL, coiling_nr7=True)["total"] == 0


def test_bad_params_are_rejected(client):
    assert client.get(URL, params={"lookback_days": 0}).status_code == 422
    assert client.get(URL, params={"min_mcap_cr": "1000 OR 1=1"}).status_code == 422
    assert client.get(URL, params={"debug_symbol": "AAA';DROP"}).status_code == 422


def test_debug_symbol_restricts_and_explains(client):
    body = _get(client, URL, debug_symbol="small", min_volume=0)
    assert body["rows"] == []
    dbg = body["meta"]["context"]["debug"]
    assert dbg["symbol"] == "SMALL" and dbg["in_list"] is False
    failed = [c["label"] for c in dbg["checks"] if not c["passed"]]
    assert any("Market cap" in f for f in failed)
    ok = _get(client, URL, debug_symbol="AAA")
    assert [r["symbol"] for r in ok["rows"]] == ["AAA"]
    assert ok["meta"]["context"]["debug"]["in_list"] is True


def test_new_and_dropped_vs_previous_session(env, client):
    body = _get(client, URL)
    assert body["meta"]["context"]["previous_session"] == sessions()[-2].isoformat()
    assert all(r["is_new"] is False for r in body["rows"])
    # Make AAA fail today's 52W-high condition only on the last session: it drops.
    con = duckdb.connect(str(env))
    con.execute("UPDATE indicators_daily SET away_52w_high_pct = -40 WHERE symbol = 'AAA' AND trade_date = ?",
                [pd.Timestamp(LAST)])
    con.close()
    from App.services import db

    db.clear_cache()
    body = _get(client, URL)
    assert [r["symbol"] for r in body["rows"]] == ["NULLRS"]
    assert [d["symbol"] for d in body["meta"]["context"]["dropped"]] == ["AAA"]


def test_as_of_bounds_the_scan(client):
    body = _get(client, URL, as_of=sessions()[-5].isoformat())
    assert body["as_of"] == sessions()[-5].isoformat()
    assert all(r["trigger_date"] <= body["as_of"] for r in body["rows"])


def test_evidence_short_history_is_unavailable_not_500(client):
    body = _get(client, URL + "/evidence")
    assert body["meta"]["status"] == "unavailable" and body["rows"] == []


def test_evidence_counts_hits_per_bucket(tmp_path, monkeypatch):
    """60 sessions: forward returns exist, AAA/NULLRS are hits every session in 0_2%."""
    from App.services import common, db, momentum
    import test_api_v2_helpers as h

    orig = h.sessions
    monkeypatch.setattr(h, "sessions", lambda last=h.LAST, n=60: orig(last, n))
    path = h.build_market_db(tmp_path / "m.duckdb")
    monkeypatch.setenv("MP_DB_PATH", str(path))
    monkeypatch.setenv("MP_HOLIDAYS_PATH", str(tmp_path / "none.json"))
    db.clear_cache()
    res = momentum.evidence(None)
    rows = {r["bucket"]: r for r in res.rows}
    assert res.status == "ok"
    b = rows["0_2%"]
    assert b["n_5"] > 0 and b["hit_rate_5"] == 100.0  # prices rise every session in the fixture
    assert b["n_20"] < b["n_5"]  # the last 20 sessions have no 20-session forward return
    assert rows["All hits"]["n_5"] == b["n_5"]
    assert rows["Below 10EMA"]["n_5"] == 0 and rows["Below 10EMA"]["hit_rate_5"] is None
    db.clear_cache()
