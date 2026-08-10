"""Build decision-system tables from the existing canonical MarketPulse tables."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from candidate_engine import score_candidates
from decision_policy import DecisionPolicy
from index_history import build_index_features, parse_market_activity_history
from migrations import run_migrations
from outcomes import calculate_outcome
from reference_history import load_reference_history
from signal_service import update_signal_ledger
from watchlist_service import persist_candidate_snapshot


def _load(db_path: Path, table: str) -> pd.DataFrame:
    with duckdb.connect(str(db_path), read_only=True) as db:
        exists = db.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [table]).fetchone()[0]
        return db.execute(f'SELECT * FROM "{table}"').fetchdf() if exists else pd.DataFrame()


def _write_candidates(db_path: Path, candidates: pd.DataFrame, trade_date: date) -> None:
    if candidates.empty:
        return
    with duckdb.connect(str(db_path)) as db:
        db.execute("DELETE FROM candidate_daily WHERE trade_date = ? AND score_version = ?", [trade_date, str(candidates.iloc[0]["score_version"])])
        schema = {row[1] for row in db.execute("PRAGMA table_info(candidate_daily)").fetchall()}
        columns = [col for col in candidates.columns if col in schema]
        frame = candidates[columns].copy()
        db.register("candidate_rows", frame)
        quoted = ",".join(f'"{col}"' for col in columns)
        db.execute(f"INSERT INTO candidate_daily ({quoted}) SELECT {quoted} FROM candidate_rows")


def _write_ledger(db_path: Path, ledger: pd.DataFrame) -> None:
    if ledger.empty:
        return
    columns = ["signal_id", "symbol", "setup_type", "score_version", "first_seen_date", "last_seen_date", "trigger_date", "invalidation_date", "expiry_date", "status", "initial_score", "peak_score", "trigger_price", "invalidation_price", "market_regime", "sector_state", "industry_state", "feature_snapshot", "state_history"]
    with duckdb.connect(str(db_path)) as db:
        for _, row in ledger.iterrows():
            db.execute(
                f"INSERT INTO signal_ledger ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) ON CONFLICT(signal_id) DO UPDATE SET last_seen_date=excluded.last_seen_date, trigger_date=excluded.trigger_date, invalidation_date=excluded.invalidation_date, status=excluded.status, peak_score=excluded.peak_score, trigger_price=excluded.trigger_price, invalidation_price=excluded.invalidation_price, feature_snapshot=excluded.feature_snapshot, state_history=excluded.state_history",
                [row.get(col) for col in columns],
            )


def _write_outcomes(db_path: Path, prices: pd.DataFrame, ledger: pd.DataFrame) -> None:
    if prices.empty or ledger.empty:
        return
    with duckdb.connect(str(db_path)) as db:
        for _, signal in ledger.iterrows():
            for outcome in calculate_outcome(prices, signal.to_dict()):
                columns = list(outcome)
                values = [outcome[col] for col in columns]
                db.execute(f"INSERT INTO signal_outcomes ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) ON CONFLICT(signal_id, horizon_sessions, as_of_date) DO UPDATE SET forward_return_pct=excluded.forward_return_pct, max_favourable_excursion_pct=excluded.max_favourable_excursion_pct, max_adverse_excursion_pct=excluded.max_adverse_excursion_pct, resolved=excluded.resolved", values)


def materialize_decision_tables(db_path: Path, as_of: date | None = None, policy: DecisionPolicy | None = None) -> pd.DataFrame:
    db_path = Path(db_path)
    policy = policy or DecisionPolicy()
    run_migrations(db_path)
    reference_history = _load(db_path, "security_reference_daily")
    if reference_history.empty:
        reference_history = load_reference_history(db_path.parent.parent)
        if not reference_history.empty:
            with duckdb.connect(str(db_path)) as db:
                db.register("reference_rows", reference_history)
                db.execute("INSERT INTO security_reference_daily SELECT * FROM reference_rows ON CONFLICT DO NOTHING")
    indicators = _load(db_path, "indicators_daily")
    if indicators.empty:
        return pd.DataFrame()
    as_of = pd.Timestamp(as_of or indicators["trade_date"].max()).date()
    breadth = _load(db_path, "breadth_daily")
    rotations = _load(db_path, "sector_rotation")
    deals = _load(db_path, "deals")
    master = _load(db_path, "stocks_master")
    index_daily = _load(db_path, "index_daily")
    if index_daily.empty:
        root = db_path.parent.parent
        index_daily = parse_market_activity_history(sorted((root / "Input" / "downloads").glob("*/MA*.csv")))
        if not index_daily.empty:
            with duckdb.connect(str(db_path)) as db:
                db.register("index_rows", index_daily)
                db.execute("INSERT INTO index_daily SELECT * FROM index_rows ON CONFLICT DO NOTHING")
    index_features = build_index_features(index_daily)
    events = _load(db_path, "security_events")
    candidates = score_candidates(indicators, breadth, rotations, deals, index_features, events, master, as_of, policy=policy)
    _write_candidates(db_path, candidates, as_of)
    persist_candidate_snapshot(db_path, candidates, as_of)
    existing = _load(db_path, "signal_ledger")
    ledger = update_signal_ledger(existing, candidates, as_of)
    _write_ledger(db_path, ledger)
    _write_outcomes(db_path, _load(db_path, "prices_daily"), ledger)
    return candidates


def materialize_decision_date(db_path: Path, as_of: date, policy: DecisionPolicy | None = None) -> pd.DataFrame:
    """Materialize exactly one versioned decision session."""

    return materialize_decision_tables(db_path, as_of=as_of, policy=policy or DecisionPolicy())
