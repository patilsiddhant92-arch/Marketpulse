"""Deals tab (HarkPro/08-tab-deals.md, mockup v1.2): verdict engine, deal watch, history patterns, houses,
cross-tab feeds, and the one-message Telegram digest. Synthetic DuckDB only; no network."""
from __future__ import annotations

from datetime import date

import duckdb
import numpy as np
import pandas as pd
import pytest

from Scripts.derived import deal_desk as dd

S = pd.bdate_range("2026-05-01", periods=40)
LAST = S[-1].date()

# symbol: (mcap, start price, daily drift, strong chart?, rvol)
STOCKS = {
    "AAA": (5000, 100.0, 0.002, True, 2.0),     # fresh net buy day 35, holds -> confirm
    "BBB": (5000, 50.0, 0.0, True, 2.0),        # inter-se transfer day 38
    "CCC": (5000, 80.0, 0.0, True, 2.0),        # net seller day 38 (one small DII buyer)
    "DDD": (5000, 30.0, 0.0, False, 1.0),       # churn day 39, quiet
    "EEE": (5000, 200.0, 0.0, True, 2.0),       # placement day 39
    "FFF": (5000, 40.0, 0.0, False, 2.0),       # fresh buy day 39, weak chart -> no edge
    "GGG": (5000, 60.0, 0.0, True, 2.0),        # fresh buy day 39, strong chart -> watch day 3
    "HHH": (5000, 100.0, -0.01, False, 2.0),    # BAD FUND's losing bets (days 0-4)
    "III": (5000, 90.0, 0.0, True, 2.0),        # BAD FUND buys day 39 -> poor-record buyer
    "M&M": (5000, 70.0, 0.0, True, 2.0),        # ampersand symbol for the TV mapping
    "SMALL": (500, 10.0, 0.0, True, 2.0),       # below the floor
}
for i in range(12):                              # flat market filler for the equal-weight benchmark
    STOCKS[f"Z{i:02d}"] = (5000, 100.0, 0.0, False, 1.0)


def _ind_rows():
    rows = []
    for sym, (mcap, p0, drift, strong, rvol) in STOCKS.items():
        for k, d in enumerate(S):
            c = p0 * (1 + drift) ** k
            rows.append(dict(symbol=sym, trade_date=d, open_price=c, high_price=c * 1.01, low_price=c * 0.99, close_price=c,
                             ema_50=c * 0.95, ema_200=c * (0.8 if strong else 1.2), rs_percentile=90.0 if strong else 30.0,
                             away_52w_high_pct=-5.0 if strong else -40.0, return_1m_pct=5.0, rvol=rvol))
    return pd.DataFrame(rows)


def _dsn(day, sym, event, net, buy_vwap=None, sell_vwap=None, gross=None, prop=0.0):
    return dict(trade_date=S[day], symbol=sym, event_type=event, net_value_cr_ex_prop=net, gross_ex_prop_cr=gross or abs(net),
                prop_value_cr=prop, buy_vwap=buy_vwap, sell_vwap=sell_vwap, vwap=buy_vwap or sell_vwap)


def _deal(day, sym, client, side, value_cr, price, cls="OTHER", prop=False):
    qty = int(round(value_cr * 1e7 / price))
    return dict(trade_date=S[day], symbol=sym, client_name=client, side=side, quantity=qty, price=price,
                deal_value_cr=value_cr, clientele=cls, is_prop=prop, deal_type="Bulk")


