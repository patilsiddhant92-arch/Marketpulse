"""Tests for Sector Intel 2.0 Read Model and UI integration."""

from pathlib import Path
import pytest
from App.sector_read_model import LEVEL_COLUMNS, query_sector_deep_dive, query_sector_rotation_overview


DB_PATH = Path("Database/marketpulse.duckdb")


@pytest.mark.skipif(not DB_PATH.exists(), reason="Database not built")
def test_query_sector_rotation_overview():
    res = query_sector_rotation_overview(DB_PATH, level="Sector")
    assert res["as_of"] is not None
    assert res["total"] > 0
    assert "quadrants" in res
    assert "Leading" in res["quadrants"]
    assert "Improving" in res["quadrants"]
    assert "Weakening" in res["quadrants"]
    assert "Lagging" in res["quadrants"]
    assert not res["heatmap"].empty
    assert "top_leaders" in res["heatmap"].columns
    assert "turnover_share_pct" in res["heatmap"].columns


@pytest.mark.skipif(not DB_PATH.exists(), reason="Database not built")
def test_query_sector_deep_dive():
    overview = query_sector_rotation_overview(DB_PATH, level="Sector")
    assert not overview["heatmap"].empty
    first_group = str(overview["heatmap"].iloc[0]["group_name"])

    deep = query_sector_deep_dive(DB_PATH, level="Sector", group_name=first_group, min_mcap=500.0)
    assert "group_stats" in deep
    assert "stocks" in deep
    assert not deep["stocks"].empty
    assert "symbol" in deep["stocks"].columns
    assert "rs_percentile" in deep["stocks"].columns
    assert "close_price" in deep["stocks"].columns


@pytest.mark.skipif(not DB_PATH.exists(), reason="Database not built")
def test_all_taxonomy_levels():
    for lvl in LEVEL_COLUMNS.keys():
        res = query_sector_rotation_overview(DB_PATH, level=lvl)
        assert res["total"] > 0
        assert not res["heatmap"].empty
