from __future__ import annotations

import json
from datetime import date

import backfill_archives
from backfill_archives import load_manifest, run_backfill
from nse_archive import FetchResult


def fake_fetch_factory(table):
    calls = []

    def fake_fetch(session, url, **kw):
        calls.append(url)
        return table.get(url, FetchResult("not_published", None, "HTTP 404"))

    return fake_fetch, calls


def test_downloads_writes_files_and_manifest(tmp_path, monkeypatch):
    d = date(2021, 9, 24)
    url = backfill_archives.KINDS["bhav"](d)
    fake, calls = fake_fetch_factory({url: FetchResult("ok", b"SYMBOL, SERIES\n", "HTTP 200")})
    monkeypatch.setattr(backfill_archives, "fetch", fake)
    counts = run_backfill(d, d, ["bhav", "index"], session=None, out_dir=tmp_path, sleep=lambda _: None)
    assert counts == {"ok": 1, "not_published": 1, "pending": 0, "error": 0, "skipped": 0, "aborted": 0}
    assert (tmp_path / "bhav" / "sec_bhavdata_full_24092021.csv").read_bytes() == b"SYMBOL, SERIES\n"
    lines = [json.loads(l) for l in (tmp_path / "manifest.jsonl").read_text().splitlines()]
    assert {(l["kind"], l["status"]) for l in lines} == {("bhav", "ok"), ("index", "not_published")}
    assert len(lines[0]["sha256"]) == 64 or lines[0]["status"] != "ok"


def test_rerun_skips_ok_and_not_published_but_retries_errors(tmp_path, monkeypatch):
    d = date(2021, 9, 24)
    first = {backfill_archives.KINDS["bhav"](d): FetchResult("error", None, "HTTP 503")}
    fake, _ = fake_fetch_factory(first)
    monkeypatch.setattr(backfill_archives, "fetch", fake)
    run_backfill(d, d, ["bhav", "index"], session=None, out_dir=tmp_path, sleep=lambda _: None)
    fake2, calls2 = fake_fetch_factory({backfill_archives.KINDS["bhav"](d): FetchResult("ok", b"x", "HTTP 200")})
    monkeypatch.setattr(backfill_archives, "fetch", fake2)
    counts = run_backfill(d, d, ["bhav", "index"], session=None, out_dir=tmp_path, sleep=lambda _: None)
    assert calls2 == [backfill_archives.KINDS["bhav"](d)]  # index was not_published → skipped
    assert counts["ok"] == 1 and counts["skipped"] == 1
    latest = load_manifest(tmp_path / "manifest.jsonl")
    assert latest[("2021-09-24", "bhav")]["status"] == "ok"


def test_skip_weekends(tmp_path, monkeypatch):
    fake, calls = fake_fetch_factory({})
    monkeypatch.setattr(backfill_archives, "fetch", fake)
    run_backfill(date(2021, 9, 25), date(2021, 9, 26), ["bhav"], session=None, out_dir=tmp_path,
                 sleep=lambda _: None, skip_weekends=True)
    assert calls == []


# ---------------------------------------------------------------------------
# I2: abort after too many consecutive errors
# ---------------------------------------------------------------------------

def test_run_backfill_aborts_after_max_consecutive_errors(tmp_path, monkeypatch):
    def always_error(session, url, **kw):
        return FetchResult("error", None, "HTTP 503")

    monkeypatch.setattr(backfill_archives, "fetch", always_error)
    counts = run_backfill(date(2021, 1, 1), date(2021, 6, 30), ["bhav"], session=None, out_dir=tmp_path,
                          sleep=lambda _: None, max_consecutive_errors=25)
    assert counts["aborted"] == 1
    assert counts["error"] == 25
    lines = (tmp_path / "manifest.jsonl").read_text().splitlines()
    assert len(lines) == 25


