"""Rebuild index_daily from all staged MA files under Input/."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "Scripts"
for p in (ROOT, SCRIPTS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from config import DB_PATH  # noqa: E402
from index_history import build_index_features, load_all_market_activity_history  # noqa: E402
from true_rs import BENCH_MIDSML400, BENCH_NIFTY50, bench_session_counts  # noqa: E402


def rebuild(db_path: Path = DB_PATH) -> dict[str, int]:
    raw = load_all_market_activity_history(ROOT)
    if raw.empty:
        raise SystemExit("No MA files found under Input/downloads|archive|daily")
    features = build_index_features(raw)
    with duckdb.connect(str(db_path)) as con:
        con.register("index_features_df", features)
        con.execute("DROP TABLE IF EXISTS index_daily")
        con.execute("CREATE TABLE index_daily AS SELECT * FROM index_features_df")
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_index_daily_date_name ON index_daily(trade_date, index_name)"
        )
    counts = bench_session_counts(features)
    print(f"index_daily rows={len(features):,} benches={counts}")
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()
    rebuild(args.db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
