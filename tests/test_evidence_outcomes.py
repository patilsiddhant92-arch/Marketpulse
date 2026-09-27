"""Setup outcomes: fill, stop, R path, 1R/2R before stop, identity reset, aggregates (spec §5)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from Scripts.evidence.outcomes import aggregate_setup_outcomes, compute_setup_outcomes, environment_calibration
from Scripts.evidence.setups import assign_identity

DATES = pd.bdate_range("2025-01-01", periods=60)


def _prices(symbol: str, bars: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame({
        "symbol": symbol, "trade_date": DATES[: len(bars)],
        "open_price": [b[0] for b in bars], "high_price": [b[1] for b in bars],
        "low_price": [b[2] for b in bars], "close_price": [b[3] for b in bars],
    })


def _setup(symbol: str, day: int, trigger: float, stop: float, queue: str = "vcp") -> dict:
    return {"queue": queue, "symbol": symbol, "trade_date": DATES[day], "trigger_price": trigger, "stop_price": stop}


def test_fill_next_session_and_hit_2r_before_horizon():
    bars = [(100, 101, 99, 100)] * 3 + [(100, 103, 100, 102.5), (102.5, 108, 102, 107), (107, 114, 106, 113)] + \
        [(113, 114, 112, 113)] * 30
    out = compute_setup_outcomes(pd.DataFrame([_setup("AAA", 2, 102.0, 98.0)]), _prices("AAA", bars), horizon=20)
    r = out.iloc[0]
    assert r["status"] == "horizon"
    assert r["fill_date"] == DATES[3]
    assert r["entry_price"] == pytest.approx(102.0)  # open 100 < trigger => fill at trigger
    assert bool(r["hit_1r"]) and bool(r["hit_2r"])  # 1R = 106, 2R = 110 reached on day 5
    assert r["days_held"] == 20
    assert r["r_multiple"] == pytest.approx((113 - 102) / 4)
    assert r["mfe_pct"] == pytest.approx((114 / 102 - 1) * 100)


def test_gap_fill_at_open_and_stop_exit():
    bars = [(100, 101, 99, 100)] * 3 + [(105, 106, 104, 105), (104, 104, 95, 96)] + [(96, 97, 95, 96)] * 30
    out = compute_setup_outcomes(pd.DataFrame([_setup("BBB", 2, 102.0, 98.0)]), _prices("BBB", bars))
    r = out.iloc[0]
    assert r["entry_price"] == pytest.approx(105.0)
    assert r["status"] == "stopped" and r["exit_reason"] == "stop"
    assert r["exit_price"] == pytest.approx(98.0)
    assert r["r_multiple"] == pytest.approx((98 - 105) / 7)
    assert not bool(r["hit_1r"])
    assert r["days_held"] == 2


def test_stop_and_target_same_day_counts_as_stop():
    bars = [(100, 101, 99, 100)] * 3 + [(101, 103, 100, 102), (102, 115, 90, 100)] + [(100, 101, 99, 100)] * 30
    r = compute_setup_outcomes(pd.DataFrame([_setup("CCC", 2, 102.0, 98.0)]), _prices("CCC", bars)).iloc[0]
    assert r["status"] == "stopped" and not bool(r["hit_1r"]) and not bool(r["hit_2r"])


def test_no_fill_open_and_invalid():
    flat = [(100, 101, 99, 100)] * 40
    s = pd.DataFrame([_setup("DDD", 2, 150.0, 90.0), _setup("DDD", 3, 150.0, 90.0, queue="darvas_squeeze")])
    s.loc[1, "stop_price"] = np.nan
    out = compute_setup_outcomes(s, _prices("DDD", flat)).set_index("queue")
    assert out.loc["vcp", "status"] == "no_fill" and pd.isna(out.loc["vcp", "r_multiple"])
    assert out.loc["darvas_squeeze", "status"] == "invalid"
    # filled near the end of data: not enough forward sessions => open, no R
    bars = [(100, 101, 99, 100)] * 36 + [(100, 103, 100, 102)] + [(102, 103, 101, 102)] * 3
    r = compute_setup_outcomes(pd.DataFrame([_setup("EEE", 35, 102.0, 98.0)]), _prices("EEE", bars)).iloc[0]
    assert r["status"] == "open" and pd.isna(r["r_multiple"]) and pd.isna(r["exit_date"])


def test_identity_resets_after_five_absent_sessions():
    rows = pd.DataFrame([_setup("FFF", d, 1, 0) for d in (0, 1, 2, 6, 7, 13)])  # gap of 3 then 5 absent sessions
    ids = assign_identity(rows, pd.Series(DATES))
    assert ids["setup_id"].nunique() == 2
    assert ids["first_seen"].iloc[-1] == DATES[13]
    assert list(ids["setup_age_sessions"])[:5] == [1, 2, 3, 7, 8]


def test_order_uses_trigger_of_each_in_queue_day():
    bars = [(100, 101, 99, 100)] * 3 + [(100, 101.5, 99, 101), (101, 104, 100, 103)] + [(103, 104, 102, 103)] * 30
    s = pd.DataFrame([_setup("GGG", 2, 102.0, 98.0), _setup("GGG", 3, 103.5, 99.0)])
    r = compute_setup_outcomes(s, _prices("GGG", bars)).iloc[0]
    assert r["trigger_date"] == DATES[3] and r["fill_date"] == DATES[4]
    assert r["entry_price"] == pytest.approx(103.5) and r["stop_price"] == pytest.approx(99.0)


def _synthetic_outcomes(n: int, env: str, r: float) -> pd.DataFrame:
    return pd.DataFrame({
        "queue": "vcp", "setup_id": [f"vcp:X{i}:{env}" for i in range(n)], "symbol": "X",
        "signal_date": pd.bdate_range("2025-01-01", periods=n), "fill_date": pd.bdate_range("2025-01-02", periods=n),
        "r_multiple": [r + (0.1 if i % 2 else -0.1) for i in range(n)], "hit_1r": [i % 2 == 0 for i in range(n)],
        "hit_2r": [i % 3 == 0 for i in range(n)], "mae_pct": -3.0, "mfe_pct": 6.0, "days_held": 10,
        "environment_state": env, "group_quadrant": "Leading",
    })


def test_aggregates_mark_insufficient_sample_and_print_n():
    o = pd.concat([_synthetic_outcomes(40, "Favourable", 1.0), _synthetic_outcomes(12, "Weak", -0.5)])
    agg = aggregate_setup_outcomes(o)
    fav = agg.loc[(agg["environment_state"] == "Favourable") & (agg["group_quadrant"] == "all")].iloc[0]
    weak = agg.loc[(agg["environment_state"] == "Weak") & (agg["group_quadrant"] == "all")].iloc[0]
    assert fav["n"] == 40 and not fav["insufficient_sample"] and fav["avg_r"] == pytest.approx(1.0)
    assert weak["n"] == 12 and weak["insufficient_sample"] and weak["label"] == "insufficient sample"
    assert pd.isna(weak["avg_r"]) and pd.isna(weak["hit_rate_2r"])
    tot = agg.loc[(agg["queue"] == "all") & (agg["environment_state"] == "all") & (agg["group_quadrant"] == "all")].iloc[0]
    assert tot["n"] == 52


def test_environment_calibration_ship_gate():
    o = pd.concat([_synthetic_outcomes(40, "Favourable", 1.0), _synthetic_outcomes(40, "Danger", -0.5)])
    cal = environment_calibration(o)
    gate = cal.loc[(cal["queue"] == "all") & (cal["kind"] == "ship_gate")].iloc[0]
    assert gate["n_good"] == 40 and gate["n_bad"] == 40
    assert gate["gap_r"] == pytest.approx(1.5) and bool(gate["passes"])
