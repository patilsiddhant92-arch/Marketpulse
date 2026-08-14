from datetime import date

import pandas as pd


def test_signal_ledger_creates_stable_id_and_updates_trigger():
    from Scripts.signal_service import update_signal_ledger

    candidate = pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "score_version": "focused-v1",
                "candidate_state": "Prepare",
                "eligibility_status": "eligible",
                "total_score": 70,
                "trigger_price": 103,
                "invalidation_price": 96,
                "market_regime": "Constructive",
                "sector_state": "Leading",
                "industry_state": "Improving",
            }
        ]
    )
    first = update_signal_ledger(pd.DataFrame(), candidate, date(2026, 8, 3))
    candidate.loc[0, "candidate_state"] = "Triggered"
    second = update_signal_ledger(first, candidate, date(2026, 8, 4))

    assert first.iloc[0]["signal_id"] == second.iloc[0]["signal_id"]
    assert second.iloc[0]["trigger_date"] == date(2026, 8, 4)
    assert "Triggered" in str(second.iloc[0]["state_history"])


def test_eligible_observe_enters_ledger():
    from Scripts.signal_service import update_signal_ledger

    candidate = pd.DataFrame(
        [
            {
                "symbol": "BBB",
                "score_version": "focused-v2",
                "candidate_state": "Observe",
                "eligibility_status": "eligible",
                "total_score": 55,
                "setup_first_seen": None,
            }
        ]
    )
    ledger = update_signal_ledger(pd.DataFrame(), candidate, date(2026, 8, 7))
    assert len(ledger) == 1
    assert ledger.iloc[0]["status"] == "observe"
    assert ledger.iloc[0]["first_seen_date"] == date(2026, 8, 7)


def test_blocked_does_not_enter_ledger():
    from Scripts.signal_service import update_signal_ledger

    candidate = pd.DataFrame(
        [
            {
                "symbol": "CCC",
                "score_version": "focused-v2",
                "candidate_state": "Blocked",
                "eligibility_status": "blocked",
                "total_score": 40,
            }
        ]
    )
    ledger = update_signal_ledger(pd.DataFrame(), candidate, date(2026, 8, 7))
    assert ledger.empty


def test_stable_first_seen_survives_second_session_when_scorer_stamps_as_of():
    from Scripts.signal_service import apply_stable_identity, update_signal_ledger

    day1 = pd.DataFrame(
        [
            {
                "symbol": "DDD",
                "score_version": "focused-v2",
                "candidate_state": "Observe",
                "eligibility_status": "eligible",
                "total_score": 62,
                "setup_first_seen": None,
            }
        ]
    )
    first = update_signal_ledger(pd.DataFrame(), day1, date(2026, 8, 6))
    # Scorer mistakenly stamps as_of on day 2 — identity must ignore and reuse day1.
    day2 = pd.DataFrame(
        [
            {
                "symbol": "DDD",
                "score_version": "focused-v2",
                "candidate_state": "Prepare",
                "eligibility_status": "eligible",
                "total_score": 66,
                "setup_first_seen": date(2026, 8, 7),
            }
        ]
    )
    identified = apply_stable_identity(day2, first, date(2026, 8, 7), session_dates=[date(2026, 8, 6), date(2026, 8, 7)])
    assert identified.iloc[0]["setup_first_seen"] == date(2026, 8, 6)
    assert identified.iloc[0]["setup_age_sessions"] >= 2
    second = update_signal_ledger(first, identified, date(2026, 8, 7))
    assert second.iloc[0]["signal_id"] == first.iloc[0]["signal_id"]
    assert second.iloc[0]["first_seen_date"] == date(2026, 8, 6)
