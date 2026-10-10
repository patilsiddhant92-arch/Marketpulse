"""Setups tab (HarkPro/06-tab2-setups.md, locked): pure rules + API smoke on the real DB (-m realdb)."""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from App.services import setups, setups_logic as L
from Scripts.desk_contract import DARVAS


# --------------------------------------------------------------------------- group state
def test_group_state_favour_needs_all_three():
    st, why = L.group_state(a50=65, x21=2.0, x63=1.0, r5=1.0, sh5=1.0, sh20=1.0, ew=110, ew50=100)
    assert st == L.FAVOUR and "65%" in why and "+2.0" in why
    # EW index below its 50 EMA -> not Favour
    assert L.group_state(a50=65, x21=2.0, x63=1.0, r5=1.0, sh5=1.0, sh20=1.0, ew=90, ew50=100)[0] == L.NEUTRAL


def test_group_state_caution_money_leaving_or_weak():
    st, why = L.group_state(a50=70, x21=3.0, x63=1.0, r5=-1.5, sh5=0.80, sh20=1.00, ew=110, ew50=100)
    assert st == L.CAUTION and why.startswith("Money leaving")
    st, why = L.group_state(a50=30, x21=-1.0, x63=-4.0, r5=0.5, sh5=1.0, sh20=1.0, ew=90, ew50=100)
    assert st == L.CAUTION and why.startswith("Weak")
    # share falling but group rising is not money leaving
    assert L.group_state(a50=50, x21=0.0, x63=0.0, r5=1.0, sh5=0.5, sh20=1.0, ew=1, ew50=1)[0] == L.NEUTRAL


def test_group_state_missing_history_is_neutral():
    assert L.group_state(None, None, None, None, None, None, None, None) == (L.NEUTRAL, "Not enough group history.")


# --------------------------------------------------------------------------- stock derivations
def test_delivery_streak_counts_consecutive_days_above_own_average():
    assert L.delivery_streak([40, 50, 60, 55], [45, 45, 45, 45]) == 3
    assert L.delivery_streak([40, 50, 40], [45, 45, 45]) == 0
    assert L.delivery_streak([60, None, 60], [45, 45, 45]) == 1  # NULL breaks the streak


def test_turnover_multiples_vs_own_3m_average():
    tov = [10.0] * 58 + [20.0] * 5
    m = L.turnover_multiples(tov)
    base = sum(tov) / 63
    assert m["1d"] == round(20 / base, 2)
    assert m["1w"] == round(20 / base, 2)
    assert m["1m"] == round((16 * 10 + 5 * 20) / 21 / base, 2)
    assert L.turnover_multiples([5.0] * 10) == {"1d": None, "1w": None, "1m": None}  # too short: NULL


def test_ten_ema_case_and_tier():
    assert L.ten_ema_tag("Pullback", 101, 100) == ("Retrace", "10E Retrace T1", 1)
    assert L.ten_ema_tag("Trace-back", 99, 100) == ("Retrace", "10E Retrace T2", 2)
    assert L.ten_ema_tag("Catch-up", 100, 100)[1] == "10E Catch-up T1"
    assert L.ten_ema_tag("Pullback", None, 100)[2] is None


def test_risk_and_room_to_run():
    assert L.risk_pct(100, 93) == 7.0
    assert L.risk_pct(100, 101) is None and L.risk_pct(None, 90) is None
    assert L.room_to_run(100, 110) == (10.0, False)
    assert L.room_to_run(100, 100.3) == (None, True)


def test_box_character_held_and_failed():
    top = np.full(40, 100.0)
    close = np.full(40, 99.0)
    close[10] = 101.0
    close[11] = 102.0
    close[12] = 107.0  # +5% within 10 -> held
    close[25] = 101.0
    close[26] = 99.5   # back in the box within 5 -> failed
    close[27:] = 99.0
    assert L.box_character(top, close) == (1, 1)


def test_weekly_check():
    w = [100.0] * 9 + [110.0, 110.5, 111.0]
    out = L.weekly_check(w)
    assert out["above_10w"] is True and out["tight"] is True
    assert L.weekly_check([100.0, 120.0])["above_10w"] is None


def test_squeeze_gate_failures_names_gate_and_value():
    fails = L.squeeze_gate_failures(close=100, high=101, low=99, ema10=99.5, ema10_prev=99.0, ema20=98,
                                    top=101, rvol=1.4, darvas=DARVAS)
    assert fails == ["RVOL 1.40 (needs ≤ 1)"]
    fails = L.squeeze_gate_failures(close=100, high=101, low=99, ema10=90, ema10_prev=89, ema20=88,
                                    top=101, rvol=0.5, darvas=DARVAS)
    assert len(fails) == 1 and fails[0].startswith("Squeeze 10.9%")


