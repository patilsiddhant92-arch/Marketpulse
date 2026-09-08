from __future__ import annotations

from datetime import date

import duckdb


def test_risk_off_prepare_is_downgraded_to_observe_in_read_model(tmp_path):
    from App.decision_read_model import load_decision_snapshot

    db_path = tmp_path / "marketpulse.duckdb"
    with duckdb.connect(str(db_path)) as db:
        db.execute(
            """
            CREATE TABLE candidate_daily (
                trade_date DATE, symbol TEXT, score_version TEXT,
                candidate_state TEXT, total_score DOUBLE, eligibility_status TEXT,
                market_cap_cr DOUBLE, market_regime TEXT, warning_reasons TEXT
            )
            """
        )
        db.execute(
            "INSERT INTO candidate_daily VALUES (?, 'AAA', 'focused-v2', 'Prepare', 82, 'eligible', 2500, 'Risk-Off', '')",
            [date(2026, 8, 17)],
        )

    snapshot = load_decision_snapshot(db_path, expected_date=date(2026, 8, 17))

    assert snapshot.market_gate == "Risk-Off"
    assert snapshot.eligible.iloc[0]["candidate_state"] == "Observe"
    assert "market_regime_risk_off" in snapshot.eligible.iloc[0]["warning_reasons"]


def test_geometry_outlier_is_invalidated_instead_of_presented_as_huge_rr():
    from Scripts.candidate_engine import calculate_risk_geometry

    geometry = calculate_risk_geometry(
        {
            "close_price": 100.0,
            "high_20d": 101.0,
            "low_10d": 99.0,
            "ema_20": 99.0,
            "high_50d": 1000.0,
        }
    )

    assert geometry["geometry_valid"] is False
    assert geometry["geometry_warning"] == "reward_to_risk_outlier"


def test_primary_relative_strength_requires_complete_history():
    from Scripts.indicators import rs_quarterly_mix
    import pandas as pd

    values = pd.Series([100.0] * 100)

    result = rs_quarterly_mix(values)

    assert result.isna().sum() > 0


def test_build_pipeline_uses_corrected_primary_semantics():
    from pathlib import Path

    source = Path("Scripts/build_database.py").read_text(encoding="utf-8")

    assert 'indicators["rs_percentile_primary"] = rs_score_no_fill' in source
    assert 'indicators["distance_to_high_pct"] = indicators["distance_to_high_pct_corrected"]' in source
    assert 'g["atr_pct_primary"] = g["atr_pct_wilder"]' in source


def test_adaptive_mixer_is_side_column_and_never_assigned_to_rs_percentile():
    from pathlib import Path

    source = Path("Scripts/build_database.py").read_text(encoding="utf-8")

    assert 'indicators["rs_percentile"] = indicators["rs_percentile_primary"]' in source
    assert 'indicators["rs_score_adaptive"]' in source
    assert 'indicators["rs_percentile_ipo"]' in source
    assert 'g["adr_20_pct"] = adr_pct' in source
    assert 'indicators["rs_rank_t5"]' in source
    assert 'indicators["rs_rank_t15"]' in source
    assert 'indicators["rs_rank_t30"]' in source
    assert 'indicators["rs_percentile"] = indicators["rs_score_adaptive"]' not in source
    assert 'indicators["rs_percentile"] = indicators["rs_percentile_ipo"]' not in source


def test_risk_off_prepare_policy_cannot_be_disabled():
    from pathlib import Path

    source = Path("Scripts/candidate_engine.py").read_text(encoding="utf-8")

    assert 'if candidate_state == "Prepare" and market_regime == "Risk-Off":' in source


def test_adr_pct_calculation():
    """ADR% measures average daily range percentage."""
    from Scripts.indicators import adr_pct
    import numpy as np
    import pandas as pd

    highs = pd.Series([105.0] * 20)
    lows = pd.Series([100.0] * 20)
    result = adr_pct(highs, lows, window=20)
    assert np.isclose(result.iloc[-1], 5.0)


def test_nr7_detection():
    """NR7 identifies narrowest range candle in last 7 sessions."""
    from Scripts.indicators import nr7
    import pandas as pd

    highs = pd.Series([105.0, 105.0, 105.0, 105.0, 105.0, 105.0, 101.0])
    lows = pd.Series([100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0])
    result = nr7(highs, lows, window=7)
    assert result.iloc[-1] == True
    assert result.iloc[5] == False


def test_rs_adaptive_mix_for_ipos():
    """IPOs and newer listings (<252 bars) receive a valid adaptive RS score instead of NaN."""
    from Scripts.indicators import rs_adaptive_mix
    import numpy as np
    import pandas as pd

    prices = pd.Series(np.linspace(100.0, 150.0, 100))
    result = rs_adaptive_mix(prices, min_periods=20)
    assert not np.isnan(result.iloc[-1])
    assert result.iloc[-1] > 0

