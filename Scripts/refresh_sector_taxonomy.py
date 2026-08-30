"""Fill missing stocks_master sector/industry from screener.in, slowly.

Ports the Google Apps Script batch/retry/parser logic — not a scrape of
financials. Official NSE Input/static/sector.csv stays the source of truth;
this job only appends names that have no taxonomy yet (new listings).

Screener rate-limits and Cloudflare-blocks aggressive parallel fetches, so
each EOD run takes a small sequential batch and checkpoints skips/retries.
"""

from __future__ import annotations

import argparse
import csv
import html as html_lib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import quote

import duckdb
import pandas as pd

from config import DATABASE_DIR, DB_PATH, SECTOR_FILE

BATCH_SIZE = 10
MINI_DELAY_S = 1.5
RETRY_DELAY_S = 1.2
SEQUENTIAL_BACKOFF_S = (0.8, 1.6, 2.4)
STATE_PATH = DATABASE_DIR / "sector_taxonomy_state.json"
SCREENER_URL = "https://www.screener.in/company/{symbol}/"
COLUMNS = ("symbol", "broad_sector", "sector", "broad_industry", "industry")
SUB_BLOCK = re.compile(r'<p class="sub">([\s\S]*?)</p>', re.IGNORECASE)
ANCHOR = re.compile(r"<a[^>]*>(.*?)</a>", re.IGNORECASE)
TAG = re.compile(r"<[^>]+>")

FetchFn = Callable[[str], "FetchResult"]
SleepFn = Callable[[float], None]


@dataclass(frozen=True)
class FetchResult:
    status_code: int
    text: str
    error: str = ""


@dataclass(frozen=True)
class SymbolOutcome:
    symbol: str
    status: str
    hierarchy: tuple[str, str, str, str] | None = None
    detail: str = ""


def extract_hierarchy_from_html(raw_html: str) -> list[str]:
    """Same parser as the Apps Script: links inside the first <p class="sub">."""
    if not raw_html:
        return []
    if "Just a moment" in raw_html or "cf-browser-verification" in raw_html:
        return []
    match = SUB_BLOCK.search(raw_html)
    if not match:
        return []
    parts: list[str] = []
    for anchor in ANCHOR.finditer(match.group(1)):
        text = TAG.sub("", anchor.group(1))
        text = html_lib.unescape(text).strip()
        if text:
            parts.append(text)
    return parts


def map_hierarchy(parts: list[str]) -> tuple[str, str, str, str] | None:
    clean = [p for p in parts if p and p.casefold() != "not found"]
    if not clean:
        return None
    while len(clean) < 4:
        clean.append(clean[-1])
    return (clean[0], clean[1], clean[2], clean[3])


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"skip": {}, "retry": {}, "filled": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"skip": {}, "retry": {}, "filled": []}
    payload.setdefault("skip", {})
    payload.setdefault("retry", {})
    payload.setdefault("filled", [])
    return payload


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def list_missing_symbols(db_path: Path) -> list[str]:
    with duckdb.connect(str(db_path), read_only=True) as db:
        rows = db.execute(
            """
            SELECT symbol
            FROM stocks_master
            WHERE coalesce(nullif(trim(cast(sector AS VARCHAR)), ''), '') = ''
               OR coalesce(nullif(trim(cast(industry AS VARCHAR)), ''), '') = ''
               OR coalesce(nullif(trim(cast(broad_sector AS VARCHAR)), ''), '') = ''
               OR coalesce(nullif(trim(cast(broad_industry AS VARCHAR)), ''), '') = ''
            ORDER BY coalesce(market_cap_cr, 0) DESC, symbol
            """
        ).fetchall()
    return [str(row[0]).strip().upper() for row in rows if row and row[0]]


def _retry_ready(entry: dict, now: datetime) -> bool:
    nxt = str(entry.get("next_ok_at") or "")
    if not nxt:
        return True
    try:
        ready = datetime.fromisoformat(nxt)
    except ValueError:
        return True
    if ready.tzinfo is None:
        ready = ready.replace(tzinfo=timezone.utc)
    return now >= ready


