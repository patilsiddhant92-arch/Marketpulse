"""Sprint 2 extras: Research trait strip + signal log/scorecard, Deals follows + Telegram followed alerts,
research_lab in the daily pipeline. Synthetic temp DBs only (never the live market DB)."""
from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from test_research_lab import DAYS, TAIL_DAY, build_db


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
def _add_setup_daily(path: Path) -> None:
    """Three synthetic Desk signals on MOVER / S01 (first_seen rows) + one 'active' follow-on row."""
    rows = []
    d0, d1 = DAYS[300], DAYS[380]
    con = duckdb.connect(str(path))
    c0 = con.execute("SELECT close_price FROM indicators_daily WHERE symbol='MOVER' AND trade_date=?", [d0.date()]).fetchone()[0]
    c1 = con.execute("SELECT close_price FROM indicators_daily WHERE symbol='S01' AND trade_date=?", [d1.date()]).fetchone()[0]
    last = con.execute("SELECT close_price FROM indicators_daily WHERE symbol='S02' AND trade_date=?", [TAIL_DAY.date()]).fetchone()[0]
    rows.append({"trade_date": d0, "queue": "vcp", "symbol": "MOVER", "setup_id": f"vcp:MOVER:{d0:%Y%m%d}", "first_seen": d0,
                 "status": "new", "close_price": c0, "trigger_price": c0 * 1.02, "stop_price": c0 * 0.95, "risk_pct": 5.0,
                 "rs_percentile": 90.0, "adv_cr": 10.0, "mcap_cr": 5000.0, "features": "{}"})
    rows.append({"trade_date": DAYS[301], "queue": "vcp", "symbol": "MOVER", "setup_id": f"vcp:MOVER:{d0:%Y%m%d}", "first_seen": d0,
                 "status": "active", "close_price": c0, "trigger_price": c0, "stop_price": c0, "risk_pct": 1.0,
                 "rs_percentile": 90.0, "adv_cr": 10.0, "mcap_cr": 5000.0, "features": "{}"})
    rows.append({"trade_date": d1, "queue": "darvas_10ema", "symbol": "S01", "setup_id": f"darvas_10ema:S01:{d1:%Y%m%d}",
                 "first_seen": d1, "status": "new", "close_price": c1, "trigger_price": c1 * 1.01, "stop_price": None,
                 "risk_pct": None, "rs_percentile": 70.0, "adv_cr": 10.0, "mcap_cr": 5000.0,
                 "features": '{"flavor": "Catch-up"}'})
    rows.append({"trade_date": TAIL_DAY, "queue": "darvas_squeeze", "symbol": "S02", "setup_id": f"darvas_squeeze:S02:{TAIL_DAY:%Y%m%d}",
                 "first_seen": TAIL_DAY, "status": "new", "close_price": last, "trigger_price": last * 1.03,
                 "stop_price": last * 0.97, "risk_pct": 3.0, "rs_percentile": 60.0, "adv_cr": 10.0, "mcap_cr": 5000.0,
                 "features": "{}"})
    df = pd.DataFrame(rows)
    con.register("_s", df)
    con.execute("CREATE OR REPLACE TABLE setup_daily AS SELECT * FROM _s")
    con.unregister("_s")
    con.close()


@pytest.fixture(scope="module")
def market_db(tmp_path_factory) -> Path:
    p = build_db(tmp_path_factory.mktemp("extras") / "market.duckdb")
    _add_setup_daily(p)
    return p


@pytest.fixture()
def env(market_db, tmp_path, monkeypatch):
    monkeypatch.setenv("MP_DB_PATH", str(market_db))
    monkeypatch.setenv("MP_RESEARCH_DB_PATH", str(tmp_path / "research_lab.duckdb"))
    monkeypatch.setenv("MP_USER_DB_PATH", str(tmp_path / "user.duckdb"))
    monkeypatch.setenv("MP_STATUS_PATH", str(tmp_path / "status.json"))
    monkeypatch.setenv("MP_HOLIDAYS_PATH", str(tmp_path / "no_holidays.json"))
    from App.services import db, research_lab

    db.clear_cache()
    research_lab.clear_big_cache()
    yield tmp_path
    db.clear_cache()
    research_lab.clear_big_cache()


