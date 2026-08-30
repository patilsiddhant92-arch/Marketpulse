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


def test_asof_reference_multi_symbol_preserves_length_and_order():
    """Regression: global merge_asof raised 'left keys must be sorted' on CI full rebuild."""
    from Scripts.reference_history import asof_reference

    symbols = [f"S{i:04d}" for i in range(50)]
    rows = []
    refs = []
    for sym in symbols:
        for d in (date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 8)):
            rows.append({"symbol": sym, "trade_date": d})
        refs.append({"symbol": sym, "effective_date": date(2026, 1, 1), "high_52w": 10.0})
        refs.append({"symbol": sym, "effective_date": date(2026, 1, 6), "high_52w": 20.0})

    # Deliberately unsorted input (what broke Actions)
    frame = pd.DataFrame(rows).sample(frac=1.0, random_state=42).reset_index(drop=True)
    original_symbols = frame["symbol"].tolist()
    original_dates = pd.to_datetime(frame["trade_date"]).tolist()

    result = asof_reference(pd.DataFrame(refs), frame)

    assert len(result) == len(frame)
    assert result["symbol"].tolist() == original_symbols
    assert pd.to_datetime(result["trade_date"]).tolist() == original_dates
    # After 6 Jan snapshot, high should be 20; before that, 10
    after = result[pd.to_datetime(result["trade_date"]) >= pd.Timestamp("2026-01-06")]
    before = result[pd.to_datetime(result["trade_date"]) < pd.Timestamp("2026-01-06")]
    assert (after["high_52w"] == 20.0).all()
    assert (before["high_52w"] == 10.0).all()


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


def test_reference_history_collapse_merges_last_non_null_values():
    """Reference snapshots from separate reports must merge without row-wise Python loops."""
    from Scripts.reference_history import _collapse_reference_rows

    frame = pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "effective_date": "2026-01-01",
                "source_date": "2026-01-01",
                "market_cap_cr": 10.0,
                "high_52w": None,
                "source_checksum": "mcap",
            },
            {
                "symbol": "AAA",
                "effective_date": "2026-01-01",
                "source_date": "2026-01-01",
                "market_cap_cr": None,
                "high_52w": 120.0,
                "source_checksum": "high",
            },
            {
                "symbol": "AAA",
                "effective_date": "2026-01-01",
                "source_date": "2026-01-01",
                "market_cap_cr": 12.0,
                "high_52w": None,
                "source_checksum": "latest",
            },
        ]
    )

    result = _collapse_reference_rows(frame)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["market_cap_cr"] == 12.0
    assert row["high_52w"] == 120.0
    assert row["source_checksum"] == "latest"
