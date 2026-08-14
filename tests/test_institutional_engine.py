from __future__ import annotations

from datetime import date
from pathlib import Path
import duckdb
import pandas as pd

from Scripts.institutional_engine import (
    classify_client,
    enrich_deals_with_tiers,
    net_deals_daily,
    get_cluster_buys,
    compute_stock_deal_metrics,
)
from App.ui.stock_drawer import query_stock_360_data



def test_classify_entity():
    # HFT
    c1 = classify_client("GRAVITON RESEARCH CAPITAL LLP")
    assert c1["tier"] == "HFT / Arbitrage" and c1["is_hft"] is True and c1["is_institutional"] is False

    c2 = classify_client("HRTI PRIVATE LIMITED")
    assert c2["tier"] == "HFT / Arbitrage" and c2["is_hft"] is True

    c3 = classify_client("MICROCURVES TRADING PRIVATE LIMITED")
    assert c3["tier"] == "HFT / Arbitrage" and c3["is_hft"] is True

    # DII Mutual Funds & Institutions
    d1 = classify_client("HDFC MUTUAL FUND")
    assert "DII" in d1["tier"] and d1["is_institutional"] is True and d1["is_hft"] is False

    d2 = classify_client("NIPPON INDIA MUTUAL FUND")
    assert "DII" in d2["tier"] and d2["is_institutional"] is True

    d3 = classify_client("LIFE INSURANCE CORPORATION OF INDIA")
    assert "DII" in d3["tier"] and d3["is_institutional"] is True

    # FII
    f1 = classify_client("GOLDMAN SACHS (SINGAPORE) PTE.")
    assert "FII" in f1["tier"] and f1["is_institutional"] is True

    f2 = classify_client("SOCIETE GENERALE")
    assert "FII" in f2["tier"] and f2["is_institutional"] is True

    f3 = classify_client("NORGES BANK ON BEHALF OF THE GOVERNMENT OF NORWAY")
    assert "FII" in f3["tier"] and f3["is_institutional"] is True

    # Super Investor
    s1 = classify_client("REKHA JHUNJHUNWALA")
    assert "Super Investor" in s1["tier"] and s1["is_institutional"] is True

    s2 = classify_client("ASHISH KACHOLIA")
    assert "Super Investor" in s2["tier"] and s2["is_institutional"] is True



def test_net_deals_daily():
    raw = pd.DataFrame([
        {"trade_date": date(2026, 8, 10), "symbol": "TEST", "side": "BUY", "quantity": 1000, "price": 100.0, "deal_value_cr": 10.0, "client_name": "HDFC MUTUAL FUND"},
        {"trade_date": date(2026, 8, 10), "symbol": "TEST", "side": "SELL", "quantity": 500, "price": 100.0, "deal_value_cr": 5.0, "client_name": "GRAVITON RESEARCH"},
    ])
    netted = net_deals_daily(raw, exclude_hft=True)
    assert len(netted) == 1
    assert netted.iloc[0]["net_value_cr"] == 10.0
    assert netted.iloc[0]["buy_value_cr"] == 10.0
    assert netted.iloc[0]["sell_value_cr"] == 0.0


def test_cluster_buys():
    raw = pd.DataFrame([
        {"trade_date": date(2026, 8, 10), "symbol": "CLUSTER_SYM", "side": "BUY", "deal_value_cr": 15.0, "client_name": "HDFC MUTUAL FUND", "tier": "DII (Domestic Institutional)", "is_hft": False, "is_institutional": True},
        {"trade_date": date(2026, 8, 9), "symbol": "CLUSTER_SYM", "side": "BUY", "deal_value_cr": 25.0, "client_name": "GOLDMAN SACHS", "tier": "FII / Foreign Institutional", "is_hft": False, "is_institutional": True},
        {"trade_date": date(2026, 8, 10), "symbol": "SOLO_SYM", "side": "BUY", "deal_value_cr": 10.0, "client_name": "REKHA JHUNJHUNWALA", "tier": "Super Investor / HNI", "is_hft": False, "is_institutional": True},
    ])
    clusters = get_cluster_buys(raw, lookback_days=10, min_institutions=2)
    assert len(clusters) == 1
    assert clusters.iloc[0]["symbol"] == "CLUSTER_SYM"
    assert clusters.iloc[0]["institutions_count"] == 2
    assert clusters.iloc[0]["total_buy_cr"] == 40.0



def test_stock_360_data_fetcher(tmp_path):
    db_path = tmp_path / "test_360.duckdb"
    with duckdb.connect(str(db_path)) as con:
        con.execute("CREATE TABLE stocks_master (symbol TEXT, company_name TEXT, sector TEXT, industry TEXT, broad_sector TEXT, broad_industry TEXT, band TEXT, market_cap_cr DOUBLE)")
        con.execute("INSERT INTO stocks_master VALUES ('TCS', 'Tata Consultancy Services', 'Information Technology', 'IT Services', 'Tech', 'Services', 'EQ', 1500000.0)")
        
        con.execute("CREATE TABLE indicators_daily (symbol TEXT, trade_date DATE, close_price DOUBLE, sma_20 DOUBLE, sma_50 DOUBLE, ema_200 DOUBLE, rsi_14 DOUBLE, rs_percentile DOUBLE, turnover_cr DOUBLE, avg_trade_size DOUBLE, vwap_distance_pct DOUBLE, away_52w_high_pct DOUBLE)")
        con.execute("INSERT INTO indicators_daily VALUES ('TCS', '2026-08-13', 4200.0, 4150.0, 4050.0, 3900.0, 65.4, 88.0, 500.0, 2500.0, 0.45, -2.1)")
        
        con.execute("CREATE TABLE candidate_daily (symbol TEXT, trade_date DATE, candidate_state TEXT, total_score DOUBLE)")
        con.execute("CREATE TABLE security_events (symbol TEXT, event_date DATE, event_type TEXT, headline TEXT)")
        con.execute("CREATE TABLE deals (symbol TEXT, trade_date DATE, client_name TEXT, side TEXT, quantity DOUBLE, price DOUBLE, deal_value_cr DOUBLE)")
        con.execute("INSERT INTO deals VALUES ('TCS', '2026-08-13', 'LIC OF INDIA', 'BUY', 100000, 4200.0, 42.0)")

    data = query_stock_360_data(db_path, "TCS")
    assert data["symbol"] == "TCS"
    assert data["profile"]["close_price"] == 4200.0
    assert not data["deals"].empty
    assert "DII" in data["deals"].iloc[0]["tier"]


