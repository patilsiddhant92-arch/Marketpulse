"""Regression tests: fetch_deal_attribution_df must rescale deal_price by the
cumulative price_factor as of the deal date, so a split/bonus between the
deal and today doesn't show up as a fake return.

Uses a tiny tmp_path DuckDB fixture (not the live DB, not skip-gated).
"""

from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from Scripts.institutional_attribution import fetch_deal_attribution_df


def _make_deals_and_prices_db(path, with_adjustment: bool) -> None:
    """One BUY deal on day0 at raw price 1000, then a 2:1 split after day2.

    Raw closes: 1000, 1005, 998 (pre-split) -> 500, 503, 499, 501 (post-split)
    -- a fake ~-50% one-day move at the split if read raw.

    Adjusted closes (raw * price_factor, factor 0.5 pre-split / 1.0 post-split):
    500, 502.5, 499 -> 500, 503, 499, 501 -- continuous, no discontinuity.
    """
    con = duckdb.connect(str(path))
    try:
        con.execute(
            """
            CREATE TABLE deals (
                trade_date DATE, symbol VARCHAR, client_name VARCHAR,
                price DOUBLE, deal_value_cr DOUBLE, clientele VARCHAR,
                clientele_sub VARCHAR, side VARCHAR, is_prop BOOLEAN, is_hft BOOLEAN
            )
            """
        )
        con.execute(
            """
            INSERT INTO deals VALUES
            ('2025-01-01', 'TESTCO', 'ACME MUTUAL FUND', 1000.0, 25.0, 'DII', 'MF', 'BUY', False, False)
            """
        )

        raw_rows = [
            # trade_date, open, high, low, close, price_factor
            ("2025-01-01", 1000.0, 1010.0, 995.0, 1000.0, 0.5),  # sess_idx 0 (deal date)
            ("2025-01-02", 1000.0, 1012.0, 998.0, 1005.0, 0.5),  # sess_idx 1
            ("2025-01-03", 1005.0, 1006.0, 990.0, 998.0, 0.5),   # sess_idx 2
            ("2025-01-06", 500.0, 505.0, 495.0, 500.0, 1.0),     # sess_idx 3 (post 2:1 split)
            ("2025-01-07", 500.0, 508.0, 498.0, 503.0, 1.0),     # sess_idx 4
            ("2025-01-08", 503.0, 504.0, 495.0, 499.0, 1.0),     # sess_idx 5
            ("2025-01-09", 499.0, 505.0, 498.0, 501.0, 1.0),     # sess_idx 6 (latest -> cmp)
        ]

        if with_adjustment:
            con.execute(
                """
                CREATE TABLE prices_daily (
                    symbol VARCHAR, trade_date DATE,
                    open_price DOUBLE, high_price DOUBLE, low_price DOUBLE, close_price DOUBLE,
                    price_factor DOUBLE,
                    adj_open_price DOUBLE, adj_high_price DOUBLE, adj_low_price DOUBLE, adj_close_price DOUBLE
                )
                """
            )
            for trade_date, o, h, l, c, factor in raw_rows:
                con.execute(
                    "INSERT INTO prices_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ["TESTCO", trade_date, o, h, l, c, factor, o * factor, h * factor, l * factor, c * factor],
                )
        else:
            con.execute(
                """
                CREATE TABLE prices_daily (
                    symbol VARCHAR, trade_date DATE,
                    open_price DOUBLE, high_price DOUBLE, low_price DOUBLE, close_price DOUBLE
                )
                """
            )
            for trade_date, o, h, l, c, _factor in raw_rows:
                con.execute(
                    "INSERT INTO prices_daily VALUES (?, ?, ?, ?, ?, ?)",
                    ["TESTCO", trade_date, o, h, l, c],
                )
    finally:
        con.close()


def test_forward_returns_use_adjusted_close_and_deal_price_rescaled_by_factor(tmp_path):
    """With adj_*/price_factor columns present, a split between the deal and
    today must not show up as a fake return: the deal_price is rescaled by
    the price_factor as of the deal date, and forward closes come from the
    adjusted (continuous) series.
    """
    db_path = tmp_path / "adjusted.duckdb"
    _make_deals_and_prices_db(db_path, with_adjustment=True)

    df = fetch_deal_attribution_df(db_path, min_deal_cr=1.0)
    assert len(df) == 1
    row = df.iloc[0]

    # deal_price (1000) * factor_on_deal_date (0.5) = 500 adjusted basis.
    # close_5d (sess_idx 5) = adj_close 499 -> (499/500 - 1) * 100 = -0.2%
    assert row["ret_5d"] == pytest.approx(-0.2, abs=1e-6)
    # cmp = adj_close at sess_idx 6 = 501 -> (501/500 - 1) * 100 = 0.2%, rounded to 1dp
    assert row["ret_current"] == pytest.approx(0.2, abs=1e-6)
    assert row["cmp"] == pytest.approx(501.0, abs=1e-6)

    # The critical regression check: no fake ~-50% split discontinuity.
    assert row["ret_5d"] > -5.0
    assert row["ret_current"] > -5.0


def test_fallback_without_adj_columns_computes_raw_returns(tmp_path):
    """Without adj_*/price_factor columns (today's live DB shape), the helper
    falls back to raw columns -- documenting the old (pre-Task-7) behaviour,
    including the fake ~-50% split discontinuity this task fixes once the
    adjusted columns exist.
    """
    db_path = tmp_path / "raw.duckdb"
    _make_deals_and_prices_db(db_path, with_adjustment=False)

    df = fetch_deal_attribution_df(db_path, min_deal_cr=1.0)
    assert len(df) == 1
    row = df.iloc[0]

    # deal_price stays 1000 (no price_factor column -> factor treated as 1.0).
    # close_5d (raw) = 499 -> (499/1000 - 1) * 100 = -50.1%
    assert row["ret_5d"] == pytest.approx(-50.1, abs=1e-6)
    # cmp (raw) = 501 -> (501/1000 - 1) * 100 = -49.9%, rounded to 1dp
    assert row["ret_current"] == pytest.approx(-49.9, abs=1e-6)
    assert row["cmp"] == pytest.approx(501.0, abs=1e-6)

    # Documents the fake split discontinuity the adjusted path (above) avoids.
    assert row["ret_5d"] < -45.0
    assert row["ret_current"] < -45.0
