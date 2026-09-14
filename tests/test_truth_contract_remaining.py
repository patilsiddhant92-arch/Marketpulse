"""Truth-contract #3–#5: near_pivot key, board filter stats, UC flag helpers."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from Scripts.desk_contract import QUEUE_DISPLAY_CAPS, QUEUE_META


def test_queue_key_vcp_is_primary_not_near_pivot() -> None:
    from Scripts.desk_contract import QUEUE_META
    assert "vcp" in QUEUE_META
    assert "near_pivot" not in QUEUE_META
    assert QUEUE_META["vcp"]["tv_key"] == "vcp"
    assert QUEUE_META["vcp"]["tier"] == "primary"


def test_action_desk_queue_dict_only_three() -> None:
    from pathlib import Path
    src = Path("App/pages/action_desk.py").read_text(encoding="utf-8")
    assert '"vcp": vcp_df' in src or '"vcp":' in src
    assert '"near_pivot": vcp_df' not in src
    assert "MORE SETUPS" not in src


def test_rotation_board_filter_stats_shape(tmp_path):
    from App.sector_read_model import rotation_board_filter_stats

    # Empty / missing DB returns zeros
    stats = rotation_board_filter_stats(tmp_path / "missing.duckdb", level="Broad Industry")
    assert stats["total"] == 0
    assert stats["shown"] == 0
    assert stats["hidden"] == 0


def test_uc_flag_label():
    from App.indicators.uc_thrust import uc_flag_label

    assert uc_flag_label(8.5) == "UC~8.5"
    assert uc_flag_label(None) == "—"


def test_sector_board_shows_filter_honesty_copy():
    src = Path("App/pages/research/sector_board.py").read_text(encoding="utf-8")
    assert "rotation_board_filter_stats" in src
    assert "Money board:" in src
    assert "hidden" in src
