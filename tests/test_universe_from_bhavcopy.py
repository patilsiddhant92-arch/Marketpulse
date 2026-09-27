"""Universe comes from the bhavcopies (series whitelist) in both the full build and the append,
and symbol changes (HEG -> HEGAM on 22-Sep-2026) give one continuous series in both paths."""
from __future__ import annotations

import pandas as pd
import pytest

import append_database
import build_database
import config

HEADER = "SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER"

# (file date ddmmyyyy, DATE1, rows)
SESSIONS = [
    ("17092026", "17-Sep-2026", [("HEG", "EQ", 500), ("INFY", "EQ", 1500), ("GONE", "BE", 20), ("GSEC", "GS", 100)]),
    ("18092026", "18-Sep-2026", [("HEG", "EQ", 505), ("INFY", "EQ", 1510), ("GONE", "BE", 19)]),
    ("21092026", "21-Sep-2026", [("HEG", "EQ", 510), ("INFY", "EQ", 1520)]),
    ("22092026", "22-Sep-2026", [("HEGAM", "EQ", 512), ("INFY", "EQ", 1530), ("NEWBZ", "BZ", 3)]),
    ("23092026", "23-Sep-2026", [("HEGAM", "EQ", 520), ("INFY", "EQ", 1525), ("NEWBZ", "BZ", 3.1)]),
]

CHANGES = "HEG Advanced Materials Limited,HEG,HEGAM,22-SEP-2026\n"


def _write_session(folder, ddmmyyyy, date1, rows):
    lines = [HEADER]
    for sym, series, close in rows:
        lines.append(f"{sym}, {series}, {date1}, {close}, {close}, {close}, {close}, {close}, {close}, {close}, 1000, 1.0, 10, 500, 50.0")
    (folder / f"sec_bhavdata_full_{ddmmyyyy}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    root = tmp_path / "Input"
    archive, daily, reference = root / "archive", root / "daily", root / "reference"
    for d in (archive, daily, reference, archive / "backfill" / "bhav"):
        d.mkdir(parents=True)
    (reference / "symbolchange.csv").write_text(CHANGES, encoding="utf-8")
    for mod in (build_database, config):
        monkeypatch.setattr(mod, "ARCHIVE_DIR", archive)
        monkeypatch.setattr(mod, "INPUT_DIR", root)
    monkeypatch.setattr(build_database, "DAILY_DIR", daily)
    monkeypatch.setattr(append_database, "DAILY_DIR", daily)
    monkeypatch.setattr(append_database, "INPUT_DIR", root, raising=False)
    return archive


def _cols(frame):
    keep = ["symbol", "series", "trade_date", "close_price", "open_price", "volume", "delivery_qty"]
    return frame[keep].sort_values(["symbol", "trade_date"]).reset_index(drop=True)


def test_full_build_uses_bhavcopy_universe_and_renames(inputs):
    for s in SESSIONS:
        _write_session(inputs, *s)
    prices = build_database.build_prices(None)
    assert set(prices["symbol"]) == {"HEGAM", "INFY", "GONE", "NEWBZ"}  # GS series filtered, HEG renamed
    heg = prices[prices["symbol"] == "HEGAM"].sort_values("trade_date")
    assert heg["close_price"].tolist() == [500, 505, 510, 512, 520]


def test_append_matches_full_build(inputs):
    # Earlier DB: built from the first three sessions, before NSE published the rename.
    changes = inputs.parent / "reference" / "symbolchange.csv"
    changes.write_text("", encoding="utf-8")
    for s in SESSIONS[:3]:
        _write_session(inputs, *s)
    existing = build_database.build_prices(None)
    assert "HEG" in set(existing["symbol"])
    latest = existing["trade_date"].max()
    # The rename is published and new sessions arrive (HEGAM is not in EQUITY_L).
    changes.write_text(CHANGES, encoding="utf-8")
    for s in SESSIONS[3:]:
        _write_session(inputs, *s)
    new = append_database._new_daily_prices(None, latest)
    assert "HEGAM" in set(new["symbol"]) and "NEWBZ" in set(new["symbol"])
    merged = append_database.merge_new_prices(existing, new)
    full = build_database.build_prices(None)
    pd.testing.assert_frame_equal(_cols(merged), _cols(full), check_dtype=False)
    heg = merged[merged["symbol"] == "HEGAM"].sort_values("trade_date")
    assert heg["close_price"].tolist() == [500, 505, 510, 512, 520]
    assert "HEG" not in set(merged["symbol"])


def test_master_covers_latest_session_and_flags_active(inputs):
    for s in SESSIONS:
        _write_session(inputs, *s)
    prices = build_database.build_prices(None)
    equity = pd.DataFrame({"symbol": ["INFY", "SUSP"], "security_name": ["Infosys", "Suspended Co"],
                           "listing_date": [None, None], "isin": ["INE009A01021", "INE000000000"]})
    empty = pd.DataFrame(columns=["symbol"])
    master = build_database.build_master(equity, pd.DataFrame(columns=["symbol", "sector"]), prices,
                                         pd.DataFrame(columns=["symbol", "security_name"]), empty, empty)
    by_sym = master.set_index("symbol")
    # every latest-session symbol is present, even if EQUITY_L lacks it
    assert {"HEGAM", "INFY", "NEWBZ"} <= set(by_sym.index)
    assert by_sym.loc["HEGAM", "is_active"] and by_sym.loc["NEWBZ", "is_active"] and by_sym.loc["INFY", "is_active"]
    # an EQUITY_L symbol with no latest-session row stays, flagged inactive
    assert not by_sym.loc["SUSP", "is_active"]
    # delisted symbols (history only, not in EQUITY_L) do not enter the master
    assert "GONE" not in by_sym.index
    assert master["symbol"].is_unique


def test_latest_session_screens_exclude_delisted(inputs):
    for s in SESSIONS:
        _write_session(inputs, *s)
    prices = build_database.build_prices(None)
    latest = prices["trade_date"].max()
    assert "GONE" not in set(prices.loc[prices["trade_date"] == latest, "symbol"])