def test_drop_reason_order():
    kw = dict(has_bar=True, in_pool=True, low=95.0, ema10=98.0, stop=96.0)
    assert L.drop_reason(close=105.0, trigger=104.0, **kw)[0] == "broke_out"
    assert L.drop_reason(close=97.0, trigger=104.0, **kw)[0] == "hit_stop"
    assert L.drop_reason(close=97.0, trigger=104.0, **{**kw, "low": 96.5})[0] == "below_10ema"
    assert L.drop_reason(close=99.0, trigger=104.0, **{**kw, "low": 98.5})[0] == "rule_failed"
    assert L.drop_reason(has_bar=True, in_pool=False, close=1, low=1, ema10=1, trigger=2, stop=0.5)[0] == "left_pool"
    assert L.drop_reason(has_bar=False, in_pool=False, close=None, low=None, ema10=None, trigger=None, stop=None)[0] == "no_bar"


def test_percentile_and_median():
    assert L.percentile_of([1, 2, 3, 4], 3) == 75
    assert L.percentile_of([], 3) is None
    assert L.median([3, 1, 2]) == 2 and L.median([1, 2, 3, 4]) == 2.5 and L.median([None]) is None


def test_sort_key_confluence_then_state_then_rs():
    rows = [
        {"symbol": "A", "screeners": ["vcp"], "group_state": L.FAVOUR, "rs_percentile": 99},
        {"symbol": "B", "screeners": ["vcp", "momentum"], "group_state": L.CAUTION, "rs_percentile": 50},
        {"symbol": "C", "screeners": ["vcp"], "group_state": L.FAVOUR, "rs_percentile": 80},
        {"symbol": "D", "screeners": ["vcp"], "group_state": L.CAUTION, "rs_percentile": 99},
    ]
    assert [r["symbol"] for r in sorted(rows, key=L.sort_key)] == ["B", "A", "C", "D"]


def test_readout_follows_style_rules():
    counts = {"darvas_squeeze": {"today": 120, "median_20": 102, "percentile": 83},
              "momentum": {"today": 150, "median_20": None, "percentile": None}}
    out = L.readout(counts=counts, split={L.FAVOUR: 10, L.NEUTRAL: 5, L.CAUTION: 2}, total=17, confluence=3,
                    base={}, session_gap_days=56)
    assert out["lines"][0].startswith("The previous session is 56 days")
    assert 1 <= len(out["what_to_do"]) <= 3
    for s in out["lines"]:
        assert ";" not in s
        for sentence in s.split(". "):
            assert len(sentence.split()) <= 20, sentence


def test_board_params_template_switch():
    ema = setups.BoardParams().momentum_params()
    assert ema.ema10_gt_20 and not ema.sma50_gt_150 and ema.min_volume == 1_000_000 and ema.min_avg_volume_20d == 0
    sma = setups.BoardParams(template="sma", volume_mode="avg20d").momentum_params()
    assert sma.sma50_gt_150 and sma.sma200_rising and not sma.ema10_gt_20
    assert sma.min_volume == 0 and sma.min_avg_volume_20d == 1_000_000


# --------------------------------------------------------------------------- real DB smoke
@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from App.api.v2 import create_app
    return TestClient(create_app())


@pytest.mark.realdb
def test_board_real_db(client):
    r = client.get("/api/v2/setups/board", params={"as_of": "2026-08-13", "limit": 5000})
    assert r.status_code == 200
    j = r.json()
    assert j["as_of"] == "2026-08-13" and j["total"] > 100
    ctx = j["meta"]["context"]
    assert ctx["counts"]["darvas_squeeze"]["today"] == 120  # strict Squeeze unchanged
    assert ctx["readout"]["what_to_do"]
    for row in j["rows"]:
        assert row["group_state"] in ("Favour", "Neutral", "Caution") and row["group_reason"]
        assert row["market_cap_cr"] is None or row["market_cap_cr"] >= 1000
        assert not any(c["kind"] == "fno" for c in row["chips"])
    assert set(ctx["excluded_5pct_band"]).isdisjoint({x["symbol"] for x in j["rows"]})


@pytest.mark.realdb
def test_other_endpoints_real_db(client):
    assert client.get("/api/v2/setups/near-miss", params={"as_of": "2026-08-13"}).json()["total"] > 0
    d = client.get("/api/v2/setups/dropped", params={"as_of": "2026-08-13"}).json()
    assert d["meta"]["context"]["previous_session"] == "2026-08-12" and d["total"] > 0
    det = client.get("/api/v2/setups/detail/NATIONALUM", params={"as_of": "2026-08-13"}).json()
    assert det["meta"]["context"]["peers"]
    assert client.get("/api/v2/setups/detail/ZZZZNOPE", params={"as_of": "2026-08-13"}).status_code == 404


def test_bad_params_are_422(client):
    assert client.get("/api/v2/setups/board", params={"template": "xx"}).status_code == 422
    assert client.get("/api/v2/setups/detail/BAD$$").status_code == 422
    assert date  # keep import used
