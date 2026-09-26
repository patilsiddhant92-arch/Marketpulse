from __future__ import annotations

import inspect

import pytest

from App.api import server


def test_momentum_sql_has_no_fabricated_coalesce():
    src = inspect.getsource(server.get_momentum_screener)
    assert "COALESCE(c.rs_percentile, 50)" not in src
    assert "COALESCE(c.delivery_pct, 45" not in src
    assert "COALESCE(c.away_10ema_pct, 0" not in src


@pytest.mark.realdb
def test_momentum_rs_matches_db_including_nulls():
    import duckdb
    from fastapi.testclient import TestClient
    body = TestClient(server.app).get("/api/screener/momentum", params={"cmp_gt_200": "false", "limit": 2000}).json()
    api_rs = {c["symbol"]: c["rs_percentile"] for c in body["candidates"]}
    assert api_rs, "momentum returned no rows"
    with duckdb.connect(str(server.DB_PATH), read_only=True) as con:
        db_rs = dict(con.execute(
            "SELECT symbol, rs_percentile FROM indicators_daily WHERE trade_date = (SELECT max(trade_date) FROM indicators_daily)"
        ).fetchall())
    for sym, rs in api_rs.items():
        expected = db_rs.get(sym)
        if expected is None:
            assert rs is None, f"{sym}: DB rs is NULL but API returned {rs}"
        else:
            assert rs == round(float(expected), 1), f"{sym}: {rs} != {expected}"