def select_batch(missing: list[str], state: dict, *, batch_size: int, retry_failed: bool) -> list[str]:
    skip = {str(k).upper() for k in (state.get("skip") or {})}
    retry = {str(k).upper(): v for k, v in (state.get("retry") or {}).items()}
    now = datetime.now(timezone.utc)
    chosen: list[str] = []
    if retry_failed:
        for symbol in missing:
            if symbol in skip:
                continue
            entry = retry.get(symbol)
            if entry and len(chosen) < batch_size:
                chosen.append(symbol)
        return chosen
    for symbol in missing:
        if symbol in skip or len(chosen) >= batch_size:
            continue
        entry = retry.get(symbol)
        if entry and not _retry_ready(entry, now):
            continue
        chosen.append(symbol)
    return chosen


def classify_response(result: FetchResult) -> str:
    if result.error and result.status_code == 0:
        return "RETRY"
    code = int(result.status_code)
    text = result.text or ""
    if code == 404:
        return "Invalid Symbol"
    if code == 200:
        if "Just a moment" in text or "cf-browser-verification" in text:
            return "CF_Block"
        return "OK"
    if code in {403, 429, 503}:
        return "RETRY"
    return "RETRY"


def default_fetch(symbol: str) -> FetchResult:
    from curl_cffi import requests

    url = SCREENER_URL.format(symbol=quote(symbol, safe="-"))
    last_error = ""
    for attempt, pause in enumerate(SEQUENTIAL_BACKOFF_S):
        if attempt:
            time.sleep(pause)
        try:
            session = requests.Session(impersonate="chrome124")
            session.headers.update(
                {
                    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "accept-language": "en-US,en;q=0.5",
                    "referer": "https://www.screener.in/",
                }
            )
            response = session.get(url, timeout=30)
            return FetchResult(int(response.status_code), response.text or "")
        except Exception as exc:
            last_error = str(exc)
    return FetchResult(0, "", last_error)


def upsert_sector_csv(sector_file: Path, rows: list[dict[str, str]]) -> int:
    existing_symbols: set[str] = set()
    if sector_file.exists():
        current = pd.read_csv(
            sector_file,
            header=None,
            names=list(COLUMNS),
            dtype=str,
        )
        current["symbol"] = current["symbol"].fillna("").astype(str).str.strip().str.upper()
        existing_symbols = set(current["symbol"])
    fresh = [row for row in rows if row["symbol"] not in existing_symbols]
    if not fresh:
        return 0
    sector_file.parent.mkdir(parents=True, exist_ok=True)
    with sector_file.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        for row in fresh:
            writer.writerow([row[col] for col in COLUMNS])
    return len(fresh)


def update_stocks_master(db_path: Path, rows: list[dict[str, str]]) -> int:
    if not rows:
        return 0
    updated = 0
    with duckdb.connect(str(db_path)) as db:
        for row in rows:
            db.execute(
                """
                UPDATE stocks_master
                SET broad_sector = ?,
                    sector = ?,
                    broad_industry = ?,
                    industry = ?
                WHERE symbol = ?
                  AND (
                    coalesce(nullif(trim(cast(sector AS VARCHAR)), ''), '') = ''
                    OR coalesce(nullif(trim(cast(industry AS VARCHAR)), ''), '') = ''
                    OR coalesce(nullif(trim(cast(broad_sector AS VARCHAR)), ''), '') = ''
                    OR coalesce(nullif(trim(cast(broad_industry AS VARCHAR)), ''), '') = ''
                  )
                """,
                [
                    row["broad_sector"],
                    row["sector"],
                    row["broad_industry"],
                    row["industry"],
                    row["symbol"],
                ],
            )
            updated += 1
    return updated


def _mark_retry(state: dict, symbol: str, status: str) -> None:
    retry = state.setdefault("retry", {})
    prior = retry.get(symbol) or {}
    attempts = int(prior.get("attempts") or 0) + 1
    wait_s = min(3600, 15 * (2 ** min(attempts, 6)))
    nxt = datetime.now(timezone.utc).timestamp() + wait_s
    retry[symbol] = {
        "status": status,
        "attempts": attempts,
        "next_ok_at": datetime.fromtimestamp(nxt, tz=timezone.utc).isoformat(timespec="seconds"),
    }


