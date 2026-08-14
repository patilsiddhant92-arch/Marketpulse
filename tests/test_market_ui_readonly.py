from __future__ import annotations

from pathlib import Path

import duckdb


def test_app_package_has_no_market_write_connects():
    app_dir = Path("App")
    offenders: list[str] = []
    for path in app_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if "duckdb.connect" not in line:
                continue
            if "USER_DB" in line or "user_db" in line or "user_db" in line.lower():
                continue
            # Allow RO market and parameterized read_only=
            if "read_only=True" in line or "read_only=read_only" in line:
                continue
            # user_data_service writes only user_db
            if path.name == "user_data_service.py":
                continue
            offenders.append(f"{path}:{i}:{line.strip()}")
    assert offenders == [], "Market DB must be opened read-only from App/:\n" + "\n".join(offenders)


def test_journal_round_trip_on_user_db(tmp_path, monkeypatch):
    from Scripts.user_data import initialize_user_db

    user = tmp_path / "marketpulse_user.duckdb"
    initialize_user_db(user)
    with duckdb.connect(str(user)) as db:
        db.execute(
            """
            INSERT INTO trade_journal VALUES (
                1, now(), now(), DATE '2026-08-01', 'ACME', 'Buy', 'Manual',
                100, 10, 95, 120, 1000, 50, 5, 20, 4, 'Open',
                NULL, NULL, NULL, 'note', NULL
            )
            """
        )
    with duckdb.connect(str(user), read_only=True) as db:
        row = db.execute("SELECT symbol, status FROM trade_journal WHERE id = 1").fetchone()
    assert row == ("ACME", "Open")
