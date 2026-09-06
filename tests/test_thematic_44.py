"""Tests for 44 Official NSE Thematic & Sectoral Indices Leadership Engine."""

from __future__ import annotations

from pathlib import Path
import pytest
import pandas as pd

from App.thematic_engine import (
    CANONICAL_44_INDICES,
    build_thematic_leaderboard,
    get_macro_pulse,
    get_index_constituents,
    get_stock_thematic_tags,
)
from App.pages.action_desk import fetch_action_desk_data


@pytest.fixture
def db_path() -> Path:
    p = Path("Database/marketpulse.duckdb")
    if not p.exists():
        pytest.skip("Market database not available")
    return p


@pytest.fixture
def user_db_path() -> Path:
    p = Path("Database/marketpulse_user.duckdb")
    if not p.exists():
        pytest.skip("User database not available")
    return p


def test_canonical_44_indices_count():
    assert len(CANONICAL_44_INDICES) == 44
    thematic_count = sum(1 for v in CANONICAL_44_INDICES.values() if v["category"] == "Thematic")
    sectoral_count = sum(1 for v in CANONICAL_44_INDICES.values() if v["category"] == "Sectoral")
    assert thematic_count == 28
    assert sectoral_count == 16


def test_thematic_leaderboard_build(db_path: Path):
    df = build_thematic_leaderboard(db_path)
    assert not df.empty
    assert len(df) == 44
    required_cols = [
        "rank", "index_name", "clean_name", "category", "close_price",
        "return_1d_pct", "rsi_14", "above_10", "above_20", "above_50", "above_200",
        "stack_count", "trail_vals", "net_momentum", "trend_state"
    ]
    for col in required_cols:
        assert col in df.columns, f"Missing required column: {col}"

    # Check rank order
    assert list(df["rank"]) == list(range(1, 45))

    # Check trail_vals has 4 elements
    for trail in df["trail_vals"]:
        assert len(trail) == 4
        for val in trail:
            assert 0 <= val <= 100


def test_macro_pulse_top_and_bottom(db_path: Path):
    pulse = get_macro_pulse(db_path)
    assert "top" in pulse
    assert "bottom" in pulse
    assert len(pulse["top"]) == 3
    assert len(pulse["bottom"]) == 3
    for item in pulse["top"]:
        assert "name" in item
        assert "return_1d" in item
        assert "trend" in item


def test_index_constituents_lookup(db_path: Path, user_db_path: Path):
    # Test Defence constituents
    def_stocks = get_index_constituents(db_path, user_db_path, "Nifty Ind Defence")
    assert not def_stocks.empty
    assert len(def_stocks) >= 10
    assert "symbol" in def_stocks.columns
    assert "theme" in def_stocks.columns
    assert "close_price" in def_stocks.columns
    # Verify prominent defence stocks are in the list
    syms = set(def_stocks["symbol"])
    assert any(s in syms for s in ["HAL", "BEL", "MAZDOCK", "LT", "PREMEXPLN"])

    # Test Capital Markets constituents
    cap_stocks = get_index_constituents(db_path, user_db_path, "Nifty Capital Mkt")
    assert not cap_stocks.empty
    assert len(cap_stocks) >= 5


def test_action_desk_thematic_integration(db_path: Path):
    data = fetch_action_desk_data(db_path)
    assert data["ready"] is True
    assert "macro_pulse" in data
    assert len(data["macro_pulse"]["top"]) == 3

    # Verify candidate queues contain the 'theme' column
    darvas_df = data["queues"].get("darvas", pd.DataFrame())
    if not darvas_df.empty:
        assert "theme" in darvas_df.columns
        assert not darvas_df["theme"].isna().all()