def process_symbol(symbol: str, fetch_one: FetchFn) -> SymbolOutcome:
    result = fetch_one(symbol)
    status = classify_response(result)
    if status != "OK":
        return SymbolOutcome(symbol, status, detail=result.error or str(result.status_code))
    mapped = map_hierarchy(extract_hierarchy_from_html(result.text))
    if mapped is None:
        return SymbolOutcome(symbol, "RETRY", detail="no hierarchy")
    return SymbolOutcome(symbol, "OK", hierarchy=mapped)


def run_batch(
    *,
    db_path: Path | None = None,
    sector_file: Path | None = None,
    state_path: Path | None = None,
    batch_size: int = BATCH_SIZE,
    mini_delay_s: float = MINI_DELAY_S,
    fetch_one: FetchFn | None = None,
    sleep: SleepFn = time.sleep,
    retry_failed: bool = False,
) -> dict:
    db_path = Path(db_path or DB_PATH)
    sector_file = Path(sector_file or SECTOR_FILE)
    state_path = Path(state_path or STATE_PATH)
    fetch_one = fetch_one or default_fetch
    state = load_state(state_path)
    missing = list_missing_symbols(db_path)
    batch = select_batch(missing, state, batch_size=max(1, batch_size), retry_failed=retry_failed)
    summary = {
        "missing_before": len(missing),
        "attempted": len(batch),
        "filled": 0,
        "retried": 0,
        "invalid": 0,
        "symbols": batch[:],
        "message": "",
    }
    if not batch:
        summary["message"] = "No missing sector/industry names due this run."
        save_state(state_path, state)
        return summary

    fills: list[dict[str, str]] = []
    for index, symbol in enumerate(batch):
        if index:
            sleep(mini_delay_s)
        outcome = process_symbol(symbol, fetch_one)
        if outcome.status == "OK" and outcome.hierarchy:
            fills.append(
                {
                    "symbol": symbol,
                    "broad_sector": outcome.hierarchy[0],
                    "sector": outcome.hierarchy[1],
                    "broad_industry": outcome.hierarchy[2],
                    "industry": outcome.hierarchy[3],
                }
            )
            state.setdefault("retry", {}).pop(symbol, None)
            if symbol not in state.setdefault("filled", []):
                state["filled"].append(symbol)
            print(f"{symbol}: {outcome.hierarchy[0]} / {outcome.hierarchy[1]}")
            continue
        if outcome.status == "Invalid Symbol":
            state.setdefault("skip", {})[symbol] = "invalid_symbol"
            state.setdefault("retry", {}).pop(symbol, None)
            summary["invalid"] += 1
            print(f"{symbol}: invalid (404)")
            continue
        _mark_retry(state, symbol, outcome.status)
        summary["retried"] += 1
        print(f"{symbol}: {outcome.status} — will retry later")
        if outcome.status in {"RETRY", "CF_Block"}:
            break

    if fills:
        csv_n = upsert_sector_csv(sector_file, fills)
        try:
            update_stocks_master(db_path, fills)
        except Exception as exc:
            print(f"stocks_master update deferred (csv written): {exc}")
        summary["filled"] = csv_n or len(fills)

    remaining = max(0, summary["missing_before"] - summary["filled"])
    summary["message"] = (
        f"Filled {summary['filled']} · retry {summary['retried']} · "
        f"invalid {summary['invalid']} · still missing ~{remaining}."
    )
    save_state(state_path, state)
    print(summary["message"])
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fill missing NSE sector/industry from screener.in in small rate-limited batches."
    )
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--retry", action="store_true", help="Only retry CF_Block / RETRY symbols.")
    parser.add_argument("--delay", type=float, default=MINI_DELAY_S, help="Seconds between symbols.")
    args = parser.parse_args()
    if os.environ.get("MP_SKIP_SECTOR_TAXONOMY", "").strip() in {"1", "true", "yes"}:
        print("MP_SKIP_SECTOR_TAXONOMY=1 — skipped.")
        return 0
    run_batch(batch_size=args.batch_size, mini_delay_s=max(0.0, args.delay), retry_failed=args.retry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
