"""Taxonomy navigator: grain flatness + Leading→Lagging sort."""
from __future__ import annotations

from App.pages.research.sector_board import (
    STATE_SORT_ORDER,
    _prune_taxonomy_for_grain,
    _sort_taxonomy_by_state,
)


def _node(level: str, name: str, state: str, children=None):
    return {
        "id": f"{level}:{name}",
        "level": level,
        "name": name,
        "rotation_state": state,
        "stock_count": 1,
        "children": children or [],
    }


def test_sort_taxonomy_leading_before_lagging():
    nodes = [
        _node("Broad Industry", "Zulu", "Lagging"),
        _node("Broad Industry", "Alpha", "Leading"),
        _node("Broad Industry", "Beta", "Emerging"),
    ]
    ordered = _sort_taxonomy_by_state(nodes)
    assert [n["name"] for n in ordered] == ["Alpha", "Beta", "Zulu"]
    assert STATE_SORT_ORDER["Leading"] < STATE_SORT_ORDER["Emerging"] < STATE_SORT_ORDER["Lagging"]


def test_prune_broad_industry_is_flat_not_twelve_sectors():
    tree = [
        _node(
            "Broad Sector",
            "Energy",
            "Leading",
            [
                _node("Broad Industry", "Oil", "Leading"),
                _node("Broad Industry", "Consumable Fuels", "Emerging"),
            ],
        ),
        _node(
            "Broad Sector",
            "Consumer Discretionary",
            "Lagging",
            [
                _node("Broad Industry", "Auto Components", "Lagging"),
            ],
        ),
    ]
    pruned = _prune_taxonomy_for_grain(tree, "Broad Industry")
    assert all(n["level"] == "Broad Industry" for n in pruned)
    assert [n["name"] for n in pruned] == ["Oil", "Consumable Fuels", "Auto Components"]
