"""
MarketPulse end-of-day automation.

Runs without prompts:
  1) Download latest published NSE session (--auto)
  2) Append database (skip full rebuild)
  3) Telegram BUY deals (if configured)
  4) Write Database/status.json + Logs/pipeline_*.log

Intended for Windows Task Scheduler at 20:00 IST.

If a run fails (NSE not fully published, network blip, partial download),
retries after a wait (default 10 minutes, up to 3 attempts).
That is why Aug-6 style mid-download failures can recover at 20:10 / 20:20.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from io import StringIO
from pathlib import Path

import duckdb
import pandas as pd

from config import DAILY_DIR, DATABASE_DIR, DB_PATH, LOGS_DIR, ROOT_DIR
from download_nse_reports import parse_date, run as download_run, resolve_auto_date
from decision_pipeline import process_accepted_session

STATUS_PATH = DATABASE_DIR / "status.json"
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_WAIT_MINUTES = 10


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _db_max_trade_date() -> str | None:
    if not DB_PATH.exists():
        return None
    try:
        with duckdb.connect(str(DB_PATH), read_only=True) as con:
            value = con.execute("SELECT max(trade_date) FROM prices_daily").fetchone()[0]
        if value is None:
            return None
        return pd.to_datetime(value).date().isoformat()
    except Exception:
        return None


def _daily_bhav_date() -> str | None:
    if not DAILY_DIR.exists():
        return None
    files = sorted(DAILY_DIR.glob("sec_bhavdata_full_*.csv"))
    if not files:
        return None
    name = files[-1].name
    try:
        day = parse_date(name[len("sec_bhavdata_full_") : name.rfind(".")])
        return day.date().isoformat()
    except Exception:
        return None


def _write_status(payload: dict) -> None:
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _run_append() -> dict:
    """Call append_database.main logic; return summary dict."""
    # Import here so download-only mode is lighter if append deps fail later
    from append_database import _load_table, _new_daily_prices
    from build_database import (
        build_breadth_daily,
        build_enrichment,
        build_master,
        build_sector_rotation,
        calc_indicators,
        enrich_deals,
        make_screener_results,
        read_52_week,
        read_all_deals,
        read_equity_symbols,
        read_market_cap,
        read_pe,
        read_price_band,
        read_sector,
        write_database,
    )
    import shutil

    if not DB_PATH.exists():
        print("No database found — running full rebuild...")
        from build_database import main as full_build

        old_argv = sys.argv
        try:
            sys.argv = [old_argv[0]]
            full_build()
        finally:
            sys.argv = old_argv
        return {"action": "full_rebuild", "message": "Created database from scratch."}

    equity = read_equity_symbols()
    universe = set(equity["symbol"])
    existing_prices = _load_table("prices_daily")
    latest_date = pd.to_datetime(existing_prices["trade_date"]).max()
    new_prices = _new_daily_prices(universe, latest_date)
    if new_prices.empty:
        msg = f"No new bhavcopy rows after {latest_date.date()}. Database unchanged."
        print(msg)
        return {
            "action": "noop",
            "message": msg,
            "db_date": latest_date.date().isoformat(),
        }

    print(
        f"Appending {len(new_prices):,} price rows "
        f"from {new_prices['trade_date'].min().date()} to {new_prices['trade_date'].max().date()}."
    )
    prices = pd.concat([existing_prices, new_prices], ignore_index=True)
    prices["trade_date"] = pd.to_datetime(prices["trade_date"])
    prices = prices.sort_values(["symbol", "trade_date"]).drop_duplicates(
        ["symbol", "trade_date"], keep="last"
    )

    from reference_history import load_reference_history

    sector = read_sector()
    mcap = read_market_cap()
    bands = read_price_band()
    pe = read_pe()
    high52 = read_52_week()
    enrichment = build_enrichment(mcap, bands, pe, high52, pd.DataFrame(), pd.DataFrame())
    master = build_master(equity, sector, prices, mcap, bands, pe)
    # Same path as append_database: date-keyed 52W/mcap/PE history (not latest-only paint)
    reference_history = load_reference_history(ROOT_DIR)
    indicators = calc_indicators(
        prices, reference_history if not reference_history.empty else enrichment
    )
    deals_raw = read_all_deals()
    deals = enrich_deals(deals_raw, prices, indicators, master)
    latest_deals = deals[deals["trade_date"] == deals["trade_date"].max()] if not deals.empty else deals
    enrichment = build_enrichment(mcap, bands, pe, high52, latest_deals, pd.DataFrame())
    breadth_daily = build_breadth_daily(indicators)
    sector_rotation = build_sector_rotation(indicators, master)
    screener_results = make_screener_results(indicators, master, deals, sector_rotation)

    backup = DB_PATH.with_suffix(".preappend.backup.duckdb")
    shutil.copy2(DB_PATH, backup)
    write_database(
        prices, master, enrichment, indicators, deals, breadth_daily, sector_rotation, screener_results
    )
    new_max = pd.to_datetime(prices["trade_date"]).max().date().isoformat()
    msg = f"Append complete through {new_max}. Backup: {backup.name}"
    print(msg)
    return {
        "action": "append",
        "message": msg,
        "db_date": new_max,
        "new_rows": int(len(new_prices)),
        "backup": str(backup),
    }


def run_pipeline(
    *,
    skip_download: bool = False,
    skip_append: bool = False,
    skip_telegram: bool = False,
    date: datetime | None = None,
    lookback: int = 7,
) -> int:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"pipeline_{stamp}.log"
    status: dict = {
        "started_at": _now_iso(),
        "finished_at": None,
        "ok": False,
        "db_date_before": _db_max_trade_date(),
        "db_date_after": None,
        "download_date": None,
        "daily_bhav_date": None,
        "steps": [],
        "message": "",
        "error": None,
        "log_file": str(log_path),
    }

    buffer = StringIO()
    exit_code = 1
    try:
        with redirect_stdout(buffer), redirect_stderr(buffer):
            print(f"MarketPulse daily pipeline started at {status['started_at']}")
            print(f"Root: {ROOT_DIR}")
            print(f"DB before: {status['db_date_before']}")

            # --- Download ---
            if not skip_download:
                try:
                    day = date if date is not None else resolve_auto_date(lookback_days=lookback)
                    status["download_date"] = day.date().isoformat()
                    # If DB already has this session, still refresh daily files (refs/deals)
                    # but append will no-op — that is OK.
                    rc = download_run(day, dry_run=False)
                    if rc != 0:
                        raise RuntimeError(f"Download returned code {rc}")
                    status["steps"].append({"step": "download", "ok": True, "date": status["download_date"]})
                    print("Download step OK")
                except Exception as exc:
                    status["steps"].append({"step": "download", "ok": False, "error": str(exc)})
                    raise
            else:
                status["steps"].append({"step": "download", "ok": True, "skipped": True})
                print("Download skipped")

            status["daily_bhav_date"] = _daily_bhav_date()

            # --- Append ---
            if not skip_append:
                try:
                    append_result = _run_append()
                    status["steps"].append({"step": "append", "ok": True, **append_result})
                except Exception as exc:
                    status["steps"].append({"step": "append", "ok": False, "error": str(exc)})
                    raise
            else:
                status["steps"].append({"step": "append", "ok": True, "skipped": True})
                print("Append skipped")

            # --- PR reports + focused-v2 decision snapshot ---
            if not skip_append:
                decision_text = status.get("download_date") or status.get("daily_bhav_date")
                if decision_text:
                    decision_day = datetime.fromisoformat(str(decision_text)).date()
                    session_dir = ROOT_DIR / "Input" / "downloads" / decision_day.strftime("%d%m%Y")
                    try:
                        decision_result = process_accepted_session(DB_PATH, session_dir, decision_day)
                        status["steps"].append({"step": "decisions", "ok": True, **decision_result})
                        print(
                            f"Decision snapshot OK: {decision_result['score_version']} "
                            f"through {decision_result['trade_date']} ({decision_result['decision_rows']} rows)."
                        )
                    except Exception as exc:
                        status["steps"].append({"step": "decisions", "ok": False, "error": str(exc)})
                        raise
                else:
                    status["steps"].append({"step": "decisions", "ok": False, "error": "no accepted session date"})
                    raise RuntimeError("Cannot materialize decisions without an accepted session date")
            else:
                status["steps"].append({"step": "decisions", "ok": True, "skipped": True})
                print("Decision materialization skipped")

            status["db_date_after"] = _db_max_trade_date()
            status["ok"] = True
            action = next(
                (s.get("action") for s in status["steps"] if s.get("step") == "append" and "action" in s),
                "done",
            )
            if action == "noop":
                status["message"] = (
                    f"Up to date. DB through {status['db_date_after']}. "
                    f"Daily files for {status['daily_bhav_date']}."
                )
            else:
                status["message"] = (
                    f"Pipeline OK. DB {status['db_date_before']} → {status['db_date_after']}. "
                    f"Download session {status['download_date']}."
                )
            print(status["message"])

            # --- Telegram deals (TV paste lists) after successful DB path ---
            if not skip_telegram:
                try:
                    from telegram_deals import notify_deals

                    # Always notify after a successful pipeline so deals stay current
                    # even when append is noop (download refreshed daily deals).
                    tg = notify_deals(dry_run=False, lookback_days=10, min_mcap_cr=1000.0)
                    status["steps"].append(
                        {
                            "step": "telegram_deals",
                            "ok": True,
                            "as_of": tg.get("as_of"),
                            "buy_count": tg.get("buy_count"),
                            "message_count": tg.get("message_count"),
                            "sessions": len(tg.get("days") or []),
                        }
                    )
                except Exception as exc:
                    # Do not fail the whole EOD job if Telegram is misconfigured
                    print(f"Telegram deals notify skipped/failed: {exc}")
                    status["steps"].append({"step": "telegram_deals", "ok": False, "error": str(exc)})
            else:
                status["steps"].append({"step": "telegram_deals", "ok": True, "skipped": True})

            exit_code = 0
    except Exception as exc:
        status["ok"] = False
        status["error"] = str(exc)
        status["message"] = f"Pipeline failed: {exc}"
        print(status["message"])
        traceback.print_exc()
        exit_code = 1
    finally:
        status["finished_at"] = _now_iso()
        if status["db_date_after"] is None:
            status["db_date_after"] = _db_max_trade_date()
        text = buffer.getvalue()
        log_path.write_text(text, encoding="utf-8")
        # Also mirror to stdout for interactive runs
        sys.stdout.write(text)
        try:
            _write_status(status)
            print(f"Status written: {STATUS_PATH}")
            print(f"Log written: {log_path}")
        except Exception as write_exc:
            print(f"Could not write status.json: {write_exc}", file=sys.stderr)

    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Automated MarketPulse EOD pipeline: download latest session + append DB."
    )
    parser.add_argument(
        "--date",
        type=parse_date,
        default=None,
        help="Force download date DDMMYYYY (default: auto latest published session).",
    )
    parser.add_argument("--lookback", type=int, default=7, help="Auto date lookback days (default 7).")
    parser.add_argument("--skip-download", action="store_true", help="Only append from current Input/daily.")
    parser.add_argument("--skip-append", action="store_true", help="Only download; do not touch DuckDB.")
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="Alias for --skip-append.",
    )
    parser.add_argument(
        "--append-only",
        action="store_true",
        help="Alias for --skip-download.",
    )
    parser.add_argument(
        "--skip-telegram",
        action="store_true",
        help="Do not send Telegram deals after update.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_MAX_ATTEMPTS,
        help=f"Max attempts if pipeline fails (default {DEFAULT_MAX_ATTEMPTS}).",
    )
    parser.add_argument(
        "--retry-wait",
        type=int,
        default=DEFAULT_RETRY_WAIT_MINUTES,
        help=f"Minutes to wait between failed attempts (default {DEFAULT_RETRY_WAIT_MINUTES}).",
    )
    args = parser.parse_args()
    skip_download = args.skip_download or args.append_only
    skip_append = args.skip_append or args.download_only
    max_attempts = max(1, args.retries)
    retry_wait_sec = max(0, args.retry_wait) * 60

    last_rc = 1
    for attempt in range(1, max_attempts + 1):
        print(
            f"\n=== MarketPulse EOD attempt {attempt}/{max_attempts} "
            f"at {datetime.now().astimezone().isoformat(timespec='seconds')} ===\n"
        )
        last_rc = run_pipeline(
            skip_download=skip_download,
            skip_append=skip_append,
            skip_telegram=args.skip_telegram,
            date=args.date,
            lookback=max(1, args.lookback),
        )
        if last_rc == 0:
            if attempt > 1:
                print(f"Succeeded on attempt {attempt}/{max_attempts}.")
            return 0

        if attempt < max_attempts:
            mins = retry_wait_sec // 60
            print(
                f"\nAttempt {attempt}/{max_attempts} FAILED. "
                f"Waiting {mins} min then retrying "
                f"(NSE files are often late or flaky right at 8 PM)...\n"
            )
            if retry_wait_sec > 0:
                time.sleep(retry_wait_sec)

    print(f"\nAll {max_attempts} attempts failed. See Logs\\pipeline_*.log and Database\\status.json")
    return last_rc


if __name__ == "__main__":
    raise SystemExit(main())