def build_db(path):
    con = duckdb.connect(str(path))
    ind = _ind_rows()
    con.execute("CREATE TABLE indicators_daily AS SELECT * FROM ind")
    sm = pd.DataFrame([dict(symbol=s, security_name=f"{s} Ltd", market_cap_cr=float(v[0]), sector="Sec",
                            industry="Ind A" if s in ("AAA", "GGG", "EEE") else "Ind B") for s, v in STOCKS.items()])
    con.execute("CREATE TABLE stocks_master AS SELECT * FROM sm")
    p = lambda s, d: STOCKS[s][1] * (1 + STOCKS[s][2]) ** d  # noqa: E731
    dsn = [
        _dsn(35, "AAA", "fresh", 30.0, buy_vwap=p("AAA", 35)),
        _dsn(38, "BBB", "transfer_interse", 0.0, buy_vwap=50.0, sell_vwap=50.0, gross=40.0),
        _dsn(38, "CCC", "distribute", -25.0, buy_vwap=80.0, sell_vwap=80.0, gross=35.0),
        _dsn(39, "DDD", "churn", 0.0, buy_vwap=30.0, sell_vwap=30.0, gross=4.0, prop=12.0),
        _dsn(39, "EEE", "placement", 0.0, buy_vwap=198.0, sell_vwap=198.0, gross=300.0),
        _dsn(39, "FFF", "fresh", 8.0, buy_vwap=40.0),
        _dsn(39, "GGG", "fresh", 12.0, buy_vwap=59.5),
        _dsn(39, "III", "fresh", 9.0, buy_vwap=90.0),
        _dsn(39, "M&M", "fresh", 6.0, buy_vwap=70.0),
        _dsn(39, "SMALL", "fresh", 6.0, buy_vwap=10.0),
    ] + [_dsn(d, "HHH", "fresh", 6.0, buy_vwap=p("HHH", d)) for d in range(5)]
    dsn = pd.DataFrame(dsn)
    con.execute("CREATE TABLE deal_session_net AS SELECT * FROM dsn")
    deals = [
        _deal(35, "AAA", "SBI MUTUAL FUND", "BUY", 30.0, p("AAA", 35), "DII"),
        _deal(38, "BBB", "PI OPPORTUNITIES AIF", "BUY", 20.0, 50.0, "OTHER"),
        _deal(38, "BBB", "PIONEER INVESTMENT", "SELL", 20.0, 50.0, "OTHER"),
        _deal(38, "CCC", "PROMOTER HOLDCO PVT LTD", "SELL", 30.0, 80.0, "CORPORATE"),
        _deal(38, "CCC", "HDFC MUTUAL FUND", "BUY", 5.0, 80.0, "DII"),
        _deal(39, "DDD", "XYZ STOCK BROKING", "BUY", 6.0, 30.0, "PROP", True),
        _deal(39, "DDD", "XYZ STOCK BROKING", "SELL", 6.0, 30.0, "PROP", True),
        _deal(39, "EEE", "FOUNDER CORP", "SELL", 150.0, 198.0, "CORPORATE"),
        _deal(39, "EEE", "SBI MUTUAL FUND", "BUY", 150.0, 198.0, "DII"),
        _deal(39, "FFF", "SOME TRADER", "BUY", 8.0, 40.0, "OTHER"),
        _deal(39, "GGG", "NOMURA SINGAPORE LIMITED", "BUY", 12.0, 59.5, "FII"),
        _deal(39, "III", "BAD FUND", "BUY", 9.0, 90.0, "FII"),
        _deal(39, "M&M", "NOMURA SINGAPORE LIMITED", "BUY", 6.0, 70.0, "FII"),
        _deal(39, "SMALL", "SOME TRADER", "BUY", 6.0, 10.0, "OTHER"),
    ] + [_deal(d, "HHH", "BAD FUND", "BUY", 6.0, p("HHH", d), "FII") for d in range(5)]
    deals = pd.DataFrame(deals)
    con.execute("CREATE TABLE deals AS SELECT * FROM deals")
    con.close()
    return path


@pytest.fixture()
def dbpath(tmp_path):
    return build_db(tmp_path / "market.duckdb")


@pytest.fixture()
def core(dbpath):
    con = duckdb.connect(str(dbpath), read_only=True)
    try:
        yield dd.build(con, LAST)
    finally:
        con.close()


def _by(rows):
    return {r["symbol"]: r for r in rows}


# ------------------------------------------------------------------------------------------- verdict engine
def test_verdict_rules_follow_the_evidence():
    assert dd.verdict("transfer_interse", True, 5, 2, [])[0] == "ignore"
    assert dd.verdict("churn", True, 5, 1.0, [])[:2] == ("avoid", "Churn on a quiet day")
    assert dd.verdict("churn", True, 5, 4.0, [])[0] == "churn"
    assert dd.verdict("churn", True, 5, None, [])[0] == "churn"      # unknown RVOL is not called quiet
    assert dd.verdict("placement", True, 5, 2, [])[1] == "Placement on a strong chart"
    assert dd.verdict("distribute", True, 5, 2, [])[0] == "supply"
    assert dd.verdict("fresh", True, 35, 2, [])[1] == "Extended: skip"
    assert dd.verdict("fresh", True, -12, 2, [])[1] == "Falling knife"
    assert dd.verdict("fresh", True, 5, 2, [{"grade": "poor"}])[1] == "Poor-record buyer"
    assert dd.verdict("fresh", True, 5, 2, [])[0] == "watch"
    assert dd.verdict("fresh", False, 5, 2, [])[0] == "none"


