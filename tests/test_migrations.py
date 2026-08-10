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
    from Scripts.migrations import run_migrations

    path = tmp_path / "marketpulse.duckdb"
    with duckdb.connect(str(path)) as db:
        db.execute("CREATE TABLE trade_journal (id BIGINT, notes TEXT)")
        db.execute("INSERT INTO trade_journal VALUES (1, 'keep me')")

    run_migrations(path)
    run_migrations(path)

    with duckdb.connect(str(path), read_only=True) as db:
        assert db.execute("SELECT * FROM trade_journal").fetchall() == [(1, "keep me")]
        assert db.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 2
