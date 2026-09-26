from __future__ import annotations

import inspect

from App.api import server
from App.api.server import vcp_row

ROW = {
    "symbol": "gcsl", "cmp": 656.3, "trigger_price": 655.0, "stop_loss": 557.2,
    "pivot_price": 655.0, "stop_price": 560.0, "vdu_ratio": 0.55, "vdu_active": True,
    "risk_pct": 17.55, "pivot_distance_pct": -0.2, "rs_percentile": 88.0, "sector": "Chemicals",
    "why_now": "3T VCP (16.7% → 13.1% → 3.1% → 9.2%) · VDU ✓ · Pivot -0.2%",
}


def test_vcp_row_uses_real_vdu_and_desk_geometry():
    r = vcp_row(ROW)
    assert r["symbol"] == "GCSL"
    assert r["vdu_ratio"] == 0.55
    assert r["vdu_confirmed"] is True
    assert r["pivot_entry"] == 655.0
    assert r["stop_loss"] == 557.2
    assert r["risk_pct"] == 17.55
    assert r["dist_to_pivot_pct"] == -0.2
    assert r["wave_sequence"] == "3T VCP (16.7% → 13.1% → 3.1% → 9.2%)"
    assert r["suggested_shares_for_10k_risk"] == int(10000 / (655.0 - 557.2))


def test_vcp_row_missing_values_stay_null():
    r = vcp_row({"symbol": "abc", "cmp": 100.0, "why_now": ""})
    for key in ("vdu_ratio", "pivot_entry", "stop_loss", "risk_pct", "dist_to_pivot_pct",
                "wave_sequence", "suggested_shares_for_10k_risk"):
        assert r[key] is None, key
    assert r["vdu_confirmed"] is False


def test_vcp_row_nan_sector_is_none():
    r = vcp_row({"symbol": "abc", "cmp": 100.0, "why_now": "", "sector": float("nan")})
    assert r["sector"] is None


def test_no_fabricated_fallback_remains():
    src = inspect.getsource(server.get_vcp_screener)
    for banned in ("15% → 7% → 3%", "0.72", "cmp_val * 1.025", "cmp_val * 1.02", "0.65 if", "cmp_val * 0.96"):
        assert banned not in src, banned
