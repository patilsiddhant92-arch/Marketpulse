"""
Tests for UC Thrust Radar: Empirical Pre-Circuit Detection Engine.
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd
import pytest

from App.indicators.uc_thrust import calculate_uc_thrust_candidates
from Scripts.config import DB_PATH


def test_uc_thrust_candidates_on_live_db():
    if not Path(DB_PATH).exists():
        pytest.skip("Database does not exist")

    df = calculate_uc_thrust_candidates(DB_PATH, limit=20)
    assert isinstance(df, pd.DataFrame)
    if not df.empty:
        required_cols = [
            "symbol",
            "cmp",
            "uc_score",
            "day_pct",
            "rvol",
            "delivery_pct",
            "away_10ema_pct",
            "rs_percentile",
            "sector",
            "deal_flow",
            "why_now",
        ]
        for col in required_cols:
            assert col in df.columns, f"Missing column: {col}"

        # Assert sorted descending by score
        scores = df["uc_score"].tolist()
        assert scores == sorted(scores, reverse=True)

        # Assert all stocks have valid price and positive scores
        assert (df["cmp"] > 0).all()
        assert (df["uc_score"] >= 0).all()

        # Assert why_now contains UC Score explanation
        assert all("UC Score" in str(w) for w in df["why_now"])


def test_uc_thrust_empty_on_missing_db(tmp_path):
    missing_db = tmp_path / "missing.duckdb"
    df = calculate_uc_thrust_candidates(missing_db)
    assert df.empty


def test_uc_thrust_preset_in_app_source():
    app_text = Path("App/app.py").read_text(encoding="utf-8")
    assert "_preset_uc_thrust" in app_text
    assert "UC Thrust Radar" in app_text
