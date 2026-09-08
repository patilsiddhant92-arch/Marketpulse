"""Contract tests for Sector Rotation read-model integrity."""

from __future__ import annotations

import inspect
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from App.sector_read_model import (
    query_child_groups,
    query_group_members,
    query_rotation_board,
    query_sector_rotation_overview,
    query_taxonomy_hierarchy,
    session_lag_date,
)

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


def test_mixed_vs_nifty_does_not_fillna_null_rows_into_leading(tmp_path):
    db_path = tmp_path / "mixed_vs_nifty.duckdb"
    with duckdb.connect(str(db_path)) as db:
        _create_empty_metrics_table(db)
        db.execute(
            """
            INSERT INTO sector_metrics_daily VALUES
              (?, 'Sector', 'Healthcare', 10, 1.5, 4.0, 50, 50, 100, 50, 100, 1, 0, 0, 0, ''),
              (?, 'Sector', 'IPO Group', 2, NULL, NULL, 50, 50, 100, 50, 100, 0, 0, 0, 0, '')
            """,
            [AS_OF, AS_OF],
        )

    res = query_sector_rotation_overview(db_path, level="Sector")
    df = res["leaderboard"]
    assert res["insufficient_index_history"] is False

    health = df.loc[df["group_name"] == "Healthcare"].iloc[0]
    assert float(health["rs_vs_nifty_63d"]) == pytest.approx(4.0)
    assert str(health["rotation_state"]) in {"Leading", "Improving", "Weakening", "Lagging"}

    ipo = df.loc[df["group_name"] == "IPO Group"].iloc[0]
    assert pd.isna(ipo["rs_vs_nifty_63d"])
    assert pd.isna(ipo["return_3m_pct"])
    assert str(ipo.get("rotation_state") or "").strip() == ""
    if "rs_ratio" in df.columns:
        assert pd.isna(ipo["rs_ratio"])

    names_in_quads = {item["group_name"] for items in res["quadrants"].values() for item in items}
    assert "Healthcare" in names_in_quads
    assert "IPO Group" not in names_in_quads


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


def test_query_sector_rotation_overview_default_level_stays_sector():
    signature = inspect.signature(query_sector_rotation_overview)
    assert signature.parameters["level"].default == "Sector"


def test_session_lag_date_is_kth_prior_session_not_last_element():
    dates = ["T0", "T-1", "T-2", "T-3", "T-4", "T-5"]
    assert session_lag_date(dates, 5) == "T-5"
    assert session_lag_date(dates[:3], 5) is None
    assert session_lag_date(dates[:3], 5) != dates[:3][-1]


def test_sector_board_does_not_label_industry_as_mantis_58():
    source = Path("App/pages/research/sector_board.py").read_text(encoding="utf-8")
    assert "Industry (58)" not in source
    assert "Broad Industry (59)" in source
    assert "Industry (187)" in source
    assert "5D % sort (daily rows)" in source
    assert "resampled_timeframe_features" not in source
    assert 'os.environ.get("MP_SECTOR_V2"' in source


def test_mp_sector_v2_defaults_off(monkeypatch):
    monkeypatch.delenv("MP_SECTOR_V2", raising=False)
    from App.pages.research.sector_board import sector_v2_enabled

    assert sector_v2_enabled() is False
    monkeypatch.setenv("MP_SECTOR_V2", "1")
    assert sector_v2_enabled() is True


def test_weekly_toggle_is_costume_label_not_weekly_aggregator():
    source = Path("App/pages/research/sector_board.py").read_text(encoding="utf-8")
    assert 'TIMEFRAME_OPTIONS' in source
    assert '"Weekly": "5D % sort (daily rows)"' in source
    assert "not a weekly group aggregator" in source
    action = Path("App/pages/action_desk.py").read_text(encoding="utf-8")
    assert "query_rotation_board" in action
    assert "ORDER BY s.avg_rs DESC" not in action


def test_sector_intel_is_deprecated_after_harvest():
    source = Path("App/pages/research/sector_intel.py").read_text(encoding="utf-8")
    assert "DEPRECATED" in source
    assert "_render_taxonomy_tree_workspace" in source
    board = Path("App/pages/research/sector_board.py").read_text(encoding="utf-8")
    assert "mp-sector-workspace" in board
    assert "mp-taxonomy-tree-host" in board
    assert "ui.tree(" in board


