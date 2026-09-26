"""Task 10: per-file parse cache for adjust_prices, plus the vectorised source parsers."""
from __future__ import annotations

import io
import math
import os
import zipfile

import numpy as np
import pandas as pd
import pytest

import price_adjustment as pa
from test_price_adjustment_apply import PRICES
from test_price_adjustment_pipeline import _seed_root


def _goodluck():
    return PRICES[PRICES["symbol"] == "GOODLUCK"].reset_index(drop=True)


def _boom(*_args, **_kwargs):
    raise AssertionError("must not be called")


def _files(path):
    return {p for p in path.rglob("*")}


def test_default_cache_dir_is_under_input_archive(tmp_path):
    _seed_root(tmp_path)
    pa.adjust_prices(_goodluck(), tmp_path)
    cache = tmp_path / "Input" / "archive" / ".adjust_cache"
    assert cache == pa.default_cache_dir(tmp_path)
    assert cache.is_dir() and any(cache.iterdir())


def test_cache_dir_none_reads_and_writes_nothing(tmp_path, monkeypatch):
    _seed_root(tmp_path)
    monkeypatch.setattr(pa, "_read_cache_entry", _boom)
    monkeypatch.setattr(pa, "_write_cache_entry", _boom)
    before = _files(tmp_path)
    _, adjustments = pa.adjust_prices(_goodluck(), tmp_path, cache_dir=None)
    assert _files(tmp_path) == before
    assert adjustments["applied"].any()


def test_warm_cache_gives_identical_result_without_reparsing_sources(tmp_path, monkeypatch):
    _seed_root(tmp_path)
    cache = tmp_path / "cache"
    adjusted1, adjustments1 = pa.adjust_prices(_goodluck(), tmp_path, cache_dir=cache)
    monkeypatch.setattr(pa, "_parse_pr_zip", _boom)
    monkeypatch.setattr(pa, "_parse_mcap_csv", _boom)
    adjusted2, adjustments2 = pa.adjust_prices(_goodluck(), tmp_path, cache_dir=cache)
    pd.testing.assert_frame_equal(adjustments1, adjustments2)
    pd.testing.assert_frame_equal(adjusted1, adjusted2)


def test_stale_cache_entry_is_rebuilt_when_the_file_changes(tmp_path):
    zip_path = _seed_root(tmp_path)
    cache = tmp_path / "cache"
    _, first = pa.adjust_prices(_goodluck(), tmp_path, cache_dir=cache)
    assert "BONUS 2:1" in set(first["description"])

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("bc21082026.csv",
                    "SERIES,SYMBOL,SECURITY,RECORD_DT,BC_STRT_DT,BC_END_DT,EX_DT,ND_STRT_DT,ND_END_DT,PURPOSE\n"
                    "EQ,GOODLUCK,Goodluck India Ltd,2026-08-21,,,2026-08-21,,,BONUS 3:1 (REVISED TEXT)\n")
    st = zip_path.stat()
    os.utime(zip_path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))

    _, second = pa.adjust_prices(_goodluck(), tmp_path, cache_dir=cache)
    assert "BONUS 3:1 (REVISED TEXT)" in set(second["description"])
    assert "BONUS 2:1" not in set(second["description"])