def test_run_backfill_does_not_abort_when_errors_are_not_consecutive(tmp_path, monkeypatch):
    calls = {"n": 0}

    def alternating(session, url, **kw):
        calls["n"] += 1
        if calls["n"] % 2 == 0:
            return FetchResult("ok", b"x", "HTTP 200")
        return FetchResult("error", None, "HTTP 503")

    monkeypatch.setattr(backfill_archives, "fetch", alternating)
    counts = run_backfill(date(2021, 1, 1), date(2021, 1, 31), ["bhav"], session=None, out_dir=tmp_path,
                          sleep=lambda _: None, max_consecutive_errors=5)
    assert counts["aborted"] == 0


def test_main_returns_2_when_aborted(tmp_path, monkeypatch):
    monkeypatch.setattr(backfill_archives, "BACKFILL_DIR", tmp_path)
    monkeypatch.setattr(backfill_archives, "run_backfill",
                        lambda *a, **kw: {"ok": 0, "not_published": 0, "pending": 0, "error": 0, "skipped": 0, "aborted": 1})
    import download_nse_reports
    monkeypatch.setattr(download_nse_reports, "make_session", lambda: None)
    rc = backfill_archives.main(["--from", "2021-01-01", "--to", "2021-01-02"])
    assert rc == 2


# ---------------------------------------------------------------------------
# I3: a 404 on a recent weekday is "pending" (retried), not final
# ---------------------------------------------------------------------------

def test_recent_weekday_404_is_pending_and_retried_next_run(tmp_path, monkeypatch):
    today = date(2026, 9, 26)  # Saturday
    day = date(2026, 9, 25)    # Friday, 1 day before today
    url = backfill_archives.KINDS["bhav"](day)
    fake, calls = fake_fetch_factory({url: FetchResult("not_published", None, "HTTP 404")})
    monkeypatch.setattr(backfill_archives, "fetch", fake)

    counts = run_backfill(day, day, ["bhav"], session=None, out_dir=tmp_path, sleep=lambda _: None, today=today)
    assert counts["pending"] == 1
    assert counts["not_published"] == 0
    latest = load_manifest(tmp_path / "manifest.jsonl")
    assert latest[(day.isoformat(), "bhav")]["status"] == "pending"

    # Retried on the next run because "pending" is not a FINAL status.
    fake2, calls2 = fake_fetch_factory({url: FetchResult("ok", b"x", "HTTP 200")})
    monkeypatch.setattr(backfill_archives, "fetch", fake2)
    counts2 = run_backfill(day, day, ["bhav"], session=None, out_dir=tmp_path, sleep=lambda _: None, today=today)
    assert calls2 == [url]
    assert counts2["ok"] == 1


def test_old_weekday_404_is_not_published_and_skipped_next_run(tmp_path, monkeypatch):
    today = date(2026, 9, 26)
    day = date(2026, 9, 16)  # Wednesday, 10 days before today
    url = backfill_archives.KINDS["bhav"](day)
    fake, calls = fake_fetch_factory({url: FetchResult("not_published", None, "HTTP 404")})
    monkeypatch.setattr(backfill_archives, "fetch", fake)

    counts = run_backfill(day, day, ["bhav"], session=None, out_dir=tmp_path, sleep=lambda _: None, today=today)
    assert counts["not_published"] == 1
    assert counts["pending"] == 0

    # Not retried on the next run because "not_published" is FINAL.
    fake2, calls2 = fake_fetch_factory({url: FetchResult("ok", b"x", "HTTP 200")})
    monkeypatch.setattr(backfill_archives, "fetch", fake2)
    counts2 = run_backfill(day, day, ["bhav"], session=None, out_dir=tmp_path, sleep=lambda _: None, today=today)
    assert calls2 == []
    assert counts2["skipped"] == 1


# ---------------------------------------------------------------------------
# M3: a truncated last manifest line is skipped, not fatal
# ---------------------------------------------------------------------------

def test_load_manifest_skips_truncated_last_line(tmp_path):
    manifest_path = tmp_path / "manifest.jsonl"
    good = json.dumps({"date": "2021-09-24", "kind": "bhav", "status": "ok"})
    manifest_path.write_text(good + "\n" + '{"date": "2021-09-25", "kind": "bhav", "stat')
    latest = load_manifest(manifest_path)
    assert latest == {("2021-09-24", "bhav"): {"date": "2021-09-24", "kind": "bhav", "status": "ok"}}
