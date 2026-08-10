"""Separate storage and migration helpers for manual MarketPulse data."""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import duckdb


USER_SCHEMA_VERSION = 1
LEGACY_MIGRATION_KEY = "legacy_market_data_migrated"


@dataclass(frozen=True)
class MigrationReport:
    copied_tables: tuple[str, ...] = ()
    rows_copied: int = 0
    backup_path: Path | None = None


def _create_schema(db: duckdb.DuckDBPyConnection) -> None:
    db.execute("CREATE TABLE IF NOT EXISTS user_schema_migrations (version INTEGER PRIMARY KEY, applied_at TIMESTAMP DEFAULT current_timestamp)")
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS trade_journal (
            id BIGINT PRIMARY KEY, created_at TIMESTAMP, updated_at TIMESTAMP, trade_date DATE,
            symbol VARCHAR, trade_type VARCHAR, setup_type VARCHAR, entry_price DOUBLE, quantity DOUBLE,
            stop_loss DOUBLE, target DOUBLE, position_size DOUBLE, risk_amount DOUBLE, risk_pct DOUBLE,
            reward_pct DOUBLE, r_multiple_target DOUBLE, status VARCHAR, exit_date DATE, exit_price DOUBLE,
            exit_reason VARCHAR, notes VARCHAR, mistake_tag VARCHAR
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio_positions (
            symbol VARCHAR PRIMARY KEY, status VARCHAR, qty DOUBLE, avg_buy_price DOUBLE, buy_date DATE,
            sell_date DATE, sell_price DOUBLE, notes VARCHAR, tags VARCHAR, setup_type VARCHAR,
            stop_price DOUBLE, target_price DOUBLE, thesis VARCHAR, invalidation_note VARCHAR,
            planned_risk_inr DOUBLE, max_risk_pct DOUBLE, created_at TIMESTAMP, updated_at TIMESTAMP
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio_events (
            id BIGINT PRIMARY KEY, symbol VARCHAR, event_type VARCHAR, event_date DATE,
            qty DOUBLE, price DOUBLE, notes VARCHAR, created_at TIMESTAMP
        )
        """
    )
    db.execute("CREATE TABLE IF NOT EXISTS portfolio_settings (setting_key VARCHAR PRIMARY KEY, setting_value VARCHAR, updated_at TIMESTAMP DEFAULT current_timestamp)")
    db.execute("INSERT INTO user_schema_migrations(version) SELECT ? WHERE NOT EXISTS (SELECT 1 FROM user_schema_migrations WHERE version = ?)", [USER_SCHEMA_VERSION, USER_SCHEMA_VERSION])


def initialize_user_db(user_db: Path) -> None:
    user_db = Path(user_db)
    user_db.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(user_db)) as db:
        _create_schema(db)


def _tables(db: duckdb.DuckDBPyConnection) -> set[str]:
    return {str(row[0]) for row in db.execute("SHOW TABLES").fetchall()}


def _copy_table(market: duckdb.DuckDBPyConnection, user: duckdb.DuckDBPyConnection, table: str) -> int:
    if table not in _tables(market) or int(user.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]):
        return 0
    source_columns = {str(row[1]) for row in market.execute(f'PRAGMA table_info("{table}")').fetchall()}
    target_columns = [str(row[1]) for row in user.execute(f'PRAGMA table_info("{table}")').fetchall()]
    columns = [column for column in target_columns if column in source_columns]
    if not columns:
        return 0
    quoted = ", ".join(f'"{column}"' for column in columns)
    frame = market.execute(f'SELECT {quoted} FROM "{table}"').fetchdf()
    if frame.empty:
        return 0
    user.register("migration_rows", frame)
    try:
        user.execute(f'INSERT INTO "{table}" ({quoted}) SELECT {quoted} FROM migration_rows')
    finally:
        user.unregister("migration_rows")
    return len(frame)


def backup_user_db(user_db: Path, backup_dir: Path) -> Path:
    user_db = Path(user_db)
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"{user_db.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{user_db.suffix}"
    shutil.copy2(user_db, target)
    return target


def migrate_user_data(market_db: Path, user_db: Path, backup_dir: Path | None = None) -> MigrationReport:
    user_db = Path(user_db)
    existed_before = user_db.exists()
    initialize_user_db(user_db)
    backup_path: Path | None = None
    copied: list[str] = []
    rows = 0
    with duckdb.connect(str(market_db), read_only=True) as market, duckdb.connect(str(user_db)) as user:
        already_migrated = user.execute(
            "SELECT count(*) FROM portfolio_settings WHERE setting_key = ?",
            [LEGACY_MIGRATION_KEY],
        ).fetchone()[0]
        if already_migrated:
            return MigrationReport((), 0, None)
        if backup_dir and existed_before:
            backup_path = backup_user_db(user_db, backup_dir)
        user.execute("BEGIN")
        try:
            for table in ("trade_journal", "portfolio_positions", "portfolio_events"):
                count = _copy_table(market, user, table)
                if count:
                    copied.append(table)
                    rows += count
            user.execute(
                "INSERT INTO portfolio_settings(setting_key, setting_value) VALUES (?, ?) "
                "ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value, updated_at = now()",
                [LEGACY_MIGRATION_KEY, datetime.now().isoformat(timespec="seconds")],
            )
            user.execute("COMMIT")
        except Exception:
            user.execute("ROLLBACK")
            raise
    return MigrationReport(tuple(copied), rows, backup_path)


def migrate_user_tables(market_db: Path, user_db: Path) -> MigrationReport:
    return migrate_user_data(market_db, user_db)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Initialize and migrate MarketPulse manual data storage.")
    parser.add_argument("--market-db", type=Path, required=True)
    parser.add_argument("--user-db", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()
    print(migrate_user_data(args.market_db, args.user_db, args.backup_dir))
