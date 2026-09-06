"""Contract tests for Sector Rotation read-model integrity."""

from pathlib import Path
import pytest
from App.sector_read_model import query_sector_rotation_overview

DB_PATH = Path("Database/marketpulse.duckdb")


@pytest.mark.skipif(not DB_PATH.exists(), reason="Database not built")
def test_sector_rotation_contract_has_real_metrics():
    res = query_sector_rotation_overview(DB_PATH, level="Sector")
    assert res["as_of"] is not None
    assert res["total"] > 0
    df = res["leaderboard"]
    assert not df.empty

    # Top leaders must not be empty
    non_empty_leaders = df["top_leaders"].astype(str).str.strip().ne("")
    assert non_empty_leaders.sum() > 0, "Top leaders must be populated"

    # Rotation rank must be populated
    assert "rotation_rank" in df.columns
    assert df["rotation_rank"].notna().sum() > 0

    # Quadrants must include all expected states
    quads = res["quadrants"]
    assert "Leading" in quads
    assert "Improving" in quads
    assert "Weakening" in quads
    assert "Lagging" in quads
    total_in_quads = sum(len(v) for v in quads.values())
    assert total_in_quads == len(df), "All groups must be categorized into quadrants"
