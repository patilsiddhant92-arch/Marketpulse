"""Tests for Next-Gen Tech Thematic Megatrend Read Model."""

from pathlib import Path
import pytest
from App.thematic_read_model import (
    NEXTGEN_TECH_UNIVERSE,
    get_all_thematic_symbols,
    get_symbol_thematic_metadata,
    query_thematic_constituents,
    query_thematic_overview,
)


DB_PATH = Path("Database/marketpulse.duckdb")


def test_thematic_universe_integrity():
    symbols = get_all_thematic_symbols()
    assert len(symbols) >= 60
    assert len(NEXTGEN_TECH_UNIVERSE) == 8
    assert "Silicon & Chip Design" in NEXTGEN_TECH_UNIVERSE
    assert "Compute & AI Servers" in NEXTGEN_TECH_UNIVERSE
    assert "Batteries & Backup Power" in NEXTGEN_TECH_UNIVERSE
    assert "Cooling & Precision HVAC" in NEXTGEN_TECH_UNIVERSE

    pillar, role = get_symbol_thematic_metadata("MOSCHIP")
    assert pillar == "Silicon & Chip Design"
    assert "ASIC" in role

    pillar_net, role_net = get_symbol_thematic_metadata("NETWEB")
    assert pillar_net == "Compute & AI Servers"
    assert "Nvidia" in role_net


@pytest.mark.skipif(not DB_PATH.exists(), reason="Database not built")
def test_query_thematic_overview():
    overview = query_thematic_overview(DB_PATH)
    assert overview["as_of"] is not None
    assert overview["total_stocks"] >= 60
    assert len(overview["pillars"]) == 8

    first_pillar = overview["pillars"][0]
    assert "pillar_name" in first_pillar
    assert "avg_rs" in first_pillar
    assert "top_symbols" in first_pillar
    assert len(first_pillar["top_symbols"]) > 0


@pytest.mark.skipif(not DB_PATH.exists(), reason="Database not built")
def test_query_thematic_constituents():
    df = query_thematic_constituents(DB_PATH, limit=30)
    assert not df.empty
    assert "symbol" in df.columns
    assert "pillar" in df.columns
    assert "role_desc" in df.columns
    assert "rs_percentile" in df.columns
    assert "close_price" in df.columns

    # Test filtering by specific sub-pillar
    silicon_df = query_thematic_constituents(DB_PATH, pillar_name="Silicon & Chip Design")
    assert not silicon_df.empty
    assert (silicon_df["pillar"] == "Silicon & Chip Design").all()
