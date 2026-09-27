"""Serving guard for unexplained price gaps (App/services/data_gaps.py) against a fixture DuckDB.

Symbols added on top of the standard API v2 fixture (30 sessions):
- GAPPY     relisting: 3.19 -> 205.2 (x64) on session 20, recorded as an unapplied unexplained_gap
- RATIO     x0.5 drop on session 25, nothing in price_adjustments (ratio guard only)
- REVIEWED  x2.5 jump on session 10 with a confidence='reviewed' row (override kind: ignore) -> not guarded
- OLDGAP    unapplied unconfirmed bonus on session 2: 1M window is clear by the last session, 3M is not
"""
from __future__ import annotations

import json

import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from test_api_v2_helpers import LAST, build_market_db, sessions

DAYS = sessions()


def _series(sym: str, closes: list[float]) -> pd.DataFrame:
    rows = []
    for d, c in zip(DAYS, closes):
        rows.append({
            "symbol": sym, "series": "EQ", "trade_date": pd.Timestamp(d), "close_price": c, "prev_close": c,
            "open_price": c, "high_price": c * 1.01, "low_price": c * 0.99, "volume": 2_000_000, "turnover_cr": 20.0,
            "delivery_pct": 50.0, "avg_delivery_pct_20d": 40.0, "avg_volume_20d": 1_500_000, "rvol": 1.2,
            "rs_percentile": 99.0, "rs_rank_t5": 98.0, "rs_rank_t15": 97.0, "rs_rank_t30": 96.0,
            "rs_vs_midsml400_21d": 900.0, "rs_vs_midsml400_63d": 6000.0, "rs_vs_nifty50_21d": 900.0,
            "rs_vs_nifty50_63d": 6000.0, "trend_template_pass_n": 8, "trend_template_pass": True,
            "away_52w_high_pct": -1.0, "away_52w_low_pct": 6000.0, "away_10ema_pct": 1.0,
            "return_1m_pct": 900.0, "return_3m_pct": 6000.0, "return_6m_pct": 6000.0,
            "ema_10": c * 0.99, "ema_20": c * 0.98, "ema_50": c * 0.9, "ema_100": c * 0.8, "ema_200": c * 0.5,
            "avg_traded_value_cr_20d": 18.0, "high_52w": c * 1.01, "low_52w": 3.0, "sma_50": c * 0.9,
            "sma_150": c * 0.7, "sma_200": c * 0.5, "sma_200_rising": True, "rsi_14": 70.0, "rsi_14_w": 70.0,
            "nr7": False, "inside_bar": False, "delivery_spike": False, "price_up_delivery_up": True,
        })
    return pd.DataFrame(rows)


def _step(before: float, after: float, at: int) -> list[float]:
    return [before + 0.01 * i if i < at else after + 0.01 * i for i in range(len(DAYS))]


