from datetime import date, timedelta

import duckdb
import pandas as pd

from App.pages.sma_template import CHECKS, pass_mask, scan_template


def test_pass_mask_requires_enabled_gates_only():
    frame = pd.DataFrame(
        {
            "close_price": [120.0],
            "sma_50": [110.0],
            "sma_150": [100.0],
            "sma_200": [90.0],
            "sma_200_rising": [True],
            "away_52w_low_pct": [40.0],
            "away_52w_high_pct": [-5.0],
            "rs_percentile": [80.0],
        }
    )
    gates = {
        "price_gt_150_200": True,
        "sma_150_gt_200": True,
        "sma_200_rising": True,
        "sma_50_gt_150": True,
        "sma_50_gt_200": True,
        "price_gt_50": True,
        "rs_70": True,
    }
    assert bool(pass_mask(frame, gates, 70).iloc[0])
    fail_rs = frame.copy()
    fail_rs["rs_percentile"] = 10
    assert not bool(pass_mask(fail_rs, {"rs_70": True}, 70).iloc[0])
    assert bool(pass_mask(fail_rs, {"rs_70": False, "price_gt_50": True}, 70).iloc[0])
    far_high = frame.copy()
    far_high["away_52w_high_pct"] = -40
    assert not bool(pass_mask(far_high, {"price_gt_50": True}, 70, max_high_away=25).iloc[0])
    assert bool(pass_mask(far_high, {"price_gt_50": True}, 70, max_high_away=50).iloc[0])


def test_scan_template_computes_sma_from_prices(tmp_path):
    db = tmp_path / "m.duckdb"
    start = date(2025, 1, 2)
    rows = []
    for i in range(220):
        d = start + timedelta(days=i)
        # skip weekends-ish by using sequential calendar; prices still have 220 bars
        rows.append(("AAA", d, 100 + i * 0.1, 101, 99, 100 + i * 0.1, 1000))
    with duckdb.connect(str(db)) as con:
        con.execute(
            "CREATE TABLE prices_daily (symbol TEXT, trade_date DATE, open_price DOUBLE, high_price DOUBLE, low_price DOUBLE, close_price DOUBLE, volume DOUBLE)"
        )
        con.execute(
            "CREATE TABLE indicators_daily (symbol TEXT, trade_date DATE, close_price DOUBLE, rs_percentile DOUBLE, away_52w_high_pct DOUBLE, away_52w_low_pct DOUBLE, turnover_cr DOUBLE, rvol DOUBLE, delivery_pct DOUBLE)"
        )
        con.execute(
            "CREATE TABLE stocks_master (symbol TEXT, market_cap_cr DOUBLE, sector TEXT, industry TEXT, band DOUBLE)"
        )
        con.executemany(
            "INSERT INTO prices_daily VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(s, d, o, h, l, c, v) for s, d, o, h, l, c, v in rows],
        )
        last = rows[-1][1]
        con.execute(
            "INSERT INTO indicators_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ["AAA", last, rows[-1][5], 80.0, -4.0, 50.0, 12.0, 1.2, 40.0],
        )
        con.execute("INSERT INTO stocks_master VALUES (?, ?, ?, ?, ?)", ["AAA", 5000.0, "IT", "Software", 20])
    frame = scan_template(db, 1000)
    assert not frame.empty
    assert pd.notna(frame.iloc[0]["sma_50"])
    assert pd.notna(frame.iloc[0]["sma_200"])
    assert float(frame.iloc[0]["sma_50"]) > float(frame.iloc[0]["sma_200"])
    assert "sma_50_gt_150" in dict(CHECKS)
    assert "sma_50_gt_200" in dict(CHECKS)
    assert "sma_50_stack" not in dict(CHECKS)
