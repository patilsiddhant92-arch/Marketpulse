"""Pulse tab (HarkPro/02-tab1-pulse.md): pure rules + live-DB smoke (read-only, skipped without the DB)."""
from __future__ import annotations

import math
import os
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from App.services import pulse

ROOT = Path(__file__).resolve().parents[1]
GOOD_SESSION = "2026-08-13"  # last session before the committed-data gap (HarkPro/05-data-gaps.md #2)


# --------------------------------------------------------------------------- pure rules
def test_expanding_pctl_is_point_in_time():
    a = [10, 20, 15, np.nan, 30, 5]
    out = pulse.expanding_pctl(a)
    assert out[0] == 0.0                      # alone: nothing below
    assert out[1] == pytest.approx(50.0)      # 10 < 20, 1 of 2
    assert out[2] == pytest.approx(100 / 3)   # 10 < 15 of [10,20,15]
    assert math.isnan(out[3])
    assert out[4] == pytest.approx(75.0)      # 3 of 4
    assert out[5] == 0.0
    # adding a future value never changes the past
    assert list(pulse.expanding_pctl(a + [1000])[:5])[:3] == list(out[:3])


def test_mood_labels_bands():
    assert pulse.mood_label(70)[0] == "Strong"
    assert pulse.mood_label(69.9)[0] == "Healthy"
    assert pulse.mood_label(55)[0] == "Healthy"
    assert pulse.mood_label(54.9)[0] == "Mixed"
    assert pulse.mood_label(45)[0] == "Mixed"
    assert pulse.mood_label(44)[0] == "Weak"
    assert pulse.mood_label(30)[0] == "Weak"
    assert pulse.mood_label(29.9)[0] == "Very weak"
    assert pulse.mood_label(None) == (None, None)


def test_direction_qualifier():
    assert pulse.direction_qualifier(40, 51) == "cooling"
    assert pulse.direction_qualifier(40, 50) is None
    assert pulse.direction_qualifier(61, 50) == "improving"
    assert pulse.direction_qualifier(None, 50) is None


@pytest.mark.parametrize("mood,chg,rule", [
    (74, -15, "strong_but_cooling"),
    (55, -10.5, "strong_but_cooling"),
    (50, -11, "cooling"),
    (40, -11, "cooling"),
    (40, -5, "weak"),
    (50, 3, "mixed"),
    (54.9, None, "mixed"),
    (55, -10, "healthy"),   # exactly -10 is not "more than 10"
    (80, 12, "healthy"),
])
def test_action_rules_first_match_wins(mood, chg, rule):
    assert pulse.choose_action(mood, chg) == rule
    assert pulse.ACTIONS[rule].endswith(".")


def test_action_texts_follow_style():
    for text in pulse.ACTIONS.values():
        assert ";" not in text
        for sentence in text.split(". "):
            assert len(sentence.split()) <= 20


def test_xp_thresholds_and_flag():
    rel = np.r_[np.linspace(-0.05, 0.05, 100)]
    th = pulse.xp_thresholds(rel)
    assert th == (-0.15, 0.15)  # floors win when the history is calm
    wide = np.r_[np.linspace(-0.6, 0.6, 200)]
    lo, hi = pulse.xp_thresholds(wide)
    assert lo < -0.5 and hi > 0.5
    assert pulse.xp_thresholds(rel[:10]) is None  # too little history
    assert pulse.xp_flag(0.5, 250, (-0.15, 0.15)) == 1
    assert pulse.xp_flag(0.5, 90, (-0.15, 0.15)) == 0      # fewer than 100 stocks
    assert pulse.xp_flag(-0.3, -150, (-0.15, 0.15)) == -1
    assert pulse.xp_flag(-0.3, -150, None) == 0


