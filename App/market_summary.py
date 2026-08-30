"""Market tape read model — daily/weekly/monthly summary, movers, turnover.

No candidate_state. No Prepare/Observe/Blocked.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd


def _q(db_path: Path, sql: str, params=None) -> pd.DataFrame:
    with duckdb.connect(str(db_path), read_only=True) as db:
        return db.execute(sql, params or []).fetchdf()


def session_dates(db_path: Path) -> dict:
    row = _q(db_path, "SELECT max(trade_date) AS d FROM indicators_daily")
    d = row.iloc[0]["d"] if not row.empty else None
    return {"as_of": d}


def tape(db_path: Path) -> dict:
    out: dict = {"as_of": None, "breadth": {}, "nifty": {}, "midcap": {}, "session_turnover_cr": None}
    dates = session_dates(db_path)
    out["as_of"] = dates["as_of"]
    try:
        b = _q(db_path, "SELECT * FROM breadth_daily ORDER BY trade_date DESC LIMIT 1")
        if not b.empty:
            out["breadth"] = b.iloc[0].to_dict()
    except Exception:
        pass
    try:
        hist = _q(db_path, "SELECT * FROM breadth_daily ORDER BY trade_date DESC LIMIT 21")
        out["breadth_hist"] = hist
    except Exception:
        out["breadth_hist"] = pd.DataFrame()
    try:
        idx = _q(
            db_path,
            """
            SELECT index_name, close_price, return_1d_pct, previous_close
            FROM index_daily
            WHERE trade_date = (SELECT max(trade_date) FROM index_daily)
            """,
        )
        out["indices"] = idx
        for name, key in (("Nifty 50", "nifty"), ("NIFTY MIDCAP 150", "midcap"), ("Nifty Midcap 150", "midcap")):
            hit = idx[idx["index_name"].astype(str).str.lower() == name.lower()] if not idx.empty else pd.DataFrame()
            if not hit.empty:
                out[key] = hit.iloc[0].to_dict()
    except Exception:
        out["indices"] = pd.DataFrame()
    try:
        t = _q(
            db_path,
            """
            SELECT sum(turnover_cr) AS session_turnover_cr
            FROM indicators_daily
            WHERE trade_date = (SELECT max(trade_date) FROM indicators_daily)
            """,
        )
        if not t.empty:
            out["session_turnover_cr"] = t.iloc[0]["session_turnover_cr"]
    except Exception:
        pass
    return out


def movers(db_path: Path, min_mcap: float = 1000.0) -> pd.DataFrame:
    return _q(
        db_path,
        """
        WITH latest AS (SELECT max(trade_date) d FROM indicators_daily)
        SELECT i.symbol, i.close_price,
               (i.close_price / nullif(i.prev_close, 0) - 1) * 100 AS day_pct,
               i.return_5d_pct AS week_pct,
               i.return_1m_pct AS month_pct,
               i.turnover_cr AS t_o_today,
               i.avg_traded_value_cr_20d AS t_o_20d_avg,
               i.volume / nullif(i.avg_volume_20d, 0) AS rvol,
               i.delivery_pct, i.rs_percentile, i.away_52w_high_pct,
               m.market_cap_cr, m.sector, m.industry
        FROM indicators_daily i
        JOIN stocks_master m USING(symbol), latest
        WHERE i.trade_date = latest.d
          AND coalesce(m.market_cap_cr, 0) >= ?
        """,
        [min_mcap],
    )


def stock_turnover(db_path: Path, min_mcap: float = 1000.0) -> pd.DataFrame:
    return _q(
        db_path,
        """
        WITH latest AS (SELECT max(trade_date) d FROM indicators_daily),
        roll AS (
            SELECT symbol,
                   sum(turnover_cr) FILTER (WHERE trade_date >= (SELECT d FROM latest) - INTERVAL 5 DAY) AS t_o_1w,
                   sum(turnover_cr) FILTER (WHERE trade_date >= (SELECT d FROM latest) - INTERVAL 21 DAY) AS t_o_1m
            FROM indicators_daily, latest
            GROUP BY symbol
        )
        SELECT i.symbol,
               (i.close_price / nullif(i.prev_close, 0) - 1) * 100 AS day_pct,
               i.turnover_cr AS t_o_today,
               r.t_o_1w, r.t_o_1m,
               i.turnover_cr / nullif(i.avg_traded_value_cr_20d, 0) AS vs_20d,
               m.sector, m.industry, m.market_cap_cr, i.rs_percentile
        FROM indicators_daily i
        JOIN stocks_master m USING(symbol)
        LEFT JOIN roll r USING(symbol), latest
        WHERE i.trade_date = latest.d
          AND coalesce(m.market_cap_cr, 0) >= ?
        ORDER BY i.turnover_cr DESC NULLS LAST
        LIMIT 40
        """,
        [min_mcap],
    )


def group_tape(db_path: Path, level: str = "sector") -> pd.DataFrame:
    col = "sector" if level == "sector" else "industry"
    frame = _q(
        db_path,
        f"""
        WITH latest AS (SELECT max(trade_date) d FROM indicators_daily),
        today AS (
            SELECT m.{col} AS grp,
                   count(*) AS n,
                   sum(i.turnover_cr) AS t_o_today,
                   avg((i.close_price / nullif(i.prev_close, 0) - 1) * 100) AS day_pct,
                   avg(i.return_5d_pct) AS week_pct,
                   avg(i.return_1m_pct) AS month_pct,
                   avg(i.rs_percentile) AS rs,
                   sum(CASE WHEN i.close_price > i.prev_close THEN 1 ELSE 0 END) * 100.0 / count(*) AS advance_pct,
                   sum(CASE WHEN i.close_price > i.ema_50 THEN 1 ELSE 0 END) * 100.0 / count(*) AS above_50
            FROM indicators_daily i
            JOIN stocks_master m USING(symbol), latest
            WHERE i.trade_date = latest.d AND m.{col} IS NOT NULL
            GROUP BY 1
        ),
        hist AS (
            SELECT m.{col} AS grp, i.trade_date, sum(i.turnover_cr) AS t_o
            FROM indicators_daily i
            JOIN stocks_master m USING(symbol), latest
            WHERE i.trade_date >= (SELECT d FROM latest) - INTERVAL 21 DAY
              AND m.{col} IS NOT NULL
            GROUP BY 1, 2
        ),
        roll AS (
            SELECT grp,
                   sum(t_o) FILTER (WHERE trade_date >= (SELECT d FROM latest) - INTERVAL 5 DAY) AS t_o_1w,
                   avg(t_o) AS t_o_20d_avg
            FROM hist, latest
            GROUP BY grp
        )
        SELECT t.*, r.t_o_1w, r.t_o_20d_avg,
               t.t_o_today / nullif(r.t_o_20d_avg, 0) AS vs_20d
        FROM today t
        LEFT JOIN roll r USING(grp)
        ORDER BY t.t_o_today DESC NULLS LAST
        """,
    )
    if not frame.empty and "rs" in frame.columns:
        frame["rs_rank"] = frame["rs"].rank(ascending=False, method="min").astype("Int64")
    return frame


def group_trend(db_path: Path, level: str = "sector", top_n: int = 6, days: int = 21) -> pd.DataFrame:
    col = "sector" if level == "sector" else "industry"
    top_n = max(1, min(10, int(top_n)))
    days = max(5, min(60, int(days)))
    return _q(
        db_path,
        f"""
        WITH latest AS (SELECT max(trade_date) d FROM indicators_daily),
        top AS (
            SELECT m.{col} AS grp, sum(i.turnover_cr) AS t_o
            FROM indicators_daily i
            JOIN stocks_master m USING(symbol), latest
            WHERE i.trade_date = latest.d AND m.{col} IS NOT NULL
            GROUP BY 1
            ORDER BY t_o DESC NULLS LAST
            LIMIT {top_n}
        )
        SELECT i.trade_date, m.{col} AS grp,
               avg((i.close_price / nullif(i.prev_close, 0) - 1) * 100) AS day_pct
        FROM indicators_daily i
        JOIN stocks_master m USING(symbol), latest
        WHERE i.trade_date >= (SELECT d FROM latest) - INTERVAL {days} DAY
          AND m.{col} IN (SELECT grp FROM top)
        GROUP BY 1, 2
        ORDER BY i.trade_date
        """,
    )


def near_highs(db_path: Path, within_pct: float = 5.0, min_mcap: float = 1000.0) -> pd.DataFrame:
    return _q(
        db_path,
        """
        WITH latest AS (SELECT max(trade_date) d FROM indicators_daily)
        SELECT i.symbol,
               (i.close_price / nullif(i.prev_close, 0) - 1) * 100 AS day_pct,
               i.away_52w_high_pct, i.rs_percentile, i.rvol, i.turnover_cr AS t_o_today,
               i.delivery_pct, m.sector, m.industry, m.market_cap_cr
        FROM indicators_daily i
        JOIN stocks_master m USING(symbol), latest
        WHERE i.trade_date = latest.d
          AND i.away_52w_high_pct BETWEEN ? AND 2
          AND coalesce(m.market_cap_cr, 0) >= ?
        ORDER BY i.away_52w_high_pct DESC NULLS LAST, i.rvol DESC NULLS LAST
        LIMIT 25
        """,
        [-abs(within_pct), min_mcap],
    )


def delivery_thrust(db_path: Path, min_mcap: float = 1000.0) -> pd.DataFrame:
    return _q(
        db_path,
        """
        WITH latest AS (SELECT max(trade_date) d FROM indicators_daily)
        SELECT i.symbol,
               (i.close_price / nullif(i.prev_close, 0) - 1) * 100 AS day_pct,
               i.delivery_pct, i.rvol, i.turnover_cr AS t_o_today,
               i.rs_percentile, i.away_52w_high_pct, m.sector, m.industry, m.market_cap_cr
        FROM indicators_daily i
        JOIN stocks_master m USING(symbol), latest
        WHERE i.trade_date = latest.d
          AND (i.close_price / nullif(i.prev_close, 0) - 1) * 100 > 0
          AND i.delivery_pct >= 50
          AND coalesce(i.rvol, 0) >= 1.2
          AND coalesce(m.market_cap_cr, 0) >= ?
        ORDER BY i.rvol DESC NULLS LAST, i.delivery_pct DESC NULLS LAST
        LIMIT 20
        """,
        [min_mcap],
    )
