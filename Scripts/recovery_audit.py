"""Read-only audit of the data boundaries that drive the recovery release."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb


@dataclass(frozen=True)
class RecoveryAudit:
    database_date: date | None
    candidate_date: date | None
    score_versions: dict[str, int]
    latest_candidate_count: int
    below_market_cap_count: int
    missing_market_cap_count: int
    portfolio_count: int
    pr_table_counts: dict[str, int]


_PR_TABLES = (
    "security_events",
    "corporate_actions",
    "security_risk_daily",
    "top_value_daily",
    "ingested_reports",
)


def _table_names(db: duckdb.DuckDBPyConnection) -> set[str]:
    return {str(row[0]) for row in db.execute("SHOW TABLES").fetchall()}


def _latest_date(db: duckdb.DuckDBPyConnection, table: str) -> date | None:
    try:
        value = db.execute(f'SELECT max(trade_date) FROM "{table}"').fetchone()[0]
    except duckdb.Error:
        return None
    if value is None:
        return None
    return value.date() if hasattr(value, "date") else date.fromisoformat(str(value)[:10])


def audit_database(db_path: Path) -> RecoveryAudit:
    """Inspect a market database without creating tables or writing state."""

    path = Path(db_path)
    with duckdb.connect(str(path), read_only=True) as db:
        tables = _table_names(db)
        candidate_date = _latest_date(db, "candidate_daily") if "candidate_daily" in tables else None

        dates = [
            _latest_date(db, table)
            for table in ("prices_daily", "indicators_daily", "candidate_daily")
            if table in tables
        ]
        database_date = max((value for value in dates if value is not None), default=None)

        score_versions: dict[str, int] = {}
        latest_candidate_count = 0
        below_market_cap_count = 0
        missing_market_cap_count = 0
        if "candidate_daily" in tables:
            for version, count in db.execute(
                "SELECT score_version, count(*) FROM candidate_daily GROUP BY score_version ORDER BY score_version"
            ).fetchall():
                score_versions[str(version)] = int(count)
            if candidate_date is not None:
                latest_candidate_count = int(
                    db.execute("SELECT count(*) FROM candidate_daily WHERE trade_date = ?", [candidate_date]).fetchone()[0]
                )
                below_market_cap_count = int(
                    db.execute(
                        "SELECT count(*) FROM candidate_daily WHERE trade_date = ? AND market_cap_cr < 1000",
                        [candidate_date],
                    ).fetchone()[0]
                )
                missing_market_cap_count = int(
                    db.execute(
                        "SELECT count(*) FROM candidate_daily WHERE trade_date = ? AND market_cap_cr IS NULL",
                        [candidate_date],
                    ).fetchone()[0]
                )

        portfolio_count = 0
        if "portfolio_positions" in tables:
            columns = {str(row[1]) for row in db.execute("PRAGMA table_info(portfolio_positions)").fetchall()}
            sql = "SELECT count(*) FROM portfolio_positions"
            if "status" in columns:
                sql += " WHERE upper(coalesce(status, '')) = 'OPEN'"
            portfolio_count = int(db.execute(sql).fetchone()[0])

        pr_table_counts = {
            table: int(db.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]) if table in tables else 0
            for table in _PR_TABLES
        }

    return RecoveryAudit(
        database_date=database_date,
        candidate_date=candidate_date,
        score_versions=score_versions,
        latest_candidate_count=latest_candidate_count,
        below_market_cap_count=below_market_cap_count,
        missing_market_cap_count=missing_market_cap_count,
        portfolio_count=portfolio_count,
        pr_table_counts=pr_table_counts,
    )


__all__ = ["RecoveryAudit", "audit_database"]


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Audit a MarketPulse DuckDB without writing to it.")
    parser.add_argument("db_path", type=Path)
    args = parser.parse_args()
    report = audit_database(args.db_path)
    print(json.dumps(report.__dict__, default=str, indent=2))
