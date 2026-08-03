from datetime import date

import pandas as pd


def test_signal_ledger_creates_stable_id_and_updates_trigger():
    from Scripts.signal_service import update_signal_ledger

    candidate = pd.DataFrame([{"symbol": "AAA", "score_version": "focused-v1", "candidate_state": "Prepare", "total_score": 70, "trigger_price": 103, "invalidation_price": 96, "market_regime": "Constructive", "sector_state": "Leading", "industry_state": "Improving"}])
    first = update_signal_ledger(pd.DataFrame(), candidate, date(2026, 8, 3))
    candidate.loc[0, "candidate_state"] = "Triggered"
    second = update_signal_ledger(first, candidate, date(2026, 8, 4))

    assert first.iloc[0]["signal_id"] == second.iloc[0]["signal_id"]
    assert second.iloc[0]["trigger_date"] == date(2026, 8, 4)
    assert "Triggered" in str(second.iloc[0]["state_history"])
