import duckdb


REQUIRED_TABLES = {
    "schema_migrations",
    "security_reference_daily",
    "corporate_actions",
    "price_adjustment_factors",
    "index_daily",
    "security_events",
    "candidate_daily",
    "watchlist_candidates",
    "signal_ledger",
    "signal_outcomes",
    "ingestion_batches",
    "ingested_reports",
}


def table_names(path):
    with duckdb.connect(str(path)) as db:
        return {row[0] for row in db.execute("SHOW TABLES").fetchall()}


def test_migrations_create_focused_watchlist_schema(tmp_path):
    from Scripts.migrations import run_migrations, schema_version

    path = tmp_path / "marketpulse.duckdb"
    run_migrations(path)

    assert REQUIRED_TABLES <= table_names(path)
    assert schema_version(path) >= 1


def test_migrations_are_idempotent_and_preserve_user_tables(tmp_path):
    from Scripts.migrations import CURRENT_SCHEMA_VERSION, run_migrations

    path = tmp_path / "marketpulse.duckdb"
    with duckdb.connect(str(path)) as db:
        db.execute("CREATE TABLE trade_journal (id BIGINT, notes TEXT)")
        db.execute("INSERT INTO trade_journal VALUES (1, 'keep me')")

    run_migrations(path)
    run_migrations(path)

    with duckdb.connect(str(path), read_only=True) as db:
        assert db.execute("SELECT * FROM trade_journal").fetchall() == [(1, "keep me")]
        assert db.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == CURRENT_SCHEMA_VERSION


def test_migration_repairs_legacy_pr_tables_for_conflict_upserts(tmp_path):
    """Legacy databases must gain the keys required by PR-report ON CONFLICT writes."""
    from Scripts.migrations import CURRENT_SCHEMA_VERSION, run_migrations, schema_version

    path = tmp_path / "legacy.duckdb"
    with duckdb.connect(str(path)) as db:
        # Simulate the pre-repair database: tables exist, but were created without
        # the primary keys declared in the current schema.sql.
        db.execute("CREATE TABLE security_events (symbol TEXT, event_date DATE, event_type TEXT, headline TEXT, source_id TEXT, source_checksum TEXT)")
        db.execute("CREATE TABLE corporate_actions (symbol TEXT, ex_date DATE, action_type TEXT, ratio_from DOUBLE, ratio_to DOUBLE, cash_amount DOUBLE, description TEXT, source_checksum TEXT)")
        db.execute("CREATE TABLE security_risk_daily (trade_date DATE, symbol TEXT, security_name TEXT, risk_type TEXT, new_value DOUBLE, previous_value DOUBLE, status TEXT, source_file TEXT, source_checksum TEXT)")
        db.execute("CREATE TABLE top_value_daily (trade_date DATE, symbol TEXT, security_name TEXT, previous_close DOUBLE, close_price DOUBLE, net_trade_qty BIGINT, net_trade_value_cr DOUBLE, source_checksum TEXT)")
        db.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TIMESTAMP DEFAULT current_timestamp)")
        db.execute("INSERT INTO schema_migrations(version) VALUES (4)")

    run_migrations(path)

    with duckdb.connect(str(path)) as db:
        indexes = db.execute(
            """
            SELECT table_name, index_name, is_unique
            FROM duckdb_indexes()
            WHERE table_name IN ('security_events', 'corporate_actions', 'security_risk_daily', 'top_value_daily')
            """
        ).fetchall()
        by_table = {table: (name, unique) for table, name, unique in indexes if unique}

        db.execute(
            """
            INSERT INTO security_events(symbol, event_date, event_type, headline, source_id, source_checksum)
            VALUES ('AAA', '2026-08-17', 'test', 'first', 'id-1', 'one')
            ON CONFLICT (symbol, event_date, event_type, source_id)
            DO UPDATE SET headline = excluded.headline
            """
        )
        db.execute(
            """
            INSERT INTO security_events(symbol, event_date, event_type, headline, source_id, source_checksum)
            VALUES ('AAA', '2026-08-17', 'test', 'second', 'id-1', 'two')
            ON CONFLICT (symbol, event_date, event_type, source_id)
            DO UPDATE SET headline = excluded.headline
            """
        )
        assert db.execute("SELECT count(*) FROM security_events WHERE symbol = 'AAA'").fetchone()[0] == 1
        assert db.execute("SELECT headline FROM security_events WHERE symbol = 'AAA'").fetchone()[0] == "second"

    assert schema_version(path) == CURRENT_SCHEMA_VERSION
    assert by_table["security_events"][0] == "ux_security_events_natural_key"
    assert by_table["corporate_actions"][0] == "ux_corporate_actions_natural_key"
    assert by_table["security_risk_daily"][0] == "ux_security_risk_daily_natural_key"
    assert by_table["top_value_daily"][0] == "ux_top_value_daily_natural_key"
