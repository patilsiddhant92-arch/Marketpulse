"""Cross-tab context, "why is this stock here", Desk vs-last-week and the Groups rotation grid."""
from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from test_api_v2_helpers import LAST, build_market_db, sessions


@pytest.fixture()
def rich(tmp_path, monkeypatch):
    """Fixture market DB plus setup_daily, regime_daily and a group_daily with Health history."""
    market = build_market_db(tmp_path / "ctx.duckdb")
    con = duckdb.connect(str(market))
    days = sessions()
    con.execute("""CREATE TABLE setup_daily (trade_date DATE, queue VARCHAR, symbol VARCHAR, first_seen DATE,
                   setup_age_sessions BIGINT, trigger_price DOUBLE, stop_price DOUBLE, risk_pct DOUBLE,
                   distance_to_trigger_pct DOUBLE, features VARCHAR)""")
    con.execute("INSERT INTO setup_daily VALUES (?, 'vcp', 'AAA', ?, 4, 110, 100, 10, 2.5, '{\"flavor\": null}')",
                [days[-1], days[-4]])
    con.execute("INSERT INTO setup_daily VALUES (?, 'vcp', 'AAA', ?, 1, 110, 100, 10, 2.5, NULL)", [days[-6], days[-6]])
    con.execute("INSERT INTO setup_daily VALUES (?, 'darvas_squeeze', 'SMALL', ?, 1, 21, 19, 10, 1, NULL)", [days[-6], days[-6]])
    con.execute("""CREATE TABLE regime_daily (trade_date DATE, verdict VARCHAR, above_50ema_pct DOUBLE,
                   above_200ema_pct DOUBLE, net_new_highs DOUBLE, advancers DOUBLE)""")
    for i, d in enumerate(days):
        con.execute("INSERT INTO regime_daily VALUES (?, ?, ?, 40, ?, 900)", [d, "Mixed" if i == len(days) - 1 else "Weak", 30 + i * 0.1, i])
    con.execute("""CREATE TABLE group_daily (trade_date TIMESTAMP, level VARCHAR, floor VARCHAR, group_name VARCHAR,
                   members BIGINT, ret_ew_1d DOUBLE, ret_ew_21d DOUBLE, rs_ratio DOUBLE, rs_momentum DOUBLE,
                   rrg_quadrant VARCHAR, rank DOUBLE, rs_ratio_self DOUBLE, rs_momentum_self DOUBLE, ew_index DOUBLE,
                   ew_index_ema50 DOUBLE, ew_index_ema200 DOUBLE, abs_trend VARCHAR, quadrant_note VARCHAR,
                   health DOUBLE, health_rank DOUBLE, days_in_quadrant DOUBLE)""")
    for i, d in enumerate(days):
        con.execute("INSERT INTO group_daily VALUES (?, 'Industry', '1000cr', 'Heavy Electrical', 3, 0.5, -1.0, 101, 100, "
                    "'Leading', 1, 103, 101, ?, NULL, NULL, 'Down', 'falling', ?, 1, 3)", [d, 100 + i, 40 + i * 0.5])
        con.execute("INSERT INTO group_daily VALUES (?, 'Industry', '1000cr', 'Logistics', 1, 0.1, 1.0, 99, 99, "
                    "'Lagging', NULL, 99, 99, 100, NULL, NULL, 'Flat', NULL, 50, NULL, 3)", [d])
    con.close()
    monkeypatch.setenv("MP_DB_PATH", str(market))
    monkeypatch.setenv("MP_USER_DB_PATH", str(tmp_path / "user.duckdb"))
    monkeypatch.setenv("MP_HOLIDAYS_PATH", str(tmp_path / "none.json"))
    from App.api.v2 import create_app
    from App.services import db

    db.clear_cache()
    yield TestClient(create_app()), days
    db.clear_cache()


def _ok(c, url):
    r = c.get(url)
    assert r.status_code == 200, (url, r.text[:400])
    return r.json()


def test_context_stocks_batches_group_deals_setups_events(rich):
    c, days = rich
    body = _ok(c, "/api/v2/context/stocks?symbols=AAA,nullrs,NOPE")
    rows = {r["symbol"]: r for r in body["rows"]}
    assert set(rows) == {"AAA", "NULLRS", "NOPE"}
    a = rows["AAA"]
    assert a["in_session"] and a["industry"] == "Heavy Electrical"
    g = a["group"]
    from App.services.groups import health_zone

    assert g["health_zone"] == health_zone(g["health"]) and g["rrg_quadrant"] == "Leading" and g["quadrant_note"] == "falling"
    assert len(g["health_spark_21"]) == 21 and g["health_spark_21"][-1] == g["health"]
    assert a["setups"][0]["queue"] == "vcp" and a["setups"][0]["label"] == "VCP" and a["setups"][0]["trigger_price"] == 110
    assert a["deal_prints_10s"] == 1 and a["deal_net_10s_cr"] > 0  # bulk ∩ block collapsed into one print
    assert a["next_results"] is not None
    assert rows["NOPE"]["in_session"] is False and rows["NOPE"]["group"] is None


def test_context_stocks_validates_symbols(rich):
    c, _ = rich
    assert c.get("/api/v2/context/stocks?symbols=AA%24A").status_code == 422
    many = ",".join(f"S{i}" for i in range(201))
    assert c.get(f"/api/v2/context/stocks?symbols={many}").status_code == 422


