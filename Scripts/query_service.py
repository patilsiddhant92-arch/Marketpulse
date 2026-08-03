"""Shared read service for decision pages."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd


def _query(db_path: Path, sql: str, params=None) -> pd.DataFrame:
    with duckdb.connect(str(db_path), read_only=True) as db:
        return db.execute(sql, params or []).fetchdf()


def load_today_snapshot(db_path: Path, limit: int = 15, trade_date=None) -> pd.DataFrame:
    if trade_date is None:
        sql = "SELECT * FROM candidate_daily WHERE trade_date = (SELECT max(trade_date) FROM candidate_daily) ORDER BY total_score DESC NULLS LAST, symbol LIMIT ?"
        return _query(db_path, sql, [int(limit)])
    sql = "SELECT * FROM candidate_daily WHERE trade_date = ? ORDER BY total_score DESC NULLS LAST, symbol LIMIT ?"
    return _query(db_path, sql, [trade_date, int(limit)])


def load_candidate_changes(db_path: Path, trade_date=None) -> pd.DataFrame:
    if trade_date is None:
        trade_date = _query(db_path, "SELECT max(trade_date) AS trade_date FROM candidate_daily").iloc[0]["trade_date"]
    return _query(
        db_path,
        """
        WITH current_day AS (SELECT * FROM candidate_daily WHERE trade_date = ?), previous_day AS (SELECT * FROM candidate_daily WHERE trade_date = (SELECT max(trade_date) FROM candidate_daily WHERE trade_date < ?))
        SELECT c.symbol, c.candidate_state, c.total_score, p.total_score AS previous_score, c.latest_change, c.event_risk
        FROM current_day c LEFT JOIN previous_day p USING(symbol, score_version)
        ORDER BY c.total_score DESC NULLS LAST, c.symbol
        """,
        [trade_date, trade_date],
    )


def load_market_context(db_path: Path, trade_date=None) -> dict[str, pd.DataFrame]:
    if trade_date is None:
        trade_date = _query(db_path, "SELECT max(trade_date) AS trade_date FROM breadth_daily").iloc[0]["trade_date"]
    breadth = _query(db_path, "SELECT * FROM breadth_daily WHERE trade_date = ?", [trade_date])
    index = _query(db_path, "SELECT * FROM index_daily WHERE trade_date = ?", [trade_date])
    rotations = _query(db_path, "SELECT * FROM sector_rotation WHERE trade_date = ?", [trade_date])
    return {"breadth": breadth, "index": index, "rotations": rotations}
