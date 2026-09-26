from __future__ import annotations

import json
from datetime import date

import build_index_name_map
import run_archive_backfill
from run_archive_backfill import main, refresh_reference_files, summarize


class FakeResponse:
    def __init__(self, status_code: int, content: bytes):
        self.status_code = status_code
        self.content = content


class FakeSession:
    def __init__(self, symbolchange_response):
        self._symbolchange_response = symbolchange_response
        self.gets = []

    def get(self, url, **kw):
        self.gets.append(url)
        return self._symbolchange_response


# ---------------------------------------------------------------------------
# refresh_reference_files
# ---------------------------------------------------------------------------

def test_refresh_reference_files_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(run_archive_backfill, "refresh_holidays", lambda session, path: [])
    session = FakeSession(FakeResponse(200, b"OLD SYMBOL,NEW SYMBOL\nABC,XYZ\n"))
    result = refresh_reference_files(session, tmp_path)
    assert result == {"holidays": "ok", "symbolchange": "ok"}
    assert (tmp_path / "symbolchange.csv").read_bytes() == b"OLD SYMBOL,NEW SYMBOL\nABC,XYZ\n"


def test_refresh_reference_files_html_response_not_written(tmp_path, monkeypatch):
    monkeypatch.setattr(run_archive_backfill, "refresh_holidays", lambda session, path: [])
    session = FakeSession(FakeResponse(200, b"<html><body>blocked</body></html>"))
    result = refresh_reference_files(session, tmp_path)
    assert result["holidays"] == "ok"
    assert result["symbolchange"].startswith("failed:")
    assert not (tmp_path / "symbolchange.csv").exists()


def test_refresh_reference_files_holidays_failure_does_not_block_symbolchange(tmp_path, monkeypatch):
    def raise_holidays(session, path):
        raise RuntimeError("boom")

    monkeypatch.setattr(run_archive_backfill, "refresh_holidays", raise_holidays)
    session = FakeSession(FakeResponse(200, b"OLD SYMBOL,NEW SYMBOL\n"))
    result = refresh_reference_files(session, tmp_path)
    assert result["holidays"] == "failed: boom"
    assert result["symbolchange"] == "ok"
    assert (tmp_path / "symbolchange.csv").exists()


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------

def test_summarize():
    manifest = {
        ("2026-09-24", "bhav"): {"status": "ok"},
        ("2026-09-25", "bhav"): {"status": "ok"},
        ("2026-09-25", "index"): {"status": "not_published"},
        ("2026-09-24", "pr"): {"status": "error"},
    }
    holidays = {date(2026, 10, 2)}
    summary = summarize(manifest, holidays, date(2026, 9, 24), date(2026, 9, 27), [])
    assert summary["by_kind_status"]["bhav:ok"] == 2
    assert summary["first_last_ok"]["bhav"] == ["2026-09-24", "2026-09-25"]
    assert summary["calendar_reasons"] == {"session": 2, "weekend": 2}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def test_main_happy_path_calls_collaborators_in_order(tmp_path, monkeypatch):
    calls = []

    monkeypatch.setattr(run_archive_backfill, "make_session", lambda: calls.append("make_session") or "SESSION")
    monkeypatch.setattr(
        run_archive_backfill,
        "refresh_reference_files",
        lambda session, ref_dir: calls.append("refresh_reference_files") or {"holidays": "ok", "symbolchange": "ok"},
    )

    def fake_run_backfill(start, end, kinds, *, session, out_dir, **kw):
        calls.append("run_backfill")
        return {"ok": 1, "not_published": 0, "error": 0, "skipped": 0}

    monkeypatch.setattr(run_archive_backfill, "run_backfill", fake_run_backfill)
    monkeypatch.setattr(build_index_name_map, "main", lambda: calls.append("build_index_name_map.main") or 0)
    monkeypatch.setattr(run_archive_backfill, "BACKFILL_DIR", tmp_path)

    rc = main(["--from", "2026-09-24", "--to", "2026-09-27"])

    assert rc == 0
    assert calls == ["make_session", "refresh_reference_files", "run_backfill", "build_index_name_map.main"]
    assert (tmp_path / "last_run_summary.json").exists()
    summary = json.loads((tmp_path / "last_run_summary.json").read_text())
    assert "by_kind_status" in summary


def test_main_returns_2_when_backfill_has_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(run_archive_backfill, "make_session", lambda: "SESSION")
    monkeypatch.setattr(run_archive_backfill, "refresh_reference_files", lambda session, ref_dir: {})
    monkeypatch.setattr(
        run_archive_backfill,
        "run_backfill",
        lambda start, end, kinds, *, session, out_dir, **kw: {"ok": 1, "not_published": 0, "error": 3, "skipped": 0},
    )
    monkeypatch.setattr(build_index_name_map, "main", lambda: 0)
    monkeypatch.setattr(run_archive_backfill, "BACKFILL_DIR", tmp_path)

    rc = main(["--from", "2026-09-24", "--to", "2026-09-27"])
    assert rc == 2


def test_main_skip_flags_skip_reference_and_name_map(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(run_archive_backfill, "make_session", lambda: calls.append("make_session") or "SESSION")
    monkeypatch.setattr(
        run_archive_backfill,
        "refresh_reference_files",
        lambda session, ref_dir: calls.append("refresh_reference_files") or {},
    )
    monkeypatch.setattr(
        run_archive_backfill,
        "run_backfill",
        lambda start, end, kinds, *, session, out_dir, **kw: calls.append("run_backfill")
        or {"ok": 1, "not_published": 0, "error": 0, "skipped": 0},
    )
    monkeypatch.setattr(build_index_name_map, "main", lambda: calls.append("build_index_name_map.main") or 0)
    monkeypatch.setattr(run_archive_backfill, "BACKFILL_DIR", tmp_path)

    rc = main(["--from", "2026-09-24", "--to", "2026-09-27", "--skip-reference", "--skip-name-map"])

    assert rc == 0
    assert calls == ["make_session", "run_backfill"]
