"""Read-only signal evidence summaries for the operator-facing health desk."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import duckdb
import pandas as pd


EVIDENCE_COLUMNS = [
    "score_version",
    "market_regime",
    "sector_state",
    "setup_type",
    "horizon_sessions",
    "resolved_count",
    "hit_rate_pct",
    "avg_forward_return_pct",
    "median_forward_return_pct",
    "avg_mfe_pct",
    "avg_mae_pct",
]


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=EVIDENCE_COLUMNS)


def summarize_signal_outcomes(
    db_path: Path,
    *,
    score_version: str | None = None,
    horizons: Iterable[int] = (5, 10, 20, 60),
) -> pd.DataFrame:
    """Summarise resolved walk-forward outcomes without inventing evidence.

    The function deliberately returns an empty frame when the evidence tables
    are not materialised yet.  This keeps the UI truthful during a fresh
    install or before the first outcome backfill.
    """

    db_path = Path(db_path)
    if not db_path.exists():
        return _empty_frame()

    horizon_values = [int(value) for value in horizons]
    if not horizon_values:
        return _empty_frame()

    try:
        with duckdb.connect(str(db_path), read_only=True) as db:
            tables = {
                str(row[0])
                for row in db.execute("SHOW TABLES").fetchall()
            }
            if not {"signal_ledger", "signal_outcomes"}.issubset(tables):
                return _empty_frame()

            placeholders = ", ".join("?" for _ in horizon_values)
            params: list[object] = list(horizon_values)
            version_clause = ""
            if score_version:
                version_clause = " AND l.score_version = ?"
                params.append(score_version)

            frame = db.execute(
                f"""
                SELECT
                    l.score_version,
                    COALESCE(NULLIF(l.market_regime, ''), 'Unknown') AS market_regime,
                    COALESCE(NULLIF(l.sector_state, ''), 'Unknown') AS sector_state,
                    COALESCE(NULLIF(l.setup_type, ''), 'Unknown') AS setup_type,
                    o.horizon_sessions,
                    COUNT(*) FILTER (WHERE o.resolved) AS resolved_count,
                    AVG(CASE WHEN o.resolved THEN CASE WHEN o.forward_return_pct > 0 THEN 1.0 ELSE 0.0 END ELSE NULL END) * 100.0 AS hit_rate_pct,
                    AVG(o.forward_return_pct) FILTER (WHERE o.resolved) AS avg_forward_return_pct,
                    MEDIAN(o.forward_return_pct) FILTER (WHERE o.resolved) AS median_forward_return_pct,
                    AVG(o.max_favourable_excursion_pct) FILTER (WHERE o.resolved) AS avg_mfe_pct,
                    AVG(o.max_adverse_excursion_pct) FILTER (WHERE o.resolved) AS avg_mae_pct
                FROM signal_ledger l
                JOIN signal_outcomes o ON o.signal_id = l.signal_id
                WHERE o.horizon_sessions IN ({placeholders}){version_clause}
                GROUP BY l.score_version, l.market_regime, l.sector_state, l.setup_type, o.horizon_sessions
                HAVING COUNT(*) FILTER (WHERE o.resolved) > 0
                ORDER BY l.score_version, market_regime, sector_state, setup_type, o.horizon_sessions
                """,
                params,
            ).fetchdf()
    except (duckdb.Error, OSError):
        return _empty_frame()

    if frame.empty:
        return _empty_frame()
    for column in EVIDENCE_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    return frame[EVIDENCE_COLUMNS]


__all__ = ["summarize_signal_outcomes"]
