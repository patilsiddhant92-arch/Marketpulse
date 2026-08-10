from __future__ import annotations


def test_policy_has_explicit_swing_universe_thresholds():
    from Scripts.decision_policy import DecisionPolicy

    policy = DecisionPolicy()

    assert policy.score_version == "focused-v2"
    assert policy.min_market_cap_cr == 1000.0
    assert policy.min_avg_traded_value_cr_20d == 10.0
    assert policy.max_initial_risk_pct == 8.0
    assert policy.min_reward_to_risk == 1.5


def test_market_cap_gate_blocks_below_threshold_and_missing_values():
    from Scripts.decision_policy import DecisionPolicy, evaluate_candidate_eligibility

    policy = DecisionPolicy()
    eligible = evaluate_candidate_eligibility(
        {
            "market_cap_cr": 1000.0,
            "avg_traded_value_cr_20d": 25.0,
            "band": 10.0,
            "initial_risk_pct": 5.0,
            "reward_to_risk": 2.0,
            "distance_to_trigger_pct": 2.0,
        },
        policy,
    )
    low = evaluate_candidate_eligibility({"market_cap_cr": 999.99}, policy)
    missing = evaluate_candidate_eligibility({"market_cap_cr": None}, policy)

    assert eligible.eligible is True
    assert "market_cap_below_minimum" in low.blocking_reasons
    assert low.eligible is False
    assert "market_cap_missing" in missing.blocking_reasons
    assert missing.eligible is False


def test_missing_risk_geometry_is_a_blocker_not_a_synthetic_trade_plan():
    from Scripts.decision_policy import DecisionPolicy, evaluate_candidate_eligibility

    result = evaluate_candidate_eligibility(
        {
            "market_cap_cr": 2500.0,
            "avg_traded_value_cr_20d": 25.0,
            "band": 10.0,
            "initial_risk_pct": None,
            "reward_to_risk": None,
            "distance_to_trigger_pct": None,
        },
        DecisionPolicy(),
    )

    assert result.eligible is False
    assert "risk_geometry_missing" in result.blocking_reasons
    assert "reward_to_risk_below_minimum" in result.blocking_reasons
