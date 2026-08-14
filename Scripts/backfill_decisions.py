"""Oldest→newest decision backfill from indicators_daily (PR-LEDGER).

Does not expect multi-day candidate_daily partitions — re-scores each as_of
from indicator/history tables so first_seen identity can accumulate.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from config import DB_PATH
from decision_policy import DecisionPolicy
from materialize_decision_tables import materialize_decision_date


def list_indicator_sessions(db_path: Path) -> list[date]:
    with duckdb.connect(str(db_path), read_only=True) as db:
        rows = db.execute(
            "SELECT DISTINCT trade_date FROM indicators_daily ORDER BY trade_date"
        ).fetchall()
    return [pd.Timestamp(r[0]).date() for r in rows if r[0] is not None]


def backfill_decisions(
    db_path: Path,
    *,
    sessions: int = 20,
    score_version: str = "focused-v2",
    end_date: date | None = None,
) -> dict:
    db_path = Path(db_path)
    all_dates = list_indicator_sessions(db_path)
    if not all_dates:
        return {"ok": False, "error": "no indicator sessions", "written": 0, "dates": []}
    if end_date is not None:
        end_date = pd.Timestamp(end_date).date()
        all_dates = [d for d in all_dates if d <= end_date]
    window = all_dates[-sessions:] if sessions > 0 else all_dates
    policy = DecisionPolicy(score_version=score_version)
    written = []
    for as_of in window:  # oldest → newest
        print(f"Materializing {score_version} for {as_of} ...")
        candidates = materialize_decision_date(db_path, as_of, policy=policy)
        written.append({"trade_date": as_of.isoformat(), "rows": int(len(candidates))})
    return {
        "ok": True,
        "written": len(written),
        "dates": [item["trade_date"] for item in written],
        "sessions": written,
        "order": "oldest_to_newest",
        "source_of_truth": "indicators_daily",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill focused decision partitions oldest→newest.")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--sessions", type=int, default=20, help="Number of latest indicator sessions to rematerialize.")
    parser.add_argument("--score-version", default="focused-v2")
    parser.add_argument("--end-date", default=None, help="Optional ISO end date YYYY-MM-DD.")
    args = parser.parse_args()
    end = date.fromisoformat(args.end_date) if args.end_date else None
    result = backfill_decisions(args.db, sessions=args.sessions, score_version=args.score_version, end_date=end)
    print(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
