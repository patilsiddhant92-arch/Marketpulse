import duckdb
import subprocess
import sys
from pathlib import Path


def test_app_snapshot_loads_today_data_only(tmp_path):
    from Scripts.migrations import run_migrations
    from App.query_service import load_app_snapshot

    path = tmp_path / "marketpulse.duckdb"
    run_migrations(path)
    with duckdb.connect(str(path)) as db:
        db.execute("INSERT INTO candidate_daily (trade_date, symbol, score_version, candidate_state, total_score) VALUES ('2026-08-03', 'AAA', 'focused-v1', 'Prepare', 80)")
        db.execute("CREATE TABLE IF NOT EXISTS breadth_daily (trade_date DATE, breadth_state TEXT, advance_pct DOUBLE, above_50ema_pct DOUBLE, above_200ema_pct DOUBLE)")
        db.execute("INSERT INTO breadth_daily VALUES ('2026-08-03', 'Broad', 60, 65, 55)")

    snapshot = load_app_snapshot(path)
    assert set(snapshot) == {"candidates", "breadth", "changes"}
    assert snapshot["candidates"].iloc[0]["symbol"] == "AAA"


def test_app_entrypoint_imports_when_launched_from_app_directory():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", "import app"],
        cwd=root / "App",
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
