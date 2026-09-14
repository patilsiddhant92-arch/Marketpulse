"""Manas Focus primary queue gates."""
from __future__ import annotations

import numpy as np
import pandas as pd

from Scripts.manas_focus import MANAS, classify_manas_focus_frame, purple_density, ret_3m_pct
from Scripts.desk_contract import PRIMARY_QUEUES, QUEUE_META


def _frame(*, shakeout=True, force=True, purple=True, close=100.0):
    dates = pd.bdate_range("2026-05-01", periods=70)
    rows = []
    c = 70.0
    for i, d in enumerate(dates):
        if force:
            # drift up strongly over 63 sessions
            c = c * 1.008
        else:
            c = c * 1.001
        vol = 2_000_000.0
        if purple and i in (15, 25, 35, 45, 55, 65):
            c = c * 1.06
            vol = 2_000_000.0
        elif purple is False and i in (15, 25, 35):
            c = c * 1.06
            vol = 100_000.0  # big move but thin — not purple
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


def test_primary_queues_include_manas():
    assert PRIMARY_QUEUES[-1] == "manas"
    assert QUEUE_META["manas"]["tv_key"] == "manas"
    assert QUEUE_META["manas"]["tier"] == "primary"
    assert QUEUE_META["manas"]["title"] == "3. Manas Focus"


def test_purple_density_counts_1m_days():
    # Isolated purple days: move then flat so the next bar is not another |ret|>=5%
    close = np.array([100.0, 100.0, 100.0, 106.0, 106.0, 106.0, 100.0, 100.0, 100.0, 100.0], dtype=float)
    vol = np.array([2e6] * 10, dtype=float)
    # day3: +6%, day6: -5.66% → 2 purple days
    assert purple_density(vol, close, lookback=10) == 2


def test_ret_3m_fail_closed_when_short():
    assert np.isnan(ret_3m_pct(np.array([1.0, 2.0, 3.0]), sessions=63))


def test_classify_passes_shakeout_force_purple():
    df = _frame(shakeout=True, force=True, purple=True, close=120.0)
    # ensure 3M >= 30
    out = classify_manas_focus_frame(df)
    assert not out.empty
    assert bool(out.iloc[0]["qualifies"])
    assert out.iloc[0]["purple_n"] >= MANAS["purple_min_count"]


def test_no_shakeout_rejects():
    out = classify_manas_focus_frame(_frame(shakeout=False))
    assert out.empty


def test_close_under_30_rejects():
    out = classify_manas_focus_frame(_frame(close=25.0))
    assert out.empty


def test_thin_purple_rejects():
    out = classify_manas_focus_frame(_frame(purple=False))
    assert out.empty
