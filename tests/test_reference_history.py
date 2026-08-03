from datetime import date

import pandas as pd


def test_asof_reference_never_uses_future_reference():
    from Scripts.reference_history import asof_reference

    reference = pd.DataFrame(
        [
            {"symbol": "AAA", "effective_date": date(2026, 1, 1), "high_52w": 100.0},
            {"symbol": "AAA", "effective_date": date(2026, 2, 1), "high_52w": 200.0},
        ]
    )
    result = asof_reference(reference, pd.DataFrame({"symbol": ["AAA", "AAA"], "trade_date": [date(2026, 1, 15), date(2026, 2, 5)]}))

    assert result["high_52w"].tolist() == [100.0, 200.0]
    assert (pd.to_datetime(result["effective_date"]) <= pd.to_datetime(result["trade_date"])).all()


def test_reference_history_deduplicates_same_symbol_date():
    from Scripts.reference_history import build_security_reference_history

    frame = pd.DataFrame(
        [
            {"symbol": "AAA", "effective_date": "2026-01-01", "market_cap_cr": 10, "source_checksum": "old"},
            {"symbol": "AAA", "effective_date": "2026-01-01", "market_cap_cr": 20, "source_checksum": "new"},
        ]
    )
    result = build_security_reference_history(frame, pd.DataFrame(), pd.DataFrame(), pd.DataFrame())

    assert len(result) == 1
    assert result.iloc[0]["market_cap_cr"] == 20
