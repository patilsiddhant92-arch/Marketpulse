from __future__ import annotations

from pathlib import Path

import pandas as pd

import append_database
import config


def _touch(folder: Path, ddmmyyyy: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"sec_bhavdata_full_{ddmmyyyy}.csv"
    path.write_text("stub")
    return path


def _setup(monkeypatch, tmp_path, session_by_file: dict[str, str]):
    """Fake bhavcopies; `session_by_file` maps filename -> the DATE1 session inside it."""
    daily, archive, inputs = tmp_path / "daily", tmp_path / "archive", tmp_path / "input"
    monkeypatch.setattr(append_database, "DAILY_DIR", daily)
    monkeypatch.setattr(config, "ARCHIVE_DIR", archive)
    monkeypatch.setattr(config, "INPUT_DIR", inputs)
    parsed: list[str] = []

    def fake_read(path, universe):
        parsed.append(path.name)
        return pd.DataFrame({"symbol": ["AAA"], "trade_date": [pd.Timestamp(session_by_file[path.name])]})

    monkeypatch.setattr(append_database, "read_bhavcopy", fake_read)
    return daily, archive, inputs, parsed


def test_skips_files_dated_well_before_db_max(monkeypatch, tmp_path):
    names = {f"sec_bhavdata_full_{d}.csv": s for d, s in [
        ("01082026", "2026-08-01"), ("02092026", "2026-09-02"), ("24092026", "2026-09-24"), ("25092026", "2026-09-25")]}
    daily, archive, _, parsed = _setup(monkeypatch, tmp_path, names)
    for d in ("01082026", "02092026", "24092026"):
        _touch(archive, d)
    _touch(daily, "25092026")

    out = append_database._new_daily_prices({"AAA"}, pd.Timestamp("2026-09-24"))

    assert list(out["trade_date"]) == [pd.Timestamp("2026-09-25")]
    assert "sec_bhavdata_full_01082026.csv" not in parsed
    assert "sec_bhavdata_full_02092026.csv" not in parsed


def test_still_reads_recent_files_whose_session_differs_from_filename(monkeypatch, tmp_path):
    # Muhurat-style file: named for the next day but holding a newer-than-DB session.
    names = {"sec_bhavdata_full_05112021.csv": "2021-11-04", "sec_bhavdata_full_03112021.csv": "2021-11-03"}
    _, archive, _, parsed = _setup(monkeypatch, tmp_path, names)
    _touch(archive, "03112021")
    _touch(archive, "05112021")

    out = append_database._new_daily_prices({"AAA"}, pd.Timestamp("2021-11-03"))

    assert list(out["trade_date"]) == [pd.Timestamp("2021-11-04")]


def test_parses_files_without_a_filename_date(monkeypatch, tmp_path):
    names = {"sec_bhavdata_full_latest.csv": "2026-09-25"}
    daily, _, _, parsed = _setup(monkeypatch, tmp_path, names)
    daily.mkdir(parents=True)
    (daily / "sec_bhavdata_full_latest.csv").write_text("stub")

    out = append_database._new_daily_prices({"AAA"}, pd.Timestamp("2026-09-24"))

    assert parsed == ["sec_bhavdata_full_latest.csv"]
    assert len(out) == 1