def test_house_key_merges_entities():
    assert dd.house_key("Nomura Singapore Limited - ODI") == dd.house_key("NOMURA SINGAPORE LTD")
    assert dd.grade("CORPORATE", 50, 5.0, 80) == "ungraded"
    assert dd.grade("FII", 4, 5.0, 80) == "ungraded"
    assert dd.grade("FII", 5, 1.0, 60) == "good"
    assert dd.grade("DII", 5, -1.0, 60) == "poor"
    assert dd.grade("DII", 5, 1.0, 40) == "mixed"


def test_today_verdicts_and_skips(core):
    t = _by(core["today"])
    assert core["deal_session"] == LAST.isoformat()
    assert t["EEE"]["verdict"] == "place" and t["EEE"]["side"] == "P"
    assert t["FFF"]["verdict"] == "none"
    assert t["GGG"]["verdict"] == "watch" and t["GGG"]["status"] == "day 0"
    assert t["DDD"]["verdict"] == "avoid" and "Churn warning" in t["DDD"]["chips"]
    assert "SMALL" not in t                                   # below ₹1,000 Cr
    assert core["skipped"] == {"transfer": 0, "churn": 1, "small": 1}


def test_poor_record_is_out_of_sample(core):
    t = _by(core["today"])
    assert t["III"]["verdict"] == "avoid" and t["III"]["verdict_title"] == "Poor-record buyer"
    assert t["III"]["buyers"][0]["grade"] == "poor"
    assert core["graded_houses"] >= 1


def test_poor_record_unknown_before_bets_finish(dbpath):
    con = duckdb.connect(str(dbpath), read_only=True)
    try:
        early = dd.build(con, S[20].date())                 # HHH bets exit at T+20 -> none finished by day 20
    finally:
        con.close()
    assert early["graded_houses"] == 0


def test_deal_watch_day3_upgrade_and_transfer_kept_out_of_buys(core):
    w = _by(core["watch"])
    assert w["AAA"]["sessions_since"] == 4 and w["AAA"]["status"] == "holding"
    assert w["AAA"]["verdict"] == "confirm" and "Holding deal price" in w["AAA"]["chips"]
    assert w["BBB"]["verdict"] == "ignore" and w["BBB"]["status"] is None
    assert w["CCC"]["verdict"] == "supply" and w["CCC"]["net_cr"] < 0


def test_lost_deal_price_downgrades(dbpath, tmp_path):
    con = duckdb.connect(str(dbpath))
    con.execute("UPDATE indicators_daily SET close_price = close_price * 0.9 WHERE symbol = 'AAA' AND trade_date > ?", [S[35]])
    con.close()
    con = duckdb.connect(str(dbpath), read_only=True)
    try:
        w = _by(dd.build(con, LAST)["watch"])
    finally:
        con.close()
    assert w["AAA"]["status"] == "lost" and w["AAA"]["verdict"] == "avoid"


def test_history_patterns(core):
    h = _by(dd.history_rows(core, 20))
    assert h["BBB"]["pattern"] == "transfers_only"
    assert h["CCC"]["pattern"] == "selling_only"
    assert h["DDD"]["pattern"] == "churn_only"
    assert h["GGG"]["pattern"] == "single_buy" and h["GGG"]["cells"][-1] == "B"
    assert len(h["GGG"]["cells"]) == len(core["sessions20"])
    assert "SMALL" not in h
    h5 = _by(dd.history_rows(core, 5))
    assert len(h5["GGG"]["cells"]) == 5


def test_groups_and_fund_spread(core):
    g = {x["industry"]: x for x in core["groups"]}
    assert "BBB" not in sum((x["symbols"] for x in core["groups"]), [])   # transfers out
    assert "DDD" not in sum((x["symbols"] for x in core["groups"]), [])   # churn out
    assert g["Ind A"]["buying_names"] == 3                                 # AAA, EEE, GGG
    sbi = next(h for h in core["houses"] if h["house"] == dd.house_key("SBI MUTUAL FUND"))
    assert sbi["buyer_class"] == "DII" and sbi["spread"][0]["industry"] == "Ind A"
    fg = {x["industry"]: x for x in core["fund_groups"]}
    assert fg["Ind A"]["dii_cr"] == pytest.approx(180.0) and fg["Ind A"]["fii_cr"] == pytest.approx(12.0)


