"""P1 Morning honesty: gate single-owner + brief fields + health default."""
from __future__ import annotations

from Scripts.desk_contract import EXPOSURE_RULES, brief_fields_from_gate, match_exposure


def test_brief_fields_mirror_gate_pct_and_state():
    gate = match_exposure(
        {
            "adv_pct": 36.0,
            "ab20_pct": 36.0,
            "ab200_pct": 38.0,
            "vix": 12.0,
            "vix_spike": False,
            "net_lows_expanding": True,
            "count_52w_lows": 138,
            "count_52w_highs": 67,
            "vix_1d_pct": 4.0,
        }
    )
    brief = brief_fields_from_gate(gate)
    assert brief["exposure_pct"] == gate["pct"]
    assert brief["exposure_state"] == gate["state"]
    assert gate["pct"] in brief["posture_title"]
    assert gate["state"] in brief["posture_title"]
    # Must not resurrect the old Overview-only 25–40% band wording
    assert "25% – 40%" not in brief["posture_title"]
    assert "60% – 75% Cash" not in brief["posture_title"]


def test_brief_fields_cover_every_exposure_rule_id():
    for rule in EXPOSURE_RULES:
        brief = brief_fields_from_gate(
            {"id": rule["id"], "pct": rule["pct"], "state": rule["state"], "guidance": rule["guidance"]}
        )
        assert brief["exposure_id"] == rule["id"]
        assert rule["pct"] in brief["posture_title"]
        assert "Cash" in brief["cash_recommendation"]


def test_market_health_strip_accepts_expanded_kwarg():
    import inspect
    from App.ui.market_health import render_market_health_strip

    sig = inspect.signature(render_market_health_strip)
    assert "expanded" in sig.parameters
    assert sig.parameters["expanded"].default is True
