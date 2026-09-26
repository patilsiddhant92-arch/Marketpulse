from __future__ import annotations

import pytest

from App.api.server import parse_exposure_band, playbook_for_band


@pytest.mark.parametrize("raw,expected", [
    ("75% - 100%", (75.0, 100.0)),
    ("50% - 75%", (50.0, 75.0)),
    ("0% - 15%", (0.0, 15.0)),
    ("25%", (25.0, 25.0)),
    ("", (None, None)),
    (None, (None, None)),
    ("n/a", (None, None)),
])
def test_parse_exposure_band(raw, expected):
    assert parse_exposure_band(raw) == expected


def test_playbook_tiers_follow_band_low():
    assert playbook_for_band(75.0, 60.0)["action_bias"].startswith("Bullish")
    assert playbook_for_band(50.0, 45.0)["action_bias"].startswith("Selective")
    assert playbook_for_band(25.0, 30.0)["action_bias"].startswith("Defensive")
    assert playbook_for_band(0.0, 20.0)["action_bias"].startswith("Defensive")
    assert playbook_for_band(None, None)["action_bias"] == "Unknown — exposure inputs missing"


def test_selective_playbook_quotes_real_breadth_not_hardcoded_threshold():
    text = playbook_for_band(50.0, 45.3)["execution_playbook"]
    assert "45.3%" in text
    assert "sub-40%" not in text


@pytest.mark.realdb
def test_regime_band_matches_gate_and_sees_52w_lows():
    from fastapi.testclient import TestClient
    from App.api.server import app
    body = TestClient(app).get("/api/market/regime").json()
    gate = body["exposure_gate"]
    assert gate["band"] and "%" in gate["band"]
    assert gate["recommended_pct"] == gate["band_low"]
    assert "stage2_pool_count" in body["setups_summary"]
