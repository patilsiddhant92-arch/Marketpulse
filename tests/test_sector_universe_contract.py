from __future__ import annotations

import duckdb


def test_status_filter_can_be_strict_at_a_selected_taxonomy_level():
    from App.sector_read_model import filter_taxonomy_tree

    tree = [
        {
            "id": "Broad Sector|One",
            "level": "Broad Sector",
            "name": "One",
            "rotation_state": "Leading",
            "children": [
                {
                    "id": "Sector|A",
                    "level": "Sector",
                    "name": "A",
                    "rotation_state": "Lagging",
                    "children": [],
                },
                {
                    "id": "Sector|B",
                    "level": "Sector",
                    "name": "B",
                    "rotation_state": "Leading",
                    "children": [],
                },
            ],
        }
    ]

    filtered = filter_taxonomy_tree(tree, statuses={"Leading"}, level="Sector", status_mode="strict")

    assert filtered[0]["name"] == "One"
    assert [child["name"] for child in filtered[0]["children"]] == ["B"]

    branch = filter_taxonomy_tree(tree, statuses={"Leading"}, level="Sector", status_mode="branch")
    assert [child["name"] for child in branch[0]["children"]] == ["A", "B"]


def test_sector_data_contract_reports_missing_computed_metrics(tmp_path):
    from App.sector_read_model import query_sector_data_contract

    db_path = tmp_path / "marketpulse.duckdb"
    with duckdb.connect(str(db_path)) as db:
        db.execute("CREATE TABLE sector_rotation (trade_date DATE)")

    contract = query_sector_data_contract(db_path)

    assert contract["metrics_available"] is False
    assert contract["rotation_available"] is True
    assert contract["degraded"] is True


def test_sector_data_contract_treats_empty_computed_table_as_degraded(tmp_path):
    from App.sector_read_model import query_sector_data_contract

    db_path = tmp_path / "marketpulse.duckdb"
    with duckdb.connect(str(db_path)) as db:
        db.execute("CREATE TABLE sector_metrics_daily (trade_date DATE)")

    contract = query_sector_data_contract(db_path)

    assert contract["metrics_table_exists"] is True
    assert contract["metrics_available"] is False
    assert contract["degraded"] is True
