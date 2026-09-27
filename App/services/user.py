"""User data (watchlist, notes) in the user DB — the only v2 writes."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from App.services import db

MAX_WATCHLIST = 1000
MAX_NOTE_CHARS = 20_000


def _ensure(con: Any) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS v2_watchlist (
            symbol VARCHAR PRIMARY KEY,
            position INTEGER,
            added_at TIMESTAMP DEFAULT current_timestamp
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS v2_notes (
            symbol VARCHAR PRIMARY KEY,
            body VARCHAR,
            updated_at TIMESTAMP DEFAULT current_timestamp
        )
        """
    )


def get_watchlist() -> list[dict[str, Any]]:
    with db.user_conn() as con:
        _ensure(con)
        rows = db.records(con, "SELECT symbol, position, added_at FROM v2_watchlist ORDER BY position, symbol")
    return [{"symbol": r["symbol"], "position": r["position"], "added_at": r["added_at"]} for r in rows]


def put_watchlist(symbols: list[str]) -> list[dict[str, Any]]:
    """Replace the watchlist with `symbols` (already validated, order kept, de-duplicated)."""
    seen: list[str] = []
    for s in symbols:
        if s not in seen:
            seen.append(s)
    if len(seen) > MAX_WATCHLIST:
        raise ValueError(f"watchlist is limited to {MAX_WATCHLIST} symbols")
    with db.user_conn() as con:
        _ensure(con)
        existing = {r[0]: r[1] for r in con.execute("SELECT symbol, added_at FROM v2_watchlist").fetchall()}
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute("DELETE FROM v2_watchlist")
            now = datetime.now()
            for i, s in enumerate(seen):
                con.execute("INSERT INTO v2_watchlist (symbol, position, added_at) VALUES (?, ?, ?)",
                            [s, i, existing.get(s, now)])
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    return get_watchlist()


def get_note(symbol: str) -> dict[str, Any] | None:
    with db.user_conn() as con:
        _ensure(con)
        row = con.execute("SELECT symbol, body, updated_at FROM v2_notes WHERE symbol = ?", [symbol]).fetchone()
    return {"symbol": row[0], "body": row[1], "updated_at": row[2]} if row else None


def put_note(symbol: str, body: str) -> dict[str, Any] | None:
    if len(body) > MAX_NOTE_CHARS:
        raise ValueError(f"note is limited to {MAX_NOTE_CHARS} characters")
    with db.user_conn() as con:
        _ensure(con)
        if body.strip() == "":
            con.execute("DELETE FROM v2_notes WHERE symbol = ?", [symbol])
        else:
            con.execute(
                """
                INSERT INTO v2_notes (symbol, body, updated_at) VALUES (?, ?, current_timestamp)
                ON CONFLICT (symbol) DO UPDATE SET body = excluded.body, updated_at = excluded.updated_at
                """,
                [symbol, body],
            )
    return get_note(symbol)