@pytest.fixture()
def client(env):
    from App.api.v2 import create_app

    return TestClient(create_app())


# --------------------------------------------------------------------------
# 1. Trait strip
# --------------------------------------------------------------------------
def _fake_profile(monkeypatch):
    """The synthetic DB has too few resolved lifts for real cuts: give every trait a fixed cut."""
    from App.services import research_premove as pm, research_traits as rt

    prof = [{"trait": k, "label": label, "group": label[0], "n": 99, "runner_median": 1.0, "fizzle_median": 0.0,
             "low_third_pct": 10.0, "high_third_pct": 30.0, "better_when": "high" if i % 2 else "low",
             "lift": round(2.0 - i / 100, 2), "cut_low": 0.0, "cut_high": 0.0} for i, (k, label) in enumerate(pm.TRAITS.items())]
    monkeypatch.setattr(rt, "_family_profile", lambda E, end, days, family: (prof, 20.0, 99))


def test_family_profile_uses_only_resolved_lifts_of_the_family():
    from App.services import research_traits as rt

    days = [d.date() for d in pd.bdate_range("2024-01-01", periods=400)]
    rng = np.random.default_rng(1)
    n = 300
    E = pd.DataFrame({"trade_date": pd.to_datetime([days[i] for i in rng.integers(0, 380, n)]),
                      "family": np.where(np.arange(n) % 3 == 0, "turnaround", "trend"),
                      "outcome": rng.choice(["runner", "fizzle", "middle"], n)})
    from App.services.research_premove import TRAITS

    for k in TRAITS:
        E[k] = rng.normal(size=n) if k in ("d_rsi14", "b_range_50d") else np.nan
    prof, base, n_study = rt._family_profile(E, days[-1], days, "trend")
    ei = len(days) - 1
    idx = {pd.Timestamp(x): i for i, x in enumerate(days)}
    want = E[(E.family == "trend") & E.outcome.isin(["runner", "fizzle"]) &
             (E.trade_date.map(idx).apply(lambda i: ei - i >= 120))]
    assert n_study == len(want)
    assert base == pytest.approx((want.outcome == "runner").mean() * 100)
    assert {p["trait"] for p in prof} == {"d_rsi14", "b_range_50d"}


def test_trait_strip_endpoint(client, monkeypatch):
    _fake_profile(monkeypatch)
    r = client.get("/api/v2/research/case-study/MOVER/traits")
    assert r.status_code == 200, r.text[:400]
    body = r.json()
    ctx = body["meta"]["context"]
    assert "not advice" in ctx["caveat"]
    cols = ctx["columns"]
    assert 2 <= len(cols) <= 14 and cols[-1]["label"] in ("lift", "now")
    assert [c["date"] for c in cols] == sorted(c["date"] for c in cols)
    assert ctx["lift"]["family"] in ("trend", "turnaround")
    assert body["rows"], "profile traits expected"
    for row in body["rows"]:
        assert len(row["values"]) == len(row["on"]) == len(cols)
        assert row["group"] in "DWMAIB"
        assert row["weeks_on"] <= row["weeks_known"] <= len(cols) - 1
    assert len(ctx["score"]) == len(cols) and max(ctx["score"]) <= ctx["score_max"]
    groups = [g["group"] for g in ctx["groups"]]
    assert groups == sorted(groups, key="DWMAIB".index)


def test_trait_strip_on_rule_and_point_in_time(env, monkeypatch):
    from App.services import research_traits as rt

    _fake_profile(monkeypatch)
    assert rt._is_on(5.0, "high", 1.0, 4.0) is True
    assert rt._is_on(3.0, "high", 1.0, 4.0) is False
    assert rt._is_on(0.5, "low", 1.0, 4.0) is True
    assert rt._is_on(float("nan"), "low", 1.0, 4.0) is None
    as_of = DAYS[330].date()
    res = rt.trait_strip.uncached(as_of, "MOVER")
    assert res.status == "ok", res.reason
    assert all(pd.Timestamp(c["date"]).date() <= as_of for c in res.extra["columns"])


