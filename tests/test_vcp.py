"""VCP primary queue gates (former Manas Focus)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from Scripts.vcp import VCP, classify_vcp_frame, purple_density, ret_3m_pct
from Scripts.desk_contract import MORE_QUEUES, PRIMARY_QUEUES, QUEUE_META


def _frame(*, shakeout=True, force=True, purple=True, close=100.0):
    dates = pd.bdate_range("2026-05-01", periods=70)
    rows = []
    c = 70.0
    for i, d in enumerate(dates):
        if force:
            c = c * 1.008
        else:
            c = c * 1.001
        vol = 2_000_000.0
        if purple and i in (15, 25, 35, 45, 55, 65):
            c = c * 1.06
            vol = 2_000_000.0
        elif purple is False and i in (15, 25, 35):
            c = c * 1.06
            vol = 100_000.0
        rows.append(
            {
                "symbol": "DEMO",
                "trade_date": d,
                "close_price": c if i < len(dates) - 1 else close,
                "volume": vol,
                "ema_shakeout": False,
                "close_location_pct": 70.0,
                "ema_10": c * 0.99,
            }
        )
    rows[-1]["ema_shakeout"] = shakeout
    rows[-1]["close_price"] = close
    rows[-1]["ema_10"] = close * 0.99
    rows[-2]["ema_10"] = close * 0.985
    return pd.DataFrame(rows)


def test_primary_queues_only_three():
    assert PRIMARY_QUEUES == ("darvas", "darvas_10ema", "vcp")
    assert MORE_QUEUES == ()
    assert set(QUEUE_META) == {"darvas", "darvas_10ema", "vcp"}
    assert QUEUE_META["vcp"]["tv_key"] == "vcp"
    assert QUEUE_META["vcp"]["tier"] == "primary"
    assert QUEUE_META["vcp"]["title"] == "3. VCP"
    assert "manas" not in QUEUE_META
    assert "near_pivot" not in QUEUE_META


def test_purple_density_counts_1m_days():
    close = np.array(
        [100.0, 100.0, 100.0, 106.0, 106.0, 106.0, 100.0, 100.0, 100.0, 100.0],
        dtype=float,
    )
    vol = np.array([2e6] * 10, dtype=float)
    assert purple_density(vol, close, lookback=10) == 2


def test_ret_3m_fail_closed_when_short():
    assert np.isnan(ret_3m_pct(np.array([1.0, 2.0, 3.0]), sessions=63))


def test_classify_passes_shakeout_force_purple():
    out = classify_vcp_frame(_frame(shakeout=True, force=True, purple=True, close=120.0))
    assert not out.empty
    assert bool(out.iloc[0]["qualifies"])
    assert out.iloc[0]["purple_n"] >= 0


def test_no_shakeout_rejects_when_required():
    # When require_shakeout is explicitly enabled, it filters out false shakeout
    assert classify_vcp_frame(_frame(shakeout=False), cfg={"require_shakeout": True}).empty
    # But by default under Manas Arora VCP, shakeout is an optional confirmation, not a hard barrier
    out = classify_vcp_frame(_frame(shakeout=False))
    assert not out.empty


def test_close_under_30_rejects():
    assert classify_vcp_frame(_frame(close=25.0)).empty


def test_thin_purple_rejects_when_required():
    assert classify_vcp_frame(_frame(purple=False), cfg={"purple_min_count": 3}).empty


def test_manas_vcp_contraction_and_vdu():
    from Scripts.vcp import analyze_manas_vcp

    # Progressive contractions with drying volume
    highs = np.array([100.0] * 15 + [98.0] * 15 + [97.0] * 20)
    lows = np.array([82.0] * 15 + [89.0] * 15 + [93.5] * 20)
    closes = np.array([90.0] * 15 + [95.0] * 15 + [96.5] * 20)
    volumes = np.array([1_000_000.0] * 40 + [250_000.0] * 10)

    res = analyze_manas_vcp(highs, lows, closes, volumes)
    assert res["vcp_stage"] in ("3T VCP", "2T VCP", "Tight Coil")
    assert res["vdu_active"] is True
    assert res["vdu_ratio"] < 0.8
    assert res["pivot_distance_pct"] <= 0.0
    assert res["vcp_score"] >= 70.0
    assert res["pivot_price"] == 100.0
    assert res["stop_price"] <= 95.0


def test_manas_vcp_stage2_filter():
    # Stage 2 requires trading above 200 EMA and within 25% of 52W high
    df = _frame(close=120.0)
    df["ema_200"] = 130.0  # Close below 200 EMA
    assert classify_vcp_frame(df).empty

    df["ema_200"] = 110.0  # Close above 200 EMA -> qualifies
    assert not classify_vcp_frame(df).empty

    df["away_52w_high_pct"] = -30.0  # Farther than -25% from 52W high
    assert classify_vcp_frame(df).empty

    df["away_52w_high_pct"] = -12.0  # Within 25% -> qualifies
    out = classify_vcp_frame(df)
    assert not out.empty
    assert "pivot_price" in out.columns
    assert "stop_price" in out.columns
    assert "vcp_score" in out.columns


