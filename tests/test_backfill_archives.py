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
    assert counts == {"ok": 1, "not_published": 1, "error": 0, "skipped": 0}
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