def test_trait_strip_unknown_symbol(client, monkeypatch):
    _fake_profile(monkeypatch)
    body = client.get("/api/v2/research/case-study/NOPE/traits").json()
    assert body["meta"]["status"] == "unavailable" and body["rows"] == []


# --------------------------------------------------------------------------
# 2. Signal log: grading maths
# --------------------------------------------------------------------------
def _bars(closes, opens=None, highs=None, lows=None, start="2025-01-01", gap_after=None):
    n = len(closes)
    dates = list(pd.bdate_range(start, periods=n))
    if gap_after is not None:
        dates = dates[:gap_after + 1] + [d + pd.Timedelta(days=40) for d in dates[gap_after + 1:]]
    c = np.array(closes, dtype=float)
    return pd.DataFrame({"symbol": "X", "trade_date": dates, "open_price": opens or list(c), "high_price": highs or list(c * 1.01),
                         "low_price": lows or list(c * 0.99), "close_price": list(c)})


def _sig(bars, stop=None, trigger=None, i=0):
    return pd.DataFrame([{"setup_id": "s1", "symbol": "X", "trade_date": bars.trade_date[i], "signal_close": bars.close_price[i],
                          "trigger_price": trigger, "stop_price": stop}])


def test_grade_r_multiple_and_excess():
    from App.services.research_signals import grade_frame

    closes = [100 + k for k in range(25)]  # +1 a day, never near the stop
    b = _bars(closes)
    ew = pd.Series([100.0 * (1.001 ** k) for k in range(25)], index=b.trade_date)
    g = grade_frame(_sig(b, stop=95.0, trigger=103.0), b, ew).iloc[0]
    assert g.ret_5 == pytest.approx(5.0)
    assert g.r_5 == pytest.approx(1.0)        # +5 on 5 of risk
    assert g.r_20 == pytest.approx(4.0)
    assert g.stopped_20 is False or g.stopped_20 == False  # noqa: E712
    assert g.excess_10 == pytest.approx(10.0 - (1.001 ** 10 - 1) * 100)
    assert g.triggered_5 and g.date_20 == b.trade_date[20].date()


def test_grade_stop_fills_at_gap_down_open():
    from App.services.research_signals import grade_frame

    closes = [100, 101, 102, 90, 91, 92, 93, 94, 95, 96, 97] + [98] * 12
    opens = list(map(float, closes))
    opens[3] = 90.0  # gaps below the 95 stop
    lows = [c * 0.99 for c in closes]
    b = _bars(closes, opens=opens, lows=lows)
    g = grade_frame(_sig(b, stop=95.0), b, None).iloc[0]
    assert g.stopped_5 and g.r_5 == pytest.approx((90 - 100) / 5)  # filled at the open, not the stop
    assert g.excess_5 is None  # no EW market -> no excess
    assert g.triggered_5 is None  # no trigger


def test_grade_skips_windows_across_a_calendar_gap_and_unfinished_windows():
    from App.services.research_signals import grade_frame

    b = _bars([100.0] * 15, gap_after=7)
    g = grade_frame(_sig(b, stop=90.0), b, None).iloc[0]
    assert g.date_5 is not None and g.r_5 == pytest.approx(0.0)
    assert pd.isna(g.date_10) and g.grade_note == "gap"
    assert pd.isna(g.date_20)


