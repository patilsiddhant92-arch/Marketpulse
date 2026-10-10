"""Deals fund follow (HarkPro/08-tab-deals.md §5.3-4): the user's followed houses, in the user DB.

Like the watchlist and notes (App/services/user.py), this is user data: it lives in the user DB
(marketpulse_user.duckdb), never in the shared market DB. A house is keyed by the Deals tab's house key
(Scripts/derived/deal_desk.house_key: upper case, PVT/LTD/FPI/ODI dropped, first three words), so a follow
matches the same house however NSE spells the client name. Scripts/telegram_deals.py reads this table
(read-only) for the followed-houses alert section.
"""
from __future__ import annotations

from typing import Any

from App.services import db
from Scripts.derived.deal_desk import house_key

TABLE = "v2_followed_houses"
MAX_FOLLOWS = 500
MAX_NAME_CHARS = 200


def ensure(con: Any) -> None:
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            house VARCHAR PRIMARY KEY,
            name VARCHAR,
            added_at TIMESTAMP DEFAULT current_timestamp
        )
        """
    )


def _key(house: str) -> str:
    raw = str(house or "").strip()
    if not raw or len(raw) > MAX_NAME_CHARS:
        raise ValueError(f"house must be 1-{MAX_NAME_CHARS} characters")
    key = house_key(raw)
    if not key:
        raise ValueError("house name has no usable words")
    return key


def list_follows() -> list[dict[str, Any]]:
    with db.user_conn() as con:
        ensure(con)
        rows = db.records(con, f"SELECT house, name, added_at FROM {TABLE} ORDER BY added_at, house")
    return [{"house": r["house"], "name": r["name"] or r["house"].title(), "added_at": r["added_at"]} for r in rows]


def add_follow(house: str, name: str | None = None) -> list[dict[str, Any]]:
    key = _key(house)
    label = (str(name).strip()[:MAX_NAME_CHARS] if name else "") or key.title()
    with db.user_conn() as con:
        ensure(con)
        n = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
        exists = con.execute(f"SELECT 1 FROM {TABLE} WHERE house = ?", [key]).fetchone()
        if not exists and n >= MAX_FOLLOWS:
            raise ValueError(f"you can follow at most {MAX_FOLLOWS} houses")
        con.execute(f"INSERT INTO {TABLE} (house, name) VALUES (?, ?) ON CONFLICT (house) DO NOTHING", [key, label])
    return list_follows()


def remove_follow(house: str) -> list[dict[str, Any]]:
    key = _key(house)
    with db.user_conn() as con:
        ensure(con)
        con.execute(f"DELETE FROM {TABLE} WHERE house = ?", [key])
    return list_follows()


def followed_keys(user_db_path: Any = None) -> set[str]:
    """Read-only set of followed house keys; empty when the user DB or the table does not exist yet."""
    import duckdb
    from pathlib import Path

    path = Path(user_db_path) if user_db_path is not None else db.user_db_path()
    if not path.exists():
        return set()
    try:
        con = duckdb.connect(str(path), read_only=True)
    except duckdb.Error:
        return set()
    try:
        if not db.table_exists(con, TABLE):
            return set()
        return {str(r[0]) for r in con.execute(f"SELECT house FROM {TABLE}").fetchall()}
    except duckdb.Error:
        return set()
    finally:
        con.close()
