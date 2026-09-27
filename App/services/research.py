"""Research (spec §7.6): market analogs, big movers, pre-move watch, group studies.

Backed by evidence-engine tables (Scripts/evidence): `market_analogs`, `big_move_events`,
`big_move_features`, `big_move_lift`, `big_move_precision`, `big_move_paths`, `big_move_group_stats`,
`group_entry_study`, `pre_move_watch`. Until they exist every call returns the normal envelope with
rows=[] and status "unavailable". Rows are passed through (NULL stays NULL), bounded to as_of:

- analogs: the k = 10 analogs stored for the latest session <= as_of (analog dates are >= 60 sessions
  earlier, so their forward returns were known on that session).
- big moves: an event is listed once it was *confirmed* on or before as_of (UC on T; else the first close
  through the +30 % / +50 % line). Fields measured after as_of (move_pct over 60 sessions, peak, path) are
  nulled while the 60-session window is still open at as_of.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any

from App.services import db
from App.services.common import Result, no_session, unavailable

try:
    from Scripts.evidence.analogs import analog_summary
except ModuleNotFoundError:  # pragma: no cover - script-style import
    from evidence.analogs import analog_summary  # type: ignore

LEVELS = {"broad_sector": "Broad Sector", "sector": "Sector", "broad_industry": "Broad Industry", "industry": "Industry"}
_FUTURE_FIELDS = ("move_pct", "move_20d_pct", "peak_date", "path_pct", "catalyst", "catalysts", "catalyst_detail",
                  "industry_moved_share")


def _clean(v: Any) -> Any:
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if hasattr(v, "year") and hasattr(v, "month"):
        return db.to_date(v)
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if hasattr(v, "tolist") and not isinstance(v, (str, bytes)):
        return _clean(v.tolist())
    return v


def _passthrough(con: Any, table: str, date_col_candidates: tuple[str, ...], as_of: date,
                 where: str = "", params: list[Any] | None = None, order: str | None = None) -> list[dict[str, Any]]:
    cols = db.table_columns(con, table)
    date_col = next((c for c in date_col_candidates if c in cols), None)
    clauses, p = [], []
    if date_col:
        clauses.append(f"{db.quote_ident(date_col)} <= ?")
        p.append(as_of)
    if where:
        clauses.append(where)
        p.extend(params or [])
    sql = f"SELECT * FROM {db.quote_ident(table)}"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    if order:
        sql += f" ORDER BY {order}"
    elif date_col:
        sql += f" ORDER BY {db.quote_ident(date_col)} DESC"
    return [{k: _clean(v) for k, v in r.items()} for r in db.records(con, sql, p)]


def _table_records(con: Any, table: str, sql_tail: str = "", params: list[Any] | None = None) -> list[dict[str, Any]]:
    if not db.table_exists(con, table):
        return []
    return [{k: _clean(v) for k, v in r.items()} for r in db.records(con, f"SELECT * FROM {db.quote_ident(table)} {sql_tail}", params)]


def analogs(as_of: date | None) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if not db.table_exists(con, "market_analogs"):
            return unavailable(resolved, "market_analogs not built yet (evidence engine, spec §5)", ["market_analogs"],
                               agreement=None, k=10)
        if resolved is None:
            return no_session(as_of)
        rows = _passthrough(con, "market_analogs", ("as_of_date", "trade_date", "query_date"), resolved,
                            order='"as_of_date" DESC, "rank"' if "rank" in db.table_columns(con, "market_analogs") else None)
        validation = _table_records(con, "market_analog_validation")
    key = next((c for c in ("as_of_date", "trade_date", "query_date") if rows and c in rows[0]), None)
    latest = [r for r in rows if key and r.get(key) == rows[0].get(key)] if rows else []
    summary = analog_summary(latest)
    return Result(as_of=resolved, rows=latest, sources=["market_analogs"],
                  extra={"k": len(latest), "agreement": summary.get("agreement"), "summary": summary,
                         "query_date": latest[0].get(key) if latest else None, "validation": validation},
                  notes=["Analogs exclude the 60 sessions before the query date; the vector is z-scored with statistics "
                         "known on the query date only."] + ([summary["warning"]] if summary.get("warning") else []),
                  metric_keys=["analog_distance", "forward_return_20d"])


def _lift_context(con: Any) -> list[dict[str, Any]]:
    cols = set(db.table_columns(con, "big_move_lift")) if db.table_exists(con, "big_move_lift") else set()
    where = """WHERE "offset" = 1""" + (" AND subset = 'all'" if "subset" in cols else "")
    lift = _table_records(con, "big_move_lift", f"{where} ORDER BY stable_oos DESC, lift DESC NULLS LAST")
    prec = {r["rule"]: r for r in _table_records(con, "big_move_precision")}
    out = []
    for r in lift:
        p = prec.get(r["feature"], {})
        out.append({
            "feature": r["feature"], "bucket": r.get("rule"), "meaning": r.get("meaning"), "lift": r.get("lift"),
            "lift_train": r.get("lift_train"), "lift_test": r.get("lift_test"),
            "event_rate": r.get("event_rate"), "control_rate": r.get("control_rate"),
            "n_movers": r.get("n_events"), "n_controls": r.get("n_controls"),
            "n_movers_test": r.get("n_events_test"), "n_controls_test": r.get("n_controls_test"),
            "oos": r.get("stable_oos"), "precision_20d": p.get("precision_20d"), "base_rate_20d": p.get("base_rate_20d"),
            "precision_n": p.get("n_stock_days"), "label": r.get("label"), "metric_key": None,
        })
    return out


def _path_context(con: Any) -> list[dict[str, Any]]:
    rows = _table_records(con, "big_move_paths")
    by: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        k = (r["feature"], r["offset"])
        d = by.setdefault(k, {"feature": r["feature"], "offset": r["offset"], "movers": None, "controls": None,
                              "n_movers": None, "n_controls": None})
        if r["role"] == "event":
            d["movers"], d["n_movers"] = r.get("median"), r.get("n")
        else:
            d["controls"], d["n_controls"] = r.get("median"), r.get("n")
    return sorted(by.values(), key=lambda d: (d["feature"], d["offset"]))


def _honest_events(rows: list[dict[str, Any]], as_of: date) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        conf = r.get("confirmed_date")
        if conf is not None and conf > as_of:
            continue
        wend = r.get("window_end_date")
        if wend is None or wend > as_of:
            r = dict(r)
            for f in _FUTURE_FIELDS:
                if f in r:
                    r[f] = None
            r["window_open"] = True
        out.append(r)
    return out


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
        rows = _honest_events(_passthrough(con, "big_move_events", ("event_date", "trade_date"), resolved, where, params),
                              resolved)
        uc_lift = _table_records(con, "big_move_lift", """WHERE "offset" = 1 AND subset = 'upper_circuit' ORDER BY lift DESC NULLS LAST""")             if "subset" in set(db.table_columns(con, "big_move_lift") if db.table_exists(con, "big_move_lift") else []) else []
        extra = {"min_mcap_cr": min_mcap_cr, "lift": _lift_context(con), "lift_upper_circuit": uc_lift,
                 "feature_path": _path_context(con),
                 "precision": _table_records(con, "big_move_precision"),
                 "catalyst_stats": _table_records(con, "big_move_catalyst_stats"),
                 "definition": ("Event = upper circuit (high >= prev close x (1 + band) x 0.9995) | +30% within 20 sessions "
                                "| +50% within 60 sessions, first qualifying day of an episode (new episode after 20 quiet "
                                "sessions); mcap >= 1,000 Cr at T-1 (point-in-time), EQ, 20-day ADV >= 1 Cr."),
                 "path_start_offset": -60}
    return Result(as_of=resolved, rows=rows, sources=["big_move_events", "big_move_lift", "big_move_paths"], extra=extra,
                  notes=["Lift = share of movers with the trait / share of matched controls (same date, Industry, mcap "
                         "quintile); train/test split is chronological with a 60-session embargo."],
                  metric_keys=["precision_20d", "lift"])


def _event_features(con: Any, event_id: str) -> list[dict[str, Any]]:
    if not db.table_exists(con, "big_move_features"):
        return []
    recs = db.records(con, """
        WITH ev AS (SELECT feature, "offset", value FROM big_move_features WHERE event_id = ? AND role = 'event'),
             own AS (SELECT feature, "offset", median(value) AS control_median, count(value) AS n_controls
                     FROM big_move_features WHERE event_id = ? AND role = 'control' GROUP BY 1, 2),
             pop AS (SELECT f.feature, f."offset", avg(CASE WHEN f.value < ev.value THEN 1.0 ELSE 0.0 END) * 100 AS pct,
                            count(*) AS n_pop
                     FROM big_move_features f JOIN ev USING (feature, "offset")
                     WHERE f.role = 'control' AND f.value IS NOT NULL AND ev.value IS NOT NULL GROUP BY 1, 2)
        SELECT ev.feature, -ev."offset" AS "offset", ev.value AS mover_value, own.control_median, own.n_controls,
               pop.pct AS percentile_vs_controls, pop.n_pop AS n_population_controls
        FROM ev LEFT JOIN own USING (feature, "offset") LEFT JOIN pop USING (feature, "offset")
        ORDER BY ev.feature, ev."offset" DESC""", [event_id, event_id])
    return [{k: _clean(v) for k, v in r.items()} for r in recs]


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
        rows = _honest_events(_passthrough(con, "big_move_events", ("event_date", "trade_date"), resolved,
                                           f"CAST({db.quote_ident(id_col)} AS VARCHAR) = ?", [event_id]), resolved)
        features = _event_features(con, event_id) if rows else []
        controls = _table_records(con, "big_move_controls", "WHERE event_id = ?", [event_id]) if rows else []
    if not rows:
        return unavailable(resolved, f"no big-move event {event_id!r} on or before as_of", ["big_move_events"])
    return Result(as_of=resolved, rows=rows, sources=["big_move_events", "big_move_features"],
                  extra={"event_id": event_id, "features": features, "controls": controls,
                         "offsets": "offset -k = k sessions before the event date (T-1, T-5, T-20, T-60)"})


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
    base = rows[0].get("base_rate_20d") if rows else None
    return Result(as_of=resolved, rows=rows, sources=["pre_move_watch"],
                  extra={"label": "research", "base_rate": base, "units": "precision_20d / base_rate_20d in %"},
                  notes=["Research list: precision is printed per row; not a trade signal until it beats the base rate out of sample."],
                  metric_keys=["precision_20d", "lift"])


def group_studies(as_of: date | None, level: str = "industry") -> Result:
    """Big movers by taxonomy level (events per 1,000 eligible stock-days, lift vs all) and forward excess
    return after a group enters Leading. Whole-history study (not bounded to as_of)."""
    lv = LEVELS.get(str(level or "").strip().lower())
    if lv is None:
        raise ValueError(f"level must be one of {', '.join(LEVELS)}")
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if not db.table_exists(con, "big_move_group_stats"):
            return unavailable(resolved, "big_move_group_stats not built yet (evidence engine, spec §7.6)",
                               ["big_move_group_stats"], level=lv)
        rows = _table_records(con, "big_move_group_stats", "WHERE level = ? ORDER BY n_events DESC", [lv])
        entries = _table_records(con, "group_entry_study", "WHERE level = ?", [lv])
    return Result(as_of=resolved, rows=rows, sources=["big_move_group_stats", "group_entry_study"],
                  extra={"level": lv, "entry_study": entries},
                  notes=["Whole-history study on the current taxonomy mapping (not point-in-time)."],
                  metric_keys=["lift"])