# ------------------------------------------------------------------------------------------- Telegram digest
def test_digest_is_one_short_message_without_transfers_or_net_sellers(core):
    from Scripts.telegram_deals import DIGEST_MAX_CHARS, format_deals_digest

    text = format_deals_digest(core)
    assert len(text) <= DIGEST_MAX_CHARS
    assert text.startswith("📊 Deals · ")
    confirms = text.split("✅ Confirms a setup (watch day 3)\n", 1)[1].split("\n🏦", 1)[0]
    assert "GGG" in confirms and "CCC" not in confirms and "BBB" not in confirms
    assert "BBB" not in text                                   # the transfer is only counted
    assert "🏦 Placement" in text and "EEE" in text
    assert "🎯 Confirmed" in text and "AAA" in text
    assert "⚠️ Avoid: " in text and "III" in text
    assert "Skipped: 0 transfers, 1 churn, 1 under ₹1,000 Cr" in text
    tv = [ln for ln in text.splitlines() if ln.startswith("TV: ")][0]
    assert "NSE:GGG" in tv and "NSE:CCC" not in tv and "NSE:BBB" not in tv


def test_digest_drops_empty_sections_and_trims_to_limit():
    from Scripts.telegram_deals import DIGEST_MAX_CHARS, format_deals_digest

    core = {"as_of": "2026-08-13", "deal_session": "2026-08-13", "today": [], "watch": [], "above50_pct": 56.0,
            "skipped": {"transfer": 2, "churn": 3, "small": 4}}
    text = format_deals_digest(core)
    assert text.count("\n") == 1 and "✅" not in text and "TV:" not in text
    big = {"verdict": "watch", "event_type": "fresh", "net_cr": 10.0, "deal_price": 100.0,
           "buyers": [{"name": "A Very Long Fund House Name Indeed"}]}
    core["today"] = [dict(big, symbol=f"SYM{i:03d}LONGNAME") for i in range(40)]
    core["today"] += [dict(big, symbol=f"AV{i:03d}LONGER", verdict="avoid") for i in range(40)]
    assert len(format_deals_digest(core)) <= DIGEST_MAX_CHARS


def test_digest_maps_ampersand_for_tradingview(core):
    from Scripts.telegram_deals import format_deals_digest

    assert "NSE:M_M" in format_deals_digest(core)


def test_digest_flags_price_gap():
    from Scripts.telegram_deals import format_deals_digest

    core = {"as_of": "2026-10-08", "deal_session": "2026-10-08", "today": [], "watch": [], "skipped": {},
            "price_gap": {"from": "2026-08-13", "to": "2026-10-08"}}
    assert "Price data gap 13 Aug → 08 Oct" in format_deals_digest(core)


