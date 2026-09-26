"""Characterization + memo tests for the batched/memoised index-history loader.

``_reference_load`` below is a verbatim port of the pre-optimisation algorithm (per-file
``parse_ind_close_all`` + per-file ``parse_market_activity``, tuple-set MA filter); the
optimised ``load_all_index_history`` must reproduce it exactly, dtypes included.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import index_history
from index_history import (
    EXTRA_INDEX_COLUMNS,
    INDEX_COLUMNS,
    load_all_index_history,
    load_index_name_map,
    parse_ind_close_all,
    parse_market_activity,
)

HEADER = (
    "Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,"
    "Closing Index Value,Points Change,Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield\n"
)


def _reference_load(root: Path, name_map_path: Path | None = None) -> pd.DataFrame:
    root = Path(root)
    name_map_path = name_map_path or (root / "Input" / "reference" / "index_name_map.csv")
    folders = [root / "Input" / "archive", root / "Input" / "archive" / "backfill" / "index", root / "Input" / "daily"]
    frames = []
    for folder in folders:
        if folder.exists():
            for p in sorted(folder.glob("ind_close_all_*.csv")):
                try:
                    frames.append(parse_ind_close_all(p))
                except Exception as exc:
                    print(f"Skipped {p.name}: {exc}")
    ma_paths = []
    for pattern_root, pattern in ((root / "Input" / "downloads", "*/MA*.csv"), (root / "Input" / "archive", "MA*.csv"), (root / "Input" / "daily", "MA*.csv")):
        if pattern_root.exists():
            ma_paths.extend(pattern_root.glob(pattern))
    ma_frames = []
    for path in sorted(set(ma_paths)):
        day = index_history._parse_ma_date(Path(path))
        if day is None:
            continue
        frame = parse_market_activity(path, day)
        if not frame.empty:
            ma_frames.append(frame)
    ma = (
        pd.concat(ma_frames, ignore_index=True).drop_duplicates(["trade_date", "index_name"], keep="last").sort_values(["trade_date", "index_name"]).reset_index(drop=True)
        if ma_frames else pd.DataFrame(columns=INDEX_COLUMNS)
    )
    if frames:
        close_all = pd.concat(frames, ignore_index=True)
        name_map = load_index_name_map(name_map_path)
        close_all["index_name"] = close_all["index_name"].map(lambda n: name_map.get(n, n))
        close_all = close_all.drop_duplicates(["trade_date", "index_name"], keep="last")
        if not ma.empty:
            ma = ma.copy()
            ma["trade_date"] = pd.to_datetime(ma["trade_date"]).dt.normalize()
            have = set(zip(close_all["trade_date"], close_all["index_name"]))
            ma = ma[[(d, n) not in have for d, n in zip(ma["trade_date"], ma["index_name"])]]
            close_all = pd.concat([close_all, ma], ignore_index=True)
    else:
        close_all = ma if not ma.empty else pd.DataFrame(columns=INDEX_COLUMNS)
    close_all["trade_date"] = pd.to_datetime(close_all["trade_date"], errors="coerce").dt.normalize()
    for col in [c for c in INDEX_COLUMNS if c not in ("trade_date", "index_name")] + EXTRA_INDEX_COLUMNS:
        if col in close_all.columns:
            close_all[col] = pd.to_numeric(close_all[col], errors="coerce")
    return close_all.sort_values(["trade_date", "index_name"]).reset_index(drop=True)


def _write_tree(root: Path) -> None:
    backfill = root / "Input" / "archive" / "backfill" / "index"
    daily = root / "Input" / "daily"
    archive = root / "Input" / "archive"
    downloads = root / "Input" / "downloads" / "25092026"
    for folder in (backfill, daily, downloads):
        folder.mkdir(parents=True, exist_ok=True)
    (backfill / "ind_close_all_24092026.csv").write_text(
        HEADER
        + "Nifty 50,24-09-2026,\"24,900.00\",25000.00,24800.00,25000.00,100.00,0.40,300000000,25000.5,22.1,3.5,1.2\n"
        + "NIFTY Midsmallcap 400,24-09-2026,19000.00,19100.00,18900.00,19100.00,-20.00,-0.10,-,-,-,-,-\n"
        + "Broken Row,24-09-2026,1,2,3,-,1,1,1,1,1,1,1\n"
    )
    # mis-dated April file (Index Date is MM-DD-YYYY) -> filename date wins
    (backfill / "ind_close_all_10042023.csv").write_text(
        HEADER + "Nifty 50,04-10-2023,17400.00,17450.00,17350.00,17430.00,10.00,0.06,1,1,1,1,1\n"
    )
    (backfill / "ind_close_all_04102023.csv").write_text(
        HEADER + "Nifty 50,04-10-2023,19100.00,19150.00,19050.00,19125.00,20.00,0.10,2,2,2,2,2\n"
    )
    # optional columns missing
    (backfill / "ind_close_all_23092026.csv").write_text(
        "Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,Points Change,Change(%)\n"
        "Nifty 50,23-09-2026,24800.00,24900.00,24700.00,24900.00,50.00,0.20\n"
    )
    (backfill / "ind_close_all_22092026.csv").write_text("")  # unreadable -> skipped
    (backfill / "ind_close_all_21092026.csv").write_text(HEADER)  # header only -> 0 rows warning
    (daily / "ind_close_all_25092026.csv").write_text(
        HEADER + "Nifty 50,25-09-2026,25000.00,25100.00,24900.00,25050.00,50.00,0.20,300000000,25000.5,22.1,3.5,1.2\n"
    )
    ma = (
        ",25-Sep-2026\n,INDEX,PREVIOUS CLOSE,OPEN,HIGH,LOW,CLOSE,GAIN/LOSS\n"
        ",Nifty 50,1,1,1,1,99999,1\n"
        ",NIFTY MIDSML 400,     19100.00,19100,19200,19000,19150,50\n"
        ",Nifty IT,200,198,201,195,196,-4\n"
        ",Zero Prev,0,1,1,1,1,1\n"
        ",Bad,x,1,1,1,1,1\n"
    )
    (downloads / "MA250926.csv").write_text(ma)
    (archive / "MA240926.csv").write_text(
        ",24-Sep-2026\n,INDEX,PREVIOUS CLOSE,OPEN,HIGH,LOW,CLOSE,GAIN/LOSS\n,Nifty IT,190,190,201,189,200,10\n,Nifty 50,1,1,1,1,1,1\n"
    )
    ref = root / "Input" / "reference"
    ref.mkdir(parents=True)
    (ref / "index_name_map.csv").write_text("source_name,canonical_name\nNIFTY Midsmallcap 400,NIFTY MIDSML 400\n")


@pytest.fixture(autouse=True)
def _fresh_cache():
    index_history.clear_index_history_cache()
    yield
    index_history.clear_index_history_cache()


def test_load_all_matches_reference_algorithm(tmp_path, capsys):
    _write_tree(tmp_path)
    expected = _reference_load(tmp_path)
    expected_out = capsys.readouterr().out
    actual = load_all_index_history(tmp_path)
    actual_out = capsys.readouterr().out
    pd.testing.assert_frame_equal(actual, expected)
    assert actual_out == expected_out
    assert "ind_close_all_10042023.csv" in actual_out and "Skipped ind_close_all_22092026.csv" in actual_out
    assert "ind_close_all_21092026.csv yielded 0 rows" in actual_out


def test_repeated_calls_hit_memo_and_return_independent_copies(tmp_path, monkeypatch):
    _write_tree(tmp_path)
    first = load_all_index_history(tmp_path)
    first.loc[:, "close_price"] = -1.0  # caller mutation must not leak into the cache

    def boom(*args, **kwargs):
        raise AssertionError("cache miss: inputs were re-parsed")

    monkeypatch.setattr(index_history, "_read_ind_close_all_raw", boom)
    monkeypatch.setattr(index_history, "_market_activity_records", boom)
    second = load_all_index_history(tmp_path)
    third = load_all_index_history(tmp_path)
    assert (second["close_price"] != -1.0).all()
    pd.testing.assert_frame_equal(second, third)
    assert second is not third


def test_memo_invalidates_when_an_input_file_changes(tmp_path):
    _write_tree(tmp_path)
    before = load_all_index_history(tmp_path)
    daily = tmp_path / "Input" / "daily"
    (daily / "ind_close_all_26092026.csv").write_text(
        HEADER + "Nifty 50,26-09-2026,25050.00,25200.00,25000.00,25150.00,100.00,0.40,1,1,1,1,1\n"
    )
    after = load_all_index_history(tmp_path)
    assert len(after) == len(before) + 1
    pd.testing.assert_frame_equal(after, _reference_load(tmp_path))

    (daily / "ind_close_all_26092026.csv").write_text(
        HEADER + "Nifty 50,26-09-2026,25050.00,125200.00,25000.00,125999.00,100949.00,403.80,1,1,1,1,1\n"
    )
    changed = load_all_index_history(tmp_path).set_index(["trade_date", "index_name"])
    assert changed.loc[(pd.Timestamp("2026-09-26"), "Nifty 50"), "close_price"] == 125999.0


def test_memo_invalidates_when_name_map_changes(tmp_path):
    _write_tree(tmp_path)
    load_all_index_history(tmp_path)
    (tmp_path / "Input" / "reference" / "index_name_map.csv").write_text("source_name,canonical_name\n")
    after = load_all_index_history(tmp_path)
    assert "NIFTY Midsmallcap 400" in set(after["index_name"])
    pd.testing.assert_frame_equal(after, _reference_load(tmp_path))


def test_scandir_listing_matches_pathlib_glob(tmp_path):
    _write_tree(tmp_path)
    (tmp_path / "Input" / "daily" / "IND_CLOSE_ALL_27092026.CSV").write_text(HEADER)  # case-insensitive like glob on Windows
    (tmp_path / "Input" / "daily" / "notes.txt").write_text("x")
    root = tmp_path
    folders = [root / "Input" / "archive", root / "Input" / "archive" / "backfill" / "index", root / "Input" / "daily"]
    expected_close_all = [p for f in folders for p in sorted(f.glob("ind_close_all_*.csv"))]
    assert [p for p, _s, _m in index_history._ind_close_all_entries(root)] == expected_close_all
    expected_ma = sorted(
        set((root / "Input" / "downloads").glob("*/MA*.csv"))
        | set((root / "Input" / "archive").glob("MA*.csv"))
        | set((root / "Input" / "daily").glob("MA*.csv"))
    )
    assert sorted(set(index_history._market_activity_paths(root))) == expected_ma


def test_ma_line_prefilter_matches_full_csv_parse(tmp_path):
    body = (
        ",25-Sep-2026\r\n"
        ", Traded Value (Rs. In Crores), 66507.28\r\n"
        ",INDEX,PREVIOUS CLOSE,OPEN,HIGH,LOW,CLOSE,GAIN/LOSS\r\n"
        ",Nifty 50,     23644.80,     23637.65,     23822.80,     23562.80,     23742.90,98.1\r\n"
        ",Split A,1,2,3\r,Split B,10,10,11,9,10.5,0.5\r\n"  # stray CR record break
        ",Short,1,2\r\n"
        ",Nifty IT,200,198,201,195,196,-4,extra,cols\n"
        ",Nifty Zero,0,1,1,1,1,1"
    )
    plain = tmp_path / "MA250926.csv"
    plain.write_text(body, newline="")
    quoted = tmp_path / "MA240926.csv"
    quoted.write_text(body + '\r\n,"Quoted, Name",1,1,1,1,2,1\r\n', newline="")
    import csv

    def reference(path):
        rows = []
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            for raw in csv.reader(handle):
                values = [str(v).strip() for v in raw]
                if len(values) < 8 or values[1].upper() in {"INDEX", ""}:
                    continue
                nums = [index_history._number(v) for v in values[2:8]]
                if any(v is None for v in nums):
                    continue
                rows.append(values[1])
        return rows

    for path in (plain, quoted):
        frame = parse_market_activity(path, pd.Timestamp("2026-09-25"))
        assert frame["index_name"].tolist() == reference(path)
    assert "Split B" in parse_market_activity(plain, pd.Timestamp("2026-09-25"))["index_name"].tolist()
    assert "Quoted, Name" in parse_market_activity(quoted, pd.Timestamp("2026-09-25"))["index_name"].tolist()
