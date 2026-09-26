import duckdb
import pandas as pd


def test_materialize_decision_tables_inserts_merged_14_column_index_frame(tmp_path, monkeypatch):
    """load_all_index_history returns INDEX_COLUMNS (9) + EXTRA_INDEX_COLUMNS (5) = 14 columns,
    but index_daily's schema only has the 9 INDEX_COLUMNS. The insert must select just the
    table's columns (or use INSERT ... BY NAME) so the extra columns don't break it."""
    import Scripts.materialize_decision_tables as mdt
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

    merged = pd.DataFrame({
        "trade_date": pd.to_datetime(["2026-08-01"]),
        "index_name": ["Nifty 50"],
        "previous_close": [24950.0],
        "open_price": [24960.0],
        "high_price": [25050.0],
        "low_price": [24900.0],
        "close_price": [25000.0],
        "change_value": [50.0],
        "return_1d_pct": [0.2],
        "volume": [300000000.0],
        "turnover_cr": [25000.5],
        "pe": [22.1],
        "pb": [3.5],
        "div_yield": [1.2],
    })
    assert len(merged.columns) == 14
    monkeypatch.setattr(mdt, "load_all_index_history", lambda root: merged)

    mdt.materialize_decision_tables(path)

    with duckdb.connect(str(path), read_only=True) as db:
        rows = db.execute("SELECT * FROM index_daily").fetchdf()
        assert len(rows) == 1
        assert set(rows.columns) == set(mdt.INDEX_COLUMNS)
        assert rows.iloc[0]["close_price"] == 25000.0


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


def test_write_outcomes_rescales_ledger_prices_after_a_later_split(tmp_path):
    """signal_ledger prices are on the last_seen_date scale; a 1:2 split afterwards halves the
    adjusted history. _write_outcomes must select price_factor so calculate_outcome rescales the
    invalidation price instead of firing a false time_to_failure."""
    import Scripts.materialize_decision_tables as mdt
    from Scripts.migrations import run_migrations

    path = tmp_path / "marketpulse.duckdb"
    run_migrations(path)
    days = pd.bdate_range("2026-08-03", periods=8)
    raw_close = [100, 101, 102, 103, 52, 52.5, 53, 53.5]  # split ex on day 5
    factor = [0.5] * 4 + [1.0] * 4
    prices = pd.DataFrame({
        "symbol": "AAA", "trade_date": days.date,
        "open_price": raw_close, "high_price": [c + 1 for c in raw_close],
        "low_price": [c - 1 for c in raw_close], "close_price": raw_close, "volume": 1000.0,
        "price_factor": factor,
    })
    for col in ("open_price", "high_price", "low_price", "close_price"):
        prices[f"adj_{col}"] = prices[col] * prices["price_factor"]
    with duckdb.connect(str(path)) as db:
        db.register("p", prices)
        db.execute("CREATE TABLE prices_daily AS SELECT * FROM p")
    ledger = pd.DataFrame([{
        "signal_id": "sig1", "symbol": "AAA", "first_seen_date": days[0].date(),
        "last_seen_date": days[1].date(), "trigger_price": 102.0, "invalidation_price": 95.0,
    }])

    mdt._write_outcomes(path, None, ledger)

    with duckdb.connect(str(path), read_only=True) as db:
        rows = db.execute(
            "SELECT horizon_sessions, resolved, time_to_failure_sessions FROM signal_outcomes "
            "WHERE signal_id = 'sig1' AND horizon_sessions = 5").fetchall()
    assert rows == [(5, True, None)]
