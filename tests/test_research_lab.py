"""Research tab studies (HarkPro/10-tab-research.md §§11-13): services, the precompute script and the
/api/v2/research/* endpoints, on a synthetic temp DB (never the live market DB)."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

N = 420
DAYS = pd.bdate_range("2024-01-01", periods=N)
TAIL_DAY = DAYS[-1] + pd.Timedelta(days=60)  # one session after a long gap (the local Aug-Oct hole)


def _stock(symbol: str, seed: int, path: str = "walk") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ret = rng.normal(0.0004, 0.016, N)
    if path == "mover":  # flat, then a +150 % run over the last 150 sessions with a few pullbacks
        ret[:N - 150] = rng.normal(-0.001, 0.01, N - 150)
        ret[N - 150:] = rng.normal(0.0065, 0.012, 150)
    close = 100 * np.exp(np.cumsum(ret))
    prev = np.r_[close[0], close[:-1]]
    high = np.maximum(close, prev) * (1 + rng.uniform(0, 0.01, N))
    low = np.minimum(close, prev) * (1 - rng.uniform(0, 0.01, N))
    vol = rng.uniform(1e5, 5e5, N)
    vol[rng.choice(N, 25, replace=False)] *= 3
    df = pd.DataFrame({"symbol": symbol, "series": "EQ", "trade_date": DAYS, "prev_close": prev,
                       "open_price": prev, "high_price": high, "low_price": low, "close_price": close, "volume": vol})
    c = df.close_price
    for span in (10, 20, 50, 100, 200):
        df[f"ema_{span}"] = c.ewm(span=span, adjust=False).mean()
    for span in (50, 150, 200):
        df[f"sma_{span}"] = c.rolling(span, min_periods=1).mean()
    df["sma_200_rising"] = df.sma_200 > df.sma_200.shift(20)
    df["ema_200_rising"] = df.ema_200 > df.ema_200.shift(20)
    df["rvol"] = df.volume / df.volume.shift(1).rolling(20, min_periods=1).mean()
    df["delivery_pct"] = rng.uniform(30, 70, N)
    df["avg_delivery_pct_20d"] = df.delivery_pct.rolling(20, min_periods=1).mean()
    df["delivery_spike"] = df.delivery_pct > 65
    df["price_up_delivery_up"] = (c > prev) & (df.delivery_pct > df.delivery_pct.shift(1))
    df["high_52w"] = df.high_price.rolling(250, min_periods=1).max()
    df["away_52w_high_pct"] = (c / df.high_52w - 1) * 100
    df["away_52w_low_pct"] = (c / c.rolling(250, min_periods=1).min() - 1) * 100
    df["away_10ema_pct"] = (c / df.ema_10 - 1) * 100
    df["rs_percentile"] = rng.uniform(1, 99, N).round()
    df["trend_template_pass_n"] = rng.integers(0, 9, N)
    df["trend_template_pass"] = df.trend_template_pass_n == 8
    df["rsi_14"] = rng.uniform(30, 80, N)
    df["rsi_14_w"] = rng.uniform(30, 80, N)
    df["rsi_14_m"] = rng.uniform(30, 80, N)
    df["nr7"] = rng.random(N) < 0.1
    df["inside_bar"] = rng.random(N) < 0.1
    df["is_vcp"] = rng.random(N) < 0.03
    df["wema_10"] = c.ewm(span=50, adjust=False).mean()
    df["wma_30"] = c.rolling(150, min_periods=1).mean()
    df["mema_10"] = c.ewm(span=210, adjust=False).mean()
    df["atr_pct"] = rng.uniform(1, 4, N)
    df["atr_pct_avg_50d"] = df.atr_pct.rolling(50, min_periods=1).mean()
    df["range_50d_pct"] = (c.rolling(50, min_periods=1).max() / c.rolling(50, min_periods=1).min() - 1) * 100
    df["avg_traded_value_cr_20d"] = (df.volume * c / 1e7).rolling(20, min_periods=1).mean()
    return df


def build_db(path: Path) -> Path:
    frames = [_stock(f"S{i:02d}", i) for i in range(14)] + [_stock("MOVER", 99, "mover")]
    d = pd.concat(frames, ignore_index=True)
    tail = d[d.trade_date == DAYS[-1]].copy()
    tail["trade_date"] = TAIL_DAY
    d = pd.concat([d, tail], ignore_index=True)
    master = pd.DataFrame({"symbol": d.symbol.unique()})
    master["security_name"] = master.symbol + " Ltd"
    master["industry"] = "Test Industry"
    master["market_cap_cr"] = 5000.0
    master.loc[master.symbol == "S13", "market_cap_cr"] = 500.0  # below the floor
    breadth = d.groupby("trade_date").apply(
        lambda x: pd.Series({"above_20ema_pct": (x.close_price > x.ema_20).mean() * 100,
                             "above_50ema_pct": (x.close_price > x.ema_50).mean() * 100,
                             "above_200ema_pct": (x.close_price > x.ema_200).mean() * 100}), include_groups=False).reset_index()
    con = duckdb.connect(str(path))
    for name, df in (("indicators_daily", d), ("stocks_master", master), ("breadth_daily", breadth)):
        con.register("_x", df)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM _x")
        con.unregister("_x")
    con.execute("ALTER TABLE indicators_daily ALTER trade_date TYPE DATE")
    con.execute("ALTER TABLE breadth_daily ALTER trade_date TYPE DATE")
    con.close()
    return path


@pytest.fixture(scope="module")
def market_db(tmp_path_factory) -> Path:
    return build_db(tmp_path_factory.mktemp("research") / "market.duckdb")


@pytest.fixture()
def env(market_db, tmp_path, monkeypatch):
    monkeypatch.setenv("MP_DB_PATH", str(market_db))
    monkeypatch.setenv("MP_RESEARCH_DB_PATH", str(tmp_path / "research_lab.duckdb"))
    monkeypatch.setenv("MP_USER_DB_PATH", str(tmp_path / "user.duckdb"))
    monkeypatch.setenv("MP_STATUS_PATH", str(tmp_path / "status.json"))
    monkeypatch.setenv("MP_HOLIDAYS_PATH", str(tmp_path / "no_holidays.json"))
    from App.services import db

    db.clear_cache()
    yield tmp_path
    db.clear_cache()


@pytest.fixture()
def client(env):
    from App.api.v2 import create_app

    return TestClient(create_app())


# --------------------------------------------------------------------------
# Study end (gap tail)
# --------------------------------------------------------------------------
def test_last_good_session_drops_short_tail_after_gap():
    from App.services.research_lab import last_good_session

    base = [date(2026, 8, 1) + timedelta(days=i) for i in range(30)]
    assert last_good_session(base) == base[-1]
    with_tail = base + [date(2026, 10, 8)]
    assert last_good_session(with_tail) == base[-1]
    long_tail = base + [date(2026, 10, 8) + timedelta(days=i) for i in range(25)]
    assert last_good_session(long_tail) == long_tail[-1]
    assert last_good_session([]) is None


def test_study_end_on_fixture_skips_gap_tail(env):
    from App.services import db, research_lab as lab

    with db.market_conn() as con:
        assert lab.study_end(con, None) == DAYS[-1].date()
        assert lab.dropped_tail(con, DAYS[-1].date()) == [TAIL_DAY.date()]
        assert lab.study_end(con, DAYS[200].date()) == DAYS[200].date()


# --------------------------------------------------------------------------
# Presets = screener rules, fresh fires, ladder
# --------------------------------------------------------------------------
def test_every_screener_rule_preset_is_studied_and_maps_to_columns():
    from App.services import research_bigmove as bm, screener

    ids = [p["id"] for p in bm.preset_specs()]
    assert ids[:-1] == [p.id for p in screener.PRESETS.values() if p.kind == "rules"]
    assert ids[-1] == "vcp_flag"
    for p in bm.preset_specs():
        for r in p["rules"]:
            assert r["field"] == "is_vcp" or r["field"] in bm.FIELD_COL
            if "ref" in r:
                assert r["ref"] in bm.FIELD_COL


def test_rules_fail_closed_on_null_and_match_screener_expressions():
    from App.services import research_bigmove as bm

    d = pd.DataFrame({"symbol": ["A", "A", "A"], "close_price": [100.0, 100.0, np.nan], "ema_200": [90.0, np.nan, 90.0],
                      "ema_10": [101.0, 100, 100], "ema_20": [100.0, 100, 100], "ema_50": [99.0, 100, 100],
                      "nr7": [False, True, False], "inside_bar": [False, False, False],
                      "high_price": [10.0, 10.0, 10.0], "high_52w": [10.0, np.nan, 9.0]})
    d = bm._derive(d)
    above = bm._rule_mask(d, {"field": "close", "op": "gt", "ref": "ema_200"})
    assert above.tolist() == [True, False, False]  # NULL ema / close fails
    # screener: (greatest - least) / close * 100
    assert d._ema_spread.iat[0] == pytest.approx(2.0)
    assert d._nr7_or_inside.tolist() == [False, True, False]
    assert d._new_52w_high.tolist() == [True, False, True]


def test_fresh_fire_needs_five_quiet_sessions_within_symbol():
    from App.services.research_bigmove import _group_prior_any

    flag = np.array([0, 1, 1, 0, 0, 0, 0, 0, 1, 1, 0], dtype=bool)
    sym = np.array([0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1])
    pos = pd.Series(sym).groupby(sym).cumcount().to_numpy()
    fresh = flag & ~_group_prior_any(flag, pos, 5)
    assert np.flatnonzero(fresh).tolist() == [1, 8, 9]  # 8: quiet 3..7; 9: first row of a new symbol


def test_ladder_enters_on_entry_fire_above_20ema_and_exits_below():
    from App.services import research_bigmove as bm

    n = 10
    x = pd.DataFrame({"trade_date": pd.bdate_range("2025-01-01", periods=n),
                      "close_price": [10, 11, 12, 13, 11, 12, 14, 15, 13, 16.0],
                      "ema_20": [10.5, 10.5, 11, 11.5, 11.5, 11.5, 12, 12.5, 13.5, 13.5]})
    for k in bm.LADDER_ENTRY:
        x["f_" + k] = False
    x.loc[0, "f_delivery_thrust"] = True   # below the 20 EMA: no entry
    x.loc[1, "f_delivery_thrust"] = True   # entry 11 -> exit 11 (day 4)
    x.loc[6, "f_vcp_flag"] = True          # entry 14 -> exit 13 (day 8)
    mv = {"low_date": x.trade_date[0]}
    legs, comp = bm.ladder(x, mv)
    assert [(leg["entry"], leg["exit"], leg["signal_id"]) for leg in legs] == [(11, 11, "delivery_thrust"), (14, 13, "vcp_flag")]
    assert comp == pytest.approx((1.0 * 13 / 14 - 1) * 100, abs=0.1)


# --------------------------------------------------------------------------
# Regime: point in time
# --------------------------------------------------------------------------
def test_regime_readings_never_use_later_sessions(env):
    from App.services import db, research_regime as rr

    with db.market_conn() as con:
        early = DAYS[300].date()
        a = rr.compute_daily(con, early)
        b = rr.compute_daily(con, DAYS[-1].date())
    b = b[b.trade_date <= pd.Timestamp(early)]
    for col in ("ew_index", "chop", "er", "adx", "ft_pct", "chop_pctile", "er_pctile", "ft_pctile", "quadrant"):
        pd.testing.assert_series_equal(a[col].reset_index(drop=True), b[col].reset_index(drop=True), check_names=False)
    assert a.quadrant.notna().sum() > 50


def test_outcomes_are_hidden_until_their_window_closes(env):
    from App.services import db, research_regime as rr

    with db.market_conn() as con:
        df = rr.compute_daily(con, DAYS[-1].date())
    t = rr._bounded(df, DAYS[350].date())
    assert t.fwd20_pct.tail(20).isna().all() and t.fwd20_pct.iloc[-21:-20].notna().all()
    assert t.next10_ft_pct.tail(15).isna().all()


# --------------------------------------------------------------------------
# Before the big moves
# --------------------------------------------------------------------------
def test_days_from_low_matches_naive():
    from App.services.research_premove import _days_from_low

    rng = np.random.default_rng(3)
    cl = rng.normal(100, 5, 300)
    got = _days_from_low(cl, np.array([0, 170]))
    for b0, b1 in ((0, 170), (170, 300)):
        for i in range(b0, b1):
            k = i - b0
            if k + 1 < 60:
                assert np.isnan(got[i])
                continue
            w = cl[max(b0, i - 119): i + 1]
            assert got[i] == len(w) - 1 - int(np.argmin(w))


def test_trait_score_counts_better_thirds():
    from App.services.research_premove import bucket_of, score

    df = pd.DataFrame({"a": [1.0, 5.0, np.nan], "b": [0.0, 9.0, 1.0]})
    picks = [{"trait": "a", "side": "high", "cut": 4.0}, {"trait": "b", "side": "low", "cut": 0.5}]
    assert score(df, picks).tolist() == [1, 1, 0]
    assert [bucket_of(s) for s in (0, 2, 3, 6, 8)] == ["0-2", "0-2", "3-4", "5-6", "7-8"]


# --------------------------------------------------------------------------
# Precompute script + endpoints
# --------------------------------------------------------------------------
def test_script_builds_tables_and_api_reads_them(env, client):
    import Scripts.research_lab as script

    out = env / "research_lab.duckdb"
    counts = script.main(["--out", str(out)])
    assert counts == 0 and out.exists()
    con = duckdb.connect(str(out), read_only=True)
    meta = dict(con.execute("SELECT key, value FROM research_lab_meta").fetchall())
    tables = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    con.close()
    assert meta["study_end"] == DAYS[-1].date().isoformat()
    assert {"research_regime_daily", "research_big_movers", "research_caught", "research_precision",
            "research_premove_events", "research_size_daily"} <= tables
    from App.services import db

    db.clear_cache()
    body = client.get("/api/v2/research/scorecard").json()
    assert body["meta"]["context"]["source"] == "prebuilt"
    assert body["as_of"] == DAYS[-1].date().isoformat()
    movers = client.get("/api/v2/research/case-study").json()
    assert "MOVER" in [r["symbol"] for r in movers["rows"]]
    assert "S13" not in [r["symbol"] for r in movers["rows"]]  # < Rs 1,000 Cr


def test_script_refuses_to_write_the_market_db(env, market_db):
    import Scripts.research_lab as script

    with pytest.raises(SystemExit):
        script.build(market_db)


RESEARCH_URLS = [
    "/api/v2/research/regime", "/api/v2/research/days-like-today", "/api/v2/research/scorecard",
    "/api/v2/research/case-study", "/api/v2/research/case-study/MOVER", "/api/v2/research/before-moves",
    "/api/v2/research/before-moves?family=turnaround", "/api/v2/research/index-study",
]


@pytest.mark.parametrize("url", RESEARCH_URLS)
def test_endpoints_return_envelopes_with_caveat(client, url):
    r = client.get(url)
    assert r.status_code == 200, r.text[:400]
    body = r.json()
    assert {"as_of", "freshness", "total", "returned", "rows", "meta"} <= set(body)
    assert "not advice" in body["meta"]["context"]["caveat"]
    assert body["as_of"] == DAYS[-1].date().isoformat()  # gap tail dropped


def test_case_study_payload(client):
    body = client.get("/api/v2/research/case-study/MOVER").json()
    ctx = body["meta"]["context"]
    assert ctx["big_mover"] is True and ctx["move"]["gain_pct"] >= 100
    assert {"time", "open", "high", "low", "close", "ema_20"} <= set(body["rows"][0])
    assert len(ctx["first_fires"]) == len(ctx["presets"])
    assert all(f["in_move"] in (True, False) for f in ctx["fires"])
    assert ctx["precision"]["rows"][0]["preset_id"] == "all"
    for leg in ctx["ladder"]["legs"]:
        assert leg["entry_date"] <= leg["exit_date"]


def test_case_study_unknown_and_bad_params(client):
    body = client.get("/api/v2/research/case-study/NOPE").json()
    assert body["meta"]["status"] == "unavailable" and body["rows"] == []
    assert client.get("/api/v2/research/case-study/bad sym!").status_code == 422
    assert client.get("/api/v2/research/before-moves?family=other").status_code == 422
    assert client.get("/api/v2/research/days-like-today?k=1").status_code == 422


def test_as_of_bounds_studies(client):
    as_of = DAYS[330].date().isoformat()
    reg = client.get(f"/api/v2/research/regime?as_of={as_of}").json()
    assert reg["as_of"] == as_of and max(r["trade_date"] for r in reg["rows"]) == as_of
    an = client.get(f"/api/v2/research/days-like-today?as_of={as_of}").json()
    cutoff = DAYS[330 - 25].date().isoformat()
    assert all(r["analog_date"] < cutoff for r in an["rows"])
    bm = client.get(f"/api/v2/research/before-moves?as_of={as_of}").json()
    assert all(r["lift_date"] <= as_of for r in bm["rows"])
