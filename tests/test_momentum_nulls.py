from __future__ import annotations

import inspect

import pandas as pd
import pytest

from App.api import server


def test_momentum_sql_has_no_fabricated_coalesce():
    src = inspect.getsource(server.get_momentum_screener)
    assert "COALESCE(c.rs_percentile, 50)" not in src
    assert "COALESCE(c.delivery_pct, 45" not in src
    assert "COALESCE(c.away_10ema_pct, 0" not in src


def test_momentum_avg_rs_aggregate_no_fabricated_default():
    """Sector/industry avg_rs uses _opt_float(mean, 1), not _sanitize_float(mean).

    A group whose members are all NULL RS must report None, not a fabricated
    0.0 (or any other plausible-looking number).
    """
    src = inspect.getsource(server.get_momentum_screener)
    assert 'round(_sanitize_float(grp["rs_percentile"].mean())' not in src
    assert src.count('_opt_float(grp["rs_percentile"].mean(), 1)') == 2

    # Exercise the exact expression used in the endpoint (pandas mean + _opt_float),
    # without needing the DB or a running FastAPI app.
    all_null = pd.Series([float("nan"), float("nan"), float("nan")])
    assert server._opt_float(all_null.mean(), 1) is None

    mixed = pd.Series([50.0, float("nan"), 30.0])
    result = server._opt_float(mixed.mean(), 1)
    assert result == 40.0

    all_present = pd.Series([10.25, 20.75])
    assert server._opt_float(all_present.mean(), 1) == 15.5


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
