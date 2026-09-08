"""Test Market Health Regime Strip and Summary Query."""

from pathlib import Path

import pandas as pd
import pytest

from App.pages.action_desk import fetch_action_desk_data
from App.ui.market_health import (
    BREADTH_EXPOSURE_MAP,
    exposure_inputs_from_breadth_row,
    query_market_health_summary,
)
from Scripts.config import DB_PATH

EXPECTED_CARD_TITLES = {
    "ad_net": "Advance / decline",
    "above_20": "Above 20 EMA",
    "above_200": "Above 200 EMA",
    "rsi_60": "RSI above 60",
    "pivot": "Above daily pivot",
    "near_52w": "Near 52W high",
    "breakout": "VCP heuristic",
}


def test_breakout_card_keeps_key_and_is_titled_vcp_heuristic() -> None:
    src = Path("App/ui/market_health.py").read_text(encoding="utf-8")
    assert '"key": "breakout"' in src
    assert '"title": "VCP heuristic"' in src
    assert '"title": "Recent breakout"' not in src


def test_health_strip_mounted_on_desk_action_desk_and_sectors() -> None:
    desk = Path("App/pages/desk.py").read_text(encoding="utf-8")
    action = Path("App/pages/action_desk.py").read_text(encoding="utf-8")
    sectors = Path("App/pages/research/sector_board.py").read_text(encoding="utf-8")
    strip = Path("App/ui/market_health.py").read_text(encoding="utf-8")
    assert "render_market_health_strip" in desk
    assert "render_market_health_strip" in action
    assert "render_market_health_strip" in sectors
    assert "{as_of} · {stocks_n:,} stocks" in strip


def test_exposure_map_matches_design_columns() -> None:
    assert BREADTH_EXPOSURE_MAP == {
        "adv_pct": "advance_pct",
        "ab20_pct": "above_20ema_pct",
        "ab50_pct": "above_50ema_pct",
        "ab200_pct": "above_200ema_pct",
    }
    row = pd.Series(
        {
            "trade_date": "2026-09-07",
            "stocks": 2401,
            "advance_pct": 41.23,
            "above_20ema_pct": 38.91,
            "above_50ema_pct": 44.44,
            "above_200ema_pct": 52.07,
        }
    )
    got = exposure_inputs_from_breadth_row(row)
    assert got["adv_pct"] == 41.2
    assert got["ab20_pct"] == 38.9
    assert got["ab50_pct"] == 44.4
    assert got["ab200_pct"] == 52.1
    assert got["total_stocks"] == 2401
    assert got["as_of"] == "2026-09-07"
    assert got["source"] == "breadth_daily"


def test_action_desk_exposure_fallback_is_indicators_daily_only() -> None:
    src = Path("App/pages/action_desk.py").read_text(encoding="utf-8")
    assert "query_latest_breadth_daily" in src
    assert 'breadth_source = "breadth_daily"' in src
    assert 'breadth_source = "indicators_daily"' in src
    assert src.index("if not b_df.empty:") < src.index('breadth_source = "indicators_daily"')


@pytest.mark.skipif(not DB_PATH.exists(), reason="Database not built")
def test_query_market_health_summary_returns_7_cards():
    data = query_market_health_summary(DB_PATH)
    assert data, "Market health data must not be empty"
    assert data["as_of"] is not None
    assert data["total_stocks"] > 0
    assert "cards" in data
    assert len(data["cards"]) == 7, "Must contain exactly 7 regime cards"

    card_keys = [c["key"] for c in data["cards"]]
    expected = ["ad_net", "above_20", "above_200", "rsi_60", "pivot", "near_52w", "breakout"]
    for k in expected:
        assert k in card_keys, f"Card {k} must be present"

    by_key = {c["key"]: c for c in data["cards"]}
    for key, title in EXPECTED_CARD_TITLES.items():
        assert by_key[key]["title"] == title
    assert by_key["breakout"]["key"] == "breakout"


@pytest.mark.skipif(not DB_PATH.exists(), reason="Database not built")
def test_action_desk_exposure_reads_same_breadth_daily_row_as_strip():
    health = query_market_health_summary(DB_PATH)
    desk = fetch_action_desk_data(DB_PATH)
    exp = desk["exposure"]
    assert health, "Market health data must not be empty"
    assert desk.get("ready") is True
    assert exp["breadth_source"] == "breadth_daily"
    assert exp["adv_pct"] == health["adv_pct"]
    assert exp["ab20_pct"] == health["ab20_pct"]
    assert exp["ab50_pct"] == health["ab50_pct"]
    assert exp["ab200_pct"] == health["ab200_pct"]
