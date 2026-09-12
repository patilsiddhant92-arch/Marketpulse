"""Unit tests for Industry and Sector Peer Comparison Engine."""

from pathlib import Path
import pytest
import pandas as pd

from App.ui.stock_drawer import query_stock_peer_comparison, query_stock_360_data


DB_PATH = Path("Database/marketpulse.duckdb")


def test_peer_comparison_midhani_rank_and_options():
    """Verify MIDHANI peer comparison returns correct rank and better options."""
    if not DB_PATH.exists():
        pytest.skip("Database does not exist")

    res = query_stock_peer_comparison(DB_PATH, "MIDHANI")
    assert res is not None
    assert res["target"]["symbol"] == "MIDHANI"
    assert res["industry"] == "Aerospace & Defense"
    assert res["sector"] == "Capital Goods"
    assert res["total_peers"] >= 20
    assert 1 <= res["target_rank"] <= res["total_peers"]
    assert res["is_leader"] is False

    peers_df = res["peers_df"]
    assert not peers_df.empty
    assert "symbol" in peers_df.columns
    assert "rs_percentile" in peers_df.columns
    assert "away_10ema_pct" in peers_df.columns

    # Verify Better Options contains higher-RS leaders
    better = res["better_options"]
    assert len(better) > 0
    better_syms = [b["symbol"] for b in better]
    assert "PARAS" in better_syms or "DATAPATTNS" in better_syms or "UNIMECH" in better_syms

    # Invariant #1: All peers must be present in peers_df (no truncation)
    assert len(peers_df) == res["total_peers"]


def test_peer_comparison_leader_detection():
    """Verify leader detection when querying the top-ranked stock."""
    if not DB_PATH.exists():
        pytest.skip("Database does not exist")

    # MTARTECH is the #1 RS leader in Aerospace & Defense
    res = query_stock_peer_comparison(DB_PATH, "MTARTECH")
    assert res is not None
    assert res["target_rank"] == 1
    assert res["is_leader"] is True


def test_peer_comparison_sector_leaders():
    """Verify parent sector leaders are surfaced."""
    if not DB_PATH.exists():
        pytest.skip("Database does not exist")

    res = query_stock_peer_comparison(DB_PATH, "MIDHANI")
    assert res is not None
    sec_df = res["sector_leaders_df"]
    assert isinstance(sec_df, pd.DataFrame)
    assert not sec_df.empty
    assert len(sec_df) <= 8


def test_peer_comparison_edge_cases():
    """Verify handling of invalid or non-existent symbols."""
    if not DB_PATH.exists():
        pytest.skip("Database does not exist")

    assert query_stock_peer_comparison(DB_PATH, "") is None
    assert query_stock_peer_comparison(DB_PATH, "   ") is None
    assert query_stock_peer_comparison(DB_PATH, "NON_EXISTENT_SYMBOL_XYZ") is None


def test_stock_360_data_includes_peer_comparison():
    """Verify query_stock_360_data embeds peer_comparison dict."""
    if not DB_PATH.exists():
        pytest.skip("Database does not exist")

    data = query_stock_360_data(DB_PATH, "MIDHANI")
    assert data is not None
    assert "peer_comparison" in data
    peer_comp = data["peer_comparison"]
    assert peer_comp is not None
    assert 1 <= peer_comp["target_rank"] <= peer_comp["total_peers"]
