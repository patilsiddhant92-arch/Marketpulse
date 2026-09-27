"""Live-DB smoke for API v2 (read-only). Run: pytest -m realdb tests/test_api_v2_realdb.py

Uses MP_DB_PATH (or <repo>/Database/marketpulse.duckdb); the user DB is a temp copy.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.realdb


def _live_db() -> Path:
    env = os.environ.get("MP_DB_PATH", "").strip()
    return Path(env) if env else ROOT / "Database" / "marketpulse.duckdb"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_path = _live_db()
    if not db_path.exists():
        pytest.skip("live market DB not available")
    mp = pytest.MonkeyPatch()
    mp.setenv("MP_DB_PATH", str(db_path))
    user_src = db_path.parent / "marketpulse_user.duckdb"
    user_tmp = tmp_path_factory.mktemp("user") / "marketpulse_user.duckdb"
    if user_src.exists():
        shutil.copy(user_src, user_tmp)
    mp.setenv("MP_USER_DB_PATH", str(user_tmp))
    from App.api.v2 import create_app

    yield TestClient(create_app())
    mp.undo()


@pytest.mark.parametrize("url", [
    "/api/v2/market/health", "/api/v2/desk/queue/vcp", "/api/v2/screener/run?preset=stage2_leader",
    "/api/v2/groups/board?level=industry", "/api/v2/deals/session", "/api/v2/stock/RELIANCE",
    "/api/v2/stock/RELIANCE/bars?tf=W", "/api/v2/metrics/dictionary",
])
def test_live_endpoints_return_envelopes(client, url):
    r = client.get(url)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["returned"] == len(body["rows"]) <= body["total"]


def test_live_null_rs_and_delivery_stay_null(client):
    import duckdb

    with duckdb.connect(str(_live_db()), read_only=True) as con:
        row = con.execute(
            """
            SELECT symbol FROM indicators_daily
            WHERE trade_date = (SELECT max(trade_date) FROM indicators_daily)
              AND rs_percentile IS NULL AND delivery_pct IS NULL AND upper(symbol) <> 'TOTAL'
            LIMIT 1
            """
        ).fetchone()
    if row is None:
        pytest.skip("no NULL-RS/NULL-delivery symbol on the latest session")
    hdr = client.get(f"/api/v2/stock/{row[0]}").json()["rows"][0]
    assert hdr["rs_percentile"] is None and hdr["delivery_pct"] is None
