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
    """Ingest one accepted session and materialize its versioned decision rows.

    PR ZIP is best-effort: missing/corrupt ZIP must not block focused-v2 materialization.
    """

    db_path = Path(db_path)
    policy = policy or DecisionPolicy()
    run_migrations(db_path)
    pr_counts: dict = {}
    zip_path_str = ""
    try:
        zip_path = _pr_zip(Path(session_dir))
        zip_path_str = str(zip_path)
        bundle = parse_pr_zip(zip_path, trade_date)
        pr_counts = upsert_pr_bundle(db_path, bundle, zip_checksum(zip_path))
    except (FileNotFoundError, OSError, ValueError) as exc:
        pr_counts = {"pr_error": str(exc)}
        print(f"PR ingestion skipped/failed ({exc}); continuing with decision materialization.")
    candidates = materialize_decision_date(db_path, trade_date, policy=policy)
    return {
        "trade_date": trade_date.isoformat(),
        "pr_zip": zip_path_str,
        "pr_counts": pr_counts,
        "decision_rows": int(len(candidates)),
        "score_version": policy.score_version,
    }


__all__ = ["process_accepted_session"]
