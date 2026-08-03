from datetime import date

import pandas as pd


def test_risk_geometry_returns_valid_levels_and_reward_to_risk():
    from Scripts.candidate_engine import calculate_risk_geometry

    geometry = calculate_risk_geometry(
        {
            "close_price": 100.0,
            "high_20d": 103.0,
            "low_10d": 94.0,
            "ema_20": 96.0,
            "high_50d": 112.0,
        }
    )

    assert geometry["trigger_price"] == 103.0
    assert geometry["invalidation_price"] == 96.0
    assert geometry["first_resistance"] == 112.0
    assert geometry["initial_risk_pct"] > 0
    assert geometry["reward_to_risk"] > 0


def test_market_gate_uses_breadth_and_index_context():
    from Scripts.candidate_engine import classify_market_gate

    state = classify_market_gate(
        {"breadth_state": "Broad", "advance_pct": 65, "above_50ema_pct": 70, "above_200ema_pct": 60},
        pd.DataFrame([{"index_name": "Nifty 500", "trend_state": "Constructive"}]),
        pd.DataFrame([{"rotation_state": "Leading"}]),
    )

    assert state == "Constructive"


def test_candidate_total_is_reproducible_and_vcp_is_not_double_counted():
    from Scripts.candidate_engine import score_candidates

    indicators = pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "trade_date": date(2026, 8, 3),
                "close_price": 100.0,
                "high_20d": 103.0,
                "low_10d": 94.0,
                "ema_20": 96.0,
                "high_50d": 112.0,
                "rs_percentile": 90,
                "rs_1y_percentile": 85,
                "rs_3m_percentile": 88,
                "return_3m_pct": 12,
                "trend_score": 80,
                "contraction_score": 70,
                "volume_dryup_score": 60,
                "pivot_proximity_score": 75,
                "vcp_score": 100,
                "avg_traded_value_cr_20d": 50,
                "atr_pct": 3,
                "close_location_pct": 80,
                "volume": 100000,
                "avg_volume_20d": 90000,
                "delivery_pct": 55,
                "avg_delivery_pct_20d": 45,
                "ema_stack_bullish": True,
                "near_52w_high": True,
                "sector": "Technology",
                "industry": "Software",
            }
        ]
    )
    breadth = pd.DataFrame([{"trade_date": date(2026, 8, 3), "breadth_state": "Broad", "advance_pct": 65, "above_50ema_pct": 70, "above_200ema_pct": 60}])
    rotations = pd.DataFrame([{"trade_date": date(2026, 8, 3), "group_name": "Technology", "level": "sector", "rotation_state": "Leading", "rotation_score": 80}])
    master = pd.DataFrame([{"symbol": "AAA", "market_cap_cr": 5000, "sector": "Technology", "industry": "Software"}])
    index_features = pd.DataFrame([{"trade_date": date(2026, 8, 3), "index_name": "Nifty 500", "trend_state": "Constructive"}])

    result = score_candidates(indicators, breadth, rotations, pd.DataFrame(), index_features, pd.DataFrame(), master, date(2026, 8, 3))
    row = result.iloc[0]

    assert row["score_version"] == "focused-v1"
    assert row["total_score"] == round(0.30 * row["leadership_score"] + 0.25 * row["setup_score"] + 0.20 * row["participation_score"] + 0.15 * row["context_score"] + 0.10 * row["risk_score"], 6)
    assert row["setup_score"] < 100
    assert row["trigger_price"] > row["invalidation_price"]
