from __future__ import annotations

import pandas as pd

from build_database import collapse_cross_listed_prints


def _deal(deal_type, client="INFINITE TRADE", qty=8_600_000, price=2905.0, side="SELL"):
    return {"deal_type": deal_type, "trade_date": pd.Timestamp("2026-09-25"), "symbol": "ADANIENT",
            "security_name": "Adani Ent", "client_name": client, "side": side,
            "quantity": qty, "price": price, "source_file": f"{deal_type}.csv"}


def test_same_print_in_bulk_and_block_collapses_to_one_row():
    df = pd.DataFrame([_deal("Bulk"), _deal("Block"), _deal("Bulk", client="OTHER", qty=100)])
    out = collapse_cross_listed_prints(df)
    assert len(out) == 2
    adani = out[out["client_name"] == "INFINITE TRADE"].iloc[0]
    assert adani["deal_type"] == "Block+Bulk"
    assert (out["client_name"] == "OTHER").sum() == 1


def test_distinct_prints_are_untouched():
    df = pd.DataFrame([_deal("Bulk"), _deal("Bulk", price=2906.0)])
    assert len(collapse_cross_listed_prints(df)) == 2


def test_empty_frame_passes_through():
    empty = pd.DataFrame(columns=["deal_type", "trade_date", "symbol", "client_name", "side", "quantity", "price"])
    assert collapse_cross_listed_prints(empty).empty