# --------------------------------------------------------------------------
# 2. Signal log: pipeline write (insert-once) + API read (point in time)
# --------------------------------------------------------------------------
def test_signal_log_insert_once_and_api(env, client, market_db, monkeypatch):
    import Scripts.research_lab as script

    out = env / "research_lab.duckdb"
    assert script.main(["--out", str(out)]) == 0
    con = duckdb.connect(str(out), read_only=True)
    log = con.execute("SELECT * FROM research_signal_log ORDER BY trade_date").df()
    con.close()
    assert len(log) == 3  # the 'active' follow-on row is not a signal
    assert log.logged.tolist() == ["backfill", "backfill", "live"]
    assert log.flavor.tolist()[1] == "Catch-up"
    mover = log.iloc[0]
    assert not pd.isna(mover.date_20) and mover.r_20 is not None
    # rebuilding setup_daily with a different stop must not rewrite the logged signal
    tmp = env / "market_copy.duckdb"
    shutil.copy(market_db, tmp)
    w = duckdb.connect(str(tmp))
    w.execute("UPDATE setup_daily SET stop_price = 1.0 WHERE symbol = 'MOVER'")
    w.close()
    monkeypatch.setenv("MP_DB_PATH", str(tmp))
    from App.services import db

    db.clear_cache()
    res = script.update_signal_log(out)
    assert res["signals_added"] == 0
    con = duckdb.connect(str(out), read_only=True)
    stop = con.execute("SELECT stop_price FROM research_signal_log WHERE symbol='MOVER'").fetchone()[0]
    con.close()
    assert stop == pytest.approx(mover.stop_price)
    monkeypatch.setenv("MP_DB_PATH", str(market_db))
    db.clear_cache()

    body = client.get("/api/v2/research/signal-log?days=3650").json()
    assert body["total"] == 3 and body["rows"][0]["trade_date"] == TAIL_DAY.date().isoformat()
    sc = client.get("/api/v2/research/signal-scorecard").json()
    assert {r["setup"] for r in sc["rows"]} == {"vcp", "darvas_10ema:Catch-up", "darvas_squeeze"}
    assert "not advice" in sc["meta"]["context"]["caveat"] and sc["meta"]["context"]["monthly"]
    # time travel: 3 sessions after the MOVER signal its 5-session grade is hidden
    as_of = DAYS[303].date().isoformat()
    tt = client.get(f"/api/v2/research/signal-log?as_of={as_of}&days=3650&setup=vcp").json()
    assert tt["total"] == 1 and tt["rows"][0]["r_5"] is None and tt["rows"][0]["ret_20"] is None
    assert client.get("/api/v2/research/signal-log?setup=bogus").status_code == 422


def test_signal_endpoints_unavailable_without_log(client):
    body = client.get("/api/v2/research/signal-scorecard").json()
    assert body["meta"]["status"] == "unavailable" and "research_lab.py" in body["meta"]["reason"]


# --------------------------------------------------------------------------
# 3. Deals follows (user DB) + Telegram
# --------------------------------------------------------------------------
def test_follow_endpoints_round_trip(client, env):
    assert client.get("/api/v2/deals/follows").json()["rows"] == []
    r = client.post("/api/v2/deals/follows", json={"house": "SBI Mutual Fund", "name": "Sbi Mutual Fund"})
    assert r.status_code == 200
    assert [x["house"] for x in r.json()["rows"]] == ["SBI MUTUAL FUND"]
    r = client.post("/api/v2/deals/follows", json={"house": "sbi mutual fund pvt ltd"})  # same house key
    assert len(r.json()["rows"]) == 1
    client.post("/api/v2/deals/follows", json={"house": "GOLDMAN SACHS FUNDS - GOLDMAN SACHS INDIA"})
    rows = client.get("/api/v2/deals/follows").json()["rows"]
    assert len(rows) == 2
    r = client.delete("/api/v2/deals/follows", params={"house": "SBI MUTUAL FUND"})
    assert [x["house"] for x in r.json()["rows"]] == [rows[1]["house"]]
    assert client.delete("/api/v2/deals/follows", params={"house": "SBI MUTUAL FUND"}).status_code == 200  # idempotent
    assert client.post("/api/v2/deals/follows", json={"house": "  "}).status_code == 422
    assert client.post("/api/v2/deals/follows", json={"house": "X", "extra": 1}).status_code == 422
    # stored in the user DB, not the market DB
    from App.services import deals_follow

    assert deals_follow.followed_keys(env / "user.duckdb") == {rows[1]["house"]}
    con = duckdb.connect(str(Path(env / "user.duckdb")), read_only=True)
    assert con.execute("SELECT count(*) FROM v2_followed_houses").fetchone()[0] == 1
    con.close()


