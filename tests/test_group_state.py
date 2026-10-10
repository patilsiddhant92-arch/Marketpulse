"""One group state across tabs (HarkPro/12-sprint2-plan.md, wiring).

Pulse owns Favour / Neutral / Caution (App/services/group_state.py, GET /api/v2/pulse/group-state).
Sector Intel and Setups read it, so the same group on the same date shows the same state on all three tabs.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from App.services import group_state as gs
from App.services import setups_logic as L

DB_PATH = Path("Database/marketpulse.duckdb")
AS_OF = "2026-08-13"
needs_db = pytest.mark.skipif(not DB_PATH.exists(), reason="Database not built")


# --------------------------------------------------------------------------- pure rule
def test_rule_is_the_tab2_rule_and_setups_reads_it():
    assert L.group_state is gs.rule
    assert (L.FAVOUR, L.NEUTRAL, L.CAUTION) == (gs.FAVOUR, gs.NEUTRAL, gs.CAUTION)
    st, why = gs.rule(a50=65, x21=2.0, x63=1.0, r5=1.0, sh5=1.0, sh20=1.0, ew=110, ew50=100)
    assert st == "Favour" and "65%" in why and "+2.0 pts" in why
    assert gs.rule(a50=65, x21=2.0, x63=1.0, r5=1.0, sh5=1.0, sh20=1.0, ew=90, ew50=100)[0] == "Neutral"
    assert gs.rule(a50=70, x21=3.0, x63=1.0, r5=-1.5, sh5=0.8, sh20=1.0, ew=110, ew50=100)[1].startswith("Money leaving")
    assert gs.rule(a50=30, x21=-1.0, x63=-4.0, r5=0.5, sh5=1.0, sh20=1.0, ew=90, ew50=100)[0] == "Caution"
    assert gs.rule(None, None, None, None, None, None, None, None) == ("Neutral", "Not enough group history.")
    assert gs.rule(float("nan"), 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)[0] == "Neutral"


def test_level_key_validates():
    assert gs.level_key("Broad Industry") == "broad_industry"
    with pytest.raises(ValueError):
        gs.level_key("planet")


def test_frame_counts_sessions_in_state(monkeypatch):
    class Con:
        def execute(self, sql, params):
            rows = []
            for i, d in enumerate(pd.bdate_range("2026-01-01", periods=4)):
                fav = i >= 2  # A turns Favour on day 3
                rows.append(dict(d=d, n="A", members=10, r5=1.0, r21=5.0 if fav else -5.0, r63=1.0, a50=70.0 if fav else 50.0,
                                 sh=1.0, sh5=1.0, sh20=1.0, ew=110.0, ew50=100.0))
                rows.append(dict(d=d, n="B", members=10, r5=1.0, r21=0.0, r63=1.0, a50=50.0, sh=1.0, sh5=1.0, sh20=1.0,
                                 ew=110.0, ew50=100.0))
            df = pd.DataFrame(rows)
            return type("R", (), {"df": lambda self: df})()

    out = gs._compute_frame(Con(), "industry", pd.Timestamp("2026-01-06").date())
    a = out[out.n == "A"].reset_index(drop=True)
    assert list(a.state) == ["Neutral", "Neutral", "Favour", "Favour"]
    assert list(a.in_state) == [1, 2, 1, 2]
    assert a.state_since.iloc[-1] == pd.Timestamp("2026-01-05")


# --------------------------------------------------------------------------- the three tabs agree (local DB)
@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from App.api.v2 import create_app
    return TestClient(create_app())


def _state_map(client, level: str) -> dict[str, tuple[str, str]]:
    r = client.get("/api/v2/pulse/group-state", params={"level": level, "as_of": AS_OF, "limit": 5000})
    assert r.status_code == 200
    j = r.json()
    assert j["as_of"] == AS_OF and j["total"] > 0
    assert j["meta"]["context"]["owner"] == "pulse"
    return {x["group_name"]: (x["state"], x["reason"]) for x in j["rows"]}


@needs_db
def test_endpoint_shape_and_filter(client):
    j = client.get("/api/v2/pulse/group-state", params={"level": "sector", "as_of": AS_OF}).json()
    row = j["rows"][0]
    assert row["id"] == f"sector:{row['group_name']}" and row["state"] in gs.STATES and row["reason"]
    assert row["sessions_in_state"] >= 1
    two = [x["group_name"] for x in j["rows"][:2]]
    f = client.get("/api/v2/pulse/group-state", params={"level": "sector", "as_of": AS_OF, "groups": "|".join(two)}).json()
    assert sorted(x["group_name"] for x in f["rows"]) == sorted(two)
    assert client.get("/api/v2/pulse/group-state", params={"level": "planet"}).status_code == 422


@needs_db
def test_pulse_groups_table_shows_the_shared_state(client):
    for level in ("sector", "industry"):
        shared = _state_map(client, level)
        rows = client.get("/api/v2/pulse/groups", params={"level": level, "as_of": AS_OF}).json()["rows"]
        assert rows
        for r in rows:
            assert (r["state"], r["state_reason"]) == shared[r["name"]], r["name"]


@needs_db
def test_sector_intel_board_shows_the_shared_state(client):
    for level in ("sector", "broad_industry", "industry"):
        shared = _state_map(client, level)
        rows = client.get("/api/v2/sectors/board", params={"level": level, "as_of": AS_OF, "limit": 5000}).json()["rows"]
        assert rows
        for r in rows:
            assert (r["state"], r["state_reason"]) == shared[r["group_name"]], r["group_name"]


@needs_db
def test_setups_board_shows_the_shared_state(client):
    shared = _state_map(client, "industry")
    j = client.get("/api/v2/setups/board", params={"as_of": AS_OF, "limit": 5000}).json()
    assert j["total"] > 0
    checked = 0
    for r in j["rows"]:
        if r.get("industry") in shared:
            assert (r["group_state"], r["group_reason"]) == shared[r["industry"]], r["symbol"]
            checked += 1
    assert checked > 50


@needs_db
def test_same_group_same_state_on_all_three_tabs(client):
    """Pick a group present on every tab and check the three tabs + the endpoint agree, word for word."""
    shared = _state_map(client, "industry")
    setups = client.get("/api/v2/setups/board", params={"as_of": AS_OF, "limit": 5000}).json()["rows"]
    board = {r["group_name"]: r for r in client.get("/api/v2/sectors/board", params={"level": "industry", "as_of": AS_OF,
                                                                                        "limit": 5000}).json()["rows"]}
    pulse = {r["name"]: r for r in client.get("/api/v2/pulse/groups", params={"level": "industry", "as_of": AS_OF}).json()["rows"]}
    common = [r["industry"] for r in setups if r.get("industry") in board and r.get("industry") in pulse]
    assert common
    for g in sorted(set(common))[:25]:
        s = next(r for r in setups if r.get("industry") == g)
        assert shared[g][0] == s["group_state"] == board[g]["state"] == pulse[g]["state"]
        assert shared[g][1] == s["group_reason"] == board[g]["state_reason"] == pulse[g]["state_reason"]


# --------------------------------------------------------------------------- Pulse movers (Charts source) regression
def test_mover_chips_ignore_unknown_listing_date():
    """A NaT listing date must not crash /pulse/movers (the Charts 'Pulse movers' source); it is not an IPO."""
    from datetime import date

    from App.services import pulse
    chips = pulse.chips_for({"symbol": "X", "listing_date": pd.NaT, "h52": None, "band": None}, date(2026, 10, 8), set())
    assert "IPO" not in chips
