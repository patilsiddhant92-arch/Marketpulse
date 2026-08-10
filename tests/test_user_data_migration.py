from __future__ import annotations

import duckdb


def test_migrate_user_data_copies_legacy_manual_tables_idempotently(tmp_path):
    from Scripts.user_data import migrate_user_data

    market = tmp_path / "marketpulse.duckdb"
    user = tmp_path / "marketpulse_user.duckdb"
    backup_dir = tmp_path / "backups"
    with duckdb.connect(str(market)) as db:
        db.execute("CREATE TABLE portfolio_positions (symbol TEXT, status TEXT, qty DOUBLE, avg_buy_price DOUBLE, buy_date DATE, sell_date DATE, sell_price DOUBLE, notes TEXT, tags TEXT)")
        db.execute("INSERT INTO portfolio_positions VALUES ('ACME', 'OPEN', 10, 100, '2026-08-01', NULL, NULL, 'thesis', 'swing')")
        db.execute("CREATE TABLE portfolio_events (id BIGINT, symbol TEXT, event_type TEXT, event_date DATE, qty DOUBLE, price DOUBLE, notes TEXT, created_at TIMESTAMP)")
        db.execute("INSERT INTO portfolio_events VALUES (1, 'ACME', 'CREATE', '2026-08-01', 10, 100, 'created', current_timestamp)")
        db.execute("CREATE TABLE trade_journal (id BIGINT, notes TEXT)")
        db.execute("INSERT INTO trade_journal VALUES (1, 'keep')")

    first = migrate_user_data(market, user, backup_dir)
    second = migrate_user_data(market, user, backup_dir)

    assert set(first.copied_tables) == {"portfolio_positions", "portfolio_events", "trade_journal"}
    assert first.rows_copied == 3
    assert second.rows_copied == 0
    with duckdb.connect(str(user), read_only=True) as db:
        assert db.execute("SELECT symbol, qty FROM portfolio_positions").fetchall() == [("ACME", 10.0)]
        assert db.execute("SELECT count(*) FROM portfolio_events").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM trade_journal").fetchone()[0] == 1
