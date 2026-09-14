"""STEP2 Leading themes must never include Lagging/Weakening."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from App.sector_read_model import LEADING_ROTATION_STATES, leading_themes_from_board


def test_leading_themes_drop_lagging_even_with_positive_delta():
    board = pd.DataFrame(
        [
            {"group_name": "Oil", "rotation_state": "Lagging", "turnover_share_delta_5d": 2.5},
            {"group_name": "Banks", "rotation_state": "Leading", "turnover_share_delta_5d": 1.2},
            {"group_name": "Auto", "rotation_state": "Emerging", "turnover_share_delta_5d": 0.8},
            {"group_name": "IT", "rotation_state": "Leading", "turnover_share_delta_5d": -0.3},
            {"group_name": "Pharma", "rotation_state": "Weakening", "turnover_share_delta_5d": 3.0},
        ]
    )
    out = leading_themes_from_board(board, limit=4)
    names = out["group_name"].tolist()
    assert names == ["Banks", "Auto"]
    assert set(out["rotation_state"]) <= LEADING_ROTATION_STATES
    assert (out["turnover_share_delta_5d"] > 0).all()


def test_action_desk_imports_shared_leading_helper():
    text = Path("App/pages/action_desk.py").read_text(encoding="utf-8")
    assert "leading_themes_from_board" in text
    # Must not take raw board.head for STEP2 themes
    assert "leading_themes_from_board(board" in text
