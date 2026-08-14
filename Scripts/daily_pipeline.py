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

            # Resolve session directory for provenance / decisions
            decision_text = status.get("download_date") or status.get("daily_bhav_date")
            session_dir = None
            if decision_text:
                decision_day = datetime.fromisoformat(str(decision_text)).date()
                session_dir = ROOT_DIR / "Input" / "downloads" / decision_day.strftime("%d%m%Y")

            # --- Provenance: fail-closed bhav + promote disk manifest to DB ---
            if not skip_append:
                bhav_ok, bhav_name = _required_bhav_present(session_dir, decision_text)
                if not bhav_ok:
                    status["steps"].append(
                        {"step": "provenance", "ok": False, "error": "required bhavcopy missing or empty"}
                    )
                    raise RuntimeError(
                        "Required bhavcopy missing — refusing append/decisions "
                        "(fail-closed provenance gate)."
                    )
                if session_dir and Path(session_dir).exists():
                    try:
                        prov = _promote_manifest_to_db(session_dir, str(decision_text))
                        status["steps"].append({"step": "provenance", "ok": prov.get("ok", False), **prov, "bhav": bhav_name})
                        if not prov.get("ok"):
                            print(f"Manifest promote warning: {prov.get('error')}")
                    except Exception as exc:
                        # Disk manifest may be incomplete when download was skipped; log and continue
                        # only if daily bhav exists (already checked). DB rows may stay empty.
                        status["steps"].append(
                            {"step": "provenance", "ok": False, "error": str(exc), "bhav": bhav_name}
                        )
                        print(f"Manifest promote failed (bhav present): {exc}")
                else:
                    status["steps"].append(
                        {
                            "step": "provenance",
                            "ok": True,
                            "message": "bhav present; session dir/manifest not available to promote",
                            "bhav": bhav_name,
                        }
                    )

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
                if decision_text and session_dir is not None:
                    decision_day = datetime.fromisoformat(str(decision_text)).date()
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
