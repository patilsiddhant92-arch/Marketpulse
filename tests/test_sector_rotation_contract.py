"""Contract tests for Sector Rotation read-model integrity."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from App.sector_read_model import query_sector_rotation_overview, query_taxonomy_hierarchy

DB_PATH = Path("Database/marketpulse.duckdb")
AS_OF = date(2026, 9, 7)


def _find(nodes: list[dict], level: str, name: str) -> dict:
    for node in nodes:
        if node["level"] == level and node["name"] == name:
            return node
        found = _find(node.get("children", []), level, name)
        if found:
            return found
    return {}


def _create_empty_metrics_table(db: duckdb.DuckDBPyConnection) -> None:
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


def _insert_null_vs_nifty_metrics(db: duckdb.DuckDBPyConnection) -> None:
    db.execute(
        """
        INSERT INTO sector_metrics_daily VALUES
          (?, 'Broad Sector', 'Healthcare', 10, NULL, NULL, 50, 50, 100, 50, 100, 1, 0, 0, 0, ''),
          (?, 'Sector', 'Healthcare', 10, NULL, NULL, 50, 50, 100, 50, 100, 1, 0, 0, 0, ''),
          (?, 'Broad Industry', 'Pharmaceuticals', 10, NULL, NULL, 50, 50, 100, 50, 100, 1, 0, 0, 0, ''),
          (?, 'Industry', 'Pharmaceuticals', 10, NULL, NULL, 50, 50, 100, 50, 100, 1, 0, 0, 0, '')
        """,
        [AS_OF] * 4,
    )


def _create_rotation_table(db: duckdb.DuckDBPyConnection) -> None:
    db.execute(
        """
        CREATE TABLE sector_rotation (
            trade_date DATE, level TEXT, group_name TEXT,
            rotation_state TEXT, rs_percentile DOUBLE, rotation_rank INTEGER,
            rank_change_5d INTEGER, rotation_score DOUBLE, score_change_5d DOUBLE,
            return_5d_pct DOUBLE, return_1m_pct DOUBLE, return_3m_pct DOUBLE,
            above_50ema_pct DOUBLE, above_200ema_pct DOUBLE,
            near_52w_highs INTEGER, vcp_candidates INTEGER, stocks INTEGER,
            turnover_1d_cr DOUBLE, turnover_5d_cr DOUBLE, turnover_20d_cr DOUBLE
        )
        """
    )


def _insert_populated_rotation(db: duckdb.DuckDBPyConnection) -> None:
    db.execute(
        """
        INSERT INTO sector_rotation VALUES
          (?, 'Broad Sector', 'Healthcare', 'Leading', 62.3, 1, 4, 80.0, 2.0, 1.2, 4.5, 8.0, 70, 55, 3, 2, 10, 500, 2000, 8000),
          (?, 'Sector', 'Healthcare', 'Leading', 62.3, 1, 4, 80.0, 2.0, 1.2, 4.5, 8.0, 70, 55, 3, 2, 10, 500, 2000, 8000),
          (?, 'Broad Industry', 'Pharmaceuticals', 'Leading', 61.0, 1, 3, 78.0, 1.5, 1.0, 4.0, 7.5, 68, 52, 2, 1, 8, 400, 1600, 6400),
          (?, 'Industry', 'Pharmaceuticals', 'Leading', 60.0, 1, 2, 76.0, 1.0, 0.8, 3.5, 7.0, 65, 50, 1, 1, 6, 300, 1200, 4800)
        """,
        [AS_OF] * 4,
    )


def _assert_null_vs_nifty_not_rendered_as_return(frame: pd.DataFrame) -> None:
    for column in ("rs_vs_nifty_21d", "rs_vs_nifty_63d", "return_1m_pct", "return_3m_pct"):
        if column not in frame.columns:
            continue
        series = pd.to_numeric(frame[column], errors="coerce")
        assert series.isna().all(), f"{column} must stay null when vs-Nifty is missing, not 0.0"


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


def test_null_vs_nifty_does_not_synthesize_rrg_or_render_zero(tmp_path):
    db_path = tmp_path / "empty_metrics.duckdb"
    with duckdb.connect(str(db_path)) as db:
        _create_empty_metrics_table(db)
        _insert_null_vs_nifty_metrics(db)

    res = query_sector_rotation_overview(db_path, level="Sector")
    df = res["leaderboard"]
    assert not df.empty
    _assert_null_vs_nifty_not_rendered_as_return(df)

    states = df["rotation_state"].fillna("").astype(str).str.strip()
    assert not states.isin(["Leading", "Improving", "Weakening", "Lagging"]).any()
    assert all(len(items) == 0 for items in res["quadrants"].values())
    assert res["insufficient_index_history"] is True
    assert res["top_focus"] == []


def test_taxonomy_prefers_sector_rotation_over_empty_metrics(tmp_path):
    db_path = tmp_path / "split_brain.duckdb"
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
              ('SUNPHARMA', 'Sun Pharma', 2500, 'Healthcare', 'Healthcare', 'Pharmaceuticals', 'Pharmaceuticals')
            """
        )
        _create_empty_metrics_table(db)
        _insert_null_vs_nifty_metrics(db)
        _create_rotation_table(db)
        _insert_populated_rotation(db)

    tree = query_taxonomy_hierarchy(db_path, min_mcap=1_000)
    sector = _find(tree, "Sector", "Healthcare")
    assert sector["rotation_state"] == "Leading"
    assert sector["rs_percentile"] == pytest.approx(62.3)
    assert sector["rotation_rank"] == 1


def test_ui_ranks_come_from_sector_rotation_not_computed_metrics(tmp_path):
    db_path = tmp_path / "ranks.duckdb"
    with duckdb.connect(str(db_path)) as db:
        _create_empty_metrics_table(db)
        _insert_null_vs_nifty_metrics(db)
        _create_rotation_table(db)
        _insert_populated_rotation(db)

    res = query_sector_rotation_overview(db_path, level="Sector")
    df = res["leaderboard"]
    row = df.loc[df["group_name"] == "Healthcare"].iloc[0]
    assert int(row["rotation_rank"]) == 1
    assert float(row["rank_change_5d"]) == 4.0
    assert str(row["rotation_state"]) == "Leading"
    assert float(row["rs_percentile"]) == pytest.approx(62.3)
    assert res["quadrants"]["Leading"]
    assert res.get("insufficient_index_history") is not True
