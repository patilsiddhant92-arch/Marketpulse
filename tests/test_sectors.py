"""Sector Intel service + /api/v2/sectors/* endpoints (HarkPro/07-tab-sector-intel.md) on a small fixture DB."""
from __future__ import annotations

from datetime import date, timedelta

import duckdb
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from App.services import sectors

N = 90
GAP_AFTER = 80          # sessions 0..79 are contiguous; session 80 sits ~2 months later (the local-data gap)
GROUPS = {              # broad_industry -> (sector, industry, symbols, daily drift)
    "Lead BI": ("Sec A", "Ind A", ["L1", "L2", "L3", "L4"], 0.004),
    "Lag BI": ("Sec A", "Ind B", ["G1", "G2", "G3", "G4"], -0.003),
    "Mid BI": ("Sec B", "Ind C", ["M1", "M2", "M3"], 0.0),
    "Tiny BI": ("Sec B", "Ind D", ["T1"], 0.001),
}


def _sessions() -> list[date]:
    out, d = [], date(2026, 3, 2)
    while len(out) < GAP_AFTER:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    d = out[-1] + timedelta(days=56)
    while len(out) < N:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = _sessions()
CLEAN = DAYS[GAP_AFTER - 1]
LAST = DAYS[-1]


def _build(path):
    rows, master = [], []
    rng = np.random.default_rng(7)
    for bi, (sec, ind, syms, drift) in GROUPS.items():
        for k, s in enumerate(syms):
            master.append({"symbol": s, "security_name": s + " Ltd", "broad_sector": "BS", "sector": sec,
                           "broad_industry": bi, "industry": ind, "market_cap_cr": 5000.0 + k})
            c = 100.0
            hi52 = None
            for i, d in enumerate(DAYS):
                pc = c
                c = pc * (1 + drift + rng.normal(0, 0.004))
                high = c * 1.01
                hi52 = high if hi52 is None else max(hi52, high)
                rows.append({"symbol": s, "trade_date": pd.Timestamp(d), "open_price": pc, "high_price": high,
                             "low_price": min(pc, c) * 0.99, "close_price": c, "prev_close": pc, "turnover_cr": 10.0 + k,
                             "volume": 100000, "delivery_qty": 50000.0, "delivery_pct": 50.0, "high_52w": hi52,
                             "low_52w": 50.0, "ema_10": c * 0.99, "ema_50": c * (0.95 if drift > 0 else 1.05),
                             "ema_200": c * 0.9, "rs_percentile": 90.0 - k if drift > 0 else 20.0 + k,
                             "trend_template_pass": drift > 0, "rvol": 1.0, "atr_pct_primary": 2.0,
                             "away_52w_high_pct": (c / hi52 - 1) * 100, "return_3m_pct": 5.0, "return_6m_pct": 8.0,
                             "return_12m_pct": 10.0})
    # a small non-floor stock: counts in all-stock turnover, not in groups
    for i, d in enumerate(DAYS):
        rows.append({"symbol": "SMALL", "trade_date": pd.Timestamp(d), "open_price": 10, "high_price": 10.5, "low_price": 9.5,
                     "close_price": 10, "prev_close": 10, "turnover_cr": 100.0, "volume": 1, "delivery_qty": 1.0,
                     "delivery_pct": 1.0, "high_52w": 11, "low_52w": 5, "ema_10": 10, "ema_50": 10, "ema_200": 10,
                     "rs_percentile": 50.0, "trend_template_pass": False, "rvol": 1.0, "atr_pct_primary": 1.0,
                     "away_52w_high_pct": -9.0, "return_3m_pct": 0.0, "return_6m_pct": 0.0, "return_12m_pct": 0.0})
    master.append({"symbol": "SMALL", "security_name": "Small", "broad_sector": "BS", "sector": "Sec B", "broad_industry": "Mid BI",
                   "industry": "Ind C", "market_cap_cr": 200.0})
    con = duckdb.connect(str(path))
    con.register("ind", pd.DataFrame(rows))
    con.execute("CREATE TABLE indicators_daily AS SELECT * FROM ind")
    con.register("sm", pd.DataFrame(master))
    con.execute("CREATE TABLE stocks_master AS SELECT * FROM sm")
    deals = [  # within the last 10 clean sessions before the gap
        {"trade_date": pd.Timestamp(DAYS[GAP_AFTER - 2]), "symbol": "L1", "event_type": "accumulate", "net_value_cr_ex_prop": 50.0},
        {"trade_date": pd.Timestamp(DAYS[GAP_AFTER - 3]), "symbol": "L2", "event_type": "fresh", "net_value_cr_ex_prop": 20.0},
        {"trade_date": pd.Timestamp(DAYS[GAP_AFTER - 3]), "symbol": "L3", "event_type": "churn", "net_value_cr_ex_prop": 99.0},
        {"trade_date": pd.Timestamp(DAYS[GAP_AFTER - 4]), "symbol": "G1", "event_type": "distribute", "net_value_cr_ex_prop": -30.0},
        {"trade_date": pd.Timestamp(DAYS[GAP_AFTER - 4]), "symbol": "G2", "event_type": "transfer_interse", "net_value_cr_ex_prop": 40.0},
        {"trade_date": pd.Timestamp(DAYS[GAP_AFTER - 30]), "symbol": "G3", "event_type": "accumulate", "net_value_cr_ex_prop": 70.0},
    ]
    con.register("dl", pd.DataFrame(deals))
    con.execute("CREATE TABLE deal_session_net AS SELECT * FROM dl")
    con.execute("CREATE TABLE index_daily (trade_date TIMESTAMP, index_name VARCHAR, close_price DOUBLE)")
    for i, d in enumerate(DAYS[-40:]):
        con.execute("INSERT INTO index_daily VALUES (?, 'NIFTY MIDSML 400', ?), (?, 'NIFTY AUTO', ?)",
                    [pd.Timestamp(d), 1000 + i, pd.Timestamp(d), 500 + 2 * i])
    con.close()
    return path


