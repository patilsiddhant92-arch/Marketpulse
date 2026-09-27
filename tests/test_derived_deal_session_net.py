"""deal_session_net: collapse, class nets, houses, ADV, event classification (synthetic)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from Scripts.derived.deal_session_net import (
    EVENT_RULES,
    OUTPUT_COLUMNS,
    build_deal_session_net,
    event_rules_table,
    normalise_deals,
)

D = pd.bdate_range("2026-05-01", periods=30)


def deal(day, sym, client, side, qty, price, cls="OTHER", dtype="Bulk"):
    return dict(trade_date=D[day], symbol=sym, client_name=client, side=side, quantity=qty, price=price,
                clientele=cls, deal_type=dtype)


def prices(symbols=("AAA", "BBB", "CCC"), close=100.0, turnover=10.0, volume=1_000_000):
    rows = [dict(symbol=s, trade_date=d, close_price=close, volume=volume, turnover_cr=turnover)
            for s in symbols for d in D]
    return pd.DataFrame(rows)


def test_duplicate_bulk_block_print_counts_once():
    deals = pd.DataFrame([deal(25, "AAA", "X FUND", "BUY", 1000, 100.0, "FII", "Bulk"),
                          deal(25, "AAA", "X FUND", "BUY", 1000, 100.0, "FII", "Block")])
    p = normalise_deals(deals)
    assert len(p) == 1 and p["deal_types"].iloc[0] == "Block+Bulk"
    out = build_deal_session_net(deals, prices())
    assert out["buy_qty"].iloc[0] == 1000


def test_nets_by_class_vwap_houses_and_adv():
    deals = pd.DataFrame([
        deal(25, "AAA", "F1", "BUY", 100_000, 101.0, "FII"),
        deal(25, "AAA", "D1", "BUY", 50_000, 103.0, "DII"),
        deal(25, "AAA", "C1", "SELL", 30_000, 102.0, "CORPORATE"),
        deal(25, "AAA", "P1", "BUY", 10_000, 100.0, "PROP"),
    ])
    out = build_deal_session_net(deals, prices()).iloc[0]
    assert out["net_value_cr_fii"] == pytest.approx(100_000 * 101 / 1e7)
    assert out["net_value_cr_corporate"] == pytest.approx(-30_000 * 102 / 1e7)
    assert out["net_value_cr_ex_prop"] == pytest.approx((100_000 * 101 + 50_000 * 103 - 30_000 * 102) / 1e7)
    assert out["buying_houses"] == 2 and out["selling_houses"] == 1  # PROP not a house
    assert out["buy_vwap"] == pytest.approx((100_000 * 101 + 50_000 * 103 + 10_000 * 100) / 160_000)
    assert out["adv_cr"] == pytest.approx(10.0)  # prior-session 20d ADV from prices
    assert out["net_vs_adv"] == pytest.approx(out["net_value_cr_ex_prop"] / 10.0)
    assert out["deal_price_vs_close_pct"] == pytest.approx((out["vwap"] / 100 - 1) * 100)
    assert out["event_type"] == "fresh"


def test_adv_null_when_history_missing():
    deals = pd.DataFrame([deal(5, "AAA", "F1", "BUY", 1000, 100.0, "FII")])
    out = build_deal_session_net(deals, prices()).iloc[0]
    assert pd.isna(out["adv_cr"]) and pd.isna(out["net_vs_adv"])  # < 20 prior sessions
    out2 = build_deal_session_net(deals, None).iloc[0]
    assert pd.isna(out2["close_price"]) and pd.isna(out2["deal_price_vs_close_pct"])


def test_indicator_adv_is_previous_session_value():
    deals = pd.DataFrame([deal(25, "AAA", "F1", "BUY", 1000, 100.0, "FII")])
    ind = pd.DataFrame({"symbol": "AAA", "trade_date": D, "avg_traded_value_cr_20d": np.arange(30, dtype=float) + 1})
    out = build_deal_session_net(deals, prices(), ind).iloc[0]
    assert out["adv_cr"] == 25.0  # value on D[24]


def test_transfer_vs_placement():
    t = pd.DataFrame([deal(25, "AAA", "PROMOTER HOLDINGS", "SELL", 1_000_000, 100.0, "CORPORATE"),
                      deal(25, "AAA", "SOME PERSON", "BUY", 1_005_000, 100.1, "OTHER")])
    assert build_deal_session_net(t, prices())["event_type"].iloc[0] == "transfer_interse"
    pl = t.copy()
    pl.loc[1, "clientele"] = "FII"
    assert build_deal_session_net(pl, prices())["event_type"].iloc[0] == "placement"
    far = t.copy()
    far.loc[1, "price"] = 101.0  # price 1% apart -> not matched
    assert build_deal_session_net(far, prices())["event_type"].iloc[0] == "fresh"


def test_churn_accumulate_distribute():
    deals = pd.DataFrame([
        deal(20, "BBB", "HFT", "BUY", 50_000, 100.0, "PROP"),
        deal(20, "BBB", "HFT", "SELL", 50_000, 100.2, "PROP"),
        deal(19, "CCC", "F1", "BUY", 10_000, 100.0, "FII"),
        deal(24, "CCC", "F2", "BUY", 10_000, 100.0, "FII"),
        deal(29, "CCC", "D1", "SELL", 99_000, 100.0, "DII"),
    ])
    out = build_deal_session_net(deals, prices()).set_index(["symbol", "trade_date"])
    assert out.loc[("BBB", D[20]), "event_type"] == "churn"
    assert out.loc[("CCC", D[19]), "event_type"] == "fresh"
    assert out.loc[("CCC", D[24]), "event_type"] == "accumulate"
    assert out.loc[("CCC", D[24]), "net_buy_sessions_10"] == 2
    assert out.loc[("CCC", D[29]), "event_type"] == "distribute"
    assert out.loc[("CCC", D[29]), "net_buy_sessions_10"] == 1  # D19 fell out of the 10-session window


def test_classifier_fallback_without_clientele_column():
    deals = pd.DataFrame([deal(25, "AAA", "SBI MUTUAL FUND", "BUY", 1000, 100.0)]).drop(columns=["clientele"])
    p = normalise_deals(deals)
    assert p["clientele"].iloc[0] == "DII"


def test_schema_and_rules_published():
    out = build_deal_session_net(pd.DataFrame(), None)
    assert list(out.columns) == OUTPUT_COLUMNS and out.empty
    assert event_rules_table()["event_type"].tolist() == [r["event_type"] for r in EVENT_RULES]


def test_split_transfer_matches_in_aggregate():
    # One promoter sells 1.0M; three group entities buy 400k + 350k + 250k at the same price (ADANIENT-style).
    t = pd.DataFrame([deal(25, "AAA", "PROMOTER A", "SELL", 1_000_000, 100.0, "CORPORATE"),
                      deal(25, "AAA", "ENTITY B", "BUY", 400_000, 100.0, "CORPORATE"),
                      deal(25, "AAA", "ENTITY C", "BUY", 350_000, 100.1, "CORPORATE"),
                      deal(25, "AAA", "ENTITY D", "BUY", 250_000, 99.95, "OTHER")])
    out = build_deal_session_net(t, prices()).iloc[0]
    assert out["event_type"] == "transfer_interse"
    assert out["matched_value_cr"] == pytest.approx(out["buy_value_cr"])


def test_prop_removed_before_churn_test():
    # A PROP desk round-trips 900 Cr beside a 300 Cr fund sale (POLICYBZR-style): distribute, not churn.
    t = pd.DataFrame([deal(25, "AAA", "HFT DESK", "BUY", 4_500_000, 1000.0, "PROP"),
                      deal(25, "AAA", "HFT DESK", "SELL", 4_500_000, 1000.5, "PROP"),
                      deal(25, "AAA", "SOME FUND", "SELL", 3_000_000, 1000.0, "FII")])
    out = build_deal_session_net(t, prices()).iloc[0]
    assert out["event_type"] == "distribute"
    assert out["round_trip_ex_prop_cr"] == 0 and out["gross_ex_prop_cr"] == pytest.approx(300.0)


def test_is_prop_flag_and_stated_value_win():
    t = pd.DataFrame([deal(25, "AAA", "ALGO LLP", "BUY", 1000, 100.0, "OTHER")])
    t["is_prop"] = True
    t["deal_value_cr"] = 0.011
    p = normalise_deals(t)
    assert p["clientele"].iloc[0] == "PROP" and p["value_cr"].iloc[0] == pytest.approx(0.011)
    assert build_deal_session_net(t, prices())["event_type"].iloc[0] == "churn"  # nothing left after PROP


def test_float_noise_net_is_not_a_buy_session():
    # PROP-only day leaves a ~1e-14 net ex-PROP: it must not count as a prior net-buy session.
    rows = [deal(20, "AAA", "HFT", "BUY", 30_000, 100.1, "PROP"), deal(20, "AAA", "HFT", "SELL", 30_000, 100.1, "PROP"),
            deal(22, "AAA", "F1", "BUY", 10_000, 100.0, "FII")]
    out = build_deal_session_net(pd.DataFrame(rows), prices()).set_index("trade_date")
    assert out.loc[D[20], "net_buy_sessions_10"] == 0
    assert out.loc[D[22], "event_type"] == "fresh"


def test_live_service_uses_the_same_rules():
    from App.services import deals as live
    from Scripts.derived import deal_rules

    assert live.EVENT_RULES is deal_rules.EVENT_RULES
    assert live.classify_events is deal_rules.classify_events
