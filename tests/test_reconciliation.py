import duckdb


def test_reconcile_databases_accepts_equal_values(tmp_path):
    from Scripts.reconcile_database import reconcile_databases

    left = tmp_path / "left.duckdb"
    right = tmp_path / "right.duckdb"
    for path in (left, right):
        with duckdb.connect(str(path)) as db:
            db.execute("CREATE TABLE prices_daily (symbol TEXT, trade_date DATE, close_price DOUBLE)")
            db.execute("INSERT INTO prices_daily VALUES ('AAA', '2026-08-03', 100)")

    assert reconcile_databases(left, right, ["prices_daily"]) == []
