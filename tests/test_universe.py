from __future__ import annotations

import pandas as pd

from build_database import read_bhavcopy
from symbol_changes import parse_symbol_changes, resolve_current_symbol
from universe import apply_symbol_changes, build_universe_history

BHAV = """SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER
OLDCO, EQ, 24-Sep-2021, 10, 10, 11, 9, 10.5, 10.5, 10.2, 1000, 1.0, 10, 500, 50.0
DELISTED, BE, 24-Sep-2021, 5, 5, 5, 5, 5, 5, 5, 100, 0.05, 1, -, -
BONDX, N1, 24-Sep-2021, 100, 100, 100, 100, 100, 100, 100, 10, 0.01, 1, -, -
"""

CHANGES = """ OLD COMPANY LTD,OLDCO,MIDCO,01-JAN-2023
 MID COMPANY LTD,MIDCO,NEWCO,01-JAN-2025
 SELF LTD,SAME,SAME,01-JAN-2024
"""


def test_default_universe_is_series_whitelist(tmp_path):
    p = tmp_path / "sec_bhavdata_full_24092021.csv"
    p.write_text(BHAV)
    df = read_bhavcopy(p)
    assert set(df["symbol"]) == {"OLDCO", "DELISTED"}
    assert pd.isna(df.set_index("symbol").loc["DELISTED", "delivery_pct"])


def test_explicit_universe_still_supported(tmp_path):
    p = tmp_path / "sec_bhavdata_full_24092021.csv"
    p.write_text(BHAV)
    assert set(read_bhavcopy(p, {"OLDCO"})["symbol"]) == {"OLDCO"}


def test_symbol_change_chains(tmp_path):
    p = tmp_path / "symbolchange.csv"
    p.write_text(CHANGES)
    mapping = resolve_current_symbol(parse_symbol_changes(p))
    assert mapping == {"OLDCO": "NEWCO", "MIDCO": "NEWCO"}


def test_symbol_change_cycle_is_unmapped():
    assert resolve_current_symbol(pd.DataFrame({
        "old_symbol": ["A", "B"],
        "new_symbol": ["B", "A"],
        "change_date": [None, None],
    })) == {}


def test_apply_changes_and_universe_history():
    prices = pd.DataFrame({
        "symbol": ["OLDCO", "NEWCO", "DELISTED"],
        "series": ["EQ", "EQ", "BE"],
        "trade_date": pd.to_datetime(["2021-09-24", "2025-09-24", "2021-09-24"]),
        "close_price": [10.5, 20.0, 5.0],
    })
    merged = apply_symbol_changes(prices, {"OLDCO": "NEWCO"})
    assert sorted(merged["symbol"]) == ["DELISTED", "NEWCO", "NEWCO"]
    uh = build_universe_history(merged, active_symbols={"NEWCO"}).set_index("symbol")
    assert uh.loc["NEWCO", "status"] == "active" and uh.loc["NEWCO", "sessions"] == 2
    assert str(uh.loc["NEWCO", "first_date"].date()) == "2021-09-24"
    assert uh.loc["DELISTED", "status"] == "inactive" and uh.loc["DELISTED", "last_series"] == "BE"
