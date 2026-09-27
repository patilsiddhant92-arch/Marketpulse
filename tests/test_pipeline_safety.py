"""daily_pipeline: failure alert, streamed log, writer lock around sessions, nightly user-DB backup."""
from __future__ import annotations

import sys
from datetime import datetime

import pytest

import daily_pipeline as dp
import db_lock


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    logs, dbdir = tmp_path / "Logs", tmp_path / "Database"
    monkeypatch.setattr(dp, "LOGS_DIR", logs)
    monkeypatch.setattr(dp, "DATABASE_DIR", dbdir)
    monkeypatch.setattr(dp, "STATUS_PATH", dbdir / "status.json")
    monkeypatch.setattr(dp, "DB_PATH", dbdir / "marketpulse.duckdb")
    monkeypatch.setattr(dp, "_backup_user_db", lambda: None)
    return tmp_path


def _run_main(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["daily_pipeline.py", *argv])
    return dp.main()


@pytest.fixture
def telegram(monkeypatch):
    import telegram_deals

    sent = []
    monkeypatch.setattr(telegram_deals, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(telegram_deals, "send_message", lambda token, chat, text: sent.append((token, chat, text)))
    return sent


def test_final_failure_sends_one_alert(sandbox, monkeypatch, telegram):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    calls = []
    monkeypatch.setattr(dp, "run_pipeline", lambda **k: calls.append(k) or 1)
    rc = _run_main(monkeypatch, ["--retries", "2", "--retry-wait", "0", "--skip-download"])
    assert rc == 1 and len(calls) == 2
    assert len(telegram) == 1
    token, chat, text = telegram[0]
    assert (token, chat) == ("123:abc", "999")
    assert "failed" in text.lower() and "2" in text


def test_success_sends_no_alert(sandbox, monkeypatch, telegram):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    monkeypatch.setattr(dp, "run_pipeline", lambda **k: 0)
    assert _run_main(monkeypatch, ["--retries", "2", "--retry-wait", "0"]) == 0
    assert telegram == []


def test_missing_token_logs_only(sandbox, monkeypatch, telegram, capsys):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setattr(dp, "run_pipeline", lambda **k: 1)
    assert _run_main(monkeypatch, ["--retries", "1", "--retry-wait", "0"]) == 1
    assert telegram == []
    assert "telegram alert skipped" in capsys.readouterr().out.lower()


def test_alert_send_error_does_not_raise(sandbox, monkeypatch, capsys):
    import telegram_deals

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    monkeypatch.setattr(telegram_deals, "load_dotenv", lambda *a, **k: None)

    def boom(*a):
        raise RuntimeError("network down")

    monkeypatch.setattr(telegram_deals, "send_message", boom)
    monkeypatch.setattr(dp, "run_pipeline", lambda **k: 1)
    assert _run_main(monkeypatch, ["--retries", "1", "--retry-wait", "0"]) == 1
    assert "network down" in capsys.readouterr().out


def test_log_is_streamed_to_file_while_running(sandbox, monkeypatch):
    seen = {}

    def probe():
        print("MARKER-BEFORE-CRASH")
        log = sorted((sandbox / "Logs").glob("pipeline_*.log"))[-1]
        seen["text"] = log.read_text(encoding="utf-8")
        raise KeyboardInterrupt  # not an Exception: bypasses the pipeline's handler

    monkeypatch.setattr(dp, "_daily_bhav_date", probe)
    with pytest.raises(KeyboardInterrupt):
        dp.run_pipeline(skip_download=True, skip_append=True, skip_telegram=True, skip_taxonomy=True)
    assert "MARKER-BEFORE-CRASH" in seen["text"]
    log = sorted((sandbox / "Logs").glob("pipeline_*.log"))[-1]
    assert "MARKER-BEFORE-CRASH" in log.read_text(encoding="utf-8")
    assert (sandbox / "Database" / "status.json").exists()


def test_session_loop_holds_writer_lock_and_backs_up_user_db(sandbox, monkeypatch):
    held = []
    backups = []
    monkeypatch.setattr(dp, "_required_bhav_present", lambda session_dir, day: (True, "bhav.csv"))

    def fake_append():
        held.append(db_lock.is_held_here(dp.DB_PATH))
        return {"action": "noop", "message": "", "db_date": None, "new_rows": 0, "backup": None, "duration_ms": 0}

    monkeypatch.setattr(dp, "_run_append", fake_append)
    monkeypatch.setattr(dp, "_backup_user_db", lambda: backups.append(1) or "user-backup")
    rc = dp.run_pipeline(skip_download=True, skip_telegram=True, skip_taxonomy=True, date=datetime(2026, 9, 25))
    assert rc == 0
    assert held == [True]
    assert not db_lock.lock_path_for(dp.DB_PATH).exists()
    assert backups == [1]


def test_user_db_backup_not_taken_on_failure(sandbox, monkeypatch):
    backups = []
    monkeypatch.setattr(dp, "_required_bhav_present", lambda session_dir, day: (False, "missing"))
    monkeypatch.setattr(dp, "_backup_user_db", lambda: backups.append(1))
    rc = dp.run_pipeline(skip_download=True, skip_telegram=True, skip_taxonomy=True, date=datetime(2026, 9, 25))
    assert rc == 1 and backups == []
