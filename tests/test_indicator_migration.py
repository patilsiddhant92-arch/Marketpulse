from __future__ import annotations

import duckdb

from Scripts.migrations import CURRENT_SCHEMA_VERSION, run_migrations, schema_version


def test_schema_v7_preserves_versioned_indicator_clientele_and_sector_contracts(tmp_path) -> None:
    db_path = tmp_path / "marketpulse.duckdb"
    with duckdb.connect(str(db_path)) as db:
        db.execute("CREATE TABLE indicators_daily (symbol TEXT, trade_date DATE, atr_14 DOUBLE)")
        db.execute("CREATE TABLE deals (symbol TEXT, client_name TEXT)")

    run_migrations(db_path)

    with duckdb.connect(str(db_path), read_only=True) as db:
        indicator_columns = {row[1] for row in db.execute("PRAGMA table_info(indicators_daily)").fetchall()}
        deal_columns = {row[1] for row in db.execute("PRAGMA table_info(deals)").fetchall()}

    assert CURRENT_SCHEMA_VERSION == 7
    assert schema_version(db_path) == 7
    assert {"atr_14", "atr_14_wilder", "atr_pct_wilder", "atr_pct_primary", "distance_below_52w", "distance_to_high_pct_corrected", "rs_percentile_primary", "base_quality_score", "setup_class"} <= indicator_columns
    assert {"clientele", "clientele_sub", "is_prop", "needs_review"} <= deal_columns
    with duckdb.connect(str(db_path), read_only=True) as db:
        assert db.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'sector_metrics_daily'").fetchone()[0] == 1
