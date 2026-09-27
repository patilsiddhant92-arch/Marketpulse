"""GET /api/v2/stock/{sym}/darvas — historical Darvas boxes (same definition as the queues)."""
from __future__ import annotations

from datetime import date

import duckdb
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from Scripts.darvas_squeeze import calculate_darvas_box, darvas_box_segments
from test_api_v2_helpers import LAST, build_market_db, sessions

# Synthetic BOXY series (30 sessions). Hand-traced against the Pine definition (boxp 5):
#   0-9   flat base: high 101 / low 99 / close 100  -> no new highs, no box
#   10    new high 110 (low 104)                     -> NH = 110
#   11-13 inside: high 105 / low 102                 -> bar 13 confirms box 1: top 110, bottom min(low 9..13) = 99
#   14-15 inside                                     -> box 1 still open
#   16    close 112 (high 113, low 108)              -> box 1 broken_up at 16; NH = 113
#   17-19 high 112 / low 108 / close 110             -> bar 19 confirms box 2: top 113, bottom min(low 15..19) = 102
#   20-23 high 111 / low 104 / close 106             -> inside box 2
#   24    close 100 (high 105, low 99)               -> box 2 broken_down at 24
#   25-29 high 101 / low 97 / close 99               -> no new highs (k1 stays >= 105) -> no box 3
H = [101] * 10 + [110] + [105] * 5 + [113] + [112] * 3 + [111] * 4 + [105] + [101] * 5
L = [99] * 10 + [104] + [102] * 5 + [108] + [108] * 3 + [104] * 4 + [99] + [97] * 5
C = [100] * 10 + [107] + [104] * 5 + [112] + [110] * 3 + [106] * 4 + [100] + [99] * 5


def test_segments_match_hand_trace():
    segs = darvas_box_segments(H, L, C, boxp=5)
    assert [(s["formed_i"], s["top"], s["bottom"], s["status"], s["break_i"]) for s in segs] == [
        (13, 110.0, 99.0, "broken_up", 16),
        (19, 113.0, 102.0, "broken_down", 24),
    ]
    assert segs[0]["start_i"] == 10 and segs[0]["end_i"] == 16 and segs[0]["last_i"] == 18
    assert segs[1]["start_i"] == 16 and segs[1]["end_i"] == 24 and segs[1]["last_i"] == 29


def test_segments_share_the_queue_box_series():
    rng = np.random.default_rng(7)
    close = 100 + np.cumsum(rng.normal(0, 1.5, 400))
    high = close + rng.uniform(0.2, 2.0, 400)
    low = close - rng.uniform(0.2, 2.0, 400)
    top, bottom = calculate_darvas_box(high, low)
    segs = darvas_box_segments(high, low, close)
    assert segs, "random walk should form boxes"
    for s in segs:
        # Every box's range equals the queue's TopBox/BottomBox over its whole life.
        assert np.all(top[s["formed_i"]: s["last_i"] + 1] == s["top"])
        assert np.all(bottom[s["formed_i"]: s["last_i"] + 1] == s["bottom"])
    assert segs[-1]["status"] in ("active", "broken_up", "broken_down")
    assert all(s["status"] != "active" for s in segs[:-1])


def test_active_box_when_unbroken():
    segs = darvas_box_segments(H[:22], L[:22], C[:22])
    assert segs[-1]["status"] == "active" and segs[-1]["end_i"] == 21 and segs[-1]["break_i"] is None


