from __future__ import annotations

import math

import pandas as pd

from price_adjustment import actions_from_mcap, read_mcap_frames

HDR = "Trade Date,Symbol,Series,Security Name,Category,Last Trade Date,Face Value(Rs.),Issue Size,Close Price/Paid up value(Rs.),Market Cap(Rs.)\n"


def test_detects_split_bonus_and_ignores_small_issuance():
    f = pd.DataFrame({
        "file_date": pd.to_datetime(["2026-08-20", "2026-08-21"] * 3),
        "symbol": ["GOODLUCK", "GOODLUCK", "KIRLPNU", "KIRLPNU", "QIPCO", "QIPCO"],
        "face_value": [2.0, 2.0, 2.0, 1.0, 10.0, 10.0],
        "issue_size": [10_000_000, 30_000_000, 64_000_000, 128_000_000, 1_000_000, 1_060_000],
    })
    a = actions_from_mcap(f).set_index("symbol")
    assert a.loc["GOODLUCK", "kind"] == "bonus" and math.isclose(a.loc["GOODLUCK", "factor"], 1 / 3)
    assert a.loc["GOODLUCK", "source"] == "mcap_issue"
    assert a.loc["KIRLPNU", "kind"] == "split" and math.isclose(a.loc["KIRLPNU", "factor"], 0.5)
    assert a.loc["KIRLPNU", "source"] == "mcap_fv"
    assert str(a.loc["KIRLPNU", "ex_date"].date()) == "2026-08-21"
    assert "QIPCO" not in a.index


def test_read_mcap_frames_from_files(tmp_path):
    d = tmp_path / "Input" / "archive"
    d.mkdir(parents=True)
    (d / "mcap20082026.csv").write_text(HDR + "20 AUG 2026,GOODLUCK,EQ,GOODLUCK INDIA,Listed,20 AUG 2026,2.00,10000000,1439.40,1.0\n"
                                        "20 AUG 2026,Total     ,  ,   ,   ,   ,0.00,0,0.00,9.0\n")
    (d / "mcap21082026.csv").write_text(HDR + "21 AUG 2026,GOODLUCK,EQ,GOODLUCK INDIA,Listed,21 AUG 2026,2.00,30000000,490.90,1.0\n")
    f = read_mcap_frames(tmp_path, [])
    assert set(f["symbol"]) == {"GOODLUCK"} and len(f) == 2
    assert f["issue_size"].max() == 30_000_000


def test_read_mcap_frames_prefers_canonical_over_duplicate(tmp_path):
    """When both canonical and duplicate (with ' (2)') files exist for same date/symbol, canonical wins."""
    d = tmp_path / "Input" / "archive"
    d.mkdir(parents=True)
    # Duplicate file with different issue_size (should be ignored)
    (d / "mcap04082026 (2).csv").write_text(HDR + "04 AUG 2026,SYMBOL1,EQ,TEST,Listed,04 AUG 2026,2.00,5000000,100.00,1.0\n")
    # Canonical file with correct issue_size (should be kept)
    (d / "mcap04082026.csv").write_text(HDR + "04 AUG 2026,SYMBOL1,EQ,TEST,Listed,04 AUG 2026,2.00,8000000,100.00,1.0\n")
    f = read_mcap_frames(tmp_path, [])
    assert len(f) == 1
    assert f.iloc[0]["issue_size"] == 8_000_000  # canonical file's value
