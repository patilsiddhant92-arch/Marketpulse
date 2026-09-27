from __future__ import annotations

from datetime import date

import nse_archive
from nse_archive import FetchResult, KINDS, archive_filename, fetch


class FakeResponse:
    def __init__(self, status_code: int, content: bytes):
        self.status_code = status_code
        self.content = content


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, url, timeout=None, headers=None):
        self.calls += 1
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_urls_and_filenames():
    d = date(2021, 9, 24)
    assert KINDS["bhav"](d) == "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_24092021.csv"
    assert KINDS["index"](d) == "https://nsearchives.nseindia.com/content/indices/ind_close_all_24092021.csv"
    assert KINDS["pr"](d) == "https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR240921.zip"
    assert archive_filename("bhav", d) == "sec_bhavdata_full_24092021.csv"
    assert archive_filename("index", d) == "ind_close_all_24092021.csv"
    assert archive_filename("pr", d) == "PR240921.zip"


def test_ok_on_first_try():
    s = FakeSession([FakeResponse(200, b"SYMBOL, SERIES\nA, EQ\n")])
    r = fetch(s, "u", sleep=lambda _: None)
    assert r.status == "ok" and r.data.startswith(b"SYMBOL") and s.calls == 1


def test_404_is_not_published_without_retry():
    s = FakeSession([FakeResponse(404, b"<!DOCTYPE html>")])
    r = fetch(s, "u", sleep=lambda _: None)
    assert r.status == "not_published" and s.calls == 1


def test_html_200_and_503_are_retried_then_error():
    s = FakeSession([FakeResponse(503, b"x"), FakeResponse(200, b"<html>blocked</html>"), TimeoutError("t")])
    r = fetch(s, "u", retries=3, sleep=lambda _: None)
    assert r.status == "error" and s.calls == 3


def test_recovers_after_transient_failure():
    s = FakeSession([FakeResponse(503, b"x"), FakeResponse(200, b"PK\x03\x04zip")])
    r = fetch(s, "u", sleep=lambda _: None)
    assert r.status == "ok" and s.calls == 2
