"""Research (spec §7.6): market analogs, big movers, pre-move watch.

Backed by evidence-engine tables (`market_analogs`, `big_move_events`,
`big_move_features`, `pre_move_watch`). Until they exist every call returns the
normal envelope with rows=[] and status "unavailable"; the row shapes are fixed
by the Pydantic models in App/api/v2/models.py so the frontend can be built now.
When a table exists its rows are passed through (NULL stays NULL), bounded to as_of.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from App.services import db
from App.services.common import Result, no_session, unavailable


def _passthrough(con: Any, table: str, date_col_candidates: tuple[str, ...], as_of: date,
                 where: str = "", params: list[Any] | None = None, order: str | None = None) -> list[dict[str, Any]]:
    cols = db.table_columns(con, table)
    date_col = next((c for c in date_col_candidates if c in cols), None)
    clauses, p = [], list(params or [])
    if date_col:
        clauses.append(f"{db.quote_ident(date_col)} <= ?")
        p.append(as_of)
    if where:
        clauses.append(where)
    sql = f"SELECT * FROM {db.quote_ident(table)}"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    if order:
        sql += f" ORDER BY {order}"
    elif date_col:
        sql += f" ORDER BY {db.quote_ident(date_col)} DESC"
    out = []
    for r in db.records(con, sql, p):
        out.append({k: (db.to_date(v) if hasattr(v, "year") else v) for k, v in r.items()})
    return out




def analogs(as_of: date | None) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if not db.table_exists(con, "market_analogs"):
            return unavailable(resolved, "market_analogs not built yet (evidence engine, spec §5)", ["market_analogs"],
                               agreement=None, k=10)
        if resolved is None:
            return no_session(as_of)
        rows = _passthrough(con, "market_analogs", ("as_of_date", "trade_date", "query_date"), resolved)
    latest = [r for r in rows if r.get("as_of_date", r.get("trade_date", r.get("query_date"))) == (
        rows[0].get("as_of_date", rows[0].get("trade_date", rows[0].get("query_date"))) if rows else None)]
    return Result(as_of=resolved, rows=latest, sources=["market_analogs"], metric_keys=["analog_distance", "forward_return_20d"])


def big_moves(as_of: date | None, min_mcap_cr: float = 1000.0) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if not db.table_exists(con, "big_move_events"):
            return unavailable(resolved, "big_move_events not built yet (evidence engine, spec §7.6)", ["big_move_events"],
                               min_mcap_cr=min_mcap_cr)
        if resolved is None:
            return no_session(as_of)
        cols = set(db.table_columns(con, "big_move_events"))
        where, params = "", []
        mcap_col = next((c for c in ("mcap_cr_at_event", "market_cap_cr") if c in cols), None)
        if mcap_col:
            where, params = f"{db.quote_ident(mcap_col)} >= ?", [float(min_mcap_cr)]
        rows = _passthrough(con, "big_move_events", ("event_date", "trade_date"), resolved, where, params)
    return Result(as_of=resolved, rows=rows, sources=["big_move_events"], extra={"min_mcap_cr": min_mcap_cr},
                  metric_keys=["precision_20d", "lift"])


def big_move(as_of: date | None, event_id: str) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if not db.table_exists(con, "big_move_events"):
            return unavailable(resolved, "big_move_events not built yet (evidence engine, spec §7.6)", ["big_move_events"],
                               event_id=event_id, features=None)
        if resolved is None:
            return no_session(as_of)
        cols = set(db.table_columns(con, "big_move_events"))
        id_col = next((c for c in ("event_id", "id") if c in cols), None)
        if id_col is None:
            return unavailable(resolved, "big_move_events has no event_id column", ["big_move_events"])
        rows = _passthrough(con, "big_move_events", ("event_date", "trade_date"), resolved,
                            f"CAST({db.quote_ident(id_col)} AS VARCHAR) = ?", [event_id])
        features: list[dict[str, Any]] = []
        if rows and db.table_exists(con, "big_move_features"):
            fcols = set(db.table_columns(con, "big_move_features"))
            fid = next((c for c in ("event_id", "id") if c in fcols), None)
            if fid:
                features = _passthrough(con, "big_move_features", (), resolved,
                                        f"CAST({db.quote_ident(fid)} AS VARCHAR) = ?", [event_id])
    if not rows:
        return unavailable(resolved, f"no big-move event {event_id!r} on or before as_of", ["big_move_events"])
    return Result(as_of=resolved, rows=rows, sources=["big_move_events", "big_move_features"],
                  extra={"event_id": event_id, "features": features})


def pre_move(as_of: date | None) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if not db.table_exists(con, "pre_move_watch"):
            return unavailable(resolved, "pre-move watch not built yet (needs big_move_features, spec §7.6)",
                               ["pre_move_watch"], label="research", base_rate=None)
        if resolved is None:
            return no_session(as_of)
        rows = _passthrough(con, "pre_move_watch", ("trade_date", "as_of_date"), resolved)
        d = rows[0].get("trade_date", rows[0].get("as_of_date")) if rows else None
        rows = [r for r in rows if r.get("trade_date", r.get("as_of_date")) == d]
    return Result(as_of=resolved, rows=rows, sources=["pre_move_watch"], extra={"label": "research"},
                  notes=["Research list: precision is printed per row; not a trade signal until it beats the base rate out of sample."],
                  metric_keys=["precision_20d", "lift"])
