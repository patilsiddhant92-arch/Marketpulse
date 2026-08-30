from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd

from App.sector_read_model import (
    build_taxonomy_tree,
    filter_taxonomy_tree,
    query_taxonomy_hierarchy,
)


def _find(nodes: list[dict], level: str, name: str) -> dict:
    for node in nodes:
        if node["level"] == level and node["name"] == name:
            return node
        found = _find(node.get("children", []), level, name)
        if found:
            return found
    return {}


def test_build_taxonomy_tree_uses_strict_nse_parent_order() -> None:
    paths = pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "security_name": "Alpha Auto",
                "market_cap_cr": 2_000.0,
                "broad_sector": "Consumer Discretionary",
                "sector": "Automobile and Auto Components",
                "broad_industry": "Auto Components",
                "industry": "Auto Components & Equipments",
            },
            {
                "symbol": "BBB",
                "security_name": "Beta Battery",
                "market_cap_cr": 1_500.0,
                "broad_sector": "Consumer Discretionary",
                "sector": "Automobile and Auto Components",
                "broad_industry": "Auto Components",
                "industry": "Auto Components & Equipments",
            },
            {
                "symbol": "CCC",
                "security_name": "Cloud Systems",
                "market_cap_cr": 3_000.0,
                "broad_sector": "Information Technology",
                "sector": "Information Technology",
                "broad_industry": "IT - Software",
                "industry": "Computers - Software & Consulting",
            },
        ]
    )
    metrics = pd.DataFrame(
        [
            {
                "level": "Broad Sector",
                "group_name": "Consumer Discretionary",
                "rotation_state": "Weakening",
                "rs_percentile": 55.0,
                "rotation_rank": 4,
            },
            {
                "level": "Sector",
                "group_name": "Automobile and Auto Components",
                "rotation_state": "Leading",
                "rs_percentile": 88.0,
                "rotation_rank": 1,
            },
            {
                "level": "Broad Industry",
                "group_name": "Auto Components",
                "rotation_state": "Emerging",
                "rs_percentile": 72.0,
                "rotation_rank": 2,
            },
            {
                "level": "Industry",
                "group_name": "Auto Components & Equipments",
                "rotation_state": "Improving",
                "rs_percentile": 69.0,
                "rotation_rank": 3,
            },
        ]
    )

    tree = build_taxonomy_tree(paths, metrics)

    assert [node["name"] for node in tree] == [
        "Consumer Discretionary",
        "Information Technology",
    ]
    auto_sector = _find(tree, "Sector", "Automobile and Auto Components")
    auto_broad_industry = _find(tree, "Broad Industry", "Auto Components")
    auto_industry = _find(tree, "Industry", "Auto Components & Equipments")
    assert auto_sector["parent_name"] == "Consumer Discretionary"
    assert auto_broad_industry["parent_name"] == "Automobile and Auto Components"
    assert auto_industry["parent_name"] == "Auto Components"
    assert auto_sector["rotation_state"] == "Leading"
    assert auto_industry["stock_count"] == 2
    assert [child["name"] for child in auto_industry["children"]] == ["AAA", "BBB"]
    assert all(child["level"] == "Stock" for child in auto_industry["children"])


def test_status_filter_keeps_ancestors_and_the_matching_branch() -> None:
    tree = [
        {
            "id": "Broad Sector|Consumer",
            "level": "Broad Sector",
            "name": "Consumer",
            "rotation_state": "Weakening",
            "children": [
                {
                    "id": "Sector|Auto",
                    "level": "Sector",
                    "name": "Auto",
                    "rotation_state": "Leading",
                    "children": [
                        {
                            "id": "Industry|Parts",
                            "level": "Industry",
                            "name": "Parts",
                            "rotation_state": "Improving",
                            "children": [
                                {
                                    "id": "Stock|AAA",
                                    "level": "Stock",
                                    "name": "AAA",
                                    "rotation_state": "",
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
                {
                    "id": "Sector|Retail",
                    "level": "Sector",
                    "name": "Retail",
                    "rotation_state": "Lagging",
                    "children": [],
                },
            ],
        }
    ]

    filtered = filter_taxonomy_tree(tree, statuses={"Leading"})

    assert [node["name"] for node in filtered] == ["Consumer"]
    assert [node["name"] for node in filtered[0]["children"]] == ["Auto"]
    assert _find(filtered, "Stock", "AAA")["name"] == "AAA"
    assert not _find(filtered, "Sector", "Retail")


def test_market_cap_floor_filters_stock_leaves_not_taxonomy_groups(tmp_path) -> None:
    db_path = tmp_path / "taxonomy.duckdb"
    with duckdb.connect(str(db_path)) as db:
        db.execute(
            """
            CREATE TABLE stocks_master (
                symbol TEXT, security_name TEXT, market_cap_cr DOUBLE,
                broad_sector TEXT, sector TEXT, broad_industry TEXT, industry TEXT
            )
            """
        )
        db.execute(
            """
            INSERT INTO stocks_master VALUES
              ('AAA', 'Alpha Auto', 1500, 'Consumer', 'Auto', 'Components', 'Parts'),
              ('BBB', 'Beta Auto', 500, 'Consumer', 'Auto', 'Components', 'Parts')
            """
        )
        db.execute(
            """
            CREATE TABLE sector_rotation (
                trade_date DATE, level TEXT, group_name TEXT,
                rotation_state TEXT, rs_percentile DOUBLE, rotation_rank INTEGER
            )
            """
        )
        db.execute(
            """
            INSERT INTO sector_rotation VALUES
              (?, 'Broad Sector', 'Consumer', 'Leading', 90, 1),
              (?, 'Sector', 'Auto', 'Emerging', 80, 1),
              (?, 'Broad Industry', 'Components', 'Improving', 70, 1),
              (?, 'Industry', 'Parts', 'Leading', 85, 1)
            """,
            [date(2026, 8, 14)] * 4,
        )

    tree = query_taxonomy_hierarchy(db_path, min_mcap=1_000)

    parts = _find(tree, "Industry", "Parts")
    assert parts["stock_count"] == 2
    assert parts["eligible_stock_count"] == 1
    assert [child["name"] for child in parts["children"]] == ["AAA"]
