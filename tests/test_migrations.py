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


def test_migration_8_adds_idx_indicators_date_symbol_without_rebuild(tmp_path):
    """Live DBs at schema 7 must gain idx_indicators_date_symbol from _MIGRATION_8."""
    from Scripts.migrations import CURRENT_SCHEMA_VERSION, run_migrations, schema_version

    path = tmp_path / "live.duckdb"
    with duckdb.connect(str(path)) as db:
        db.execute("CREATE TABLE indicators_daily (symbol TEXT, trade_date DATE)")
        db.execute("INSERT INTO indicators_daily VALUES ('AAA', DATE '2026-09-07')")
        db.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT current_timestamp
            )
            """
        )
        db.execute("INSERT INTO schema_migrations(version) VALUES (7)")

    run_migrations(path)

    assert CURRENT_SCHEMA_VERSION == 9
    assert schema_version(path) == 9
    with duckdb.connect(str(path), read_only=True) as db:
        names = {
            row[0]
            for row in db.execute(
                "SELECT index_name FROM duckdb_indexes() WHERE table_name = 'indicators_daily'"
            ).fetchall()
        }
        assert "idx_indicators_date_symbol" in names


def test_migration_9_repairs_on_conflict_keys_from_ctas_tables(tmp_path):
    """Preserved CTAS tables (no PK) must accept ON CONFLICT after run_migrations."""
    from Scripts.migrations import CURRENT_SCHEMA_VERSION, run_migrations, schema_version

    path = tmp_path / "ctas.duckdb"
    with duckdb.connect(str(path)) as db:
        db.execute("CREATE TABLE ingested_reports (trade_date DATE, report_type TEXT, source_checksum TEXT, row_count BIGINT, manifest_path TEXT, batch_id TEXT)")
        db.execute("INSERT INTO ingested_reports VALUES (DATE '2026-09-21', 'bhav', 'aaa', 1, 'm.json', 'session-2026-09-21')")
        db.execute("INSERT INTO ingested_reports VALUES (DATE '2026-09-21', 'bhav', 'bbb', 1, 'm.json', 'session-2026-09-21')")
        db.execute("CREATE TABLE ingestion_batches (batch_id TEXT, start_date DATE, end_date DATE, status TEXT, started_at TIMESTAMP, completed_at TIMESTAMP, application_version TEXT, error_summary TEXT)")
        db.execute("CREATE TABLE signal_ledger (signal_id TEXT, symbol TEXT, setup_type TEXT, score_version TEXT, first_seen_date DATE, last_seen_date DATE, trigger_date DATE, invalidation_date DATE, expiry_date DATE, status TEXT, initial_score DOUBLE, peak_score DOUBLE, trigger_price DOUBLE, invalidation_price DOUBLE, market_regime TEXT, sector_state TEXT, industry_state TEXT, feature_snapshot JSON, state_history JSON)")
        db.execute("INSERT INTO signal_ledger (signal_id, symbol, status) VALUES ('sig-1', 'AAA', 'open')")
        db.execute("CREATE TABLE signal_outcomes (signal_id TEXT, horizon_sessions INTEGER, as_of_date DATE, forward_return_pct DOUBLE, max_favourable_excursion_pct DOUBLE, max_adverse_excursion_pct DOUBLE, trigger_to_invalidation_return_pct DOUBLE, time_to_trigger_sessions INTEGER, time_to_failure_sessions INTEGER, resolved BOOLEAN)")
        db.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT current_timestamp
            )
            """
        )
        db.execute("INSERT INTO schema_migrations(version) VALUES (8)")

    run_migrations(path)

    assert CURRENT_SCHEMA_VERSION == 9
    assert schema_version(path) == 9
    with duckdb.connect(str(path)) as db:
        assert db.execute("SELECT count(*) FROM ingested_reports").fetchone()[0] == 1
        db.execute(
            """
            INSERT INTO ingested_reports(trade_date, report_type, source_checksum, row_count, manifest_path, batch_id)
            VALUES (DATE '2026-09-21', 'bhav', 'ccc', 2, 'm.json', 'session-2026-09-21')
            ON CONFLICT (trade_date, report_type) DO NOTHING
            """
        )
        assert db.execute("SELECT count(*) FROM ingested_reports").fetchone()[0] == 1
        db.execute(
            """
            INSERT INTO signal_ledger(signal_id, symbol, status)
            VALUES ('sig-1', 'AAA', 'updated')
            ON CONFLICT (signal_id) DO UPDATE SET status = excluded.status
            """
        )
        assert db.execute("SELECT status FROM signal_ledger WHERE signal_id = 'sig-1'").fetchone()[0] == "updated"
        names = {
            row[0]
            for row in db.execute(
                "SELECT index_name FROM duckdb_indexes() WHERE is_unique"
            ).fetchall()
        }
        assert "ux_ingested_reports_natural_key" in names
        assert "ux_ingestion_batches_batch_id" in names
        assert "ux_signal_ledger_signal_id" in names
        assert "ux_signal_outcomes_natural_key" in names


def test_stocks_master_security_name_repaired_from_pandas_suffixes(tmp_path):
    from Scripts.migrations import run_migrations

    path = tmp_path / "master.duckdb"
    with duckdb.connect(str(path)) as db:
        db.execute("CREATE TABLE stocks_master (symbol VARCHAR, security_name_x VARCHAR, security_name_y VARCHAR)")
        db.execute("INSERT INTO stocks_master VALUES ('AAA', 'Alpha Ltd', NULL)")
        db.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT current_timestamp
            )
            """
        )
        db.execute("INSERT INTO schema_migrations(version) VALUES (8)")

    run_migrations(path)
    with duckdb.connect(str(path), read_only=True) as db:
        cols = {row[1] for row in db.execute("PRAGMA table_info(stocks_master)").fetchall()}
        assert "security_name" in cols
        assert db.execute("SELECT security_name FROM stocks_master WHERE symbol = 'AAA'").fetchone()[0] == "Alpha Ltd"
