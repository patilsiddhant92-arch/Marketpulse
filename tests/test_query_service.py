from datetime import date

import pandas as pd


def test_load_today_snapshot_is_limited_and_sorted(tmp_path):
    from Scripts.migrations import run_migrations
    from Scripts.query_service import load_today_snapshot

    path = tmp_path / "marketpulse.duckdb"
    run_migrations(path)
    frame = pd.DataFrame(
        [{"trade_date": date(2026, 8, 3), "symbol": f"S{i:02}", "score_version": "focused-v1", "candidate_state": "Prepare", "total_score": 100 - i, "sector": "Tech"} for i in range(20)]
    )
    with __import__("duckdb").connect(str(path)) as db:
        db.register("rows_df", frame)
        db.execute("INSERT INTO candidate_daily (trade_date, symbol, score_version, candidate_state, total_score, sector) SELECT * FROM rows_df")

    result = load_today_snapshot(path, limit=15)
    assert len(result) == 15
    assert result.iloc[0]["symbol"] == "S00"
