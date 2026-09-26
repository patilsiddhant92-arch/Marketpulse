from __future__ import annotations

import math

from App.api.server import _opt_float, _opt_str, cockpit_row


BASE = {
    "symbol": "lloydsme", "sector": "Metals", "cmp": 1838.3, "open_price": 1800.0,
    "day_pct": 0.88, "trigger_price": 1859.4, "stop_loss": 1805.55, "risk_pct": 2.98,
    "rvol": 0.7, "rs_percentile": float("nan"), "delivery_pct": 41.2, "why_now": "box",
    "squeeze_pct": 1.2, "market_cap_cr": 9000.0,
}


def test_opt_float_keeps_missing_as_none():
    assert _opt_float(None) is None
    assert _opt_float(float("nan")) is None
    assert _opt_float("x") is None
    assert _opt_float(0.00001, 4) == 0.0
    assert _opt_float(2.3456) == 2.35


def test_change_is_vs_previous_close_not_intraday():
    row = cockpit_row(BASE, "darvas_squeeze")
    assert row["change_1d_pct"] == 0.88


def test_distance_is_derived_from_trigger_and_close():
    row = cockpit_row(BASE, "darvas_squeeze")
    assert math.isclose(row["dist_to_pivot_pct"], (1859.4 / 1838.3 - 1) * 100, abs_tol=0.01)
    assert row["symbol"] == "LLOYDSME"


def test_no_fabricated_defaults():
    row = cockpit_row({**BASE, "risk_pct": None, "trigger_price": None, "stop_loss": None, "rvol": None}, "vcp")
    assert row["risk_pct"] is None
    assert row["trigger_price"] is None
    assert row["dist_to_pivot_pct"] is None
    assert row["rvol"] is None
    assert row["rs_percentile"] is None
    assert "reward_to_risk" not in row


def test_darvas_10ema_geometry_is_null_until_redefined():
    row = cockpit_row(BASE, "darvas_10ema")
    assert row["trigger_price"] is None
    assert row["invalidation_price"] is None
    assert row["risk_pct"] is None
    assert row["dist_to_pivot_pct"] is None


def test_blank_symbol_is_skipped():
    assert cockpit_row({**BASE, "symbol": " "}, "vcp") is None


def test_opt_str_keeps_missing_as_none():
    assert _opt_str(None) is None
    assert _opt_str(float("nan")) is None
    assert _opt_str("  ") is None
    assert _opt_str(" Metals ") == "Metals"


def test_nan_sector_and_why_now_do_not_become_the_string_nan():
    row = cockpit_row({**BASE, "sector": float("nan"), "why_now": float("nan")}, "vcp")
    assert row["sector"] is None
    assert row["why_now"] == ""