def test_context_groups_lists_every_group_with_zone(rich):
    c, _ = rich
    body = _ok(c, "/api/v2/context/groups?level=industry")
    by = {r["id"]: r for r in body["rows"]}
    assert by["industry:Heavy Electrical"]["health_rank"] == 1
    assert by["industry:Logistics"]["thin"] is True


def test_why_bullets_restate_facts(rich):
    c, _ = rich
    body = _ok(c, "/api/v2/stock/AAA/why")
    kinds = [b["kind"] for b in body["rows"]]
    assert kinds[:2] == ["setup", "trigger"] and "group" in kinds and "deals" in kinds
    trig = next(b for b in body["rows"] if b["kind"] == "trigger")
    assert "₹110.00" in trig["text"] and "risk 10.0%, wide" in trig["text"] and trig["tone"] == "warn"
    grp = next(b for b in body["rows"] if b["kind"] == "group")
    assert "falling" in grp["text"] and grp["link"] == "/groups?group=industry:Heavy Electrical"
    deals = next(b for b in body["rows"] if b["kind"] == "deals")
    assert deals["link"].endswith("q=AAA") and deals["tone"] == "positive"
    assert body["meta"]["context"]["verdict"] == "Mixed"


def test_why_bullets_are_pure_and_fail_closed():
    from App.services import context

    ctx = {"symbol": "X", "industry": None, "group": None, "setups": [], "deal_prints_10s": 0}
    out = context.bullets(ctx, {"rvol": None}, None, None, {})
    assert [b["kind"] for b in out] == ["group"] and "Unclassified" in out[0]["text"]
    out = context.bullets(ctx, {"rvol": 2.0, "change_1d_pct": 3.0}, 1.5, "Mixed", {})
    fp = next(b for b in out if b["kind"] == "footprint")
    assert "real participation" in fp["text"] and fp["tone"] == "positive"
    ev = {"vcp": {"bucket": "Mixed", "row": {"n": 12, "insufficient_sample": True}}}
    ctx2 = {**ctx, "setups": [{"queue": "vcp", "label": "VCP", "setup_age_sessions": 1}]}
    out = context.bullets(ctx2, {}, None, "Mixed", ev)
    assert any(b["kind"] == "evidence" and "too few" in b["text"] and "n=12" in b["text"] for b in out)


def test_desk_compare_now_vs_five_sessions_ago(rich):
    c, days = rich
    body = _ok(c, "/api/v2/desk/compare?sessions=5")
    rows = {r["key"]: r for r in body["rows"]}
    assert rows["queue_vcp"]["now"] == 1 and rows["queue_vcp"]["then"] == 1 and rows["queue_vcp"]["delta"] == 0
    assert rows["queue_darvas_squeeze"]["now"] == 0 and rows["queue_darvas_squeeze"]["then"] == 1
    assert rows["net_new_highs"]["delta"] == 5
    ctx = body["meta"]["context"]
    assert ctx["then_date"] == days[-6].isoformat() and ctx["verdict_now"] == "Mixed" and ctx["verdict_then"] == "Weak"
    assert [g["group_name"] for g in ctx["top_groups_now"]] == ["Heavy Electrical"]


def test_groups_rotation_grid_weekly_health(rich):
    c, days = rich
    body = _ok(c, "/api/v2/groups/rotation?level=industry&weeks=4")
    weeks = body["meta"]["context"]["weeks"]
    assert len(weeks) == 4 and weeks[-1] == LAST.isoformat()
    assert [r["group_name"] for r in body["rows"]] == ["Heavy Electrical"]  # thin Logistics is not ranked
    row = body["rows"][0]
    assert len(row["cells"]) == 4 and row["cells"][-1]["health"] == row["health_now"]
    assert row["health_change"] > 0


def test_week_ends_takes_last_session_of_each_week():
    from App.services.history import week_ends

    ds = [pd.Timestamp(d) for d in ("2026-09-14", "2026-09-18", "2026-09-21", "2026-09-24", "2026-09-28")]
    assert week_ends(ds, 2) == [pd.Timestamp("2026-09-24"), pd.Timestamp("2026-09-28")]
    assert week_ends([], 3) == []


def test_board_rows_carry_year_and_health_sparks(rich):
    c, _ = rich
    rows = {r["id"]: r for r in _ok(c, "/api/v2/groups/board?level=industry")["rows"]}
    he = rows["industry:Heavy Electrical"]
    assert he["index_spark_1y"][0] == 100 and he["index_spark_1y"][-1] > 100
    assert len(he["health_spark_21"]) == 21


def test_context_endpoints_unavailable_without_tables(tmp_path, monkeypatch):
    market = build_market_db(tmp_path / "bare.duckdb")
    monkeypatch.setenv("MP_DB_PATH", str(market))
    monkeypatch.setenv("MP_HOLIDAYS_PATH", str(tmp_path / "none.json"))
    from App.api.v2 import create_app
    from App.services import db

    db.clear_cache()
    c = TestClient(create_app())
    rot = _ok(c, "/api/v2/groups/rotation")
    assert rot["meta"]["status"] == "unavailable"
    cmp_ = _ok(c, "/api/v2/desk/compare")
    assert cmp_["meta"]["status"] == "partial"
    ctx = _ok(c, "/api/v2/context/stocks?symbols=AAA")
    assert ctx["rows"][0]["setups"] == [] and ctx["meta"]["status"] == "partial"
    db.clear_cache()