def _seed_board_fixture(db: duckdb.DuckDBPyConnection) -> None:
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
        CREATE TABLE indicators_daily (
            trade_date DATE, symbol TEXT, close_price DOUBLE, prev_close DOUBLE,
            return_5d_pct DOUBLE, rs_percentile DOUBLE, rvol DOUBLE,
            away_52w_high_pct DOUBLE, turnover_cr DOUBLE
        )
        """
    )
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
    db.execute(
        """
        INSERT INTO stocks_master VALUES
          ('AAA', 'Alpha A', 2500, 'Health', 'Healthcare', 'Pharma', 'Generic Pharma'),
          ('BBB', 'Beta B', 1800, 'Health', 'Healthcare', 'Pharma', 'Generic Pharma'),
          ('CCC', 'Gamma C', 1200, 'Health', 'Healthcare', 'Pharma', 'API'),
          ('DDD', 'Delta D', 400, 'Health', 'Healthcare', 'Hospitals', 'Hospitals'),
          ('EEE', 'Echo E', 1500, 'Health', 'Healthcare', 'Hospitals', 'Hospitals')
        """
    )
    dates = [AS_OF - timedelta(days=offset) for offset in range(5, -1, -1)]
    # Alpha share jumps on T0 (400 vs 100 history); Beta share shrinks.
    for session in dates:
        is_t0 = session == AS_OF
        alpha_to = 400.0 if is_t0 else 100.0
        beta_to = 200.0
        db.execute(
            """
            INSERT INTO sector_rotation VALUES
              (?, 'Broad Industry', 'Pharma', 'Leading', 70, 2, 1, 80, 1, 2.0, 4.0, 6.0, 60, 50, 2, 1, 8, ?, 500, 2000),
              (?, 'Broad Industry', 'Hospitals', 'Lagging', 40, 1, 0, 40, 0, 0.5, 1.0, 2.0, 40, 30, 0, 0, 8, ?, 400, 1600),
              (?, 'Broad Industry', 'Tiny', 'Neutral', 20, 3, 0, 20, 0, 0.1, 0.2, 0.3, 20, 10, 0, 0, 3, 50, 50, 200)
            """,
            [session, alpha_to, session, beta_to, session],
        )
        db.execute(
            """
            INSERT INTO indicators_daily VALUES
              (?, 'AAA', 110, 100, 5.0, 90, 1.2, -1.0, 200),
              (?, 'BBB', 105, 100, 3.0, 80, 1.1, -2.0, 150),
              (?, 'CCC', 102, 100, 2.0, 70, 1.0, -3.0, 50),
              (?, 'DDD', 99, 100, -1.0, 40, 0.8, -10.0, 40),
              (?, 'EEE', 101, 100, 0.5, 55, 0.9, -4.0, 60)
            """,
            [session] * 5,
        )


def test_query_rotation_board_sorts_by_turnover_share_delta_5d_and_filters_sql(tmp_path):
    db_path = tmp_path / "board.duckdb"
    with duckdb.connect(str(db_path)) as db:
        _seed_board_fixture(db)

    frame = query_rotation_board(db_path, level="Broad Industry")
    assert list(frame["group_name"]) == ["Pharma", "Hospitals"]
    assert "Tiny" not in set(frame["group_name"].astype(str))
    assert frame.iloc[0]["group_name"] == "Pharma"
    assert float(frame.iloc[0]["turnover_share_delta_5d"]) > float(frame.iloc[1]["turnover_share_delta_5d"])
    assert int(frame["stocks"].min()) >= 8
    assert float(frame["turnover_1d_cr"].min()) >= 200
    leaders = str(frame.loc[frame["group_name"] == "Pharma", "leader_symbols"].iloc[0])
    assert leaders == "AAA,BBB,CCC"
    weekly = query_rotation_board(db_path, level="Broad Industry", timeframe="W")
    assert list(weekly["group_name"]) == list(frame["group_name"])


def test_query_group_members_and_child_groups_accept_broad_industry(tmp_path):
    db_path = tmp_path / "members.duckdb"
    with duckdb.connect(str(db_path)) as db:
        _seed_board_fixture(db)

    members = query_group_members(db_path, level="Broad Industry", group_name="Pharma")
    assert set(members["symbol"]) == {"AAA", "BBB", "CCC"}
    for column in (
        "symbol",
        "close_price",
        "return_1d_pct",
        "return_5d_pct",
        "rs_percentile",
        "rvol",
        "away_52w_high_pct",
        "turnover_cr",
        "market_cap_cr",
    ):
        assert column in members.columns

    children = query_child_groups(
        db_path,
        parent_level="Broad Industry",
        parent_name="Pharma",
        child_level="Industry",
    )
    assert set(children["group_name"]) == {"Generic Pharma", "API"}


def test_query_rs_leadership_t5_is_fifth_prior_session(tmp_path):
    from App.pages.research.sector_board import query_rs_leadership_data

    db_path = tmp_path / "rs.duckdb"
    dates = [AS_OF - timedelta(days=offset) for offset in range(5, -1, -1)]
    with duckdb.connect(str(db_path)) as db:
        db.execute(
            """
            CREATE TABLE sector_rotation (
                trade_date DATE, level TEXT, group_name TEXT, rs_percentile DOUBLE
            )
            """
        )
        for idx, session in enumerate(dates):
            db.execute(
                "INSERT INTO sector_rotation VALUES (?, 'Sector', 'Healthcare', ?)",
                [session, 50.0 + idx],
            )

    frame = query_rs_leadership_data(db_path, level="Sector")
    assert not frame.empty
    row = frame.iloc[0]
    assert float(row["rs_t0"]) == pytest.approx(55.0)
    assert float(row["rs_t5"]) == pytest.approx(50.0)


def test_migrations_grow_sector_rotation_share_columns(tmp_path):
    from Scripts.migrations import run_migrations

    db_path = tmp_path / "migrate.duckdb"
    with duckdb.connect(str(db_path)) as db:
        db.execute(
            "CREATE TABLE sector_rotation (trade_date DATE, level TEXT, group_name TEXT, turnover_1d_cr DOUBLE)"
        )
        db.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT current_timestamp
            )
            """
        )
        db.execute("INSERT INTO schema_migrations(version) VALUES (7)")

    run_migrations(db_path)
    with duckdb.connect(str(db_path), read_only=True) as db:
        columns = {
            str(row[0]).lower()
            for row in db.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'sector_rotation'"
            ).fetchall()
        }
    assert {
        "turnover_share_pct",
        "turnover_share_delta_1d",
        "turnover_share_delta_5d",
        "adv_pct",
        "leader_symbols",
    } <= columns


