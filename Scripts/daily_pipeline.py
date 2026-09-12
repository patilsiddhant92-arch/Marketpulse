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
import os
import sys
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta
from io import StringIO
from pathlib import Path

import duckdb
import pandas as pd

from config import ARCHIVE_DIR, DAILY_DIR, DATABASE_DIR, DB_PATH, LOGS_DIR, ROOT_DIR
from download_nse_reports import (
    archive_daily_inputs,
    clear_daily_dir,
    ddmmyyyy,
    install_stage,
    make_session,
    parse_date,
    resolve_auto_date,
    run as download_run,
    session_available,
)
from decision_pipeline import process_accepted_session

STATUS_PATH = DATABASE_DIR / "status.json"
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_WAIT_MINUTES = 10


def _is_session_staged(session_dir: Path, day: datetime) -> bool:
    if not session_dir.exists() or not session_dir.is_dir():
        return False
    long_date = ddmmyyyy(day)
    bhav = session_dir / f"sec_bhavdata_full_{long_date}.csv"
    manifest = session_dir / "manifest.json"
    return bhav.exists() and bhav.stat().st_size > 0 and manifest.exists()


def get_missing_trading_dates(
    db_date: str | datetime | date | None,
    target_date: str | datetime | date,
    session=None,
) -> list[datetime]:
    """
    Compute list of missing trading sessions between db_date and target_date (inclusive).
    Skips weekends (Saturday/Sunday).
    Skips weekdays where NSE had no trading session (holidays) unless already staged locally.
    Returns sorted chronological list of datetime objects.
    """
    if db_date is None:
        target_dt = pd.to_datetime(target_date).to_pydatetime()
        return [datetime.combine(target_dt.date(), datetime.min.time())]

    start = pd.to_datetime(db_date).date() + timedelta(days=1)
    end = pd.to_datetime(target_date).date()

    if start > end:
        return []

    req_session = None
    missing: list[datetime] = []
    curr = start
    while curr <= end:
        # 1. Skip weekends
        if curr.weekday() >= 5:
            curr += timedelta(days=1)
            continue

        curr_dt = datetime.combine(curr, datetime.min.time())
        long_date = ddmmyyyy(curr_dt)

        # 2. Check local disk first: staged download, daily, or archive
        local_found = False
        staged_dir = ROOT_DIR / "Input" / "downloads" / long_date
        staged_bhav = staged_dir / f"sec_bhavdata_full_{long_date}.csv"
        if staged_bhav.exists() and staged_bhav.stat().st_size > 0:
            local_found = True
        elif (DAILY_DIR / f"sec_bhavdata_full_{long_date}.csv").exists():
            local_found = True
        elif (ARCHIVE_DIR / f"sec_bhavdata_full_{long_date}.csv").exists():
            local_found = True

        if local_found:
            missing.append(curr_dt)
            curr += timedelta(days=1)
            continue

        # 3. Probe NSE to check if this was a trading session or holiday
        if req_session is None:
            req_session = session or make_session()

        try:
            if session_available(req_session, curr_dt):
                missing.append(curr_dt)
            else:
                print(f"Skipping {curr.isoformat()}: NSE market holiday / no session published.")
        except Exception as exc:
            print(f"Warning: probe for {curr.isoformat()} failed ({exc}); assuming trading day.")
            missing.append(curr_dt)

        curr += timedelta(days=1)

    return missing


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
    """Delegate to the single append_session implementation (PR-APPEND)."""
    from append_database import append_session

    # Pipeline owns Telegram deals at the end; skip nested notify inside append.
    result = append_session(force_full=False, notify_telegram=False)
    return {
        "action": result.action,
        "message": result.message,
        "db_date": result.db_date,
        "new_rows": result.new_rows,
        "backup": result.backup,
        "duration_ms": result.duration_ms,
    }


def _required_bhav_present(session_dir: Path | None, trading_date: str | None) -> tuple[bool, str]:
    """Fail-closed gate: bhavcopy must exist for the session (disk and/or daily)."""
    patterns = []
    if trading_date:
        try:
            day = pd.Timestamp(trading_date)
            ddmmyyyy = day.strftime("%d%m%Y")
            patterns.append(f"sec_bhavdata_full_{ddmmyyyy}.csv")
        except Exception:
            pass
    if session_dir and Path(session_dir).exists():
        for path in Path(session_dir).glob("sec_bhavdata_full_*.csv"):
            if path.is_file() and path.stat().st_size > 0:
                return True, path.name
    if DAILY_DIR.exists():
        files = sorted(DAILY_DIR.glob("sec_bhavdata_full_*.csv"))
        if files and files[-1].is_file() and files[-1].stat().st_size > 0:
            return True, files[-1].name
    return False, "missing bhavcopy"


