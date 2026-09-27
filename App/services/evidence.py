"""Evidence per setup (spec §5): outcome aggregates from `setup_outcomes`, and stock analogs.

`setup_outcomes` is built by the evidence engine (Scripts/evidence): one row per setup identity with
fill / stop / R-multiple / MAE / MFE and the environment state + group quadrant on the signal date.
Only outcomes fully resolved on or before as_of are counted (exit_date <= as_of: no look-ahead), and
n < 30 reports "insufficient sample" instead of numbers.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any

import pandas as pd

from App.services import db, desk, screener
from App.services.common import Result, no_session, unavailable

try:
    from Scripts.evidence.analogs import STOCK_ANALOG_FEATURES, stock_analogs as _stock_analogs
except ModuleNotFoundError:  # pragma: no cover - script-style import
    from evidence.analogs import STOCK_ANALOG_FEATURES, stock_analogs as _stock_analogs  # type: ignore

MIN_SAMPLE = 30
EXTRA_QUEUES = {"momentum"}  # evidence-engine queue (Minervini template + strength rank >= 70, 10-day high trigger)
_COLS = {
    "setup": ("queue", "setup", "preset", "setup_type"),
    "signal_date": ("signal_date", "trade_date"),
    "exit_date": ("exit_date", "resolved_date"),
    "r": ("r_multiple", "final_r", "r"),
    "hit_2r": ("hit_2r", "hit_2r_before_stop"),
    "mae": ("mae_pct", "mae"),
    "mfe": ("mfe_pct", "mfe"),
    "env": ("environment_state", "env_state", "verdict"),
    "quadrant": ("group_quadrant", "industry_quadrant"),
}


def known_setups() -> set[str]:
    return set(desk.QUEUES) | set(screener.PRESETS) | EXTRA_QUEUES


def _clean(v: Any) -> Any:
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        try:
            v = v.item()
        except (AttributeError, ValueError):
            pass
        if isinstance(v, float) and not math.isfinite(v):
            return None
    if isinstance(v, pd.Timestamp):
        return v.date()
    return v


def _ship_gate(con: Any, key: str) -> dict[str, Any] | None:
    if not db.table_exists(con, "environment_calibration"):
        return None
    rows = db.records(con, "SELECT * FROM environment_calibration WHERE kind = 'ship_gate' AND queue = ?", [key])
    return {k: _clean(v) for k, v in rows[0].items()} if rows else None


def evidence(as_of: date | None, setup: str, by: str = "environment") -> Result:
    key = str(setup or "").strip().lower()
    if key not in known_setups():
        raise KeyError(key)
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if not db.table_exists(con, "setup_outcomes"):
            return unavailable(resolved, "setup_outcomes not built yet (evidence engine, spec §5)", ["setup_outcomes"],
                               setup=key, min_sample=MIN_SAMPLE)
        if resolved is None:
            return no_session(as_of)
        cols = set(db.table_columns(con, "setup_outcomes"))
        c = {k: next((x for x in names if x in cols), None) for k, names in _COLS.items()}
        if not (c["setup"] and c["signal_date"] and c["r"]):
            return unavailable(resolved, "setup_outcomes lacks setup / signal_date / r_multiple columns", ["setup_outcomes"])
        group_col = c["env"] if by == "environment" else c["quadrant"] if by == "quadrant" else None
        grp = db.quote_ident(group_col) if group_col else "'all'"
        hit = f"avg(CASE WHEN {db.quote_ident(c['hit_2r'])} THEN 1.0 ELSE 0.0 END) * 100" if c["hit_2r"] else "NULL"
        mae = f"avg({db.quote_ident(c['mae'])})" if c["mae"] else "NULL"
        mfe = f"avg({db.quote_ident(c['mfe'])})" if c["mfe"] else "NULL"
        exit_clause = f"AND {db.quote_ident(c['exit_date'])} <= ?" if c["exit_date"] else ""
        params: list[Any] = [key, resolved] + ([resolved] if c["exit_date"] else [])
        raws = db.records(
            con,
            f"""
            SELECT CAST({grp} AS VARCHAR) AS bucket, count(*) AS n,
                   {hit} AS hit_rate_2r, avg({db.quote_ident(c['r'])}) AS avg_r,
                   median({db.quote_ident(c['r'])}) AS median_r, {mae} AS mae_pct, {mfe} AS mfe_pct
            FROM setup_outcomes
            WHERE lower(CAST({db.quote_ident(c['setup'])} AS VARCHAR)) = ?
              AND {db.quote_ident(c['signal_date'])} <= ? {exit_clause}
              AND {db.quote_ident(c['r'])} IS NOT NULL
            GROUP BY ROLLUP (1) ORDER BY 1 NULLS FIRST
            """,
            params,
        )
        gate = _ship_gate(con, key)
    rows = []
    for r in raws:
        n = int(r["n"] or 0)
        ok = n >= MIN_SAMPLE
        rows.append({
            "bucket": r["bucket"] if r["bucket"] is not None else "all",
            "n": n,
            "insufficient_sample": not ok,
            "label": None if ok else "insufficient sample",
            "hit_rate_2r": db.num(r["hit_rate_2r"], 1) if ok else None,
            "avg_r": db.num(r["avg_r"], 2) if ok else None,
            "median_r": db.num(r["median_r"], 2) if ok else None,
            "mae_pct": db.num(r["mae_pct"], 2) if ok else None,
            "mfe_pct": db.num(r["mfe_pct"], 2) if ok else None,
        })
    extra: dict[str, Any] = {"setup": key, "by": by, "min_sample": MIN_SAMPLE}
    if gate is not None:
        extra["ship_gate"] = gate
    return Result(as_of=resolved, rows=rows, sources=["setup_outcomes"], extra=extra,
                  notes=["Counts only setups whose exit is on or before as_of; entry = next-session trigger cross, "
                         "exit = stop or 20th session close."],
                  metric_keys=["sample_n", "hit_rate_2r", "avg_r", "median_r", "mae_pct", "mfe_pct"])


# --------------------------------------------------------------------------
# Stock analogs (Stock 360)
# --------------------------------------------------------------------------
def stock_analogs(as_of: date | None, symbol: str, k: int = 30) -> Result:
    """Nearest past setups of the same queue as the stock's current setup(s), with the outcome distribution."""
    empty_dist = {"n": 0, "hit_rate_2r": None, "avg_r": None, "median_r": None, "insufficient_sample": True}
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if not db.table_exists(con, "setup_outcomes"):
            return unavailable(resolved, "stock analogs need setup_outcomes (evidence engine, spec §5)", ["setup_outcomes"],
                               symbol=symbol, distribution=empty_dist)
        if resolved is None:
            return no_session(as_of)
        recent = db.recent_sessions(con, resolved, 6)
        live_from = recent[-1] if recent else resolved
        cols = set(db.table_columns(con, "setup_outcomes"))
        feats = [f for f in STOCK_ANALOG_FEATURES if f in cols]
        current = con.execute(
            """SELECT * FROM setup_outcomes WHERE symbol = ? AND signal_date <= ? AND last_seen >= ?
               ORDER BY signal_date DESC""", [symbol, resolved, live_from]).fetchdf()
        current = current.drop_duplicates("queue")
        if current.empty:
            return Result(as_of=resolved, rows=[], sources=["setup_outcomes"],
                          extra={"symbol": symbol, "distribution": empty_dist, "distributions": {}},
                          notes=[f"{symbol} is not in a Desk / evidence queue on or near {resolved.isoformat()}."])
        rows: list[dict[str, Any]] = []
        dists: dict[str, Any] = {}
        for q in current.to_dict("records"):
            pool = con.execute(
                """SELECT * FROM setup_outcomes WHERE queue = ? AND exit_date <= ? AND r_multiple IS NOT NULL
                   AND setup_id <> ?""", [q["queue"], resolved, q["setup_id"]]).fetchdf()
            near, dist = _stock_analogs(pool, q, k=k)
            dist["queue"] = q["queue"]
            dist["query_signal_date"] = _clean(q["signal_date"])
            dists[q["queue"]] = dist
            for r in near.to_dict("records"):
                rows.append({
                    "trade_date": _clean(r["signal_date"]), "symbol": r["symbol"], "queue": r["queue"],
                    "distance": db.num(r["distance"], 3),
                    "features": {f: db.num(r.get(f), 2) for f in feats},
                    "r_multiple": db.num(r["r_multiple"], 2),
                    "hit_2r": None if r.get("hit_2r") is None or pd.isna(r.get("hit_2r")) else bool(r["hit_2r"]),
                    "days_held": None if r.get("days_held") is None or pd.isna(r.get("days_held")) else int(r["days_held"]),
                })
    first = dists[current.iloc[0]["queue"]]
    return Result(as_of=resolved, rows=rows, sources=["setup_outcomes"],
                  extra={"symbol": symbol, "distribution": first, "distributions": dists, "k": k,
                         "features": feats},
                  notes=["Neighbours: same queue, resolved on or before as_of, nearest on base depth, strength rank, "
                         "RVOL, group quadrant and environment (z-scored)."],
                  metric_keys=["sample_n", "hit_rate_2r", "avg_r", "median_r"])