def _row(sym, cls="FII", grade="good", strong=True, event="fresh", net=40.0, house="SBI MUTUAL FUND", since=0, status=None):
    return {"symbol": sym, "event_type": event, "net_cr": net, "strong_chart": strong, "deal_price": 100.0, "close": 101.0,
            "vs_deal_pct": 1.0, "sessions_since": since, "status": status, "verdict": "watch", "gross_cr": net,
            "buyers": [{"name": house.title(), "house": house, "buyer_class": cls, "value_cr": net, "grade": grade}]}


def _core(today, watch=()):
    return {"as_of": "2026-08-13", "deal_session": "2026-08-13", "today": list(today), "watch": list(watch),
            "skipped": {"transfer": 1, "churn": 2, "small": 3}, "above50_pct": 55.0}


def test_followed_alerts_follow_the_evidence_rule():
    from telegram_deals import followed_alerts

    f = {"SBI MUTUAL FUND"}
    core = _core([
        _row("AAA"),                                   # followed, good FII, strong chart, net buy -> alert
        _row("BBB", grade="mixed"),                    # not a good record -> no alert
        _row("CCC", strong=False),                     # weak chart -> no alert
        _row("DDD", cls="CORPORATE", grade="ungraded"),  # corporate -> never
        _row("EEE", event="churn"),                    # churn -> no
        _row("FFF", house="OTHER HOUSE"),              # good FII but not followed -> not in this section
    ], watch=[_row("GGG", since=3, status="holding"), _row("HHH", since=3, status="lost", grade="poor")])
    fa = followed_alerts(core, f)
    assert [x["symbol"] for x in fa["day0"]] == ["AAA"]
    assert fa["skipped"] == 4
    assert [x["symbol"] for x in fa["day3"]] == ["GGG"]
    assert followed_alerts(core, set()) == {"day0": [], "day3": [], "skipped": 0}


def test_digest_stays_one_message_with_followed_section(tmp_path):
    from telegram_deals import DIGEST_MAX_CHARS, format_deals_digest

    many = [_row(f"SYM{i:02d}", house="SBI MUTUAL FUND") for i in range(30)]
    text = format_deals_digest(_core(many, [_row("GGG", since=3, status="holding")]), followed={"SBI MUTUAL FUND"})
    assert isinstance(text, str) and len(text) <= DIGEST_MAX_CHARS
    assert text.count("📊 Deals") == 1
    assert "⭐ Followed houses" in text and "SYM00" in text and "Day 3: GGG holding" in text
    plain = format_deals_digest(_core(many))
    assert "⭐" not in plain


def test_build_digest_reads_follows_from_user_db(tmp_path, monkeypatch):
    import telegram_deals as tg

    user = tmp_path / "marketpulse_user.duckdb"
    assert tg.load_followed(user) == set()
    con = duckdb.connect(str(user))
    con.execute("CREATE TABLE v2_followed_houses (house VARCHAR PRIMARY KEY, name VARCHAR, added_at TIMESTAMP)")
    con.execute("INSERT INTO v2_followed_houses VALUES ('SBI MUTUAL FUND', 'Sbi', now())")
    con.close()
    assert tg.load_followed(user) == {"SBI MUTUAL FUND"}
    monkeypatch.setenv("MP_USER_DB_PATH", str(user))
    assert tg.load_followed() == {"SBI MUTUAL FUND"}


