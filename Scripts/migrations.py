"""Explicit DuckDB schema migrations for decision-system tables."""

from __future__ import annotations

from pathlib import Path

import duckdb


CURRENT_SCHEMA_VERSION = 2
SCHEMA_FILE = Path(__file__).with_name("schema.sql")

_MIGRATION_2 = (
    'ALTER TABLE candidate_daily ADD COLUMN IF NOT EXISTS eligibility_status TEXT',
    'ALTER TABLE candidate_daily ADD COLUMN IF NOT EXISTS blocking_reasons TEXT',
    'ALTER TABLE candidate_daily ADD COLUMN IF NOT EXISTS warning_reasons TEXT',
    'ALTER TABLE candidate_daily ADD COLUMN IF NOT EXISTS geometry_valid BOOLEAN',
)


def _ensure_migration_table(db: duckdb.DuckDBPyConnection) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT current_timestamp
        )
        """
    )


def schema_version(db_path: Path) -> int:
    if not Path(db_path).exists():
        return 0
    with duckdb.connect(str(db_path), read_only=True) as db:
        tables = {row[0] for row in db.execute("SHOW TABLES").fetchall()}
        if "schema_migrations" not in tables:
            return 0
        row = db.execute("SELECT coalesce(max(version), 0) FROM schema_migrations").fetchone()
        return int(row[0] or 0)


def run_migrations(db_path: Path) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema_sql = SCHEMA_FILE.read_text(encoding="utf-8")
    with duckdb.connect(str(db_path)) as db:
        _ensure_migration_table(db)
        current = int(db.execute("SELECT coalesce(max(version), 0) FROM schema_migrations").fetchone()[0] or 0)
        if current >= CURRENT_SCHEMA_VERSION:
            return
        db.begin()
        try:
            if current < 1:
                for statement in (part.strip() for part in schema_sql.split(";")):
                    if statement:
                        db.execute(statement)
                db.execute("INSERT INTO schema_migrations(version) VALUES (1)")
                current = 1
            if current < 2:
                for statement in _MIGRATION_2:
                    db.execute(statement)
                db.execute("INSERT INTO schema_migrations(version) VALUES (2)")
            db.commit()
        except Exception:
            db.rollback()
            raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Apply explicit MarketPulse schema migrations.")
    parser.add_argument("db_path", type=Path)
    args = parser.parse_args()
    run_migrations(args.db_path)
    print(f"Schema version: {schema_version(args.db_path)}")
