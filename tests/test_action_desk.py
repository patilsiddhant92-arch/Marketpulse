"""
Tests for Action Desk and Cache Manager.
Verifies strict quality filters, setup queue classifications, and in-memory caching.
"""
from __future__ import annotations

from pathlib import Path
import duckdb
import pytest

from App.cache_manager import get_cached, set_cached, invalidate_cache, cache_key
from App.pages.action_desk import fetch_action_desk_data
from Scripts.config import DB_PATH


def test_cache_manager_lifecycle() -> None:
    invalidate_cache()
    key = cache_key(DB_PATH, "2026-09-03", "test_metric", "arg1")
    assert get_cached(key) is None

    set_cached(key, {"value": 42})
    hit = get_cached(key)
    assert hit is not None
    assert hit["value"] == 42

    # Invalidate specific
    deleted = invalidate_cache("test_metric")
    assert deleted >= 1
    assert get_cached(key) is None


def test_action_desk_data_returns_valid_decision_structure() -> None:
    data = fetch_action_desk_data(DB_PATH)
    assert data.get("ready") is True
    assert "trade_date" in data
    assert "exposure" in data
    assert "themes" in data
    assert "queues" in data
    assert "tv_lists" in data

    exp = data["exposure"]
    assert "pct" in exp
    assert "state" in exp
    assert "guidance" in exp
    assert exp["adv_pct"] >= 0.0
    assert exp["vix"] > 0.0


def test_action_desk_enforces_strict_swing_quality_rules() -> None:
    data = fetch_action_desk_data(DB_PATH)
    queues = data["queues"]

    all_candidates = []
    for q_name, df in queues.items():
        if not df.empty:
            all_candidates.append(df)

    assert len(all_candidates) > 0

    for df in all_candidates:
        # Rule 1: No Rights Entitlements
        syms = df["symbol"].astype(str).tolist()
        for s in syms:
            assert not s.endswith("-RE")
            assert not s.endswith("_RE")
            assert "-RE" not in s

        # Rule 2: MCap >= 1000 Cr
        assert (df["market_cap_cr"] >= 1000.0).all()

        # Rule 3: No 5% Band
        assert (df["band"] > 5.0).all()

        # Rule 4: Above 200 EMA
        assert (df["cmp"] > df["ema_200"]).all()

        # Rule 5: 50 EMA > 200 EMA
        assert (df["ema_50"] > df["ema_200"]).all()

        # Rule 6: Within 25% of 52W High
        assert (df["away_52w_high_pct"] >= -25.0).all()

        # Rule 7: Strict Risk Ceiling <= 6.0%
        assert (df["risk_pct"] <= 6.0).all()
        assert (df["risk_pct"] > 0.0).all()

        # Rule 8: Leadership RS >= 70
        assert (df["rs_percentile"] >= 70.0).all()


def test_action_desk_tradingview_paste_lists() -> None:
    data = fetch_action_desk_data(DB_PATH)
    tv = data["tv_lists"]
    assert "all_focus" in tv
    assert "vcp" in tv
    assert "pullback" in tv
    assert "episodic" in tv
    assert "high52" in tv
    assert "darvas" in tv
    assert "NSE:" in tv["all_focus"]
    assert "NSE:" in tv["darvas"]


def test_action_desk_darvas_squeeze_queue() -> None:
    data = fetch_action_desk_data(DB_PATH)
    darvas_df = data["queues"].get("darvas")
    assert darvas_df is not None
    assert not darvas_df.empty
    assert "squeeze_pct" in darvas_df.columns
    assert "darvas_top" in darvas_df.columns
    assert "trigger_price" in darvas_df.columns
    assert "stop_loss" in darvas_df.columns
    assert (darvas_df["squeeze_pct"] <= 3.5).all()
    assert (darvas_df["squeeze_pct"] >= 0.0).all()
    assert (darvas_df["risk_pct"] <= 6.0).all()
    assert (darvas_df["risk_pct"] > 0.0).all()


def test_stock_candlestick_darvas_indicators() -> None:
    from App.ui.stock_drawer import query_stock_candlestick_data
    # PREMEXPLN has full OHLC strictly inside the box in near range
    res = query_stock_candlestick_data(DB_PATH, "PREMEXPLN", limit=60)
    assert "darvas_top" in res
    assert "darvas_bottom" in res
    assert len(res["darvas_top"]) == len(res["dates"])
    assert len(res["darvas_bottom"]) == len(res["dates"])
    assert "is_darvas_squeeze" in res
    assert res["is_darvas_squeeze"] is True
    assert res["darvas_squeeze_pct"] is not None
    assert res["darvas_squeeze_pct"] <= 3.5
    assert res["candle_range_pct"] is not None
    assert res["candle_range_pct"] <= 3.5

    # LUMAXIND had high poke above box ceiling (6450 vs top 6189), so it must NOT be flagged as in-box squeeze
    res_lumax = query_stock_candlestick_data(DB_PATH, "LUMAXIND", limit=60)
    assert res_lumax["is_darvas_squeeze"] is False


def test_action_desk_deal_accumulation_attached() -> None:
    data = fetch_action_desk_data(DB_PATH)
    queues = data["queues"]
    for q_name, df in queues.items():
        if not df.empty:
            assert "deal_flow" in df.columns
            # Non-empty strings
            assert df["deal_flow"].notna().all()


def test_action_desk_cockpit_layout_structure() -> None:
    page_source = Path("App/pages/action_desk.py").read_text(encoding="utf-8")
    assert "mp-cockpit-container" in page_source
    assert "mp-funnel-col" in page_source
    assert "mp-matrix-col" in page_source
    assert "mp-inspector-col" in page_source
    assert "render_stock_inspector_panel" in page_source
    assert "queue_meta" in page_source