# --------------------------------------------------------------------------
# 4. research_lab in the daily pipeline (temp DB copy only)
# --------------------------------------------------------------------------
@pytest.fixture
def pipe(tmp_path, monkeypatch, market_db):
    import daily_pipeline as dp

    dbdir = tmp_path / "Database"
    dbdir.mkdir()
    copy = dbdir / "marketpulse.duckdb"
    shutil.copy(market_db, copy)
    monkeypatch.setattr(dp, "LOGS_DIR", tmp_path / "Logs")
    monkeypatch.setattr(dp, "DATABASE_DIR", dbdir)
    monkeypatch.setattr(dp, "STATUS_PATH", dbdir / "status.json")
    monkeypatch.setattr(dp, "DB_PATH", copy)
    monkeypatch.setattr(dp, "_backup_user_db", lambda: None)
    monkeypatch.setattr(dp, "_required_bhav_present", lambda session_dir, day: (True, "bhav.csv"))
    monkeypatch.setattr(dp, "_run_append", lambda: {"action": "noop"})
    monkeypatch.setattr(dp, "process_accepted_session", lambda *a, **k: {"score_version": "s", "trade_date": "x", "decision_rows": 0})
    monkeypatch.delenv("MP_RESEARCH_DB_PATH", raising=False)
    from App.services import db, research_lab

    db.clear_cache()
    research_lab.clear_big_cache()
    return dp, copy


def _status(dp) -> dict:
    import json

    return json.loads(dp.STATUS_PATH.read_text(encoding="utf-8"))


def test_pipeline_runs_research_lab_on_the_db_copy(pipe, monkeypatch):
    dp, copy = pipe
    monkeypatch.delenv("MP_SKIP_RESEARCH_LAB", raising=False)
    before = (copy.stat().st_mtime_ns, copy.stat().st_size)
    rc = dp.run_pipeline(skip_download=True, skip_telegram=True, skip_taxonomy=True, date=pd.Timestamp(DAYS[-1]).to_pydatetime())
    assert rc == 0
    step = next(s for s in _status(dp)["steps"] if s["step"] == "research_lab")
    assert step["ok"] is True, step
    side = copy.parent / "research_lab.duckdb"
    assert Path(step["out"]) == side and side.exists()
    assert step["signal_log"] == 3
    assert (copy.stat().st_mtime_ns, copy.stat().st_size) == before  # the market DB copy was only read


def test_pipeline_research_skip_flag_and_env(pipe, monkeypatch):
    dp, _ = pipe
    called = []
    monkeypatch.setattr(dp, "_run_research_lab", lambda: called.append(1) or {})
    monkeypatch.delenv("MP_SKIP_RESEARCH_LAB", raising=False)
    dp.run_pipeline(skip_download=True, skip_telegram=True, skip_taxonomy=True, skip_research=True,
                    date=pd.Timestamp(DAYS[-1]).to_pydatetime())
    assert called == []
    assert {"step": "research_lab", "ok": True, "skipped": True} in _status(dp)["steps"]
    monkeypatch.setenv("MP_SKIP_RESEARCH_LAB", "1")
    dp.run_pipeline(skip_download=True, skip_telegram=True, skip_taxonomy=True, date=pd.Timestamp(DAYS[-1]).to_pydatetime())
    assert called == []


def test_pipeline_research_failure_does_not_fail_the_run(pipe, monkeypatch):
    dp, _ = pipe
    monkeypatch.delenv("MP_SKIP_RESEARCH_LAB", raising=False)

    def boom():
        raise SystemExit("market DB has no sessions")

    monkeypatch.setattr(dp, "_run_research_lab", boom)
    rc = dp.run_pipeline(skip_download=True, skip_telegram=True, skip_taxonomy=True, date=pd.Timestamp(DAYS[-1]).to_pydatetime())
    assert rc == 0
    step = next(s for s in _status(dp)["steps"] if s["step"] == "research_lab")
    assert step["ok"] is False and "no sessions" in step["error"]


def test_pipeline_cli_has_skip_research_flag(monkeypatch):
    import sys

    import daily_pipeline as dp

    seen = {}
    monkeypatch.setattr(dp, "run_pipeline", lambda **k: seen.update(k) or 0)
    monkeypatch.setattr(sys, "argv", ["daily_pipeline.py", "--skip-research", "--retries", "1"])
    assert dp.main() == 0 and seen["skip_research"] is True
