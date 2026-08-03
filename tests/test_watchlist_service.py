from datetime import date

import pandas as pd


def test_watchlist_transition_is_auditable():
    from Scripts.watchlist_service import transition_candidate

    state, reason = transition_candidate(
        {"candidate_state": "Prepare", "trigger_price": 103, "invalidation_price": 96},
        {"candidate_state": "Triggered", "triggered": True, "close_price": 104},
    )

    assert state == "Triggered"
    assert "trigger" in reason.lower()


def test_watchlist_snapshot_persists_state_history(tmp_path):
    from Scripts.migrations import run_migrations
    from Scripts.watchlist_service import persist_candidate_snapshot, load_watchlist

    path = tmp_path / "marketpulse.duckdb"
    run_migrations(path)
    rows = pd.DataFrame([{"symbol": "AAA", "score_version": "focused-v1", "trade_date": date(2026, 8, 3), "candidate_state": "Prepare", "trigger_price": 103, "invalidation_price": 96, "first_resistance": 112, "setup_first_seen": date(2026, 8, 3), "setup_age_sessions": 1}])
    persist_candidate_snapshot(path, rows, date(2026, 8, 3))
    rows.loc[0, "candidate_state"] = "Triggered"
    rows.loc[0, "triggered"] = True
    persist_candidate_snapshot(path, rows, date(2026, 8, 4))

    result = load_watchlist(path)
    assert len(result) == 1
    assert result.iloc[0]["candidate_state"] == "Triggered"
    assert "Triggered" in str(result.iloc[0]["state_history"])
