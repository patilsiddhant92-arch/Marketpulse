"""NSE archive URL builders and a polite, resilient fetch for one-off backfills."""
from __future__ import annotations

import random
import time
from datetime import date
from typing import Callable, NamedTuple

NSE_ARCHIVES = "https://nsearchives.nseindia.com"


def _ddmmyyyy(d: date) -> str:
    return d.strftime("%d%m%Y")


def _ddmmyy(d: date) -> str:
    return d.strftime("%d%m%y")


KINDS: dict[str, Callable[[date], str]] = {
    "bhav": lambda d: f"{NSE_ARCHIVES}/products/content/sec_bhavdata_full_{_ddmmyyyy(d)}.csv",
    "index": lambda d: f"{NSE_ARCHIVES}/content/indices/ind_close_all_{_ddmmyyyy(d)}.csv",
    "pr": lambda d: f"{NSE_ARCHIVES}/archives/equities/bhavcopy/pr/PR{_ddmmyy(d)}.zip",
}

_FILENAMES: dict[str, Callable[[date], str]] = {
    "bhav": lambda d: f"sec_bhavdata_full_{_ddmmyyyy(d)}.csv",
    "index": lambda d: f"ind_close_all_{_ddmmyyyy(d)}.csv",
    "pr": lambda d: f"PR{_ddmmyy(d)}.zip",
}


class FetchResult(NamedTuple):
    status: str  # "ok" | "not_published" | "error"
    data: bytes | None
    detail: str


def archive_filename(kind: str, day: date) -> str:
    return _FILENAMES[kind](day)


def _looks_like_html(data: bytes) -> bool:
    head = data[:500].lower()
    return b"<html" in head or b"<!doctype html" in head


def fetch(session, url: str, *, retries: int = 3, base_delay: float = 2.0,
          sleep: Callable[[float], None] = time.sleep) -> FetchResult:
    """404 means NSE did not publish the file (holiday / not yet archived): never retried."""
    last = "no attempt"
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=45)
            if resp.status_code == 404:
                return FetchResult("not_published", None, "HTTP 404")
            if resp.status_code == 200 and resp.content and not _looks_like_html(resp.content):
                return FetchResult("ok", resp.content, "HTTP 200")
            last = f"HTTP {resp.status_code}" + (" (html)" if resp.content and _looks_like_html(resp.content) else "")
        except Exception as exc:  # network errors are transient
            last = f"{type(exc).__name__}: {exc}"
        if attempt < retries - 1:
            sleep(base_delay * (2 ** attempt) + random.uniform(0, 1))
    return FetchResult("error", None, last)
