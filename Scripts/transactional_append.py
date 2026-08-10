"""Small transactional write boundary used by the ingestion pipeline."""

from __future__ import annotations

from pathlib import Path

import duckdb

from migrations import run_migrations
from ingestion_manifest import SessionPlan


ALLOWED_TABLES = {"security_reference_daily", "corporate_actions", "price_adjustment_factors", "index_daily", "security_events", "security_risk_daily", "top_value_daily", "ingestion_batches", "ingested_reports"}


def append_batch(db_path: Path, session_plan: SessionPlan) -> None:
    run_migrations(db_path)
    with duckdb.connect(str(db_path)) as db:
        db.begin()
        try:
            for table, rows in session_plan.rows_by_table.items():
                if table not in ALLOWED_TABLES:
                    raise ValueError(f"table is not appendable: {table}")
                if not rows:
                    continue
                columns = list(rows[0])
                placeholders = ",".join("?" for _ in columns)
                quoted = ",".join('"' + col.replace('"', '""') + '"' for col in columns)
                for row in rows:
                    db.execute(f"INSERT INTO {table} ({quoted}) VALUES ({placeholders}) ON CONFLICT DO NOTHING", [row.get(col) for col in columns])
            if session_plan.inject_failure:
                raise RuntimeError("injected append failure")
            db.commit()
        except Exception:
            db.rollback()
            raise
