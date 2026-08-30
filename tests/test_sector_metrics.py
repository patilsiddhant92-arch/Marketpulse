from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd

from App.sector_read_model import query_sector_rotation_overview
from Scripts.sector_metrics import compute_sector_metrics


def test_deal_metrics_are_precomputed_once_per_symbol_and_as_of_date() -> None:
    from Scripts.sector_metrics import _prepare_deal_metrics

    deals = pd.DataFrame(
        [
            {"symbol": "AAA", "trade_date": "2026-08-01", "side": "BUY", "deal_value_cr": 10.0, "clientele": "PROP"},
            {"symbol": "AAA", "trade_date": "2026-08-10", "side": "SELL", "deal_value_cr": 3.0, "clientele": "FII"},
            {"symbol": "AAA", "trade_date": "2026-07-01", "side": "BUY", "deal_value_cr": 99.0, "clientele": "PROP"},
            {"symbol": "BBB", "trade_date": "2026-08-05", "side": "BUY", "deal_value_cr": 7.0, "clientele": "DII"},
        ]
    )

    actual = _prepare_deal_metrics(
        deals,
        pd.to_datetime(["2026-08-10", "2026-09-01"]),
    ).set_index(["trade_date", "symbol"])

    assert actual.loc[(pd.Timestamp("2026-08-10"), "AAA"), "deal_net_30d_cr"] == 7.0
    assert actual.loc[(pd.Timestamp("2026-08-10"), "AAA"), "deal_prop_30d_cr"] == 10.0
    assert actual.loc[(pd.Timestamp("2026-09-01"), "AAA"), "deal_net_30d_cr"] == -3.0
    assert actual.loc[(pd.Timestamp("2026-09-01"), "AAA"), "deal_prop_30d_cr"] == 0.0
    assert actual.loc[(pd.Timestamp("2026-08-10"), "BBB"), "deal_net_30d_cr"] == 7.0


def test_sector_metrics_are_cap_weighted_and_include_technical_density() -> None:
    as_of = date(2026, 8, 13)
    indicators = pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "trade_date": as_of,
                "close_price": 110.0,
                "return_21d_pct": 10.0,
                "return_63d_pct": 12.0,
                "ema_50": 100.0,
                "ema_200": 90.0,
                "distance_below_52w": 2.0,
                "avg_traded_value_cr_20d": 40.0,
                "setup_class": "PIVOT",
            },
            {
                "symbol": "BBB",
                "trade_date": as_of,
                "close_price": 90.0,
                "return_21d_pct": 0.0,
                "return_63d_pct": -4.0,
                "ema_50": 100.0,
                "ema_200": 95.0,
                "distance_below_52w": 12.0,
                "avg_traded_value_cr_20d": 60.0,
                "setup_class": "NONE",
            },
        ]
    )
    master = pd.DataFrame(
        [
            {"symbol": "AAA", "sector": "Technology", "broad_sector": "Tech"},
            {"symbol": "BBB", "sector": "Technology", "broad_sector": "Tech"},
        ]
    )
    reference = pd.DataFrame(
        [
            {"symbol": "AAA", "effective_date": as_of, "market_cap_cr": 100.0},
            {"symbol": "BBB", "effective_date": as_of, "market_cap_cr": 300.0},
        ]
    )
    index_daily = pd.DataFrame(
        [
            {"trade_date": as_of, "index_name": "NIFTY 50", "return_21d_pct": 2.0, "return_63d_pct": 3.0},
        ]
    )

    actual = compute_sector_metrics(indicators, master, reference, index_daily)
    row = actual[(actual["level"] == "Sector") & (actual["group_name"] == "Technology")].iloc[0]

    assert row["rs_vs_nifty_21d"] == 0.5  # (10*100 + 0*300)/400 - 2
    assert row["rs_vs_nifty_63d"] == -3.0  # (12*100 - 4*300)/400 - 3
    assert row["breadth_50"] == 50.0
    assert row["breadth_200"] == 50.0
    assert row["adv_concentration_top3"] == 100.0
    assert row["near_52w_pct"] == 50.0
    assert row["tech_pass_n"] == 1


def test_sector_read_model_prefers_computed_metrics_table(tmp_path) -> None:
    db_path = tmp_path / "sector.duckdb"
    with duckdb.connect(str(db_path)) as db:
        db.execute(
            """
            CREATE TABLE sector_metrics_daily (
                trade_date DATE, level TEXT, group_name TEXT, stock_count INTEGER,
                rs_vs_nifty_21d DOUBLE, rs_vs_nifty_63d DOUBLE, breadth_50 DOUBLE,
                breadth_200 DOUBLE, adv_concentration_top3 DOUBLE, near_52w_pct DOUBLE,
                adv_total_cr DOUBLE, tech_pass_n INTEGER, funda_pass_n INTEGER,
                deal_net_10s_cr DOUBLE, deal_prop_10s_cr DOUBLE, rotation_state TEXT
            )
            """
        )
        db.execute(
            "INSERT INTO sector_metrics_daily VALUES ('2026-08-13', 'Sector', 'Technology', 2, 1.5, 4.0, 50, 50, 100, 50, 100, 1, 0, 12, 4, '')"
        )

    overview = query_sector_rotation_overview(db_path, level="Sector")

    assert overview["as_of"] == "2026-08-13"
    assert overview["leaderboard"].iloc[0]["group_name"] == "Technology"
    assert overview["leaderboard"].iloc[0]["return_3m_pct"] == 4.0
