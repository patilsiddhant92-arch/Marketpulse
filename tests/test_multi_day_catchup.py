"""Tests for smart multi-day gap detection, resilient archive downloads, and sequential catch-up."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch
from pathlib import Path
import pytest

from Scripts.daily_pipeline import get_missing_trading_dates, _is_session_staged
from Scripts.download_nse_reports import (
    ReportSpec,
    _write_auxiliary_fallback,
    validate_csv,
)


def test_get_missing_trading_dates_skips_weekends():
    # Friday to Tuesday: should return Monday and Tuesday, skipping Sat and Sun
    db_date = "2026-09-11"  # Friday
    target_date = "2026-09-15"  # Tuesday
    
    with patch("Scripts.daily_pipeline.session_available", return_value=True):
        missing = get_missing_trading_dates(db_date, target_date)
        
    dates_str = [d.strftime("%Y-%m-%d") for d in missing]
    assert "2026-09-12" not in dates_str  # Saturday skipped
    assert "2026-09-13" not in dates_str  # Sunday skipped
    assert dates_str == ["2026-09-14", "2026-09-15"]


def test_get_missing_trading_dates_skips_exchange_holidays():
    # Thursday to Monday: Friday is an exchange holiday (e.g. Oct 2 Gandhi Jayanti)
    db_date = "2026-10-01"  # Thursday
    target_date = "2026-10-05"  # Monday
    
    def mock_avail(session, dt):
        # 2026-10-02 is Friday holiday
        if dt.date() == date(2026, 10, 2):
            return False
        return True
        
    with patch("Scripts.daily_pipeline.session_available", side_effect=mock_avail):
        missing = get_missing_trading_dates(db_date, target_date)
        
    dates_str = [d.strftime("%Y-%m-%d") for d in missing]
    assert dates_str == ["2026-10-05"]


def test_get_missing_trading_dates_already_up_to_date():
    assert get_missing_trading_dates("2026-09-15", "2026-09-15") == []
    assert get_missing_trading_dates("2026-09-15", "2026-09-10") == []


def test_get_missing_trading_dates_recognizes_local_staged(tmp_path, monkeypatch):
    # If session is already staged in Input/downloads/DDMMYYYY, no probe is needed
    long_date = "14092026"
    staged_dir = tmp_path / "Input" / "downloads" / long_date
    staged_dir.mkdir(parents=True)
    bhav = staged_dir / f"sec_bhavdata_full_{long_date}.csv"
    bhav.write_text("SYMBOL,DATE1,CLOSE_PRICE\nTEST,14-Sep-2026,100\n", encoding="utf-8")
    
    monkeypatch.setattr("Scripts.daily_pipeline.ROOT_DIR", tmp_path)
    
    # Probing will raise if called
    with patch("Scripts.daily_pipeline.session_available", side_effect=RuntimeError("Should not be called!")):
        missing = get_missing_trading_dates("2026-09-11", "2026-09-14")
        
    assert [d.strftime("%Y-%m-%d") for d in missing] == ["2026-09-14"]


def test_resilient_auxiliary_fallback(tmp_path):
    # Test that fallback placeholders for non-critical archive files pass validate_csv
    specs = [
        ReportSpec("52-week high-low", "52w.csv", (), ("Symbol", "Series")),
        ReportSpec("price band", "band.csv", (), ("Symbol", "Series", "Band")),
        ReportSpec("PE", "pe.csv", (), ("SYMBOL",)),
        ReportSpec("market activity", "ma.csv", (), ()),
    ]
    for spec in specs:
        path = tmp_path / spec.output_name
        _write_auxiliary_fallback(path, spec)
        assert path.exists()
        validate_csv(path, spec.required_columns)


def test_is_session_staged(tmp_path):
    day = datetime(2026, 9, 14)
    session_dir = tmp_path / "14092026"
    assert not _is_session_staged(session_dir, day)
    
    session_dir.mkdir(parents=True)
    assert not _is_session_staged(session_dir, day)
    
    bhav = session_dir / "sec_bhavdata_full_14092026.csv"
    bhav.write_text("content", encoding="utf-8")
    assert not _is_session_staged(session_dir, day)
    
    manifest = session_dir / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    assert _is_session_staged(session_dir, day)
