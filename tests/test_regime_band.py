from __future__ import annotations

import pytest

from App.api.server import gate_inputs_from, parse_exposure_band, playbook_for_band, vix_payload
from App.pages.action_desk import compute_exposure_gate


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


def test_gate_inputs_from_keeps_missing_breadth_as_none():
    """A NULL breadth column must stay None going into the gate, never fabricated as 50.0."""
    args = gate_inputs_from({"adv_pct": None, "ab20_pct": 80.0, "ab50_pct": None, "ab200_pct": 80.0})
    assert args["adv_pct"] is None
    assert args["ab50_pct"] is None
    assert args["ab20_pct"] == 80.0
    assert args["ab200_pct"] == 80.0


def test_gate_inputs_from_feeds_none_to_risk_off_band():
    """None adv_pct must fail the gate closed (risk_off / 0%-15%), not read as a neutral 50%."""
    args = gate_inputs_from({"adv_pct": None, "ab20_pct": 80.0, "ab50_pct": None, "ab200_pct": 80.0})
    gate = compute_exposure_gate(
        adv_pct=args["adv_pct"],
        ab20_pct=args["ab20_pct"],
        ab200_pct=args["ab200_pct"],
        vix=10.0,
        vix_1d_pct=0.0,
        net_lows_expanding=False,
        count_52w_highs=0,
        count_52w_lows=0,
    )
    assert gate["id"] == "risk_off"
    assert parse_exposure_band(gate["pct"]) == (0.0, 15.0)


def test_vix_payload_missing_stays_none_not_zero():
    """Missing VIX must never render as a fabricated 0.00 'Low Risk' reading."""
    payload = vix_payload(None, None)
    assert payload == {"current": None, "change_1d_pct": None, "tone": None}


def test_vix_payload_nan_also_stays_none():
    payload = vix_payload(float("nan"), float("nan"))
    assert payload["current"] is None
    assert payload["change_1d_pct"] is None
    assert payload["tone"] is None


def test_vix_payload_low_risk_tone():
    payload = vix_payload(12.2, -1.5)
    assert payload["current"] == 12.2
    assert payload["change_1d_pct"] == -1.5
    assert payload["tone"] == "Low Risk"


def test_vix_payload_moderate_and_high_risk_tone():
    assert vix_payload(17.0, 0.0)["tone"] == "Moderate"
    assert vix_payload(25.0, 0.0)["tone"] == "High Risk"


@pytest.mark.realdb
def test_regime_band_matches_gate_and_sees_52w_lows():
    from fastapi.testclient import TestClient
    from App.api.server import app
    body = TestClient(app).get("/api/market/regime").json()
    gate = body["exposure_gate"]
    assert gate["band"] and "%" in gate["band"]
    assert gate["recommended_pct"] == gate["band_low"]
    assert "stage2_pool_count" in body["setups_summary"]