def _promote_manifest_to_db(session_dir: Path, trading_date: str) -> dict:
    """Upsert disk session manifest into ingested_reports / ingestion_batches."""
    from ingestion_manifest import SessionPlan, validate_session_manifest
    from migrations import run_migrations
    from transactional_append import append_batch

    session_dir = Path(session_dir)
    manifest_path = session_dir / "manifest.json"
    if not manifest_path.exists():
        return {"ok": False, "error": f"no manifest at {manifest_path}", "rows": 0}

    try:
        manifest = validate_session_manifest(session_dir)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "rows": 0}

    trade_date = pd.Timestamp(trading_date).date()
    batch_id = f"session-{trade_date.isoformat()}"
    report_rows = []
    for item in manifest.reports:
        report_rows.append(
            {
                "trade_date": trade_date,
                "report_type": item.report_type,
                "source_checksum": item.sha256,
                "row_count": None,
                "manifest_path": str(manifest_path),
                "batch_id": batch_id,
            }
        )
    batch_rows = [
        {
            "batch_id": batch_id,
            "start_date": trade_date,
            "end_date": trade_date,
            "status": "accepted",
            "started_at": datetime.now(),
            "completed_at": datetime.now(),
            "application_version": "marketpulse-2.0",
            "error_summary": None,
        }
    ]
    plan = SessionPlan(
        trading_dates=[trade_date.isoformat()],
        rows_by_table={"ingestion_batches": batch_rows, "ingested_reports": report_rows},
    )
    run_migrations(DB_PATH)
    append_batch(DB_PATH, plan)
    return {"ok": True, "rows": len(report_rows), "batch_id": batch_id, "manifest": str(manifest_path)}


