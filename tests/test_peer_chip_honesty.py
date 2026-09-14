"""Peer chip must be stock RS rank within industry — not sector_rotation.rotation_rank."""
from __future__ import annotations

from pathlib import Path

from App.ui.desk_chrome import peer_chip_label, rotation_badge_class


def test_peer_chip_grammar():
    assert peer_chip_label("Lubricants", 5).endswith("#5")
    assert peer_chip_label("Energy", 2).endswith("#2")


def test_rotation_badge_classes_cover_states():
    assert "mp-state-leading" in rotation_badge_class("Leading")
    assert "mp-state-lagging" in rotation_badge_class("Lagging")
    assert "mp-state-emerging" in rotation_badge_class("Emerging")


def test_action_desk_peer_chip_uses_indicators_rs_rank_not_rotation_rank():
    src = Path("App/pages/action_desk.py").read_text(encoding="utf-8")
    assert "ind_rs_rank" in src
    assert "PARTITION BY m.industry" in src
    assert "peer_chip_label" in src
    # The SQL that builds the chip must rank indicators, not sector_rotation
    start = src.index("ind_rs_rank")
    window = src[start - 200 : start + 200]
    assert "FROM indicators_daily" in window or "indicators_daily" in src[start - 400 : start + 50]


def test_symbol_cell_prefers_peer_over_sector_badge():
    from App.ui.table import SYMBOL_CELL_SLOT

    assert "props.row.peer" in SYMBOL_CELL_SLOT
    assert "v-else-if=\"props.row.sector_badge\"" in SYMBOL_CELL_SLOT or "v-else-if='props.row.sector_badge'" in SYMBOL_CELL_SLOT or 'v-else-if="props.row.sector_badge"' in SYMBOL_CELL_SLOT
