from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd

from App.deals_read_model import query_deals_desk_default
from Scripts.institutional_engine import classify_client
from Scripts.institutional_engine import compute_stock_deal_metrics


def test_clientele_waterfall_exposes_prop_conflicts_and_broker_exclusions() -> None:
    cases = {
        "HRTI PRIVATE LIMITED": ("PROP", "PROP_HFT", True, False),
        "QE SECURITIES LLP": ("PROP", "PROP_HFT", True, False),
        "MILLENNIUM": ("PROP", "PROP_HFT", True, True),
        "HDFC MUTUAL FUND": ("DII", "MF", False, False),
        "NORGES BANK ON BEHALF OF THE GOVERNMENT OF NORWAY": ("FII", "SWF", False, False),
        "ASHISH KACHOLIA": ("HNI", None, False, False),
        "BULLPULSE MARKETEDGE PRIVATE LIMITED": ("CORPORATE", None, False, False),
        "ACME CAPITAL MARKET LIMITED": ("OTHER", None, False, False),
        "ANIL LAXMICHAND SHAH": ("OTHER", None, False, False),
    }

    for name, expected in cases.items():
        result = classify_client(name)
        assert (result["clientele"], result["clientele_sub"], result["is_prop"], result["needs_review"]) == expected


def test_deals_desk_includes_prop_by_default_and_supports_explicit_legacy_exclusion(tmp_path) -> None:
    db_path = tmp_path / "deals.duckdb"
    with duckdb.connect(str(db_path)) as db:
        db.execute("CREATE TABLE deals (trade_date DATE, symbol TEXT, side TEXT, deal_value_cr DOUBLE, client_name TEXT, quantity DOUBLE, price DOUBLE)")
        db.execute("CREATE TABLE stocks_master (symbol TEXT, market_cap_cr DOUBLE, sector TEXT, industry TEXT)")
        db.execute("CREATE TABLE indicators_daily (symbol TEXT, trade_date DATE, rs_percentile DOUBLE, away_52w_high_pct DOUBLE, close_price DOUBLE, ema_200 DOUBLE)")
        db.executemany(
            "INSERT INTO deals VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (date(2026, 8, 13), "PROPTEST", "BUY", 10.0, "HRTI PRIVATE LIMITED", 1000.0, 100.0),
                (date(2026, 8, 13), "DIITEST", "BUY", 8.0, "HDFC MUTUAL FUND", 800.0, 100.0),
            ],
        )
        db.execute("INSERT INTO stocks_master VALUES ('PROPTEST', 2000, 'Technology', 'Software')")
        db.execute("INSERT INTO stocks_master VALUES ('DIITEST', 2000, 'Technology', 'Software')")
        db.execute("INSERT INTO indicators_daily VALUES ('PROPTEST', '2026-08-13', 80, -2, 100, 90)")
        db.execute("INSERT INTO indicators_daily VALUES ('DIITEST', '2026-08-13', 80, -2, 100, 90)")

    included = query_deals_desk_default(db_path)
    excluded = query_deals_desk_default(db_path, exclude_hft=True)

    assert "PROPTEST" in included.symbols_for_tv
    assert "PROPTEST" not in excluded.symbols_for_tv
    assert "DIITEST" in included.symbols_for_tv


def test_legacy_deal_rows_backfill_all_classifier_flags_when_new_columns_are_partial() -> None:
    """A v4 database may have clientele fields but not the older boolean flags."""
    deals = pd.DataFrame(
        [
            {
                "trade_date": date(2026, 8, 14),
                "symbol": "PROPTEST",
                "side": "BUY",
                "deal_value_cr": 10.0,
                "client_name": "HRTI PRIVATE LIMITED",
                "quantity": 1000.0,
                "price": 100.0,
                "clientele": "PROP",
                "needs_review": False,
            }
        ]
    )
    indicators = pd.DataFrame(
        [{"symbol": "PROPTEST", "close_price": 100.0, "avg_traded_value_cr_20d": 20.0, "rs_percentile": 80.0}]
    )

    metrics = compute_stock_deal_metrics(deals, indicators, as_of=pd.Timestamp("2026-08-14"))

    assert metrics.loc[metrics["symbol"] == "PROPTEST", "inst_count_30d"].iloc[0] == 1
