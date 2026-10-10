"""Family / promoter-group transfers (HarkPro/08-tab-deals.md 5.5 rule gap).

APOLLOPIPE 2026-08-13: Anil Laxmichand Shah bought 247,365 @ 508.81 while Kiran Anil Shah sold 247,365 @ 507.50.
The ±0.25% arm's-length price tolerance missed it (gap 0.26%), so the session was labelled accumulate and the
Deals tab / Telegram treated it as a buy. The prints below are copied from the live `deals` table.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from Scripts.derived import deal_desk
from Scripts.derived.deal_rules import family_key, family_transfers
from Scripts.derived.deal_session_net import build_deal_session_net, normalise_deals
from Scripts.telegram_deals import format_deals_digest

ROOT = Path(__file__).resolve().parents[1]
D13 = pd.Timestamp("2026-08-13")


def _deal(day, sym, client, side, qty, price, cls="OTHER"):
    return dict(trade_date=pd.Timestamp(day), symbol=sym, client_name=client, side=side, quantity=qty, price=price,
                clientele=cls, deal_type="Bulk")


# The APOLLOPIPE prints, exactly as stored (deals table, bulk.csv): four promoter-family buys, then the Shah pair.
APOLLOPIPE = [
    _deal("2026-08-04", "APOLLOPIPE", "S GUPTA HOLDING PRIVATE LIMITED", "BUY", 225000, 522.16, "CORPORATE"),
    _deal("2026-08-05", "APOLLOPIPE", "DHRUV GUPTA", "BUY", 235000, 536.20),
    _deal("2026-08-06", "APOLLOPIPE", "DHRUV GUPTA", "BUY", 270000, 536.00),
    _deal("2026-08-10", "APOLLOPIPE", "ADITYA GUPTA", "BUY", 300000, 522.82),
    _deal("2026-08-13", "APOLLOPIPE", "ANIL LAXMICHAND SHAH", "BUY", 247365, 508.81),
    _deal("2026-08-13", "APOLLOPIPE", "KIRAN ANIL SHAH", "SELL", 247365, 507.50),
]


def _prices(symbols=("APOLLOPIPE", "AAA"), start="2026-07-01", end="2026-08-20"):
    days = pd.bdate_range(start, end)
    return pd.DataFrame([dict(symbol=s, trade_date=d, close_price=508.45, volume=600_000, turnover_cr=31.0)
                         for s in symbols for d in days])


def _event(out, day, sym="APOLLOPIPE"):
    r = out[(out["trade_date"] == pd.Timestamp(day)) & (out["symbol"] == sym)]
    assert len(r) == 1
    return r.iloc[0]


@pytest.mark.parametrize("name,key", [
    ("KIRAN ANIL SHAH", "SHAH"),
    ("ANIL LAXMICHAND SHAH", "SHAH"),
    ("S GUPTA HOLDING PRIVATE LIMITED", "GUPTA"),
    ("DHRUV GUPTA", "GUPTA"),
    ("RAKESH JHUNJHUNWALA HUF", "JHUNJHUNWALA"),
    ("M/S. SHAH FAMILY TRUST", "SHAH"),
    ("A K", None),
    ("", None),
    (None, None),
])
def test_family_key(name, key):
    assert family_key(name) == key


def test_apollopipe_shah_pair_is_a_transfer():
    out = build_deal_session_net(pd.DataFrame(APOLLOPIPE), _prices())
    r = _event(out, D13)
    assert r["event_type"] == "transfer_interse"
    assert r["matched_value_cr"] == pytest.approx(247365 * 508.81 / 1e7)
    assert not bool(r["matched_buyers_institutional"])
    # The promoter-family buys with no seller stay buys.
    assert _event(out, "2026-08-04")["event_type"] == "fresh"
    assert _event(out, "2026-08-10")["event_type"] == "accumulate"


def test_apollopipe_was_missed_by_the_arms_length_tolerance():
    """Guard: the pair is 0.26% apart, outside ±0.25%, so only the family rule catches it."""
    gap = abs(508.81 - 507.50) / 508.81
    assert 0.0025 < gap < 0.01


def test_family_split_across_relatives_in_aggregate():
    deals = pd.DataFrame([
        _deal(D13, "AAA", "RAMESH KUMAR AGARWAL", "SELL", 100_000, 200.0),
        _deal(D13, "AAA", "SUNITA AGARWAL", "BUY", 60_000, 201.5),
        _deal(D13, "AAA", "VIKAS RAMESH AGARWAL", "BUY", 40_500, 201.0),
    ])
    assert len(family_transfers(normalise_deals(deals))) == 1
    assert _event(build_deal_session_net(deals, _prices()), D13, "AAA")["event_type"] == "transfer_interse"


@pytest.mark.parametrize("rows", [
    # Different families, same 0.26% gap: still an arm's-length net buy.
    [("ANIL LAXMICHAND SHAH", "BUY", 247365, 508.81), ("KIRAN ANIL MEHTA", "SELL", 247365, 507.50)],
    # Same family but the quantities differ by 10%: not a transfer.
    [("ANIL SHAH", "BUY", 247365, 508.81), ("KIRAN SHAH", "SELL", 222000, 508.81)],
    # Same family but the prices are 2% apart.
    [("ANIL SHAH", "BUY", 100_000, 510.0), ("KIRAN SHAH", "SELL", 100_000, 499.0)],
])
def test_non_family_or_mismatched_pairs_stay_net_buys(rows):
    deals = pd.DataFrame([_deal(D13, "AAA", c, s, q, p) for c, s, q, p in rows])
    r = _event(build_deal_session_net(deals, _prices()), D13, "AAA")
    assert r["event_type"] in ("fresh", "accumulate")


def test_institutions_are_never_family_matched():
    deals = pd.DataFrame([
        _deal(D13, "AAA", "SHAH CAPITAL FUND", "BUY", 100_000, 508.0, "FII"),
        _deal(D13, "AAA", "KIRAN SHAH", "SELL", 100_000, 504.0),
    ])
    assert family_transfers(normalise_deals(deals)).empty


def test_prop_desk_is_never_family_matched():
    deals = pd.DataFrame([
        _deal(D13, "AAA", "NAVIN SHAH", "BUY", 100_000, 508.0, "PROP"),
        _deal(D13, "AAA", "KIRAN SHAH", "SELL", 100_000, 507.0),
    ])
    assert family_transfers(normalise_deals(deals)).empty


def test_digest_skips_transfers_and_never_lists_them_as_buys():
    core = {
        "as_of": "2026-08-13", "deal_session": "2026-08-13",
        "today": [{"symbol": "APOLLOPIPE", "event_type": "transfer_interse", "verdict": "ignore", "net_cr": 0.0}],
        "watch": [], "skipped": {"transfer": 1, "churn": 0, "small": 0},
    }
    text = format_deals_digest(core)
    assert "APOLLOPIPE" not in text
    assert "Skipped: 1 transfers" in text


# ------------------------------------------------------------------------------------------ live DB (read-only)
def _live_db() -> Path:
    env = os.environ.get("MP_DB_PATH", "").strip()
    return Path(env) if env else ROOT / "Database" / "marketpulse.duckdb"


@pytest.mark.realdb
def test_live_apollopipe_reclassified_and_skipped_by_desk_and_digest():
    duckdb = pytest.importorskip("duckdb")
    db = _live_db()
    if not db.exists():
        pytest.skip(f"no live DB at {db}")
    src = duckdb.connect(str(db), read_only=True)
    try:
        deals = src.execute("SELECT * FROM deals WHERE trade_date BETWEEN DATE '2026-07-01' AND DATE '2026-08-13'").df()
        prices = src.execute("""SELECT symbol, trade_date, close_price, volume, turnover_cr FROM prices_daily
                                WHERE trade_date BETWEEN DATE '2026-05-01' AND DATE '2026-08-13'""").df()
    finally:
        src.close()
    if deals[(deals.symbol == "APOLLOPIPE") & (pd.to_datetime(deals.trade_date) == D13)].empty:
        pytest.skip("APOLLOPIPE 2026-08-13 prints not in this DB")
    dsn = build_deal_session_net(deals, prices)
    assert _event(dsn, D13)["event_type"] == "transfer_interse"
    # Deals tab + Telegram both read deal_desk.build over deal_session_net: rebuild it in memory over the live DB.
    con = duckdb.connect()
    try:
        con.execute(f"ATTACH '{db}' AS s (READ_ONLY)")
        for t in ("indicators_daily", "stocks_master", "deals", "prices_daily"):
            con.execute(f"CREATE VIEW {t} AS SELECT * FROM s.{t}")
        con.register("dsn_df", dsn)
        con.execute("CREATE TABLE deal_session_net AS SELECT * FROM dsn_df")
        core = deal_desk.build(con, date(2026, 8, 13))
    finally:
        con.close()
    row = next(x for x in core["today"] if x["symbol"] == "APOLLOPIPE")
    assert row["event_type"] == "transfer_interse" and row["side"] == "T" and row["verdict"] == "ignore"
    assert "APOLLOPIPE" not in format_deals_digest(core)
