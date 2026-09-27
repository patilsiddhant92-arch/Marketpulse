"""score_candidates must match a stock's sector to the sector_rotation row at the
*Sector* level. sector_rotation carries one row per (level, group_name) and the same
name can exist at several levels (e.g. "Chemicals" as both a Sector and an Industry);
matching on group_name alone picks whichever row comes first, so the output depended on
input row order."""
from datetime import date

import pandas as pd

AS_OF = date(2026, 8, 3)


def _inputs():
    indicators = pd.DataFrame([{
        "symbol": "AAA", "trade_date": AS_OF, "close_price": 100.0, "high_20d": 103.0, "low_10d": 94.0,
        "ema_20": 96.0, "high_50d": 112.0, "rs_percentile": 90, "return_63d_pct": 12, "trend_score": 80,
        "contraction_score": 70, "volume_dryup_score": 60, "pivot_proximity_score": 75,
        "avg_traded_value_cr_20d": 50, "atr_pct": 3, "sector": "Chemicals", "industry": "Chemicals",
    }])
    breadth = pd.DataFrame([{"trade_date": AS_OF, "breadth_state": "Broad", "advance_pct": 65,
                             "above_50ema_pct": 70, "above_200ema_pct": 60}])
    rotations = pd.DataFrame([
        {"trade_date": AS_OF, "level": "Broad Sector", "group_name": "Chemicals", "rotation_state": "Lagging",
         "rotation_score": 5, "return_63d_pct": -40.0},
        {"trade_date": AS_OF, "level": "Sector", "group_name": "Chemicals", "rotation_state": "Leading",
         "rotation_score": 90, "return_63d_pct": 10.0},
        {"trade_date": AS_OF, "level": "Industry", "group_name": "Chemicals", "rotation_state": "Weakening",
         "rotation_score": 20, "return_63d_pct": 30.0},
    ])
    master = pd.DataFrame([{"symbol": "AAA", "market_cap_cr": 5000, "sector": "Chemicals", "industry": "Chemicals"}])
    index_features = pd.DataFrame([{"trade_date": AS_OF, "index_name": "Nifty 50", "trend_state": "Constructive",
                                    "return_63d_pct": 5.0}])
    return indicators, breadth, rotations, master, index_features


def _score(rotations):
    from Scripts.candidate_engine import score_candidates

    indicators, breadth, _, master, index_features = _inputs()
    return score_candidates(indicators, breadth, rotations, pd.DataFrame(), index_features, pd.DataFrame(), master, AS_OF)


def test_same_group_name_at_two_levels_uses_sector_level():
    _, _, rotations, _, _ = _inputs()
    row = _score(rotations).iloc[0]
    assert row["sector_state"] == "Leading"
    # context = mean(gate, sector rotation_score, state bonus) -> uses the Sector row's 90
    sector_only = _score(rotations[rotations["level"] == "Sector"]).iloc[0]
    for col in ("sector_state", "context_score", "leadership_score", "total_score"):
        assert row[col] == sector_only[col], col


def test_output_is_independent_of_rotation_row_order():
    _, _, rotations, _, _ = _inputs()
    cols = ["sector_state", "context_score", "leadership_score", "total_score"]
    base = _score(rotations)[cols]
    for seed in range(6):
        shuffled = rotations.sample(frac=1.0, random_state=seed).reset_index(drop=True)
        pd.testing.assert_frame_equal(_score(shuffled)[cols], base)


def test_level_label_match_is_case_and_separator_insensitive():
    _, _, rotations, _, _ = _inputs()
    lowered = rotations.assign(level=rotations["level"].str.lower().str.replace(" ", "_"))
    assert _score(lowered).iloc[0]["sector_state"] == "Leading"


def test_rotations_without_level_column_still_match_on_name():
    _, _, rotations, _, _ = _inputs()
    legacy = rotations[rotations["level"] == "Sector"].drop(columns=["level"])
    assert _score(legacy).iloc[0]["sector_state"] == "Leading"
