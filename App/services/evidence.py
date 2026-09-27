"""Evidence per setup (spec §5): outcome aggregates from `setup_outcomes`.

Until the evidence engine builds `setup_outcomes`, every call is "unavailable".
When it exists: only outcomes fully resolved on or before as_of are counted
(no look-ahead), and n < 30 reports "insufficient sample" instead of numbers.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from App.services import db, desk, screener
from App.services.common import Result, no_session, unavailable

MIN_SAMPLE = 30
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
    return set(desk.QUEUES) | set(screener.PRESETS)


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
    return Result(as_of=resolved, rows=rows, sources=["setup_outcomes"],
                  extra={"setup": key, "by": by, "min_sample": MIN_SAMPLE},
                  metric_keys=["sample_n", "hit_rate_2r", "avg_r", "median_r", "mae_pct", "mfe_pct"])
