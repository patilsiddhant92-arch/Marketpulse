"""Market environment services: regime verdict (regime_daily) and breadth health history."""
from __future__ import annotations

import json
from datetime import date
from typing import Any

import pandas as pd

from App.services import db
from App.services.common import Result, no_session, unavailable

PILLARS = ("trend", "participation", "leadership", "follow_through", "stress")
PILLAR_FIELDS = ("status", "sentence", "dir_1d", "dir_1w", "dir_1m")
BENCHMARKS = {"nifty50": "Nifty 50", "midsml400": "NIFTY MIDSML 400", "vix": "India VIX"}

HEALTH_METRICS = [
    "advance_pct", "ad_line_10d", "pct_above_10ema", "pct_above_20ema", "pct_above_50ema", "pct_above_200ema",
    "new_52w_highs", "new_52w_lows", "net_new_highs", "near_52w_highs", "stage2_count", "india_vix",
    "vix_change_5d", "distribution_days_25",
]
REGIME_METRICS = [
    "environment_verdict", "days_in_state", "pillar_trend", "pillar_participation", "pillar_leadership",
    "pillar_follow_through", "pillar_stress",
]


# --------------------------------------------------------------------------
# Regime (spec §6.1) — read from regime_daily, never computed ad hoc here
# --------------------------------------------------------------------------
def _json_or_text(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in "[{":
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def shape_regime_row(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a regime_daily row (schema tolerant) onto the v2 response shape."""
    used: set[str] = {"trade_date"}
    pillars: dict[str, dict[str, Any]] = {}
    for p in PILLARS:
        entry: dict[str, Any] = {}
        for f in PILLAR_FIELDS:
            col = f"{p}_{f}"
            entry[f] = db.text(raw.get(col)) if col in raw else None
            used.add(col)
        inputs = {}
        for col, val in raw.items():
            if col.startswith(p + "_") and col not in used:
                inputs[col[len(p) + 1:]] = db.num(val) if not isinstance(val, str) else val
                used.add(col)
        entry["inputs"] = inputs
        pillars[p] = entry

    def pick(*names: str) -> Any:
        for n in names:
            if n in raw:
                used.add(n)
                return raw[n]
        return None

    verdict = db.text(pick("verdict", "state", "environment"))
    row = {
        "trade_date": db.to_date(raw.get("trade_date")),
        "verdict": verdict,
        "previous_verdict": db.text(pick("prev_verdict", "previous_verdict")),
        "rule_id": db.text(pick("rule_id", "verdict_rule_id", "rule")),
        "days_in_state": db.integer(pick("days_in_state")),
        "changed_on": db.to_date(pick("changed_on", "state_since", "since_date")),
        "readings": _json_or_text(pick("readings", "connected_readings")),
        "pillars": pillars,
    }
    other = {k: (db.num(v) if not isinstance(v, str) else v) for k, v in raw.items() if k not in used}
    row["inputs"] = other
    return row


def regime(as_of: date | None, days: int = 126) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if not db.table_exists(con, "regime_daily"):
            return unavailable(resolved, "regime_daily not built yet (data layer §4.5)", ["regime_daily"])
        if resolved is None and as_of is not None:
            return no_session(as_of)
        bound = resolved or as_of
        params: list[Any] = []
        where = ""
        if bound is not None:
            where = "WHERE trade_date <= ?"
            params.append(bound)
        raw_rows = db.records(
            con,
            f"SELECT * FROM regime_daily {where} ORDER BY trade_date DESC LIMIT ?",
            [*params, int(days)],
        )
    if not raw_rows:
        return unavailable(resolved, "regime_daily has no rows on or before as_of", ["regime_daily"])
    rows = [shape_regime_row(r) for r in raw_rows]
    return Result(as_of=rows[0]["trade_date"], rows=rows, sources=["regime_daily"], metric_keys=REGIME_METRICS)


# --------------------------------------------------------------------------
# Market health (breadth history)
# --------------------------------------------------------------------------
def _health_frame(con: Any, as_of: date, days: int) -> pd.DataFrame:
    span = int(days) + 30  # extra sessions for rolling 10/25-session measures
    frame = con.execute(
        """
        WITH b AS (
            SELECT * FROM breadth_daily WHERE trade_date <= ? ORDER BY trade_date DESC LIMIT ?
        ),
        hl AS (
            SELECT trade_date,
                   count(*) FILTER (WHERE high_52w IS NOT NULL AND high_price >= high_52w) AS new_52w_highs,
                   count(*) FILTER (WHERE low_52w IS NOT NULL AND low_52w > 0 AND low_price <= low_52w) AS new_52w_lows,
                   count(*) FILTER (WHERE ema_200 IS NOT NULL AND close_price > ema_200
                                    AND away_52w_high_pct >= -25) AS stage2_count
            FROM indicators_daily
            WHERE trade_date IN (SELECT trade_date FROM b) AND upper(symbol) <> 'TOTAL'
            GROUP BY trade_date
        ),
        ix AS (
            SELECT trade_date,
                   max(close_price) FILTER (WHERE index_name = ?) AS nifty50_close,
                   max(return_1d_pct) FILTER (WHERE index_name = ?) AS nifty50_return_1d_pct,
                   max(close_price) FILTER (WHERE index_name = ?) AS midsml400_close,
                   max(return_1d_pct) FILTER (WHERE index_name = ?) AS midsml400_return_1d_pct,
                   max(turnover_cr) FILTER (WHERE index_name = ?) AS midsml400_turnover_cr,
                   max(close_price) FILTER (WHERE index_name = ?) AS india_vix,
                   max(coalesce(return_1d_pct, (close_price / nullif(previous_close, 0) - 1) * 100))
                       FILTER (WHERE index_name = ?) AS vix_change_1d_pct
            FROM index_daily
            WHERE trade_date IN (SELECT trade_date FROM b) AND index_name IN (?, ?, ?)
            GROUP BY trade_date
        )
        SELECT b.trade_date, b.stocks, b.advancers, b.decliners, b.unchanged, b.advance_pct,
               b.above_10ema_pct, b.above_20ema_pct, b.above_50ema_pct, b.above_200ema_pct,
               b.near_52w_highs, b.breadth_state,
               hl.new_52w_highs, hl.new_52w_lows, hl.stage2_count,
               ix.nifty50_close, ix.nifty50_return_1d_pct, ix.midsml400_close, ix.midsml400_return_1d_pct,
               ix.midsml400_turnover_cr, ix.india_vix, ix.vix_change_1d_pct
        FROM b
        LEFT JOIN hl USING (trade_date)
        LEFT JOIN ix USING (trade_date)
        ORDER BY b.trade_date ASC
        """,
        [
            as_of, span,
            BENCHMARKS["nifty50"], BENCHMARKS["nifty50"],
            BENCHMARKS["midsml400"], BENCHMARKS["midsml400"], BENCHMARKS["midsml400"],
            BENCHMARKS["vix"], BENCHMARKS["vix"],
            BENCHMARKS["nifty50"], BENCHMARKS["midsml400"], BENCHMARKS["vix"],
        ],
    ).fetchdf()
    if frame.empty:
        return frame
    net = frame["advancers"] - frame["decliners"]
    frame["net_advancers"] = net
    frame["ad_line_10d"] = net.rolling(10, min_periods=10).sum()
    frame["net_new_highs"] = frame["new_52w_highs"] - frame["new_52w_lows"]
    frame["vix_change_5d_pct"] = (frame["india_vix"] / frame["india_vix"].shift(5) - 1.0) * 100.0
    # Distribution day: MidSml400 down >= 0.2% on higher turnover than the prior session.
    ret = frame["midsml400_return_1d_pct"]
    to = frame["midsml400_turnover_cr"]
    prev_to = to.shift(1)
    known = ret.notna() & to.notna() & prev_to.notna()
    dist = pd.Series([None] * len(frame), dtype=object)
    dist[known] = ((ret[known] <= -0.2) & (to[known] > prev_to[known])).values
    frame["distribution_day"] = dist
    dist_num = pd.to_numeric(dist.map(lambda v: None if v is None else float(v)), errors="coerce")
    frame["distribution_days_25"] = dist_num.rolling(25, min_periods=25).sum()
    return frame


def health(as_of: date | None, days: int = 250) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        if not db.table_exists(con, "breadth_daily"):
            return unavailable(resolved, "breadth_daily missing", ["breadth_daily"])
        frame = db.cached("market.health", (resolved, days), lambda: _health_frame(con, resolved, days))
    if frame.empty:
        return unavailable(resolved, "breadth_daily has no rows on or before as_of", ["breadth_daily"])
    frame = frame.tail(int(days)).iloc[::-1]
    rows = []
    for r in frame.to_dict("records"):
        rows.append({
            "trade_date": db.to_date(r["trade_date"]),
            "stocks": db.integer(r["stocks"]),
            "advancers": db.integer(r["advancers"]),
            "decliners": db.integer(r["decliners"]),
            "advance_pct": db.num(r["advance_pct"], 2),
            "net_advancers": db.integer(r["net_advancers"]),
            "ad_line_10d": db.integer(r["ad_line_10d"]),
            "pct_above_10ema": db.num(r["above_10ema_pct"], 2),
            "pct_above_20ema": db.num(r["above_20ema_pct"], 2),
            "pct_above_50ema": db.num(r["above_50ema_pct"], 2),
            "pct_above_200ema": db.num(r["above_200ema_pct"], 2),
            "new_52w_highs": db.integer(r["new_52w_highs"]),
            "new_52w_lows": db.integer(r["new_52w_lows"]),
            "net_new_highs": db.integer(r["net_new_highs"]),
            "near_52w_highs": db.integer(r["near_52w_highs"]),
            "stage2_count": db.integer(r["stage2_count"]),
            "nifty50_close": db.num(r["nifty50_close"], 2),
            "nifty50_return_1d_pct": db.num(r["nifty50_return_1d_pct"], 2),
            "midsml400_close": db.num(r["midsml400_close"], 2),
            "midsml400_return_1d_pct": db.num(r["midsml400_return_1d_pct"], 2),
            "india_vix": db.num(r["india_vix"], 2),
            "vix_change_1d_pct": db.num(r["vix_change_1d_pct"], 2),
            "vix_change_5d_pct": db.num(r["vix_change_5d_pct"], 2),
            "distribution_day": db.boolean(r["distribution_day"]),
            "distribution_days_25": db.integer(r["distribution_days_25"]),
            "breadth_state": db.text(r["breadth_state"]),
        })
    return Result(
        as_of=resolved,
        rows=rows,
        sources=["breadth_daily", "indicators_daily", "index_daily"],
        notes=[
            "new_52w_highs/lows count stocks whose session high/low reached the stored 52-week high/low.",
            "distribution day = NIFTY MIDSML 400 down >= 0.2% on higher index turnover than the prior session.",
        ],
        metric_keys=HEALTH_METRICS,
    )
