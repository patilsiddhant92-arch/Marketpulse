"""Explicit DuckDB schema migrations for decision-system tables."""

from __future__ import annotations

from pathlib import Path

import duckdb


CURRENT_SCHEMA_VERSION = 7
SCHEMA_FILE = Path(__file__).with_name("schema.sql")

_MIGRATION_2 = (
    'ALTER TABLE candidate_daily ADD COLUMN IF NOT EXISTS eligibility_status TEXT',
    'ALTER TABLE candidate_daily ADD COLUMN IF NOT EXISTS blocking_reasons TEXT',
    'ALTER TABLE candidate_daily ADD COLUMN IF NOT EXISTS warning_reasons TEXT',
    'ALTER TABLE candidate_daily ADD COLUMN IF NOT EXISTS geometry_valid BOOLEAN',
)

_MIGRATION_3 = (
    """
    CREATE TABLE IF NOT EXISTS security_risk_daily (
        trade_date DATE,
        symbol TEXT,
        security_name TEXT,
        risk_type TEXT,
        new_value DOUBLE,
        previous_value DOUBLE,
        status TEXT,
        source_file TEXT,
        source_checksum TEXT,
        PRIMARY KEY (trade_date, symbol, security_name, risk_type, source_file)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS top_value_daily (
        trade_date DATE,
        symbol TEXT,
        security_name TEXT,
        previous_close DOUBLE,
        close_price DOUBLE,
        net_trade_qty BIGINT,
        net_trade_value_cr DOUBLE,
        source_checksum TEXT,
        PRIMARY KEY (trade_date, security_name)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_security_risk_date ON security_risk_daily(trade_date, risk_type)",
    "CREATE INDEX IF NOT EXISTS idx_top_value_date ON top_value_daily(trade_date, net_trade_value_cr)",
)

_MIGRATION_4 = {
    "indicators_daily": (
        "ALTER TABLE indicators_daily ADD COLUMN IF NOT EXISTS atr_14_wilder DOUBLE",
        "ALTER TABLE indicators_daily ADD COLUMN IF NOT EXISTS atr_pct_wilder DOUBLE",
        "ALTER TABLE indicators_daily ADD COLUMN IF NOT EXISTS distance_below_52w DOUBLE",
        "ALTER TABLE indicators_daily ADD COLUMN IF NOT EXISTS base_quality_score DOUBLE",
        "ALTER TABLE indicators_daily ADD COLUMN IF NOT EXISTS setup_class TEXT",
        "ALTER TABLE indicators_daily ADD COLUMN IF NOT EXISTS rs_percentile_no_fill DOUBLE",
    ),
    "deals": (
        "ALTER TABLE deals ADD COLUMN IF NOT EXISTS clientele TEXT",
        "ALTER TABLE deals ADD COLUMN IF NOT EXISTS clientele_sub TEXT",
        "ALTER TABLE deals ADD COLUMN IF NOT EXISTS is_prop BOOLEAN",
        "ALTER TABLE deals ADD COLUMN IF NOT EXISTS needs_review BOOLEAN",
    ),
}

# PR ingestion uses ``ON CONFLICT`` against these natural keys.  Early
# databases were created before the constraints were present in schema.sql,
# so merely recording schema version 4 is not enough to make those writes
# safe.  Migration 5 repairs the existing tables in place.
_MIGRATION_5 = {
    "security_events": ("ux_security_events_natural_key", ("symbol", "event_date", "event_type", "source_id")),
    "corporate_actions": ("ux_corporate_actions_natural_key", ("symbol", "ex_date", "action_type", "description")),
    "security_risk_daily": ("ux_security_risk_daily_natural_key", ("trade_date", "symbol", "security_name", "risk_type", "source_file")),
    "top_value_daily": ("ux_top_value_daily_natural_key", ("trade_date", "security_name")),
}

_MIGRATION_6 = {
    "indicators_daily": (
        "ALTER TABLE indicators_daily ADD COLUMN IF NOT EXISTS atr_pct_primary DOUBLE",
        "ALTER TABLE indicators_daily ADD COLUMN IF NOT EXISTS distance_to_high_pct_corrected DOUBLE",
    ),
    "candidate_daily": (
        "ALTER TABLE candidate_daily ADD COLUMN IF NOT EXISTS geometry_warning TEXT",
    ),
}

_MIGRATION_7 = (
    "ALTER TABLE indicators_daily ADD COLUMN IF NOT EXISTS rs_percentile_primary DOUBLE",
)

_SECTOR_METRICS_TABLE = """
CREATE TABLE IF NOT EXISTS sector_metrics_daily (
    trade_date DATE,
    level TEXT,
    group_name TEXT,
    stock_count INTEGER,
    rs_vs_nifty_21d DOUBLE,
    rs_vs_nifty_63d DOUBLE,
    breadth_50 DOUBLE,
    breadth_200 DOUBLE,
    adv_concentration_top3 DOUBLE,
    near_52w_pct DOUBLE,
    adv_total_cr DOUBLE,
    tech_pass_n INTEGER,
    funda_pass_n INTEGER,
    deal_net_10s_cr DOUBLE,
    deal_prop_10s_cr DOUBLE,
    rotation_state TEXT,
    PRIMARY KEY (trade_date, level, group_name)
)
"""


def _ensure_migration_table(db: duckdb.DuckDBPyConnection) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT current_timestamp
        )
        """
    )


def _table_exists(db: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    row = db.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
        [table_name],
    ).fetchone()
    return bool(row and row[0])


def _has_primary_key(db: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    row = db.execute(
        """
        SELECT count(*)
        FROM duckdb_constraints()
        WHERE table_name = ? AND constraint_type = 'PRIMARY KEY'
        """,
        [table_name],
    ).fetchone()
    return bool(row and row[0])


def _has_index(db: duckdb.DuckDBPyConnection, index_name: str) -> bool:
    row = db.execute(
        "SELECT count(*) FROM duckdb_indexes() WHERE index_name = ?",
        [index_name],
    ).fetchone()
    return bool(row and row[0])


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
                current = 2
            if current < 3:
                for statement in _MIGRATION_3:
                    db.execute(statement)
                db.execute("INSERT INTO schema_migrations(version) VALUES (3)")
                current = 3
            if current < 4:
                for table_name, statements in _MIGRATION_4.items():
                    if not _table_exists(db, table_name):
                        continue
                    for statement in statements:
                        db.execute(statement)
                db.execute("INSERT INTO schema_migrations(version) VALUES (4)")
                current = 4
            if current < 5:
                for table_name, (index_name, columns) in _MIGRATION_5.items():
                    if (
                        not _table_exists(db, table_name)
                        or _has_primary_key(db, table_name)
                        or _has_index(db, index_name)
                    ):
                        continue
                    joined = ", ".join(f'"{column}"' for column in columns)
                    db.execute(f'CREATE UNIQUE INDEX "{index_name}" ON "{table_name}" ({joined})')
                db.execute("INSERT INTO schema_migrations(version) VALUES (5)")
                current = 5
            if current < 6:
                db.execute(_SECTOR_METRICS_TABLE)
                for table_name, statements in _MIGRATION_6.items():
                    if not _table_exists(db, table_name):
                        continue
                    for statement in statements:
                        db.execute(statement)
                db.execute("INSERT INTO schema_migrations(version) VALUES (6)")
                current = 6
            if current < 7:
                if _table_exists(db, "indicators_daily"):
                    for statement in _MIGRATION_7:
                        db.execute(statement)
                db.execute("INSERT INTO schema_migrations(version) VALUES (7)")
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
