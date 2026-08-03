import duckdb


def test_append_batch_rolls_back_all_writes_on_failure(tmp_path):
    from Scripts.ingestion_manifest import SessionPlan
    from Scripts.migrations import run_migrations
    from Scripts.transactional_append import append_batch

    path = tmp_path / "marketpulse.duckdb"
    run_migrations(path)
    plan = SessionPlan(trading_dates=["2026-08-03"], rows_by_table={"security_events": [{"symbol": "AAA", "event_date": "2026-08-03", "event_type": "results", "headline": "Q1", "source_id": "x", "source_checksum": "h"}]}, inject_failure=True)

    try:
        append_batch(path, plan)
    except RuntimeError:
        pass
    else:
        raise AssertionError("injected append failure did not raise")

    with duckdb.connect(str(path), read_only=True) as db:
        assert db.execute("SELECT count(*) FROM security_events").fetchone()[0] == 0
