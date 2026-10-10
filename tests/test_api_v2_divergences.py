"""GET /api/v2/charts/{sym}/divergences and /api/v2/setups/divergences (HarkPro/12-sprint2-plan.md contract)."""
from __future__ import annotations

from datetime import date

import duckdb
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from App.indicators import rsi_divergence as rd
from test_api_v2_helpers import LAST, build_market_db

CONTRACT = {"side", "type", "p1_date", "p2_date", "p1_price", "p2_price", "p1_rsi", "p2_rsi", "confirm_date",
            "trigger_price", "stop_price", "status"}


def _series(seed: int, n: int = 480) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(end=pd.Timestamp(LAST), periods=n)
    ret = rng.normal(0, 0.018, n) + 0.004 * np.sin(np.arange(n) / 25)
    close = 100 * np.exp(np.cumsum(ret))
    spread = np.abs(rng.normal(0, 0.012, n)) * close
    return pd.DataFrame({"trade_date": days, "open_price": close, "high_price": close + spread,
                         "low_price": close - spread, "close_price": close})


@pytest.fixture()
def env(tmp_path, monkeypatch):
    market = build_market_db(tmp_path / "market.duckdb")
    con = duckdb.connect(str(market))
    frames = {}
    for sym, seed in (("AAA", 11), ("SMALL", 11)):  # SMALL (Rs 500 Cr) has the same bars but is outside the universe
        f = _series(seed).assign(symbol=sym, series="EQ", volume=1_000_000, turnover_cr=10.0, prev_close=None,
                                 delivery_qty=None, delivery_pct=None)
        frames[sym] = f
        con.execute("DELETE FROM prices_daily WHERE symbol = ?", [sym])
        con.register("_p", f)
        con.execute("INSERT INTO prices_daily BY NAME SELECT * FROM _p")
        con.unregister("_p")
    con.close()
    monkeypatch.setenv("MP_DB_PATH", str(market))
    monkeypatch.setenv("MP_USER_DB_PATH", str(tmp_path / "user.duckdb"))
    monkeypatch.setenv("MP_STATUS_PATH", str(tmp_path / "status.json"))
    monkeypatch.setenv("MP_HOLIDAYS_PATH", str(tmp_path / "no-holidays.json"))
    from App.services import common, db

    db.clear_cache()
    monkeypatch.setattr(common, "expected_session", lambda now=None, holidays=None: LAST)
    from App.api.v2 import create_app

    yield TestClient(create_app()), frames["AAA"]
    db.clear_cache()


def _get(client, url, status=200):
    r = client.get(url)
    assert r.status_code == status, (url, r.status_code, r.text[:400])
    return r.json()


def _engine_rows(f: pd.DataFrame, upto: date | None = None) -> list[tuple]:
    g = f[f.trade_date <= pd.Timestamp(upto)] if upto else f
    divs = rd.detect(g.high_price.to_numpy(), g.low_price.to_numpy(), g.close_price.to_numpy())
    dates = list(g.trade_date.dt.date)
    return [(d.side, d.type, dates[d.p1].isoformat(), dates[d.p2].isoformat(), dates[d.confirm].isoformat()) for d in divs]


@pytest.mark.parametrize("tf", ["D", "W", "M"])
def test_chart_divergences_envelope_and_contract(env, tf):
    client, _ = env
    body = _get(client, f"/api/v2/charts/AAA/divergences?tf={tf}")
    assert body["as_of"] == LAST.isoformat() and body["meta"]["status"] == "ok"
    assert body["meta"]["context"]["timeframe"] == tf and "rules" in body["meta"]["context"]
    for r in body["rows"]:
        assert CONTRACT <= set(r)
        assert r["side"] in rd.SIDES and r["type"] in rd.TYPES and r["status"] in rd.STATUSES and r["tf"] == tf
        assert r["p1_date"] < r["p2_date"] < r["confirm_date"] <= LAST.isoformat()
    confirms = [r["confirm_date"] for r in body["rows"]]
    assert confirms == sorted(confirms)


