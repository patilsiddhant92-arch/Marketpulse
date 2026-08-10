from __future__ import annotations

from datetime import date

import duckdb


def _seed_decision_db(path):
    from Scripts.migrations import run_migrations

    run_migrations(path)
    with duckdb.connect(str(path)) as db:
        db.execute(
            """
            CREATE TABLE indicators_daily (
                symbol TEXT,
                trade_date DATE,
                close_price DOUBLE,
                high_20d DOUBLE,
                low_10d DOUBLE,
                ema_20 DOUBLE,
                high_50d DOUBLE,
                avg_traded_value_cr_20d DOUBLE,
                rs_percentile DOUBLE,
                rs_1y_percentile DOUBLE,
                rs_3m_percentile DOUBLE,
                trend_score DOUBLE,
                contraction_score DOUBLE,
                volume_dryup_score DOUBLE,
                pivot_proximity_score DOUBLE,
                close_location_pct DOUBLE,
                delivery_pct DOUBLE,
                avg_delivery_pct_20d DOUBLE,
                rvol DOUBLE,
                ema_stack_bullish BOOLEAN,
                near_52w_high BOOLEAN,
                sector TEXT,
                industry TEXT
            )
            """
        )
        db.executemany(
            "INSERT INTO indicators_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("BIG", date(2026, 8, 7), 100, 103, 94, 96, 120, 25, 90, 85, 88, 80, 70, 60, 75, 80, 55, 45, 1.4, True, True, "Technology", "Software"),
                ("SMALL", date(2026, 8, 7), 100, 103, 94, 96, 120, 25, 90, 85, 88, 80, 70, 60, 75, 80, 55, 45, 1.4, True, True, "Technology", "Software"),
            ],
        )
        db.execute("CREATE TABLE breadth_daily (trade_date DATE, breadth_state TEXT, advance_pct DOUBLE, above_50ema_pct DOUBLE, above_200ema_pct DOUBLE)")
        db.execute("INSERT INTO breadth_daily VALUES ('2026-08-07', 'Broad', 65, 70, 60)")
        db.execute("CREATE TABLE stocks_master (symbol TEXT, sector TEXT, industry TEXT, market_cap_cr DOUBLE, band DOUBLE)")
        db.executemany("INSERT INTO stocks_master VALUES (?, ?, ?, ?, ?)", [("BIG", "Technology", "Software", 2500, 10), ("SMALL", "Technology", "Software", 900, 10)])
        db.execute("CREATE TABLE deals (symbol TEXT, trade_date DATE, deal_value_cr DOUBLE, side TEXT)")
        db.execute("CREATE TABLE sector_rotation (trade_date DATE, group_name TEXT, level TEXT, rotation_state TEXT, rotation_score DOUBLE)")


def test_materialize_decision_date_persists_focused_v2_and_reasons(tmp_path):
    from Scripts.materialize_decision_tables import materialize_decision_date

    path = tmp_path / "marketpulse.duckdb"
    _seed_decision_db(path)

    rows = materialize_decision_date(path, date(2026, 8, 7))

    assert set(rows["score_version"]) == {"focused-v2"}
    small = rows.loc[rows["symbol"] == "SMALL"].iloc[0]
    assert small["eligibility_status"] == "blocked"
    assert "market_cap_below_minimum" in small["blocking_reasons"]
    with duckdb.connect(str(path), read_only=True) as db:
        assert db.execute("SELECT count(*) FROM candidate_daily WHERE score_version = 'focused-v2'").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM candidate_daily WHERE score_version = 'focused-v2' AND eligibility_status = 'eligible' AND market_cap_cr >= 1000").fetchone()[0] == 1