def _add_gap_symbols(path) -> None:
    con = duckdb.connect(str(path))
    frames = [
        _series("GAPPY", _step(3.0, 205.0, 20)),
        _series("RATIO", _step(100.0, 50.0, 25)),
        _series("REVIEWED", _step(100.0, 250.0, 10)),
        _series("OLDGAP", _step(100.0, 50.0, 2)),
    ]
    con.register("_g", pd.concat(frames, ignore_index=True))
    con.execute("INSERT INTO indicators_daily BY NAME SELECT * FROM _g")
    con.execute("INSERT INTO prices_daily BY NAME SELECT symbol, series, trade_date, prev_close, open_price, high_price, "
                "low_price, close_price, volume, turnover_cr, delivery_pct FROM _g")
    for sym in ("GAPPY", "RATIO", "REVIEWED", "OLDGAP"):
        con.execute("INSERT INTO stocks_master (symbol, security_name, broad_sector, sector, broad_industry, industry, "
                    "market_cap_cr, band) VALUES (?, ?, 'Industrials', 'Capital Goods', 'Electrical Equipment', "
                    "'Heavy Electrical', 5000, 20)", [sym, sym.title() + " Ltd"])
    con.execute("CREATE TABLE price_adjustments (symbol VARCHAR, ex_date TIMESTAMP_NS, kind VARCHAR, factor DOUBLE, "
                "source VARCHAR, confidence VARCHAR, applied BOOLEAN, description VARCHAR)")
    rows = [
        ("GAPPY", DAYS[20], "unexplained_gap", 68.3, "gap", "unconfirmed", False, None),
        ("REVIEWED", DAYS[10], "unexplained_gap", 2.5, "gap+override", "reviewed", False, "genuine re-rating"),
        ("OLDGAP", DAYS[2], "bonus", 0.5, "bc", "unconfirmed", False, "BONUS 1:1"),
        ("AAA", DAYS[5], "split", 0.5, "bc", "confirmed", True, "FV SPLIT"),  # applied: never guarded
    ]
    con.executemany("INSERT INTO price_adjustments VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [(s, pd.Timestamp(d), *rest) for s, d, *rest in rows])
    con.close()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    market = build_market_db(tmp_path / "market.duckdb")
    _add_gap_symbols(market)
    monkeypatch.setenv("MP_DB_PATH", str(market))
    monkeypatch.setenv("MP_USER_DB_PATH", str(tmp_path / "user.duckdb"))
    monkeypatch.setenv("MP_STATUS_PATH", str(tmp_path / "status.json"))
    monkeypatch.setenv("MP_HOLIDAYS_PATH", str(tmp_path / "no_holidays.json"))
    from App.services import common, db

    db.clear_cache()
    monkeypatch.setattr(common, "expected_session", lambda now=None, holidays=None: LAST)
    from App.api.v2 import create_app

    yield TestClient(create_app())
    db.clear_cache()


def _rows(client, url):
    r = client.get(url)
    assert r.status_code == 200, r.text[:500]
    return r.json()["rows"]


WINDOW_FIELDS = ("return_1m_pct", "return_3m_pct", "return_6m_pct", "rs_percentile", "rs_delta_5",
                 "excess_vs_midsml400_63d", "excess_vs_midsml400_21d", "away_52w_low_pct", "trend_template_pass")


def test_stock_header_hides_window_metrics_across_unexplained_gap(client):
    row = _rows(client, "/api/v2/stock/GAPPY")[0]
    for f in WINDOW_FIELDS:
        assert row[f] is None, f
    assert row["close"] is not None  # the price itself is real
    assert row["change_1d_pct"] is not None  # the gap was 9 sessions ago; the 1-day window is clean
    w = row["data_warning"]
    assert w and DAYS[20].isoformat() in w and "×64" in w and "hidden" in w


def test_ratio_guard_without_price_adjustments_row(client):
    row = _rows(client, "/api/v2/stock/RATIO")[0]
    assert row["return_1m_pct"] is None and row["rs_percentile"] is None
    assert "drop" in row["data_warning"] and DAYS[25].isoformat() in row["data_warning"]


def test_reviewed_gap_and_applied_split_are_not_guarded(client):
    rev = _rows(client, "/api/v2/stock/REVIEWED")[0]
    assert rev["data_warning"] is None and rev["return_3m_pct"] == 6000.0
    aaa = _rows(client, "/api/v2/stock/AAA")[0]
    assert aaa["data_warning"] is None and aaa["return_3m_pct"] == 25.0


def test_window_length_decides_what_is_hidden(client):
    row = _rows(client, "/api/v2/stock/OLDGAP")[0]
    # Gap on session 2 of 30: the 21-session window at the last session no longer contains it.
    assert row["return_1m_pct"] == 900.0 and row["excess_vs_midsml400_21d"] == 900.0
    assert row["return_3m_pct"] is None and row["rs_percentile"] is None
    assert "unconfirmed bonus" in row["data_warning"]


def test_gap_on_the_session_itself_hides_the_1d_change(client):
    row = _rows(client, f"/api/v2/stock/GAPPY?as_of={DAYS[20].isoformat()}")[0]
    assert row["change_1d_pct"] is None
    before = _rows(client, f"/api/v2/stock/GAPPY?as_of={DAYS[19].isoformat()}")[0]
    assert before["data_warning"] is None and before["return_3m_pct"] == 6000.0  # nothing leaks backwards


def test_screener_presets_fail_closed_and_sorts_put_gapped_rows_last(client):
    syms = {r["symbol"] for r in _rows(client, "/api/v2/screener/run?preset=minervini_8of8")}
    assert "AAA" in syms and "REVIEWED" in syms
    assert not {"GAPPY", "RATIO", "OLDGAP"} & syms
    stage2 = {r["symbol"] for r in _rows(client, "/api/v2/screener/run?preset=stage2_leader")}
    assert "GAPPY" not in stage2
    rules = json.dumps([{"field": "close", "op": "gt", "value": 0}])
    rows = _rows(client, f"/api/v2/screener/run?rules={rules}&sort=return_3m_pct&desc=true&min_price=0")
    order = [r["symbol"] for r in rows]
    assert order[0] == "REVIEWED"
    gappy = next(r for r in rows if r["symbol"] == "GAPPY")
    assert gappy["return_3m_pct"] is None and gappy["data_warning"]
    assert order.index("GAPPY") > order.index("AAA")


def test_screener_lookback_path_is_guarded_too(client):
    syms = {r["symbol"] for r in _rows(client, "/api/v2/screener/run?preset=minervini_8of8&lookback_days=5")}
    assert "GAPPY" not in syms and "AAA" in syms


def test_group_members_carry_the_warning(client):
    rows = _rows(client, "/api/v2/groups/industry:Heavy Electrical/members")
    by = {r["symbol"]: r for r in rows}
    assert by["GAPPY"]["data_warning"] and by["GAPPY"]["return_3m_pct"] is None
    assert by["AAA"]["data_warning"] is None


def test_guard_is_fail_soft_without_price_adjustments(tmp_path):
    from App.services import data_gaps

    path = build_market_db(tmp_path / "plain.duckdb")
    con = duckdb.connect(str(path), read_only=True)
    try:
        frame = data_gaps.compute(con)
    finally:
        con.close()
    assert frame.empty and list(frame.columns) == data_gaps.COLUMNS
