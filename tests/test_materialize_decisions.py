import duckdb


def test_materialize_decision_tables_creates_candidate_snapshot(tmp_path):
    from Scripts.materialize_decision_tables import materialize_decision_tables
    from Scripts.migrations import run_migrations

    path = tmp_path / "marketpulse.duckdb"
    run_migrations(path)
    with duckdb.connect(str(path)) as db:
        db.execute("CREATE TABLE indicators_daily (symbol TEXT, trade_date DATE, close_price DOUBLE, high_20d DOUBLE, low_10d DOUBLE, ema_20 DOUBLE)")
        db.execute("INSERT INTO indicators_daily VALUES ('AAA', '2026-08-03', 100, 103, 94, 96)")
        db.execute("CREATE TABLE breadth_daily (trade_date DATE, breadth_state TEXT, advance_pct DOUBLE, above_50ema_pct DOUBLE, above_200ema_pct DOUBLE)")
        db.execute("INSERT INTO breadth_daily VALUES ('2026-08-03', 'Broad', 65, 70, 60)")
        db.execute("CREATE TABLE stocks_master (symbol TEXT, sector TEXT, industry TEXT, market_cap_cr DOUBLE)")
        db.execute("INSERT INTO stocks_master VALUES ('AAA', 'Technology', 'Software', 5000)")
        db.execute("CREATE TABLE deals (symbol TEXT, trade_date DATE, deal_value_cr DOUBLE)")
        db.execute("CREATE TABLE sector_rotation (trade_date DATE, group_name TEXT, level TEXT, rotation_state TEXT, rotation_score DOUBLE)")

    materialize_decision_tables(path)

    with duckdb.connect(str(path), read_only=True) as db:
        assert db.execute("SELECT count(*) FROM candidate_daily").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM watchlist_candidates").fetchone()[0] == 1
