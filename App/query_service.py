"""Application-facing snapshot queries."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd


def _query(db_path: Path, sql: str, params=None) -> pd.DataFrame:
    with duckdb.connect(str(db_path), read_only=True) as db:
        return db.execute(sql, params or []).fetchdf()


def load_app_snapshot(db_path: Path, limit: int = 15) -> dict[str, pd.DataFrame]:
    candidates = _query(db_path, "SELECT * FROM candidate_daily WHERE trade_date = (SELECT max(trade_date) FROM candidate_daily) ORDER BY total_score DESC NULLS LAST, symbol LIMIT ?", [limit])
    tables = set(_query(db_path, "SELECT table_name FROM information_schema.tables WHERE table_schema='main'")["table_name"].tolist())
    if "breadth_daily" in tables:
        breadth = _query(db_path, "SELECT * FROM breadth_daily WHERE trade_date = (SELECT max(trade_date) FROM breadth_daily)")
    else:
        breadth = pd.DataFrame()
    if "candidate_daily" in tables:
        changes = _query(db_path, """
            WITH latest AS (SELECT max(trade_date) AS trade_date FROM candidate_daily), previous AS (SELECT max(trade_date) AS trade_date FROM candidate_daily WHERE trade_date < (SELECT trade_date FROM latest))
            SELECT c.symbol, c.candidate_state, c.latest_change, c.total_score, p.total_score AS previous_score
            FROM candidate_daily c LEFT JOIN candidate_daily p ON p.symbol = c.symbol AND p.score_version = c.score_version AND p.trade_date = (SELECT trade_date FROM previous)
            WHERE c.trade_date = (SELECT trade_date FROM latest)
            ORDER BY c.total_score DESC NULLS LAST, c.symbol LIMIT ?
        """, [limit])
    else:
        changes = pd.DataFrame()
    return {"candidates": candidates, "breadth": breadth, "changes": changes}
