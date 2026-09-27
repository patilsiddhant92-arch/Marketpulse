"""Fixture DuckDB builder for the API v2 contract tests (no tests in this module).

Universe (30 sessions ending 2026-09-25, weekdays only):
- AAA     healthy large cap, every value present
- NULLRS  IPO-like: rs_percentile / delivery_pct / ema_200 NULL
- SMALL   below the ₹1,000 Cr floor
- TOTAL   aggregate row from the mcap file (must never appear)
Deals: one AAA print stored twice (Bulk and Block) on the last session.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd

LAST = date(2026, 9, 25)
N_SESSIONS = 30

IND_COLS = {
    "symbol": "VARCHAR", "series": "VARCHAR", "trade_date": "TIMESTAMP", "prev_close": "DOUBLE",
    "open_price": "DOUBLE", "high_price": "DOUBLE", "low_price": "DOUBLE", "close_price": "DOUBLE",
    "volume": "BIGINT", "turnover_cr": "DOUBLE", "delivery_qty": "DOUBLE", "delivery_pct": "DOUBLE",
    "avg_volume_20d": "DOUBLE", "rvol": "DOUBLE", "avg_delivery_pct_20d": "DOUBLE", "rs_percentile": "DOUBLE",
    "rs_percentile_ipo": "DOUBLE", "rs_rank_t5": "DOUBLE", "rs_rank_t15": "DOUBLE", "rs_rank_t30": "DOUBLE",
    "rs_vs_midsml400_21d": "DOUBLE", "rs_vs_midsml400_63d": "DOUBLE", "rs_vs_nifty50_21d": "DOUBLE",
    "rs_vs_nifty50_63d": "DOUBLE", "rs_vs_sector_index_21d": "DOUBLE", "rs_vs_sector_index_63d": "DOUBLE",
    "sector_index_name": "VARCHAR", "trend_template_pass_n": "BIGINT", "trend_template_pass": "BOOLEAN",
    "away_52w_high_pct": "DOUBLE", "away_52w_low_pct": "DOUBLE", "away_10ema_pct": "DOUBLE",
    "high_52w_date": "TIMESTAMP", "adr_20_pct": "DOUBLE", "atr_pct": "DOUBLE", "trend_score": "DOUBLE",
    "return_1m_pct": "DOUBLE", "return_3m_pct": "DOUBLE", "return_6m_pct": "DOUBLE", "ema_10": "DOUBLE",
    "ema_20": "DOUBLE", "ema_50": "DOUBLE", "ema_100": "DOUBLE", "ema_200": "DOUBLE",
    "avg_traded_value_cr_20d": "DOUBLE", "high_52w": "DOUBLE", "low_52w": "DOUBLE", "band_remarks": "VARCHAR",
    "sma_50": "DOUBLE", "sma_150": "DOUBLE", "sma_200": "DOUBLE", "sma_200_rising": "BOOLEAN", "rsi_14": "DOUBLE",
    "rsi_14_w": "DOUBLE", "nr7": "BOOLEAN", "inside_bar": "BOOLEAN", "delivery_spike": "BOOLEAN",
    "price_up_delivery_up": "BOOLEAN", "ema_shakeout": "BOOLEAN", "close_location_pct": "DOUBLE",
}


def sessions(last: date = LAST, n: int = N_SESSIONS) -> list[date]:
    out, d = [], last
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def _create(con: duckdb.DuckDBPyConnection, name: str, cols: dict[str, str], frame: pd.DataFrame) -> None:
    con.execute(f"CREATE TABLE {name} ({', '.join(f'{c} {t}' for c, t in cols.items())})")
    if not frame.empty:
        con.register("_src", frame)
        con.execute(f"INSERT INTO {name} BY NAME SELECT * FROM _src")
        con.unregister("_src")


def _ind_rows(days: list[date]) -> pd.DataFrame:
    rows = []
    for i, d in enumerate(days):
        for sym, base, ok in (("AAA", 100.0, True), ("NULLRS", 50.0, False), ("SMALL", 20.0, True), ("TOTAL", 1.0, True)):
            close = base + i
            rows.append({
                "symbol": sym, "series": "EQ", "trade_date": pd.Timestamp(d), "prev_close": close - 1,
                "open_price": close - 0.5, "high_price": close + 1, "low_price": close - 1.5, "close_price": close,
                "volume": 2_000_000, "turnover_cr": 20.0, "delivery_qty": 1_000_000 if ok else None,
                "delivery_pct": 50.0 if ok else None, "avg_volume_20d": 1_500_000, "rvol": 1.3,
                "avg_delivery_pct_20d": 40.0 if ok else None,
                "rs_percentile": 88.0 if ok else None, "rs_percentile_ipo": None if ok else 77.0,
                "rs_rank_t5": 85.0 if ok else None, "rs_rank_t15": 80.0 if ok else None, "rs_rank_t30": 70.0 if ok else None,
                "rs_vs_midsml400_21d": 4.0 if ok else None, "rs_vs_midsml400_63d": 9.0 if ok else None,
                "rs_vs_nifty50_21d": 3.0 if ok else None, "rs_vs_nifty50_63d": 8.0 if ok else None,
                "trend_template_pass_n": 8 if ok else None, "trend_template_pass": True if ok else None,
                "away_52w_high_pct": -3.0, "away_52w_low_pct": 60.0, "away_10ema_pct": 1.0,
                "high_52w_date": pd.Timestamp(d - timedelta(days=3)), "adr_20_pct": 3.2, "atr_pct": 2.9,
                "return_1m_pct": 12.0, "return_3m_pct": 25.0, "return_6m_pct": 40.0,
                "ema_10": close - 1, "ema_20": close - 2, "ema_50": close - 4, "ema_100": close - 6,
                "ema_200": (close - 8) if ok else None, "avg_traded_value_cr_20d": 18.0,
                "high_52w": close + 1, "low_52w": base / 2, "sma_50": close - 4, "sma_150": close - 7,
                "sma_200": close - 8, "sma_200_rising": True, "rsi_14": 64.0, "rsi_14_w": 66.0, "nr7": False,
                "inside_bar": False, "delivery_spike": False, "price_up_delivery_up": ok,
            })
    return pd.DataFrame(rows)


def build_market_db(path: Path, *, last: date = LAST, with_regime: bool = False) -> Path:
    days = sessions(last)
    con = duckdb.connect(str(path))
    ind = _ind_rows(days)
    _create(con, "indicators_daily", IND_COLS, ind)
    price_cols = {c: IND_COLS[c] for c in ("symbol", "series", "trade_date", "prev_close", "open_price", "high_price",
                                           "low_price", "close_price", "volume", "turnover_cr", "delivery_qty",
                                           "delivery_pct")}
    _create(con, "prices_daily", price_cols, ind[list(price_cols)])
    _create(con, "stocks_master", {
        "symbol": "VARCHAR", "security_name": "VARCHAR", "broad_sector": "VARCHAR", "sector": "VARCHAR",
        "broad_industry": "VARCHAR", "industry": "VARCHAR", "market_cap_cr": "DOUBLE", "band": "DOUBLE",
        "band_remarks": "VARCHAR", "listing_date": "TIMESTAMP", "isin": "VARCHAR",
    }, pd.DataFrame([
        {"symbol": "AAA", "security_name": "Aaa Ltd", "broad_sector": "Industrials", "sector": "Capital Goods",
         "broad_industry": "Electrical Equipment", "industry": "Heavy Electrical", "market_cap_cr": 5000.0, "band": 20.0},
        {"symbol": "NULLRS", "security_name": "New Listing Ltd", "broad_sector": "Industrials", "sector": "Capital Goods",
         "broad_industry": "Electrical Equipment", "industry": "Heavy Electrical", "market_cap_cr": 3000.0, "band": 20.0},
        {"symbol": "SMALL", "security_name": "Small Ltd", "broad_sector": "Industrials", "sector": "Capital Goods",
         "broad_industry": "Electrical Equipment", "industry": "Heavy Electrical", "market_cap_cr": 500.0, "band": 20.0},
        {"symbol": "TOTAL", "security_name": "TOTAL", "broad_sector": "Services", "sector": "Services",
         "broad_industry": "Transport Services", "industry": "Logistics", "market_cap_cr": 4.77e7, "band": 20.0},
    ]))
    _create(con, "breadth_daily", {
        "trade_date": "TIMESTAMP", "stocks": "DOUBLE", "advancers": "DOUBLE", "decliners": "DOUBLE",
        "unchanged": "DOUBLE", "advance_pct": "DOUBLE", "above_10ema_pct": "DOUBLE", "above_20ema_pct": "DOUBLE",
        "above_50ema_pct": "DOUBLE", "above_200ema_pct": "DOUBLE", "near_52w_highs": "DOUBLE", "breadth_state": "VARCHAR",
    }, pd.DataFrame([{
        "trade_date": pd.Timestamp(d), "stocks": 100, "advancers": 60, "decliners": 40, "unchanged": 0,
        "advance_pct": 60.0, "above_10ema_pct": 55.0, "above_20ema_pct": 52.0, "above_50ema_pct": 51.0,
        "above_200ema_pct": 49.0, "near_52w_highs": 10, "breadth_state": "Neutral",
    } for d in days]))
    idx = []
    for i, d in enumerate(days):
        for name, base in (("Nifty 50", 24000.0), ("NIFTY MIDSML 400", 20000.0), ("India VIX", 12.0)):
            idx.append({"trade_date": pd.Timestamp(d), "index_name": name, "previous_close": base + i - 1,
                        "close_price": base + i, "return_1d_pct": 0.1, "turnover_cr": 1000.0 + i})
    _create(con, "index_daily", {"trade_date": "TIMESTAMP", "index_name": "VARCHAR", "previous_close": "DOUBLE",
                                 "close_price": "DOUBLE", "return_1d_pct": "DOUBLE", "turnover_cr": "DOUBLE"},
            pd.DataFrame(idx))
    deal = {"trade_date": pd.Timestamp(days[-1]), "symbol": "AAA", "client_name": "GOOD FUND LP", "side": "BUY",
            "quantity": 100000, "price": 128.0, "deal_value_cr": 1.28, "clientele": "FII", "is_prop": False,
            "close_price": 129.0}
    _create(con, "deals", {"deal_type": "VARCHAR", "trade_date": "TIMESTAMP", "symbol": "VARCHAR",
                           "client_name": "VARCHAR", "side": "VARCHAR", "quantity": "INTEGER", "price": "DOUBLE",
                           "deal_value_cr": "DOUBLE", "clientele": "VARCHAR", "is_prop": "BOOLEAN",
                           "close_price": "DOUBLE"},
            pd.DataFrame([dict(deal, deal_type="Bulk"), dict(deal, deal_type="Block"),
                          dict(deal, symbol="TOTAL", deal_type="Bulk")]))
    _create(con, "security_events", {"symbol": "VARCHAR", "event_date": "TIMESTAMP", "event_type": "VARCHAR",
                                     "headline": "VARCHAR"},
            pd.DataFrame([{"symbol": "AAA", "event_date": pd.Timestamp(days[-1] + timedelta(days=5)),
                           "event_type": "financial_results", "headline": "Q2 results"},
                          {"symbol": "AAA", "event_date": pd.Timestamp(days[5]), "event_type": "dividend",
                           "headline": "Dividend"}]))
    _create(con, "corporate_actions", {"symbol": "VARCHAR", "ex_date": "TIMESTAMP", "action_type": "VARCHAR",
                                       "description": "VARCHAR"}, pd.DataFrame())
    _create(con, "sector_rotation", {
        "trade_date": "TIMESTAMP", "level": "VARCHAR", "group_name": "VARCHAR", "stocks": "DOUBLE",
        "return_5d_pct": "DOUBLE", "return_1m_pct": "DOUBLE", "return_3m_pct": "DOUBLE", "rs_percentile": "DOUBLE",
        "above_50ema_pct": "DOUBLE", "above_200ema_pct": "DOUBLE", "rotation_rank": "DOUBLE",
        "rank_change_5d": "DOUBLE", "rank_change_20d": "DOUBLE", "turnover_share_pct": "DOUBLE",
        "turnover_share_delta_5d": "DOUBLE", "rotation_state": "VARCHAR", "leader_symbols": "VARCHAR",
    }, pd.DataFrame([{
        "trade_date": pd.Timestamp(d), "level": "Industry", "group_name": g, "stocks": 3, "return_1m_pct": r,
        "above_50ema_pct": None, "rotation_rank": rank, "rank_change_5d": None, "turnover_share_pct": 5.0,
        "rotation_state": "Leading", "leader_symbols": "AAA",
    } for d in days for g, r, rank in (("Heavy Electrical", 5.0, 1), ("2/3 Wheelers", -1.0, 2), ("TOTAL", 99.0, 0))]))
    if with_regime:
        _create(con, "regime_daily", {
            "trade_date": "TIMESTAMP", "verdict": "VARCHAR", "rule_id": "VARCHAR", "days_in_state": "INTEGER",
            "trend_status": "VARCHAR", "trend_sentence": "VARCHAR", "trend_midsml400_vs_50ema_pct": "DOUBLE",
            "participation_status": "VARCHAR", "follow_through_status": "VARCHAR", "stress_status": "VARCHAR",
            "leadership_status": "VARCHAR",
        }, pd.DataFrame([{
            "trade_date": pd.Timestamp(d), "verdict": "Constructive", "rule_id": "R2", "days_in_state": i + 1,
            "trend_status": "Healthy", "trend_sentence": "MidSml400 above a rising 50 EMA",
            "trend_midsml400_vs_50ema_pct": None, "participation_status": "Neutral",
            "follow_through_status": None, "stress_status": "Healthy", "leadership_status": "Neutral",
        } for i, d in enumerate(days)]))
    con.close()
    return path
