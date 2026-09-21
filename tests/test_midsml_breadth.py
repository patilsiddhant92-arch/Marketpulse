from __future__ import annotations

from pathlib import Path
import duckdb
import pytest

from Scripts.midsml_breadth import (
    classify_midsml_regime,
    build_midsml_breadth_barometer,
    query_midsml_breadth,
    _clean_val,
)
from Scripts.telegram_deals import build_deals_telegram_report


def test_clean_val_deadband():
    """Verify deadband eliminates -0.0 and contradictory +0.0 signs."""
    assert _clean_val(-0.03, deadband=0.05) == 0.0
    assert _clean_val(0.04, deadband=0.05) == 0.0
    assert _clean_val(-0.0, deadband=0.05) == 0.0
    assert _clean_val(-1.25, deadband=0.05) == -1.25
    assert _clean_val(3.50, deadband=0.05) == 3.50


def test_classify_midsml_regime_scenarios():
    """Verify automated regime classification and trader stances."""
    # 1. Capitulation Washout (<=15% advancers)
    r_washout = classify_midsml_regime(adv_pct=10.8, abv_10_pct=15.0, abv_50_pct=35.0, abv_200_pct=50.0, delta_5d=-8.0)
    assert r_washout["regime"] == "CAPITULATION WASHOUT"
    assert "⚡" in r_washout["badge"]
    assert "DEFENSIVE" in r_washout["stance"]

    # 2. Bull Expansion (>55% >10ema, >50% >50ema, >50% adv)
    r_bull = classify_midsml_regime(adv_pct=65.0, abv_10_pct=60.0, abv_50_pct=58.0, abv_200_pct=65.0, delta_5d=6.0)
    assert r_bull["regime"] == "BULL EXPANSION"
    assert "🟢" in r_bull["badge"]
    assert "SWING EXPOSURE" in r_bull["stance"]

    # 3. Correction / Downtrend (<45% >50ema, negative delta)
    r_corr = classify_midsml_regime(adv_pct=35.0, abv_10_pct=25.0, abv_50_pct=38.0, abv_200_pct=48.0, delta_5d=-6.0)
    assert r_corr["regime"] == "CORRECTION / DOWNTREND"
    assert "🔴" in r_corr["badge"]
    assert "CASH" in r_corr["stance"]

    # 4. Top Warning / Diverging (<35% >10ema, steep 5d drop)
    r_top = classify_midsml_regime(adv_pct=42.0, abv_10_pct=30.0, abv_50_pct=52.0, abv_200_pct=60.0, delta_5d=-7.0)
    assert r_top["regime"] == "TOP WARNING / DIVERGING"
    assert "🟡" in r_top["badge"]
    assert "TIGHTEN STOPS" in r_top["stance"]


def test_build_midsml_breadth_barometer_formatting():
    """Verify formatting has no -0.0 and contains essential mid-smallcap metrics."""
    metrics = {
        "as_of": "2026-09-16",
        "adv_pct": 52.5,
        "advancers": 210,
        "decliners": 190,
        "abv_10_pct": 15.5,
        "abv_20_pct": 28.0,
        "abv_50_pct": 42.5,
        "abv_200_pct": 55.0,
        "near_52w_highs": 154,
        "delta_1d": -0.03,  # near-zero negative float
        "delta_5d": -12.4,
        "midsml_ret": -0.02, # near-zero negative float
        "regime": classify_midsml_regime(adv_pct=52.5, abv_10_pct=15.5, abv_50_pct=42.5, abv_200_pct=55.0, delta_5d=-12.4),
    }

    barometer = build_midsml_breadth_barometer(metrics)
    assert "-0.0" not in barometer
    assert "-0.0%" not in barometer
    assert "MIDSML 400 BREADTH" in barometer
    assert "Regime:" in barometer
    assert "Desk Stance:" in barometer
    assert "Moving Average Support" in barometer


def test_query_midsml_breadth_on_db():
    """Verify live query_midsml_breadth operates on ranks 101-500."""
    db_path = Path("Database/marketpulse.duckdb")
    if not db_path.exists():
        pytest.skip("Database not found")

    metrics = query_midsml_breadth(db_path)
    assert metrics["as_of"] is not None
    assert metrics["universe_size"] <= 400
    assert metrics["universe_size"] >= 350
    assert 0.0 <= metrics["adv_pct"] <= 100.0
    assert 0.0 <= metrics["abv_200_pct"] <= 100.0
    assert "regime" in metrics
    assert "-0.0" not in metrics["badge"]


def test_telegram_deals_report_standalone_watchlists():
    """Verify build_deals_telegram_report outputs dedicated 1-tap copy watchlists."""
    db_path = Path("Database/marketpulse.duckdb")
    if not db_path.exists():
        pytest.skip("Database not found")

    report = build_deals_telegram_report(db_path, days=10)
    assert "messages" in report
    msgs = report["messages"]
    # We now emit Executive Briefing, Risk & Context, plus up to 4 standalone watchlists
    assert len(msgs) >= 2

    # Verify no -0.0 anywhere in generated telegram text
    for i, m in enumerate(msgs):
        assert "-0.0" not in m, f"Message {i} contained negative zero: {m}"

    # Verify tv_strings structure
    tv = report["tv_strings"]
    assert "today_buys" in tv
    assert "high_conviction" in tv
    assert "repeat" in tv
    assert "prop_pure" in tv

    # If any watchlist message was emitted, verify monospace code block formatting
    wl_msgs = [m for m in msgs if "WATCHLIST" in m]
    for w_msg in wl_msgs:
        assert "```" in w_msg or "`" in w_msg
        assert "NSE:" in w_msg
