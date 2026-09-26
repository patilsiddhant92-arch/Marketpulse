"""Small transactional write boundary used by the ingestion pipeline."""

from __future__ import annotations

from pathlib import Path

import duckdb

from migrations import run_migrations
from ingestion_manifest import SessionPlan


ALLOWED_TABLES = {"security_reference_daily", "corporate_actions", "price_adjustment_factors", "index_daily", "security_events", "security_risk_daily", "top_value_daily", "ingestion_batches", "ingested_reports"}

CONFLICT_TARGETS: dict[str, tuple[str, ...]] = {
    "security_reference_daily": ("symbol", "effective_date"),
    "corporate_actions": ("symbol", "ex_date", "action_type", "description"),
    "price_adjustment_factors": ("symbol", "trade_date"),
    "index_daily": ("trade_date", "index_name"),
    "security_events": ("symbol", "event_date", "event_type", "source_id"),
    "security_risk_daily": ("trade_date", "symbol", "security_name", "risk_type", "source_file"),
    "top_value_daily": ("trade_date", "security_name"),
    "ingestion_batches": ("batch_id",),
    "ingested_reports": ("trade_date", "report_type"),
}


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
                conflict_cols = CONFLICT_TARGETS.get(table)
                if not conflict_cols:
                    raise ValueError(f"no ON CONFLICT target for table: {table}")
                conflict = ", ".join('"' + col.replace('"', '""') + '"' for col in conflict_cols)
                for row in rows:
                    db.execute(
                        f"INSERT INTO {table} ({quoted}) VALUES ({placeholders}) ON CONFLICT ({conflict}) DO NOTHING",
                        [row.get(col) for col in columns],
                    )
            if session_plan.inject_failure:
                raise RuntimeError("injected append failure")
            db.commit()
        except Exception:
            db.rollback()
            raise