@pytest.fixture()
def env(tmp_path, monkeypatch):
    path = _build(tmp_path / "market.duckdb")
    monkeypatch.setenv("MP_DB_PATH", str(path))
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


# ----------------------------------------------------------------- pure helpers
def test_max_span_days_allows_holidays_but_not_two_months():
    assert sectors.max_span_days(1) >= 4          # a long weekend + a holiday
    assert sectors.max_span_days(1) < 56
    assert sectors.max_span_days(21) >= 35        # a month with Diwali
    assert sectors.max_span_days(252) >= 380


def test_gap_mask_flags_windows_across_a_gap():
    m = sectors.gap_mask(DAYS, 1)
    assert m[GAP_AFTER] and not m[GAP_AFTER - 1] and not m[GAP_AFTER + 1]
    m10 = sectors.gap_mask(DAYS, 10)
    assert m10[GAP_AFTER:GAP_AFTER + 10].all() and not m10[GAP_AFTER + 10:].any()
    f = sectors.fwd_gap_mask(DAYS, 21)
    assert f[GAP_AFTER - 21] and not f[GAP_AFTER - 22]


def test_own_percentile_and_labels():
    assert sectors.own_percentile(np.arange(50.0)) == 100.0
    assert sectors.own_percentile(np.arange(10.0)) is None        # too short
    assert sectors.own_percentile(np.r_[np.arange(50.0), np.nan]) is None
    assert sectors.mood_label(72) == "Strong" and sectors.mood_label(29) == "Very weak"
    assert sectors.breadth_direction(-12) == "cooling fast" and sectors.breadth_direction(3) == "steady"


def test_verdict_text_follows_house_style():
    for working in (None, True, False):
        for d in ("cooling fast", "steady", None):
            v = sectors.context_verdict(working, d)
            for sentence in (v["text"] + " " + v["todo"]).split(". "):
                assert len(sentence.split()) <= 20
            assert ";" not in v["text"] + v["todo"]
    assert "half as well" in sectors.context_verdict(True, "cooling fast")["text"]


# ----------------------------------------------------------------- service on the fixture
def test_board_on_clean_session(env):
    r = sectors.board(CLEAN, "broad_industry")
    assert r.status == "ok" and r.as_of == CLEAN
    by = {x["group_name"]: x for x in r.rows}
    assert set(by) == set(GROUPS)
    lead, lag, tiny = by["Lead BI"], by["Lag BI"], by["Tiny BI"]
    assert lead["stocks"] == 4 and lead["ranked"] and lead["small"]
    assert tiny["score_2W"] is None and not tiny["ranked"]          # < 3 members: listed, not ranked
    assert lead["score_2W"] > lag["score_2W"]
    assert r.rows[0]["group_name"] == "Lead BI"                       # default sort = score 2W
    assert lead["ret_1M"] > 0 > lag["ret_1M"]
    assert lead["rx_1M"] == pytest.approx(lead["ret_1M"] - np.median([by[g]["ret_1M"] for g in ("Lead BI", "Lag BI", "Mid BI")]), abs=0.15)
    assert lead["leaders"][0] == "L1"
    # deals 10D: L1 + L2 net buys (churn L3 ignored), G1 net sell (transfer G2 ignored, G3 outside the window)
    assert (lead["deals_buy_10d"], lead["deals_sell_10d"], lead["deals_flow_10d_cr"]) == (2, 0, 70.0)
    assert (lag["deals_buy_10d"], lag["deals_sell_10d"], lag["deals_flow_10d_cr"]) == (0, 1, -30.0)
    # turnover share uses all stocks (SMALL's Rs 100 Cr/day is in the denominator)
    total = sum(10.0 + k for g in GROUPS.values() for k in range(len(g[2]))) + 100.0
    assert lead["sh_1D"] == pytest.approx((10 + 11 + 12 + 13) / total * 100, abs=0.01)
    assert lead["tov_1D"] == 46
    assert 0 <= lead["near"] <= 100 and set(lead["pct"]) >= {"near", "score_2W"}
    ctx = r.extra
    assert ctx["level_label"] == "Broad Industry" and ctx["gap_windows"] == []
    assert ctx["mood"]["score"] is not None and "verdict" in ctx and "what_to_do" in ctx


