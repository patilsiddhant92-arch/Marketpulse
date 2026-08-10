"""Accepted-session boundary: PR ingestion followed by focused-v2 materialization."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from decision_policy import DecisionPolicy
from materialize_decision_tables import materialize_decision_date
from migrations import run_migrations
from pr_report_ingestion import parse_pr_zip, upsert_pr_bundle, zip_checksum


def _pr_zip(session_dir: Path) -> Path:
    candidates = sorted(Path(session_dir).glob("PR*.zip"))
    if not candidates:
        raise FileNotFoundError(f"no PR ZIP found in {session_dir}")
    return candidates[0]


def process_accepted_session(db_path: Path, session_dir: Path, trade_date: date, policy: DecisionPolicy | None = None) -> dict:
    """Ingest one accepted session and materialize its versioned decision rows."""

    db_path = Path(db_path)
    policy = policy or DecisionPolicy()
    run_migrations(db_path)
    zip_path = _pr_zip(Path(session_dir))
    bundle = parse_pr_zip(zip_path, trade_date)
    pr_counts = upsert_pr_bundle(db_path, bundle, zip_checksum(zip_path))
    candidates = materialize_decision_date(db_path, trade_date, policy=policy)
    return {
        "trade_date": trade_date.isoformat(),
        "pr_zip": str(zip_path),
        "pr_counts": pr_counts,
        "decision_rows": int(len(candidates)),
        "score_version": policy.score_version,
    }


__all__ = ["process_accepted_session"]
