"""Tests for Sector Intel 2.0 Read Model and UI integration."""

from pathlib import Path
import pytest
from App.sector_read_model import (
    LEVEL_COLUMNS,
    query_sector_breadth_divergence,
    query_sector_deep_dive,
    query_sector_52w_highs_overview,
    query_sector_rotation_overview,
    query_sector_turnover_overview,
)


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


@pytest.mark.skipif(not DB_PATH.exists(), reason="Database not built")
def test_query_sector_turnover_overview():
    df = query_sector_turnover_overview(DB_PATH, level="Sector")
    assert not df.empty
    assert "turnover_1d_cr" in df.columns
    assert "turnover_share_pct" in df.columns
    assert "turnover_expansion" in df.columns
    assert "turnover_surge" in df.columns
    assert df["turnover_1d_cr"].sum() > 0


@pytest.mark.skipif(not DB_PATH.exists(), reason="Database not built")
def test_query_sector_52w_highs_overview():
    df = query_sector_52w_highs_overview(DB_PATH, level="Sector")
    assert not df.empty
    assert "near_52w_count" in df.columns
    assert "high_density_pct" in df.columns
    assert "total_stocks" in df.columns
    assert df["total_stocks"].sum() > 0


@pytest.mark.skipif(not DB_PATH.exists(), reason="Database not built")
def test_query_sector_breadth_divergence():
    df = query_sector_breadth_divergence(DB_PATH, level="Sector")
    assert not df.empty
    assert "return_5d_pct" in df.columns
    assert "breadth_50" in df.columns
    assert "breadth_200" in df.columns
    assert "divergence_status" in df.columns