def test_only_the_changed_file_is_reparsed(tmp_path, monkeypatch):
    zip_path = _seed_root(tmp_path)
    other = zip_path.with_name("PR200826.zip")
    with zipfile.ZipFile(other, "w") as zf:
        zf.writestr("bc20082026.csv",
                    "SERIES,SYMBOL,SECURITY,RECORD_DT,BC_STRT_DT,BC_END_DT,EX_DT,ND_STRT_DT,ND_END_DT,PURPOSE\n"
                    "EQ,TCC,TCC Ltd,2026-09-04,,,2026-09-04,,,FVSPLT FRM RS 10 TO RS 2\n")
    cache = tmp_path / "cache"
    pa.adjust_prices(_goodluck(), tmp_path, cache_dir=cache)

    st = other.stat()
    os.utime(other, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    parsed = []
    real = pa._parse_pr_zip
    monkeypatch.setattr(pa, "_parse_pr_zip", lambda p: parsed.append(p.name) or real(p))
    monkeypatch.setattr(pa, "_parse_mcap_csv", _boom)
    pa.adjust_prices(_goodluck(), tmp_path, cache_dir=cache)
    assert parsed == ["PR200826.zip"]


def test_corrupt_cache_entry_is_ignored_and_rebuilt(tmp_path):
    _seed_root(tmp_path)
    cache = tmp_path / "cache"
    _, first = pa.adjust_prices(_goodluck(), tmp_path, cache_dir=cache)
    entries = [p for p in cache.iterdir() if p.is_file()]
    assert entries
    for p in entries:
        p.write_bytes(b"not a pickle")
    _, second = pa.adjust_prices(_goodluck(), tmp_path, cache_dir=cache)
    pd.testing.assert_frame_equal(first, second)
    assert all(p.read_bytes() != b"not a pickle" for p in entries)


def test_each_pr_zip_is_opened_once_per_run(tmp_path, monkeypatch):
    zip_path = _seed_root(tmp_path)
    opened = []
    real = zipfile.ZipFile

    def counting(file, *args, **kwargs):
        opened.append(os.fspath(file))
        return real(file, *args, **kwargs)

    monkeypatch.setattr(pa.zipfile, "ZipFile", counting)
    pa.adjust_prices(_goodluck(), tmp_path, cache_dir=None)
    assert opened.count(os.fspath(zip_path)) == 1


def test_parallel_parse_keeps_file_order_and_reports_bad_zips(tmp_path, capsys):
    hdr = "SERIES,SYMBOL,SECURITY,RECORD_DT,BC_STRT_DT,BC_END_DT,EX_DT,ND_STRT_DT,ND_END_DT,PURPOSE\n"
    zips = []
    for day in range(1, 13):
        p = tmp_path / f"PR{day:02d}0826.zip"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr(f"bc{day:02d}082026.csv", hdr + f"EQ,SYM{day:02d},X,,,,2026-09-{day:02d},,,BONUS 1:1\n")
        zips.append(p)
    bad = tmp_path / "PR130826.zip"
    bad.write_bytes(b"this is not a zip")
    zips.insert(5, bad)

    a = pa.collect_bc_actions(zips, cache_dir=tmp_path / "cache")

    assert a["symbol"].tolist() == [f"SYM{d:02d}" for d in range(1, 13)]
    assert a["published"].tolist() == [pd.Timestamp(f"2026-08-{d:02d}") for d in range(1, 13)]
    assert "Skipped PR130826.zip" in capsys.readouterr().out


# --- vectorised parsers keep the old row-by-row semantics --------------------------------------

def test_bc_dates_fall_back_across_columns_and_formats():
    text = ("SERIES,SYMBOL,SECURITY,RECORD_DT,BC_STRT_DT,BC_END_DT,EX_DT,ND_STRT_DT,ND_END_DT,PURPOSE\n"
            "EQ,AAA,A,2026-08-21,,,2026-08-20,,,BONUS 1:1\n"      # EX_DT ISO
            "EQ,BBB,B,21-Aug-2026,,,,,,BONUS 1:1\n"               # EX_DT blank -> RECORD_DT dd-Mon-yyyy
            "EQ,CCC,C, ,24/09/2019,30/09/2019, , , ,BONUS 1:1\n"  # -> BC_STRT_DT dd/mm/yyyy
            "EQ,DDD,D,,,,21-08-2026,,,BONUS 1:1\n"                # EX_DT dd-mm-yyyy
            "EQ,EEE,E,,,,,,,BONUS 1:1\n")                         # no date at all -> dropped
    raw = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    a = pa.actions_from_bc_frame(raw).set_index("symbol")["ex_date"]
    assert a.to_dict() == {"AAA": pd.Timestamp("2026-08-20"), "BBB": pd.Timestamp("2026-08-21"),
                           "CCC": pd.Timestamp("2019-09-24"), "DDD": pd.Timestamp("2026-08-21")}


def test_mcap_actions_skip_nan_rows_and_compare_with_last_valid_snapshot():
    f = pd.DataFrame({
        "file_date": pd.to_datetime(["2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21",
                                     "2026-08-18", "2026-08-19", "2026-08-20"]),
        "symbol": ["AAA"] * 4 + ["BBB"] * 3,
        "face_value": [10.0, np.nan, 10.0, 2.0, 0.0, 5.0, 5.0],
        "issue_size": [1e6, 5e6, 2e6, 1e7, 1e6, 1e6, 3e6],
    })
    a = pa.actions_from_mcap(f)
    # AAA: 08-18 -> (08-19 NaN skipped) -> 08-20 issue x2 bonus -> 08-21 FV 10 -> 2 split.
    # BBB: 08-18 has FV 0 so 08-19 isn't compared; 08-19 -> 08-20 issue x3 bonus.
    assert a[["symbol", "kind", "source"]].values.tolist() == [
        ["AAA", "bonus", "mcap_issue"], ["AAA", "split", "mcap_fv"], ["BBB", "bonus", "mcap_issue"]]
    assert a["ex_date"].tolist() == [pd.Timestamp("2026-08-20"), pd.Timestamp("2026-08-21"), pd.Timestamp("2026-08-20")]
    assert np.allclose(a["factor"], [0.5, 0.2, 1 / 3])
    assert a["description"].tolist() == ["ISSUE x2.00", "FV 10.0->2.0", "ISSUE x3.00"]


def test_rename_symbols_applies_chained_renames_in_change_date_order():
    changes = pd.DataFrame({"old_symbol": ["BBB", "AAA"], "new_symbol": ["CCC", "BBB"],
                            "change_date": pd.to_datetime(["2026-01-01", "2025-01-01"])})
    df = pd.DataFrame({"symbol": ["AAA", "AAA", "BBB", "CCC", "ZZZ", "AAA"],
                       "file_date": pd.to_datetime(["2024-06-01", "2025-06-01", "2025-06-01", "2026-06-01",
                                                    "2020-01-01", None])})
    out = pa._rename_symbols(df, changes, "file_date")
    assert out["symbol"].tolist() == ["CCC", "AAA", "CCC", "CCC", "ZZZ", "AAA"]
    assert out["file_date"].equals(df["file_date"])