def test_chart_daily_matches_engine(env):
    client, f = env
    body = _get(client, "/api/v2/charts/AAA/divergences?tf=D")
    got = [(r["side"], r["type"], r["p1_date"], r["p2_date"], r["confirm_date"]) for r in body["rows"]]
    assert got == _engine_rows(f) and len(got) > 3


def test_chart_as_of_has_no_look_ahead(env):
    client, f = env
    full = _get(client, "/api/v2/charts/AAA/divergences?tf=D")["rows"]
    cut = f.trade_date.iloc[-20].date()  # indicators_daily (as_of resolution) holds the last 30 sessions
    part = _get(client, f"/api/v2/charts/AAA/divergences?tf=D&as_of={cut.isoformat()}")["rows"]
    key = lambda r: (r["side"], r["type"], r["p1_date"], r["p2_date"], r["confirm_date"], r["trigger_price"], r["stop_price"])  # noqa: E731
    assert [key(r) for r in part] == [key(r) for r in full if r["confirm_date"] <= cut.isoformat()]
    assert part, "fixture should have divergences before the cut"
    for r in part:  # status is as of the cut: a later trigger/failure is not visible yet
        assert r["status_date"] is None or r["status_date"] <= cut.isoformat()


def test_chart_bad_params(env):
    client, _ = env
    _get(client, "/api/v2/charts/AAA/divergences?tf=X", 422)
    _get(client, "/api/v2/charts/bad$sym/divergences", 422)
    body = _get(client, "/api/v2/charts/NOPE/divergences")
    assert body["meta"]["status"] == "unavailable" and body["rows"] == []


def test_setups_divergences_universe_and_filters(env):
    client, f = env
    body = _get(client, "/api/v2/setups/divergences?tf=D&window=60")
    syms = {r["symbol"] for r in body["rows"]}
    assert "SMALL" not in syms  # < Rs 1,000 Cr
    assert syms == {"AAA"}
    for r in body["rows"]:
        assert CONTRACT <= set(r)
        assert 0 <= r["bars_since_confirm"] < 60
        assert r["group"] == "Heavy Electrical" and r["industry"] == "Heavy Electrical"
        assert r["distance_to_trigger_pct"] == pytest.approx((r["trigger_price"] / r["close"] - 1) * 100, abs=0.02)
    n_bars = len(f)
    expected = [k for k, d in zip(_engine_rows(f), rd.detect(f.high_price, f.low_price, f.close_price))
                if n_bars - 1 - d.confirm < 60]
    assert sorted((r["side"], r["type"], r["p1_date"], r["p2_date"], r["confirm_date"]) for r in body["rows"]) == sorted(expected)
    counts = body["meta"]["context"]["counts"]
    assert sum(counts.values()) == len(body["rows"])

    bull = _get(client, "/api/v2/setups/divergences?tf=D&window=60&side=bull")["rows"]
    assert bull and all(r["side"] == "bull" for r in bull)
    some = _get(client, "/api/v2/setups/divergences?tf=D&window=60&types=Strong,hidden")["rows"]
    assert all(r["type"] in ("Strong", "Hidden") for r in some)
    one = _get(client, "/api/v2/setups/divergences?tf=D&window=1")["rows"]
    assert all(r["bars_since_confirm"] == 0 and r["confirm_date"] == LAST.isoformat() for r in one)


def test_setups_divergences_bad_params(env):
    client, _ = env
    _get(client, "/api/v2/setups/divergences?types=Huge", 422)
    _get(client, "/api/v2/setups/divergences?side=up", 422)
    _get(client, "/api/v2/setups/divergences?status=open", 422)
    _get(client, "/api/v2/setups/divergences?window=0", 422)
    body = _get(client, "/api/v2/setups/divergences?tf=W&window=20")
    assert body["meta"]["status"] == "ok"