def run_pipeline(
    *,
    skip_download: bool = False,
    skip_append: bool = False,
    skip_telegram: bool = False,
    skip_taxonomy: bool = False,
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

            sessions_to_process: list[datetime] = []
            if not skip_download:
                try:
                    target_day = date if date is not None else resolve_auto_date(lookback_days=lookback)
                    status["download_date"] = target_day.date().isoformat()
                    missing = get_missing_trading_dates(status["db_date_before"], target_day)
                    if not missing:
                        sessions_to_process = [target_day]
                    else:
                        sessions_to_process = missing
                    if len(sessions_to_process) > 1:
                        session_strs = [s.strftime("%d-%m-%Y") for s in sessions_to_process]
                        print(f"Multi-day catch-up detected! {len(sessions_to_process)} sessions to process: {', '.join(session_strs)}")
                except Exception as exc:
                    status["steps"].append({"step": "download_discovery", "ok": False, "error": str(exc)})
                    raise
            else:
                print("Download skipped")
                status["steps"].append({"step": "download", "ok": True, "skipped": True})
                day_str = _daily_bhav_date()
                target_day = date if date is not None else (datetime.fromisoformat(day_str) if day_str else None)
                if target_day is not None:
                    sessions_to_process = [target_day]

            # Ingest sessions in chronological order
            for s_idx, s_day in enumerate(sessions_to_process, 1):
                s_date_str = s_day.date().isoformat()
                s_long_date = ddmmyyyy(s_day)
                session_dir = ROOT_DIR / "Input" / "downloads" / s_long_date

                print(f"\n--- Processing session {s_idx}/{len(sessions_to_process)}: {s_date_str} ---")

                # Step 1: Download / Stage
                if not skip_download:
                    try:
                        if _is_session_staged(session_dir, s_day):
                            print(f"Session {s_date_str} already staged in {session_dir}. Installing to daily...")
                            archive_daily_inputs()
                            clear_daily_dir()
                            from ingestion_manifest import validate_session_manifest
                            manifest = validate_session_manifest(session_dir)
                            expected_names = [r.filename for r in manifest.reports]
                            install_stage(session_dir, expected_names, dry_run=False)
                        else:
                            rc = download_run(s_day, dry_run=False)
                            if rc != 0:
                                raise RuntimeError(f"Download returned code {rc}")
                        status["steps"].append({"step": f"download_{s_date_str}", "ok": True, "date": s_date_str})
                        print(f"Download/install for {s_date_str} OK")
                    except Exception as exc:
                        status["steps"].append({"step": f"download_{s_date_str}", "ok": False, "error": str(exc)})
                        raise

                # Step 2: Provenance check & promote manifest
                if not skip_append:
                    bhav_ok, bhav_name = _required_bhav_present(session_dir, s_date_str)
                    if not bhav_ok:
                        status["steps"].append(
                            {"step": f"provenance_{s_date_str}", "ok": False, "error": "required bhavcopy missing or empty"}
                        )
                        raise RuntimeError(
                            f"Required bhavcopy missing for {s_date_str} — refusing append "
                            "(fail-closed provenance gate)."
                        )
                    if session_dir and session_dir.exists():
                        try:
                            prov = _promote_manifest_to_db(session_dir, s_date_str)
                            status["steps"].append({"step": f"provenance_{s_date_str}", "ok": prov.get("ok", False), **prov, "bhav": bhav_name})
                        except Exception as exc:
                            status["steps"].append(
                                {"step": f"provenance_{s_date_str}", "ok": False, "error": str(exc), "bhav": bhav_name}
                            )
                            print(f"Manifest promote failed (bhav present): {exc}")
                    else:
                        status["steps"].append(
                            {
                                "step": f"provenance_{s_date_str}",
                                "ok": True,
                                "message": "bhav present; session dir/manifest not available to promote",
                                "bhav": bhav_name,
                            }
                        )

                # Step 3: Append
                if not skip_append:
                    try:
                        append_result = _run_append()
                        status["steps"].append({"step": f"append_{s_date_str}", "ok": True, **append_result})
                    except Exception as exc:
                        status["steps"].append({"step": f"append_{s_date_str}", "ok": False, "error": str(exc)})
                        raise

                # Step 4: Decisions snapshot
                if not skip_append:
                    if session_dir and session_dir.exists():
                        try:
                            decision_result = process_accepted_session(DB_PATH, session_dir, s_day.date())
                            status["steps"].append({"step": f"decisions_{s_date_str}", "ok": True, **decision_result})
                            print(
                                f"Decision snapshot OK: {decision_result['score_version']} "
                                f"through {decision_result['trade_date']} ({decision_result['decision_rows']} rows)."
                            )
                        except Exception as exc:
                            status["steps"].append({"step": f"decisions_{s_date_str}", "ok": False, "error": str(exc)})
                            raise
                    else:
                        print(f"No session directory for {s_date_str}; skipping decision snapshot.")

            status["daily_bhav_date"] = _daily_bhav_date()
            status["db_date_after"] = _db_max_trade_date()
            status["ok"] = True
            if len(sessions_to_process) > 1:
                status["message"] = (
                    f"Multi-day catch-up complete! Processed {len(sessions_to_process)} sessions. "
                    f"DB {status['db_date_before']} -> {status['db_date_after']}."
                )
            elif status["db_date_before"] == status["db_date_after"]:
                status["message"] = (
                    f"Up to date. DB through {status['db_date_after']}. "
                    f"Daily files for {status['daily_bhav_date']}."
                )
            else:
                status["message"] = (
                    f"Pipeline OK. DB {status['db_date_before']} -> {status['db_date_after']}. "
                    f"Download session {status['download_date']}."
                )
            print(f"\n{status['message']}")

            # --- Telegram deals (TV paste lists) after successful DB path ---
            if not skip_telegram:
                try:
                    from telegram_deals import notify_deals

                    # Always notify after a successful pipeline so deals stay current
                    # even when append is noop (download refreshed daily deals).
                    tg = notify_deals(dry_run=False, lookback_days=10, min_mcap_cr=900.0)
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

            # Missing sector/industry only. Official sector.csv stays source of truth;
            # this is a small rate-limited screener.in backfill (new listings).
            skip_taxonomy = skip_taxonomy or os.environ.get("MP_SKIP_SECTOR_TAXONOMY", "").strip().lower() in {
                "1",
                "true",
                "yes",
            }
            if not skip_append and not skip_taxonomy:
                try:
                    from refresh_sector_taxonomy import run_batch as fill_sector_taxonomy

                    tax = fill_sector_taxonomy()
                    status["steps"].append({"step": "sector_taxonomy", "ok": True, **tax})
                    print(f"Sector taxonomy: {tax.get('message')}")
                except Exception as exc:
                    print(f"Sector taxonomy fill skipped/failed: {exc}")
                    status["steps"].append({"step": "sector_taxonomy", "ok": False, "error": str(exc)})
            elif skip_taxonomy:
                status["steps"].append({"step": "sector_taxonomy", "ok": True, "skipped": True})

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
        try:
            sys.stdout.write(text)
        except Exception:
            enc = sys.stdout.encoding or "ascii"
            sys.stdout.write(text.encode(enc, errors="replace").decode(enc))
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
        "--skip-taxonomy",
        action="store_true",
        help="Do not backfill missing sector/industry from screener.in.",
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
            skip_taxonomy=args.skip_taxonomy,
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
