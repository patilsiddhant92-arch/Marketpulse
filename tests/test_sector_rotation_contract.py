"""Contract tests for Sector Rotation read-model integrity."""

from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from App.sector_read_model import (
    INSUFFICIENT_INDEX_HISTORY,
    format_vs_nifty_cell,
    query_index_session_count,
    query_sector_rotation_overview,
)

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


def test_vs_nifty_cell_is_insufficient_index_history_not_zero() -> None:
    """Null vs-Nifty and short index history must not render as 0.0."""
    assert format_vs_nifty_cell(None) == INSUFFICIENT_INDEX_HISTORY
    assert format_vs_nifty_cell(float("nan")) == INSUFFICIENT_INDEX_HISTORY
    assert format_vs_nifty_cell(pd.NA) == INSUFFICIENT_INDEX_HISTORY
    assert format_vs_nifty_cell(0.0, index_sessions=48) == INSUFFICIENT_INDEX_HISTORY
    assert format_vs_nifty_cell(1.5, index_sessions=48) == INSUFFICIENT_INDEX_HISTORY
    assert "0.0" not in format_vs_nifty_cell(None, index_sessions=48)
    assert format_vs_nifty_cell(1.5, index_sessions=252) == "+1.5%"
    assert format_vs_nifty_cell(-2.0, index_sessions=252) == "-2.0%"
    assert format_vs_nifty_cell(0.0, index_sessions=252) == "0.0%"

    board_source = Path("App/pages/research/sector_board.py").read_text(encoding="utf-8")
    assert "insufficient index history" in board_source
    assert "format_vs_nifty_cell" in board_source
    assert "_fmt_vs_nifty" in board_source


def test_null_vs_nifty_from_computed_metrics_is_not_zero(tmp_path) -> None:
    db_path = tmp_path / "sector.duckdb"
    with duckdb.connect(str(db_path)) as db:
        db.execute(
            """
            CREATE TABLE sector_metrics_daily (
                trade_date DATE, level TEXT, group_name TEXT, stock_count INTEGER,
                rs_vs_nifty_21d DOUBLE, rs_vs_nifty_63d DOUBLE, breadth_50 DOUBLE,
                breadth_200 DOUBLE, adv_concentration_top3 DOUBLE, near_52w_pct DOUBLE,
                adv_total_cr DOUBLE, tech_pass_n INTEGER, funda_pass_n INTEGER,
                deal_net_10s_cr DOUBLE, deal_prop_10s_cr DOUBLE, rotation_state TEXT
            )
            """
        )
        db.execute(
            "INSERT INTO sector_metrics_daily VALUES "
            "('2026-09-07', 'Sector', 'Technology', 2, NULL, NULL, 50, 50, 100, 50, 100, 1, 0, 12, 4, '')"
        )
        db.execute(
            "CREATE TABLE index_daily (trade_date DATE, index_name TEXT, close_price DOUBLE)"
        )
        start = date(2026, 7, 2)
        for i in range(48):
            db.execute(
                "INSERT INTO index_daily VALUES (?, 'Nifty 50', 25000)",
                [start + timedelta(days=i)],
            )

    overview = query_sector_rotation_overview(db_path, level="Sector")
    assert overview["vs_nifty_available"] is False
    assert overview["vs_nifty_status"] == INSUFFICIENT_INDEX_HISTORY
    assert overview["index_sessions"] == 48
    assert query_index_session_count(db_path) == 48

    row = overview["leaderboard"].iloc[0]
    assert pd.isna(row["rs_vs_nifty_21d"]) or row["rs_vs_nifty_21d"] is None
    assert pd.isna(row["return_1m_pct"]) or row["return_1m_pct"] is None
    assert row["return_1m_pct"] != 0.0
    assert format_vs_nifty_cell(row["rs_vs_nifty_21d"], index_sessions=overview["index_sessions"]) == (
        INSUFFICIENT_INDEX_HISTORY
    )
    assert format_vs_nifty_cell(row["rs_vs_nifty_63d"], index_sessions=overview["index_sessions"]) == (
        INSUFFICIENT_INDEX_HISTORY
    )
    assert str(row["rotation_state"]) == INSUFFICIENT_INDEX_HISTORY
    assert row["rotation_state"] not in ("Leading", "Improving", "Weakening", "Lagging")
    assert all(len(items) == 0 for items in overview["quadrants"].values())
