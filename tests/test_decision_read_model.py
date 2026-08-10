from __future__ import annotations

from datetime import date

import duckdb


def _seed_candidates(path):
    with duckdb.connect(str(path)) as db:
        db.execute(
            """
            CREATE TABLE candidate_daily (
                trade_date DATE, symbol TEXT, score_version TEXT, candidate_state TEXT,
                total_score DOUBLE, market_regime TEXT, market_cap_cr DOUBLE,
                eligibility_status TEXT, blocking_reasons TEXT, warning_reasons TEXT,
                why_now TEXT, trigger_price DOUBLE, invalidation_price DOUBLE,
                first_resistance DOUBLE, distance_to_trigger_pct DOUBLE,
                initial_risk_pct DOUBLE, reward_to_risk DOUBLE, event_risk TEXT,
                sector TEXT, industry TEXT, geometry_valid BOOLEAN
            )
            """
        )
        rows = [
            (date(2026, 8, 7), "AAA", "focused-v2", "Prepare", 88, "Constructive", 1200, "eligible", "", "", "breakout", 105, 95, 125, 1.2, 4, 2.5, "none", "Tech", "Software", True),
            (date(2026, 8, 7), "LOW", "focused-v2", "Blocked", 84, "Constructive", 999.9, "blocked", "market_cap_below_1000cr", "", "strong trend", 105, 95, 125, 1.2, 4, 2.5, "none", "Tech", "Software", True),
            (date(2026, 8, 7), "MISS", "focused-v2", "Blocked", 70, "Constructive", None, "blocked", "market_cap_missing", "", "insufficient data", None, None, None, None, None, None, "none", "Industrials", "Capital Goods", False),
            (date(2026, 8, 7), "OLD", "focused-v1", "Prepare", 99, "Constructive", 2500, "eligible", "", "", "old score", 100, 90, 120, 1, 3, 3, "none", "Tech", "Software", True),
        ]
        db.executemany("INSERT INTO candidate_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)


def test_read_model_selects_focused_v2_and_never_leaks_low_cap_rows(tmp_path):
    db_path = tmp_path / "marketpulse.duckdb"
    _seed_candidates(db_path)

    from App.decision_read_model import load_decision_snapshot

    snapshot = load_decision_snapshot(db_path, expected_date=date(2026, 8, 7))

    assert snapshot.as_of == date(2026, 8, 7)
    assert snapshot.score_version == "focused-v2"
    assert snapshot.stale is False
    assert snapshot.eligible["symbol"].tolist() == ["AAA"]
    assert (snapshot.eligible["market_cap_cr"] >= 1000).all()
    assert set(snapshot.blocked["symbol"]) == {"LOW", "MISS"}
    assert snapshot.excluded_by_market_cap == 2


def test_read_model_exposes_missing_and_stale_states(tmp_path):
    missing = tmp_path / "missing.duckdb"
    from App.decision_read_model import load_decision_snapshot

    absent = load_decision_snapshot(missing)
    assert absent.stale is True
    assert absent.diagnostic == "decision_snapshot_missing"
    assert absent.eligible.empty

    db_path = tmp_path / "marketpulse.duckdb"
    _seed_candidates(db_path)
    stale = load_decision_snapshot(db_path, expected_date=date(2026, 8, 8))
    assert stale.stale is True
    assert stale.diagnostic == "decision_snapshot_stale"
