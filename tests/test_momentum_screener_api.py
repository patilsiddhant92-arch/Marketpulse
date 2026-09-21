from __future__ import annotations

import re
import pytest
from fastapi.testclient import TestClient

from App.api.server import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_momentum_screener_lookback_varies_counts(client):
    """
    Verifies that changing lookback_days produces distinct, progressive candidate pools.
    Before the fix, lookback_days was ignored in the SQL query and returned identical counts.
    """
    counts = {}
    for lb in [1, 3, 5, 10, 20, 30]:
        response = client.get(
            f"/api/screener/momentum?lookback_days={lb}&min_mcap_cr=1000&min_volume=1000000"
            "&min_avg_volume_20d=0&max_52w_away_pct=25&min_52w_low_pct=50&cmp_gt_10=true&cmp_gt_200=true"
            "&ohlc_gt_10=false&ohlc_gt_20=false&ema10_gt_20=true&ema20_gt_50=true&ema50_gt_100=true"
            "&ema100_gt_200=true&sma50_gt_150=false&sma150_gt_200=false&sma_cmp_gt_50=false"
            "&sma_cmp_gt_150_200=false&sma200_rising=false&delivery_thrust=false&coiling_nr7=false"
            "&weekly_rsi_60=false&limit=300"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["lookback_days"] == lb
        count = data["total_count"]
        assert count == len(data["candidates"])
        counts[lb] = count

    # Counts must expand as lookback window widens
    assert counts[1] <= counts[3] <= counts[5] <= counts[10] <= counts[20] <= counts[30]
    assert counts[1] < counts[20], (
        f"Lookback 20D ({counts[20]}) must capture more historical triggers than 1D ({counts[1]})"
    )


def test_momentum_screener_candidate_structure(client):
    """
    Verifies that returned candidates have required analytical fields, including trigger_date.
    """
    response = client.get("/api/screener/momentum?lookback_days=10&min_mcap_cr=1000&min_volume=1000000")
    assert response.status_code == 200
    data = response.json()
    assert "candidates" in data
    assert "buckets_tv" in data
    assert "top_sectors" in data
    assert "top_industries" in data
    assert "sector_distribution" in data

    if data["candidates"]:
        cand = data["candidates"][0]
        assert "symbol" in cand
        assert "cmp" in cand
        assert "away_10ema_pct" in cand
        assert "bucket" in cand
        assert "bullish_stack" in cand
        assert "trigger_date" in cand


def test_momentum_screener_trigger_date_clean_iso_format(client):
    """
    Verifies that trigger_date is clean ISO format (YYYY-MM-DD) without trailing timestamp artifacts.
    """
    response = client.get("/api/screener/momentum?lookback_days=20&min_mcap_cr=1000&min_volume=1000000")
    assert response.status_code == 200
    data = response.json()
    for c in data["candidates"]:
        td = c.get("trigger_date")
        if td:
            assert re.match(r"^\d{4}-\d{2}-\d{2}$", td), f"Invalid trigger_date format: {td}"


def test_momentum_screener_avg20d_mode_lookback_varies_counts(client):
    """
    Verifies that when volumeMode === 'avg20d' (min_volume = 0, min_avg_volume_20d = 1M),
    lookback correctly expands candidates between 1D and 20D.
    """
    res_1d = client.get(
        "/api/screener/momentum?lookback_days=1&min_mcap_cr=1000&min_volume=0&min_avg_volume_20d=1000000"
    ).json()
    res_20d = client.get(
        "/api/screener/momentum?lookback_days=20&min_mcap_cr=1000&min_volume=0&min_avg_volume_20d=1000000"
    ).json()

    assert res_1d["total_count"] < res_20d["total_count"], (
        f"Avg20d mode 20D ({res_20d['total_count']}) must exceed 1D ({res_1d['total_count']})"
    )


def test_momentum_screener_delivery_thrust_lookback_varies_counts(client):
    """
    Verifies that when delivery_thrust is enabled, historical delivery spikes in the lookback window
    are captured, expanding candidate counts between 1D and 20D.
    """
    res_1d = client.get(
        "/api/screener/momentum?lookback_days=1&min_mcap_cr=1000&delivery_thrust=true"
    ).json()
    res_20d = client.get(
        "/api/screener/momentum?lookback_days=20&min_mcap_cr=1000&delivery_thrust=true"
    ).json()

    assert res_1d["total_count"] < res_20d["total_count"], (
        f"Delivery thrust 20D ({res_20d['total_count']}) must exceed 1D ({res_1d['total_count']})"
    )
    # Qualifying candidates must have delivery_spike true (from trigger or current day)
    for c in res_20d["candidates"]:
        assert c["delivery_spike"] is True


def test_momentum_screener_sma_template_with_avg20d(client):
    """
    Verifies that SMA template preset combined with avg20d volume mode respects lookback.
    """
    res_1d = client.get(
        "/api/screener/momentum?lookback_days=1&min_mcap_cr=1000&min_volume=0&min_avg_volume_20d=1000000"
        "&sma50_gt_150=true&sma150_gt_200=true&sma_cmp_gt_50=true&sma_cmp_gt_150_200=true&sma200_rising=true"
        "&ema10_gt_20=false&ema20_gt_50=false&ema50_gt_100=false&ema100_gt_200=false"
    ).json()
    res_20d = client.get(
        "/api/screener/momentum?lookback_days=20&min_mcap_cr=1000&min_volume=0&min_avg_volume_20d=1000000"
        "&sma50_gt_150=true&sma150_gt_200=true&sma_cmp_gt_50=true&sma_cmp_gt_150_200=true&sma200_rising=true"
        "&ema10_gt_20=false&ema20_gt_50=false&ema50_gt_100=false&ema100_gt_200=false"
    ).json()

    assert res_1d["total_count"] < res_20d["total_count"], (
        f"SMA Template + avg20d 20D ({res_20d['total_count']}) must exceed 1D ({res_1d['total_count']})"
    )


def test_momentum_screener_lookback_1d_vs_historical_volume(client):
    """
    On lookback_days=1, all qualifying candidates must have triggered on the latest session (volume >= 1M).
    On lookback_days=20, some qualifying candidates can have today's volume < 1M because they triggered earlier.
    """
    res_1d = client.get("/api/screener/momentum?lookback_days=1&min_volume=1000000").json()
    res_20d = client.get("/api/screener/momentum?lookback_days=20&min_volume=1000000").json()

    # In 1D, every candidate volume is >= 1,000,000
    for c in res_1d["candidates"]:
        assert c["volume"] >= 1000000, f"Expected 1D volume >= 1M for {c['symbol']}, got {c['volume']}"

    # In 20D, find stocks that triggered historically and have volume < 1M today
    below_1m_today = [c for c in res_20d["candidates"] if c["volume"] < 1000000]
    assert len(below_1m_today) > 0, "Lookback 20D should retain pullback stocks with today's volume < 1M"


def test_momentum_screener_debug_symbol(client):
    """
    Tests debug_symbol filter correctly isolates a specific symbol.
    """
    response = client.get("/api/screener/momentum?lookback_days=20&debug_symbol=SHANTIGOLD")
    assert response.status_code == 200
    data = response.json()
    for c in data["candidates"]:
        assert c["symbol"] == "SHANTIGOLD"