def test_board_gap_guard_blanks_windows_after_the_gap(env):
    r = sectors.board(DAYS[GAP_AFTER], "broad_industry")
    assert set(r.extra["gap_windows"]) == {"1D", "1W", "2W", "1M"}
    assert all(x[f"ret_{wk}"] is None and x[f"score_{wk}"] is None for x in r.rows for wk in sectors.WINDOWS)
    assert all(x["near"] is not None for x in r.rows)                 # a level reading, not a window
    assert r.extra["deals_reason"] and all(x["deals_buy_10d"] is None for x in r.rows)
    assert r.extra["last_clean_session"] == str(CLEAN)
    assert any("gap guard" in n for n in r.notes)


def test_board_last_session_windows(env):
    r = sectors.board(None, "sector")              # 9 sessions after the gap: 1D / 1W clean, 2W / 1M span it
    assert r.as_of == LAST and r.status == "partial"
    assert set(r.extra["gap_windows"]) == {"2W", "1M"} and all(x["ret_1M"] is None for x in r.rows)
    assert all(x["ret_1W"] is not None for x in r.rows)


def test_members_charts_heatmap_index(env):
    m = sectors.members(CLEAN, "broad_industry:Lead BI")
    assert [x["symbol"] for x in m.rows] == ["L1", "L2", "L3", "L4"]
    assert m.rows[0]["deal_flow_10d_cr"] == 50.0 and m.rows[2]["deal_last_event"] == "churn"
    with pytest.raises(KeyError):
        sectors.members(CLEAN, "industry:Nope")
    with pytest.raises(ValueError):
        sectors.members(CLEAN, "nolevel")
    c = sectors.charts(CLEAN, ["broad_industry:Lead BI", "industry:Ind B"])
    bars = c.rows[0]["bars"]
    assert bars[-1]["time"] == str(CLEAN) and all(b["low"] <= min(b["open"], b["close"]) for b in bars)
    assert c.rows[0]["rs"][-1]["value"] > 100 > c.rows[1]["rs"][-1]["value"]
    h = sectors.heatmap(DAYS[GAP_AFTER])
    assert h.status == "partial" and "r1" in h.extra["gap_fields"]
    assert all(x["r1"] is None and x["gap"] is None for x in h.rows)
    h = sectors.heatmap(CLEAN)
    assert h.status == "ok" and any(x["r1"] is not None for x in h.rows) and len(h.rows) == 13
    ix = sectors.index_board(LAST)
    auto = next(x for x in ix.rows if x["group_name"] == "Nifty Auto")
    assert auto["ret_1W"] is not None and auto["ret_1M"] is None      # 1M spans the gap
    assert ix.status == "partial" and "constituent" in ix.notes[0]


def test_group_studies_unavailable_without_evidence_tables(env):
    r = sectors.group_studies(CLEAN, "industry")
    assert r.status == "unavailable" and r.extra["readings_study"] and r.extra["mood_study"]


# ----------------------------------------------------------------- endpoints
@pytest.mark.parametrize("url", [
    "/api/v2/sectors/board", "/api/v2/sectors/board?level=industry", "/api/v2/sectors/board?level=index",
    "/api/v2/sectors/context", "/api/v2/sectors/heatmap", "/api/v2/sectors/group-studies",
    "/api/v2/sectors/charts?id=sector:Sec%20A", "/api/v2/sectors/members?id=sector:Sec%20A",
])
def test_endpoints_return_envelopes(client, url):
    r = client.get(url + ("&" if "?" in url else "?") + f"as_of={CLEAN}")
    assert r.status_code == 200, r.text
    j = r.json()
    assert set(j) == {"as_of", "freshness", "total", "returned", "rows", "meta"}


def test_endpoint_validation(client):
    assert client.get("/api/v2/sectors/board?level=x").status_code == 422
    assert client.get("/api/v2/sectors/members?id=bad").status_code == 422
    assert client.get("/api/v2/sectors/members?id=industry:Nope").status_code == 404
    assert client.get("/api/v2/sectors/charts").status_code == 422
