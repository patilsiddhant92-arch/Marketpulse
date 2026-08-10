"""Read-only shadow comparison for focused-v1 versus focused-v2 decisions."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


@dataclass(frozen=True)
class ScoreComparisonReport:
    trade_date: date | None
    versions: tuple[str, str]
    row_counts: dict[str, int]
    overlap_count: int
    only_v1: tuple[str, ...]
    only_v2: tuple[str, ...]
    rejection_reasons: dict[str, int]
    rank_changes: pd.DataFrame = field(default_factory=pd.DataFrame)
    score_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    outcome_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    sessions_evaluated: int = 0


def _empty_report(versions: tuple[str, str], trade_date: date | None = None) -> ScoreComparisonReport:
    return ScoreComparisonReport(trade_date, versions, {versions[0]: 0, versions[1]: 0}, 0, (), (), {}, sessions_evaluated=0)


def _choose_date(db: duckdb.DuckDBPyConnection, versions: tuple[str, str], requested: date | None) -> date | None:
    if requested is not None:
        return requested
    row = db.execute(
        """
        SELECT max(trade_date) FROM candidate_daily
        WHERE score_version IN (?, ?)
          AND trade_date IN (
              SELECT trade_date FROM candidate_daily WHERE score_version = ?
              INTERSECT SELECT trade_date FROM candidate_daily WHERE score_version = ?
          )
        """,
        [versions[0], versions[1], versions[0], versions[1]],
    ).fetchone()
    return pd.Timestamp(row[0]).date() if row and row[0] is not None else None


def _outcome_summary(db: duckdb.DuckDBPyConnection, versions: tuple[str, str]) -> pd.DataFrame:
    tables = {str(row[0]) for row in db.execute("SHOW TABLES").fetchall()}
    if not {"signal_ledger", "signal_outcomes"}.issubset(tables):
        return pd.DataFrame()
    return db.execute(
        """
        SELECT l.score_version, o.horizon_sessions,
               count(*) FILTER (WHERE o.resolved) AS resolved_count,
               avg(o.forward_return_pct) FILTER (WHERE o.resolved) AS avg_forward_return_pct,
               median(o.forward_return_pct) FILTER (WHERE o.resolved) AS median_forward_return_pct,
               avg(o.max_favourable_excursion_pct) FILTER (WHERE o.resolved) AS avg_mfe_pct,
               avg(o.max_adverse_excursion_pct) FILTER (WHERE o.resolved) AS avg_mae_pct,
               avg(CASE WHEN o.resolved AND o.forward_return_pct > 0 THEN 1 ELSE 0 END) AS hit_rate
        FROM signal_ledger l
        JOIN signal_outcomes o USING(signal_id)
        WHERE l.score_version IN (?, ?)
          AND o.horizon_sessions IN (5, 10, 20, 60)
        GROUP BY l.score_version, o.horizon_sessions
        ORDER BY l.score_version, o.horizon_sessions
        """,
        [versions[0], versions[1]],
    ).fetchdf()


def compare_score_versions(db_path: Path, trade_date: date | None = None, versions: tuple[str, str] = ("focused-v1", "focused-v2")) -> ScoreComparisonReport:
    db_path = Path(db_path)
    try:
        with duckdb.connect(str(db_path), read_only=True) as db:
            tables = {str(row[0]) for row in db.execute("SHOW TABLES").fetchall()}
            if "candidate_daily" not in tables:
                return _empty_report(versions, trade_date)
            selected_date = _choose_date(db, versions, trade_date)
            if selected_date is None:
                return _empty_report(versions, None)
            frame = db.execute(
                "SELECT * FROM candidate_daily WHERE trade_date = ? AND score_version IN (?, ?)",
                [selected_date, versions[0], versions[1]],
            ).fetchdf()
            outcomes = _outcome_summary(db, versions)
    except (duckdb.Error, OSError):
        return _empty_report(versions, trade_date)

    row_counts = {version: int((frame.get("score_version") == version).sum()) for version in versions}
    by_version = {version: frame[frame["score_version"] == version].copy() for version in versions}
    symbols = {version: set(by_version[version].get("symbol", pd.Series(dtype=str)).astype(str)) for version in versions}
    overlap = symbols[versions[0]] & symbols[versions[1]]
    only_v1 = tuple(sorted(symbols[versions[0]] - symbols[versions[1]]))
    only_v2 = tuple(sorted(symbols[versions[1]] - symbols[versions[0]]))
    reasons: dict[str, int] = {}
    for value in by_version[versions[1]].get("blocking_reasons", pd.Series(dtype=str)).fillna(""):
        for reason in str(value).split(";"):
            if reason:
                reasons[reason] = reasons.get(reason, 0) + 1
    left = by_version[versions[0]].set_index("symbol") if not by_version[versions[0]].empty else pd.DataFrame()
    right = by_version[versions[1]].set_index("symbol") if not by_version[versions[1]].empty else pd.DataFrame()
    rank_changes = pd.DataFrame()
    if overlap:
        rank_changes = pd.DataFrame({"symbol": sorted(overlap)})
        rank_changes = rank_changes.merge(left[[column for column in ("rank_overall", "total_score") if column in left.columns]].reset_index(), on="symbol", how="left", suffixes=("", "_v1"))
        rank_changes = rank_changes.merge(right[[column for column in ("rank_overall", "total_score") if column in right.columns]].reset_index(), on="symbol", how="left", suffixes=("_v1", "_v2"))
        rank_v1 = "rank_overall_v1" if "rank_overall_v1" in rank_changes.columns else "rank_overall"
        rank_v2 = "rank_overall_v2" if "rank_overall_v2" in rank_changes.columns else "rank_overall"
        if rank_v1 in rank_changes.columns and rank_v2 in rank_changes.columns:
            rank_changes["rank_delta"] = pd.to_numeric(rank_changes[rank_v2], errors="coerce") - pd.to_numeric(rank_changes[rank_v1], errors="coerce")
    summaries = []
    for version in versions:
        scores = pd.to_numeric(by_version[version].get("total_score"), errors="coerce")
        summaries.append({"score_version": version, "rows": row_counts[version], "mean_score": scores.mean(), "median_score": scores.median(), "min_score": scores.min(), "max_score": scores.max()})
    score_summary = pd.DataFrame(summaries)
    sessions = int(frame["trade_date"].nunique()) if not frame.empty and "trade_date" in frame.columns else 0
    return ScoreComparisonReport(selected_date, versions, row_counts, len(overlap), only_v1, only_v2, reasons, rank_changes, score_summary, outcomes, sessions)


def _jsonable(report: ScoreComparisonReport) -> dict[str, Any]:
    payload = asdict(report)
    payload["trade_date"] = report.trade_date.isoformat() if report.trade_date else None
    payload["rank_changes"] = report.rank_changes.to_dict(orient="records")
    payload["score_summary"] = report.score_summary.to_dict(orient="records")
    payload["outcome_summary"] = report.outcome_summary.to_dict(orient="records")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare MarketPulse score versions without changing the database.")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--date", type=date.fromisoformat)
    args = parser.parse_args()
    print(json.dumps(_jsonable(compare_score_versions(args.db, args.date)), default=str, indent=2))


__all__ = ["ScoreComparisonReport", "compare_score_versions"]