def test_notify_sends_exactly_one_message_and_no_network(dbpath, monkeypatch):
    import Scripts.telegram_deals as tg

    sent = []
    monkeypatch.setattr(tg, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(tg, "send_message", lambda token, chat, text: sent.append(text))

    def no_network(*a, **k):
        raise AssertionError("network call in a test")

    monkeypatch.setattr(tg, "telegram_request", no_network)
    monkeypatch.setattr(tg.urllib.request, "urlopen", no_network)
    res = tg.notify_deals(dry_run=False, token="123:abc", chat_id="999", db_path=dbpath)
    assert res["sent"] is True and res["message_count"] == 1 and len(sent) == 1
    assert sent[0] == res["text"] and len(sent[0]) <= tg.DIGEST_MAX_CHARS
    dry = tg.notify_deals(dry_run=True, db_path=dbpath)
    assert dry["message_count"] == 1 and dry["sent"] is False


# ------------------------------------------------------------------------------------------- API
@pytest.fixture()
def client(dbpath, tmp_path, monkeypatch):
    monkeypatch.setenv("MP_DB_PATH", str(dbpath))
    monkeypatch.setenv("MP_USER_DB_PATH", str(tmp_path / "user.duckdb"))
    monkeypatch.setenv("MP_STATUS_PATH", str(tmp_path / "status.json"))
    monkeypatch.setenv("MP_HOLIDAYS_PATH", str(tmp_path / "no_holidays.json"))
    from fastapi.testclient import TestClient

    from App.api.v2 import create_app
    from App.services import db

    db.clear_cache()
    yield TestClient(create_app())
    db.clear_cache()


def _get(client, url):
    r = client.get(url)
    assert r.status_code == 200, (url, r.text[:400])
    b = r.json()
    assert {"as_of", "freshness", "total", "returned", "rows", "meta"} <= set(b)
    return b


@pytest.mark.parametrize("url", ["/api/v2/deals/tab/today", "/api/v2/deals/tab/watch", "/api/v2/deals/tab/history",
                                 "/api/v2/deals/tab/houses", "/api/v2/deals/tab/groups", "/api/v2/deals/tab/telegram",
                                 "/api/v2/deals/tab/stock/GGG", "/api/v2/deals/markers/GGG", "/api/v2/deals/flags"])
def test_endpoints_envelope(client, url):
    b = _get(client, url)
    assert b["meta"]["status"] == "ok" and b["as_of"] == LAST.isoformat()


def test_watch_filter_and_history_params(client):
    b = _get(client, "/api/v2/deals/tab/watch?status=best")
    assert {r["verdict"] for r in b["rows"]} <= {"confirm", "place", "absorbed"}
    assert b["meta"]["context"]["filter_counts"]["all"] >= b["total"]
    assert all(r["event_type"] not in ("churn", "transfer_interse") for r in _get(client, "/api/v2/deals/tab/watch")["rows"])
    h = _get(client, "/api/v2/deals/tab/history?sessions=5&pattern=churn_only")
    assert [r["symbol"] for r in h["rows"]] == ["DDD"]
    assert client.get("/api/v2/deals/tab/history?sessions=7").status_code == 422
    assert client.get("/api/v2/deals/tab/watch?status=nope").status_code == 422


def test_markers_shape_for_chart_candles(client):
    b = _get(client, "/api/v2/deals/markers/EEE")
    assert b["rows"] == [{"date": LAST.isoformat(), "side": "P", "event_type": "placement", "price": 198.0,
                          "net_cr": 0.0, "gross_cr": 300.0}]
    s = _get(client, "/api/v2/deals/markers/CCC")["rows"][0]
    assert s["side"] == "S" and s["price"] == 80.0
    assert _get(client, f"/api/v2/deals/markers/CCC?as_of={S[30].date()}")["rows"] == []   # never past as_of


def test_flags_for_cross_tab_icon(client):
    b = _get(client, "/api/v2/deals/flags?symbols=GGG,BBB,Z00")
    f = _by(b["rows"])
    assert f["GGG"]["has_recent_deal"] and f["GGG"]["side"] == "B" and f["GGG"]["verdict"] == "watch"
    assert f["GGG"]["deal_sessions_ago"] == 0
    assert f["BBB"]["side"] == "T" and f["BBB"]["verdict"] == "ignore"
    assert f["Z00"]["has_recent_deal"] is False and f["Z00"]["side"] is None
    allf = _by(_get(client, "/api/v2/deals/flags")["rows"])
    assert "SMALL" in allf and allf["SMALL"]["verdict"] is None          # below the floor: flag, no verdict
    # Window = the last 10 DEAL sessions (here only 8 exist: days 0-4, 35, 38, 39), so HHH (day 4) is 3 deal sessions ago.
    assert allf["HHH"]["deal_sessions_ago"] == 3


def test_drawers(client):
    s = _get(client, "/api/v2/deals/tab/stock/AAA")["rows"][0]
    assert s["deal"]["verdict"] == "confirm" and s["candles"] and s["price_lines"][0]["side"] == "B"
    assert s["deal"]["next_action"].startswith("Plan the trade")
    nodeal = _get(client, "/api/v2/deals/tab/stock/Z01")["rows"][0]
    assert nodeal["deal"] is None and nodeal["markers"] == []
    assert client.get("/api/v2/deals/tab/stock/NOPE").status_code == 404
    h = _get(client, "/api/v2/deals/tab/house/SBI%20MUTUAL%20FUND")
    assert h["meta"]["context"]["house"]["buyer_class"] == "DII"
    pos = _by(h["rows"])
    assert pos["AAA"]["entry_date"] == S[36].date().isoformat() and pos["AAA"]["vs_market_pct"] is not None
    assert pos["EEE"]["entry_date"] is None                               # bought on as_of: no entry yet
    assert client.get("/api/v2/deals/tab/house/NOBODY").status_code == 404


def test_missing_deal_tables_are_unavailable(tmp_path, monkeypatch):
    path = tmp_path / "bare.duckdb"
    con = duckdb.connect(str(path))
    ind = _ind_rows()
    con.execute("CREATE TABLE indicators_daily AS SELECT * FROM ind")
    con.close()
    monkeypatch.setenv("MP_DB_PATH", str(path))
    monkeypatch.setenv("MP_STATUS_PATH", str(tmp_path / "status.json"))
    from fastapi.testclient import TestClient

    from App.api.v2 import create_app
    from App.services import db

    db.clear_cache()
    c = TestClient(create_app())
    b = c.get("/api/v2/deals/tab/today").json()
    assert b["meta"]["status"] == "unavailable" and b["rows"] == []
    db.clear_cache()
