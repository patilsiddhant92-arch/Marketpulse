from __future__ import annotations

import pandas as pd

from build_database import compute_repeated_client_count


def _deal(deal_type, trade_date, client="INFINITE TRADE", symbol="ADANIENT", side="BUY"):
    return {
        "deal_type": deal_type,
        "trade_date": pd.Timestamp(trade_date),
        "symbol": symbol,
        "client_name": client,
        "side": side,
    }


def test_repeat_count_survives_bulk_to_block_bulk_reclassification():
    """A client who buys the same symbol on two days, once reported as plain
    'Bulk' and once collapsed into 'Block+Bulk' after cross-file merging,
    must still count as 2 repeats -- the key must not include deal_type."""
    df = pd.DataFrame([
        _deal("Bulk", "2026-09-24"),
        _deal("Block+Bulk", "2026-09-25"),
    ])
    counts = compute_repeated_client_count(df)
    assert (counts == 2).all()


def test_repeat_count_ignores_unrelated_clients_and_symbols():
    df = pd.DataFrame([
        _deal("Bulk", "2026-09-24", client="INFINITE TRADE"),
        _deal("Block+Bulk", "2026-09-25", client="INFINITE TRADE"),
        _deal("Bulk", "2026-09-24", client="OTHER CLIENT"),
        _deal("Bulk", "2026-09-24", client="INFINITE TRADE", symbol="TCS"),
    ])
    counts = compute_repeated_client_count(df)
    assert counts.iloc[0] == 2  # INFINITE TRADE / ADANIENT / BUY, day 1
    assert counts.iloc[1] == 2  # INFINITE TRADE / ADANIENT / BUY, day 2
    assert counts.iloc[2] == 1  # OTHER CLIENT, single day
    assert counts.iloc[3] == 1  # INFINITE TRADE but different symbol (TCS)


def test_repeat_count_same_day_same_symbol_different_side_not_merged():
    df = pd.DataFrame([
        _deal("Bulk", "2026-09-24", side="BUY"),
        _deal("Bulk", "2026-09-25", side="SELL"),
    ])
    counts = compute_repeated_client_count(df)
    assert (counts == 1).all()