def test_build_sector_rotation_persists_share_delta_adv_and_leaders():
    from Scripts.build_database import build_sector_rotation

    dates = [AS_OF - timedelta(days=offset) for offset in range(5, -1, -1)]
    rows = []
    for session in dates:
        is_t0 = session == AS_OF
        rows.extend(
            [
                {
                    "symbol": "AAA",
                    "trade_date": session,
                    "close_price": 110.0,
                    "prev_close": 100.0,
                    "return_5d_pct": 2.0,
                    "return_1m_pct": 4.0,
                    "return_3m_pct": 6.0,
                    "rs_percentile": 90.0,
                    "ema_10": 100.0,
                    "ema_50": 95.0,
                    "ema_200": 90.0,
                    "near_52w_high": True,
                    "is_vcp": False,
                    "turnover_cr": 400.0 if is_t0 else 100.0,
                },
                {
                    "symbol": "BBB",
                    "trade_date": session,
                    "close_price": 99.0,
                    "prev_close": 100.0,
                    "return_5d_pct": 0.5,
                    "return_1m_pct": 1.0,
                    "return_3m_pct": 2.0,
                    "rs_percentile": 40.0,
                    "ema_10": 100.0,
                    "ema_50": 95.0,
                    "ema_200": 90.0,
                    "near_52w_high": False,
                    "is_vcp": False,
                    "turnover_cr": 100.0,
                },
            ]
        )
    indicators = pd.DataFrame(rows)
    master = pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "broad_sector": "Health",
                "sector": "Healthcare",
                "broad_industry": "Pharma",
                "industry": "Generic Pharma",
                "market_cap_cr": 2500.0,
            },
            {
                "symbol": "BBB",
                "broad_sector": "Health",
                "sector": "Healthcare",
                "broad_industry": "Hospitals",
                "industry": "Hospitals",
                "market_cap_cr": 1800.0,
            },
        ]
    )
    frame = build_sector_rotation(indicators, master)
    latest = frame[frame["level"] == "Broad Industry"].copy()
    latest["trade_date"] = pd.to_datetime(latest["trade_date"]).dt.normalize()
    latest = latest[latest["trade_date"] == pd.Timestamp(AS_OF)]
    pharma = latest.loc[latest["group_name"] == "Pharma"].iloc[0]
    hospitals = latest.loc[latest["group_name"] == "Hospitals"].iloc[0]
    assert float(pharma["turnover_share_pct"]) == pytest.approx(80.0)
    assert float(hospitals["turnover_share_pct"]) == pytest.approx(20.0)
    assert float(pharma["turnover_share_delta_5d"]) == pytest.approx(30.0)
    assert float(hospitals["turnover_share_delta_5d"]) == pytest.approx(-30.0)
    assert float(pharma["adv_pct"]) == pytest.approx(100.0)
    assert float(hospitals["adv_pct"]) == pytest.approx(0.0)
    assert str(pharma["leader_symbols"]) == "AAA"


@pytest.mark.skipif(not DB_PATH.exists(), reason="Database not built")
def test_live_rotation_board_filters_min_names_and_turnover():
    frame = query_rotation_board(DB_PATH, level="Broad Industry")
    assert not frame.empty
    assert int(frame["stocks"].min()) >= 8
    assert float(frame["turnover_1d_cr"].min()) >= 200.0
    deltas = pd.to_numeric(frame["turnover_share_delta_5d"], errors="coerce").dropna()
    assert list(deltas) == sorted(deltas, reverse=True)