@pytest.fixture()
def client(tmp_path, monkeypatch):
    market = build_market_db(tmp_path / "market.duckdb")
    days = sessions(LAST)
    frame = pd.DataFrame({
        "symbol": "BOXY", "series": "EQ", "trade_date": [pd.Timestamp(d) for d in days],
        "open_price": [float(c) for c in C], "high_price": [float(h) for h in H], "low_price": [float(v) for v in L],
        "close_price": [float(c) for c in C], "volume": 1_000_000,
    })
    # GAPPY = BOXY with every price from session 22 on divided by 3 (an unadjusted split / relisting).
    gappy = frame.copy()
    gappy["symbol"] = "GAPPY"
    for c in ("open_price", "high_price", "low_price", "close_price"):
        gappy.loc[22:, c] = gappy.loc[22:, c] / 3.0
    con = duckdb.connect(str(market))
    for name, f in (("_boxy", frame), ("_gappy", gappy)):
        con.register(name, f)
        con.execute(f"INSERT INTO prices_daily BY NAME SELECT * FROM {name}")
    con.execute("INSERT INTO indicators_daily BY NAME SELECT symbol, series, trade_date, open_price, high_price, "
                "low_price, close_price, volume FROM _gappy")
    con.close()
    monkeypatch.setenv("MP_DB_PATH", str(market))
    monkeypatch.setenv("MP_USER_DB_PATH", str(tmp_path / "user.duckdb"))
    monkeypatch.setenv("MP_STATUS_PATH", str(tmp_path / "status.json"))
    monkeypatch.setenv("MP_HOLIDAYS_PATH", str(tmp_path / "no_holidays.json"))
    from App.services import common, db

    db.clear_cache()
    monkeypatch.setattr(common, "expected_session", lambda now=None, holidays=None: LAST)
    from App.api.v2 import create_app

    yield TestClient(create_app()), days
    db.clear_cache()


def test_endpoint_returns_known_boxes(client):
    c, days = client
    body = c.get("/api/v2/stock/BOXY/darvas").json()
    assert body["meta"]["status"] == "ok"
    rows = body["rows"]
    assert len(rows) == 2
    b1, b2 = rows
    assert (b1["top"], b1["bottom"], b1["status"]) == (110.0, 99.0, "broken_up")
    assert b1["start_date"] == days[10].isoformat() and b1["formed_date"] == days[13].isoformat()
    assert b1["end_date"] == b1["break_date"] == days[16].isoformat() and b1["break_close"] == 112.0
    assert (b2["top"], b2["bottom"], b2["status"], b2["break_date"]) == (113.0, 102.0, "broken_down", days[24].isoformat())


def test_endpoint_is_point_in_time(client):
    c, days = client
    rows = c.get(f"/api/v2/stock/BOXY/darvas?as_of={days[21].isoformat()}").json()["rows"]
    assert [r["status"] for r in rows] == ["broken_up", "active"]
    assert rows[-1]["end_date"] == days[21].isoformat() and rows[-1]["break_date"] is None
    rows = c.get(f"/api/v2/stock/BOXY/darvas?as_of={days[12].isoformat()}").json()["rows"]
    assert rows == []


def test_endpoint_limit_window_and_other_timeframes(client):
    c, _days = client
    rows = c.get("/api/v2/stock/BOXY/darvas?limit=8").json()["rows"]
    assert len(rows) == 1 and rows[0]["top"] == 113.0  # box 1's life ended before the last 8 bars
    for tf in ("W", "M"):
        r = c.get(f"/api/v2/stock/BOXY/darvas?tf={tf}")
        assert r.status_code == 200 and r.json()["meta"]["status"] == "ok"
    assert c.get("/api/v2/stock/NOPE/darvas").json()["meta"]["status"] == "unavailable"
    assert c.get("/api/v2/stock/BOXY/darvas?tf=X").status_code == 422


def test_boxes_never_span_an_unexplained_gap(client):
    c, days = client
    body = c.get("/api/v2/stock/GAPPY/darvas").json()
    assert body["meta"]["status"] == "ok"
    rows = body["rows"]
    # Box 1 is untouched; box 2 (open at the gap) is cut at the last pre-gap session, and no box straddles it.
    assert [(r["top"], r["status"]) for r in rows[:2]] == [(110.0, "broken_up"), (113.0, "superseded")]
    assert rows[1]["end_date"] == days[21].isoformat() and rows[1]["break_date"] is None
    gap = days[22].isoformat()
    assert all(r["end_date"] < gap or r["start_date"] >= gap for r in rows)
    assert any("gap" in n for n in body["meta"].get("notes", []))