def _synthetic(n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    d0 = date(2024, 1, 1)
    days = [d0 + timedelta(days=i) for i in range(n)]
    e = np.clip(50 + np.cumsum(rng.normal(0, 3, n)), 5, 95)
    df = pd.DataFrame({
        "d": days, "stocks": 2000.0, "adv_n": 1000 + rng.integers(-300, 300, n), "decl_n": 1000.0,
        "upvol": rng.uniform(30, 70, n), "e10": e, "e20": e, "e50": e * 0.9, "e100": e * 0.8, "e200": e * 0.7,
        "nh": rng.integers(0, 100, n), "nl": rng.integers(0, 50, n), "st2": rng.uniform(5, 15, n),
        "ft": rng.uniform(30, 60, n), "vix": rng.uniform(10, 20, n), "tov": rng.uniform(8e4, 1.2e5, n),
        "dlv": rng.uniform(3e4, 4e4, n), "ewret": rng.normal(0.001, 0.01, n),
    })
    # one clear 20 EMA expansion on day 100: 25% -> 60% of 2000 stocks
    df.loc[99, ["e20"]] = 25.0
    df.loc[100, ["e20"]] = 60.0
    return df


def test_derive_and_ctx_point_in_time():
    raw = _synthetic()
    full = pulse.derive(raw)
    cut = pulse.derive(raw.iloc[:80])
    for col in ("mood", "e10_pctl", "e20_sd", "tov_avg20", "ew"):
        a, b = full[col].iloc[:80].to_numpy(), cut[col].to_numpy()
        assert np.allclose(a, b, equal_nan=True), col
    ctx = pulse.Ctx(full, raw["d"].iloc[100])
    assert ctx.L == 100
    assert ctx.flag("e20", 100) == 1
    assert ctx.at("e20_n", 100) == pytest.approx(1200)
    ev = [e for e in ctx.events() if e["k"] == "e20" and e["i"] == 100]
    assert ev and ev[0]["f"] == 1
    assert ctx.fwd(100, 10) is None  # no look-ahead past as_of
    assert pulse.Ctx(full, raw["d"].iloc[119]).fwd(100, 10) is not None


def test_commentary_numbers_and_flag_sentence():
    raw = _synthetic()
    full = pulse.derive(raw)
    ctx = pulse.Ctx(full, raw["d"].iloc[100])
    com = pulse.commentary(ctx, 5, [])
    first = com["lines"][0]
    assert first["kind"] == "flag" and first["lead"] == "Breadth expansion."
    assert "from 500 to 1,200 (+140%)" in first["text"]
    short = next(x for x in com["lines"] if x["kind"] == "short")
    assert f"{ctx.at('e10', 100):.0f}%" in short["text"]
    for line in com["lines"]:
        assert ";" not in line["text"]


def test_gap_detection():
    raw = _synthetic(80)
    raw.loc[79, "d"] = raw.loc[78, "d"] + timedelta(days=40)
    full = pulse.derive(raw)
    ctx = pulse.Ctx(full, raw["d"].iloc[79])
    assert bool(full["gap_before"].iloc[79])
    assert ctx.gap_warning(5) and "Data gap" in ctx.gap_warning(5)
    assert ctx.flag("e20", 79) == 0  # no flags across a gap


def test_chips():
    d = date(2026, 8, 13)
    r = {"symbol": "AAA", "h52": True, "listing_date": date(2026, 1, 2), "band": "GSM STAGE - 0", "adr": 2.0, "x10": 7.0}
    assert pulse.chips_for(r, d, {"AAA"}) == ["DEAL", "52W", "IPO", "BAND", "EXT"]
    r2 = {"symbol": "BBB", "h52": False, "listing_date": date(2020, 1, 1), "band": "-", "adr": 3.0, "x10": 7.0}
    assert pulse.chips_for(r2, d, {"AAA"}) == []


def test_lookback_validation():
    with pytest.raises(ValueError):
        pulse._lb(7)


# --------------------------------------------------------------------------- live DB
def _live_db() -> Path:
    env = os.environ.get("MP_DB_PATH", "").strip()
    return Path(env) if env else ROOT / "Database" / "marketpulse.duckdb"


@pytest.fixture(scope="module")
def client():
    if not _live_db().exists():
        pytest.skip("live market DB not available")
    from fastapi.testclient import TestClient
    from App.api.v2 import create_app

    return TestClient(create_app())


def _get(client, path, **q):
    q.setdefault("as_of", GOOD_SESSION)
    r = client.get(f"/api/v2/pulse/{path}", params=q)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["meta"]["status"] in ("ok", "partial"), body["meta"]
    return body


@pytest.mark.parametrize("lb", [5, 10, 20, 60, 250])
def test_live_summary(client, lb):
    body = _get(client, "summary", lookback=lb)
    row = body["rows"][0]
    assert body["as_of"] == GOOD_SESSION
    assert 0 <= row["mood"] <= 100
    assert row["mood_label"] == pulse.mood_label(row["mood"])[0]
    assert row["action"] == pulse.ACTIONS[row["action_rule"]]
    assert len(row["mood_series"]) == max(lb, 20) + 1
    assert 4 <= len(row["commentary"]) <= 6


def test_live_commentary_matches_breadth(client):
    s = _get(client, "summary", lookback=5)["rows"][0]
    b = _get(client, "breadth", lookback=5)
    e50 = next(x for x in b["meta"]["context"]["stats"] if x["key"] == "e50")
    medium = next(x for x in s["commentary"] if x["kind"] == "medium")
    assert f"{e50['today']:.0f}% of stocks" in medium["text"]
    assert f"on {e50['pctl']:.0f}% of days" in medium["text"]


def test_live_breadth_counts(client):
    b = _get(client, "breadth", lookback=10)
    last = b["rows"][-1]
    for k in pulse.EMA_KEYS:
        assert last[k]["count"] == pytest.approx(last[k]["pct"] * last["stocks"] / 100, abs=1)
        assert 0 <= last[k]["count"] <= last["stocks"]
    stats = b["meta"]["context"]["stats"]
    assert all(s["min"] <= s["p10"] <= s["p90"] <= s["max"] for s in stats)


def test_live_expansions_reproduce(client):
    body = _get(client, "expansions", limit=200)
    th = {t["key"]: t for t in body["meta"]["context"]["thresholds"]}
    for r in body["rows"]:
        t = th[r["shown_key"]]
        if r["dir"] > 0:
            assert r["rel_pct"] >= t["hi_pct"] - 0.1
        else:
            assert r["rel_pct"] <= t["lo_pct"] + 0.1
    e20 = next(s for s in body["meta"]["context"]["stats"] if s["key"] == "e20")
    assert e20["expansions"]["n"] > 0


def test_live_movers_floor(client):
    for kind in pulse.MOVER_KINDS:
        body = _get(client, "movers", kind=kind)
        assert 0 < len(body["rows"]) <= 20
        assert all(r["mcap_cr"] >= 1000 for r in body["rows"])
        ctx = body["meta"]["context"]
        assert ctx["universe_floor"] <= ctx["universe_all"]
    g = _get(client, "movers", kind="gainers")["rows"]
    assert g == sorted(g, key=lambda r: -r["chg_1d_pct"])


def test_live_groups_flow_analogs_internals(client):
    for level in ("sector", "industry", "sectoral", "thematic"):
        assert _get(client, "groups", level=level)["rows"]
    f = _get(client, "flow", lookback=20)
    assert len(f["rows"]) == 20 and f["meta"]["context"]["sectors"]
    a = _get(client, "analogs")
    assert len(a["rows"]) == 8
    assert all(r["trade_date"] < "2026-07-08" for r in a["rows"])  # latest 25 sessions excluded
    i = _get(client, "internals", lookback=10)
    assert [r["key"] for r in i["rows"]] == ["adv", "upvol", "nn", "st2", "ft", "vix"]


def test_live_replay_has_no_lookahead(client):
    early = _get(client, "summary", as_of="2025-06-02")["rows"][0]
    assert early["trade_date"] <= "2025-06-02"
    assert all(p["trade_date"] <= "2025-06-02" for p in early["mood_series"])
    ex = _get(client, "expansions", as_of="2025-06-02", limit=200)
    assert all(r["trade_date"] <= "2025-06-02" for r in ex["rows"])


def test_live_gap_warning_on_latest(client):
    body = client.get("/api/v2/pulse/summary").json()
    if body["as_of"] == "2026-10-08":
        assert body["rows"][0]["data_warning"]
