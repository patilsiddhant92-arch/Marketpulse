"""Serving guard for unexplained price gaps (relistings, missed splits / bonuses / consolidations).

A *gap event* for a symbol is a session where its (adjusted) close jumped in a way no applied
corporate action explains:

  1. a `price_adjustments` row that was NOT applied to prices and is either
     ``kind = 'unexplained_gap'`` or ``confidence = 'unconfirmed'`` (the adjustment pipeline's own
     0.6 / 1.6 close-ratio detector, plus unconfirmed bonuses) — mapped to the symbol's first
     session on/after ``ex_date``; or
  2. the ratio guard: a 1-day move <= SPLIT_DOWN or >= SPLIT_UP on the adjusted close (the same
     rule and constants as Scripts/derived/group_daily.py and App/services/groups.py), unless a
     ``confidence = 'reviewed'`` row (override ``kind: ignore`` — a genuine move) sits within
     REVIEWED_WINDOW_DAYS of it.

Every multi-session metric whose window spans a gap event is served as NULL (the UI shows "—"),
so rules on it fail closed and sorts put the stock last. The window of a metric over ``h``
sessions at session t spans a gap at session g when g <= t <= g + h - 1, counted in the
symbol's own sessions (the way indicators_daily computes it). Rows inside any such window carry
``data_warning`` text naming the gap(s).

The events are computed once per database file (fingerprint-keyed cache) and registered on the
connection as the relation ``gap_windows``; `universe.snapshot_sql` joins it.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from App.services import db
from Scripts.derived.group_daily import SPLIT_DOWN, SPLIT_UP

log = logging.getLogger(__name__)

RELATION = "gap_windows"
REVIEWED_WINDOW_DAYS = 5
FAR_FUTURE = pd.Timestamp("2262-01-01")

# Metric (snapshot column name) -> window length in the symbol's own sessions.
# RS percentile is a trailing-year ranking; rs_rank_tN is that ranking N sessions ago.
METRIC_SESSIONS: dict[str, int] = {
    "change_1d_pct": 1,
    "return_1m_pct": 21, "excess_vs_midsml400_21d": 21, "excess_vs_nifty50_21d": 21, "rs_vs_sector_index_21d": 21,
    "return_3m_pct": 63, "excess_vs_midsml400_63d": 63, "excess_vs_nifty50_63d": 63, "rs_vs_sector_index_63d": 63,
    "return_6m_pct": 126,
    "rs_percentile": 252, "rs_percentile_ipo": 252, "away_52w_high_pct": 252, "away_52w_low_pct": 252,
    "trend_template_pass": 252, "trend_template_pass_n": 252, "trend_score": 252,
    "rs_rank_t5": 257, "rs_delta_5": 257, "rs_rank_t15": 267, "rs_rank_t30": 282,
}
HORIZONS: tuple[int, ...] = tuple(sorted(set(METRIC_SESSIONS.values())))
MAX_H = HORIZONS[-1]
COLUMNS = ["symbol", "gap_date", "ratio", "source", "label", *(f"end_{h}" for h in HORIZONS)]


def guard(expr: str, metric: str, row_alias: str = "i") -> str:
    """SQL: `expr`, or NULL when the row's `metric` window spans a gap (needs the `gw` lateral)."""
    h = METRIC_SESSIONS[metric]
    return f"CASE WHEN gw.e{h} >= {row_alias}.trade_date THEN NULL ELSE {expr} END"


def lateral_sql(row_alias: str = "i") -> str:
    """LEFT JOIN LATERAL giving, per row, the latest window end per horizon and the warning text."""
    ends = ", ".join(f"max(g.end_{h}) AS e{h}" for h in HORIZONS)
    return f"""
        LEFT JOIN LATERAL (
            SELECT {ends}, string_agg(g.label, '; ' ORDER BY g.gap_date) AS data_warning
            FROM {RELATION} g
            WHERE g.symbol = {row_alias}.symbol AND g.gap_date <= {row_alias}.trade_date
              AND g.end_{MAX_H} >= {row_alias}.trade_date
        ) gw ON TRUE"""


def _empty() -> pd.DataFrame:
    frame = pd.DataFrame({c: pd.Series(dtype="object") for c in ("symbol", "source", "label")})
    frame["gap_date"] = pd.Series(dtype="datetime64[ns]")
    frame["ratio"] = pd.Series(dtype="float64")
    for h in HORIZONS:
        frame[f"end_{h}"] = pd.Series(dtype="datetime64[ns]")
    return frame[COLUMNS]


def label(ratio: float | None, gap_date: Any, source: str) -> str:
    day = pd.Timestamp(gap_date).date().isoformat()
    if ratio is None or pd.isna(ratio) or ratio <= 0:
        what, mult = "unexplained price gap", "ratio unknown"
    else:
        what = "unexplained price jump" if ratio > 1 else "unexplained price drop"
        mult = f"×{ratio:.0f}" if ratio >= 10 else f"×{ratio:.2f}"
    if source == "price_adjustments:bonus":
        what = "unconfirmed bonus / price gap"
    return f"{what} on {day} ({mult}); returns across it hidden"


def compute(con: Any) -> pd.DataFrame:
    """Gap events with their window ends (one row per symbol + gap session)."""
    if not db.table_exists(con, "indicators_daily"):
        return _empty()
    have_pa = db.table_exists(con, "price_adjustments") and {
        "symbol", "ex_date", "kind", "confidence", "applied"} <= set(db.table_columns(con, "price_adjustments"))
    leads = ", ".join(
        f"lead(trade_date, {h - 1}) OVER w AS end_{h}" if h > 1 else "trade_date AS end_1" for h in HORIZONS)
    ends = ", ".join(f"end_{h}" for h in HORIZONS)
    pa_cte = ""
    pa_union = ""
    reviewed = ""
    if have_pa:
        pa_cte = """,
        pa AS (
            SELECT CAST(symbol AS VARCHAR) AS symbol, CAST(ex_date AS TIMESTAMP) AS ex_date,
                   'price_adjustments:' || CASE WHEN kind = 'unexplained_gap' THEN 'unexplained_gap'
                                                ELSE CAST(kind AS VARCHAR) END AS source
            FROM price_adjustments
            WHERE NOT COALESCE(applied, FALSE) AND ex_date IS NOT NULL
              AND ((kind = 'unexplained_gap' AND confidence IS DISTINCT FROM 'reviewed') OR confidence = 'unconfirmed')
        ),
        pa_rows AS (
            SELECT x.*, pa.source FROM pa ASOF JOIN x ON pa.symbol = x.symbol AND pa.ex_date <= x.trade_date
        )"""
        pa_union = (f"UNION ALL SELECT symbol, trade_date, close_price / nullif(pc, 0) AS ratio, source, {ends} "
                    "FROM pa_rows")
        reviewed = f"""
            AND NOT EXISTS (
                SELECT 1 FROM price_adjustments r
                WHERE CAST(r.symbol AS VARCHAR) = x.symbol AND r.confidence = 'reviewed'
                  AND abs(date_diff('day', CAST(r.ex_date AS DATE), CAST(x.trade_date AS DATE)))
                      <= {REVIEWED_WINDOW_DAYS})"""
    sql = f"""
        WITH x AS (
            SELECT CAST(symbol AS VARCHAR) AS symbol, trade_date, close_price,
                   lag(close_price) OVER w AS pc, {leads}
            FROM indicators_daily
            WHERE upper(symbol) <> 'TOTAL'
            WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
        ){pa_cte},
        ev AS (
            SELECT symbol, trade_date, close_price / pc AS ratio, 'ratio_guard' AS source, {ends}
            FROM x
            WHERE pc > 0 AND (close_price / pc - 1 <= {SPLIT_DOWN} OR close_price / pc - 1 >= {SPLIT_UP}) {reviewed}
            {pa_union}
        )
        SELECT symbol, trade_date AS gap_date, any_value(ratio) AS ratio,
               min(source) AS source, {', '.join(f'max(end_{h}) AS end_{h}' for h in HORIZONS)}
        FROM ev GROUP BY symbol, trade_date
        ORDER BY symbol, gap_date
    """
    frame = con.execute(sql).fetchdf()
    if frame.empty:
        return _empty()
    frame["gap_date"] = pd.to_datetime(frame["gap_date"])
    for h in HORIZONS:
        frame[f"end_{h}"] = pd.to_datetime(frame[f"end_{h}"]).fillna(FAR_FUTURE)
    frame["ratio"] = pd.to_numeric(frame["ratio"], errors="coerce")
    frame["label"] = [label(r, d, s) for r, d, s in zip(frame["ratio"], frame["gap_date"], frame["source"])]
    frame["symbol"] = frame["symbol"].astype(str)
    return frame[COLUMNS].reset_index(drop=True)


def events(con: Any) -> pd.DataFrame:
    """Cached gap events for the current database file (empty frame on any failure — fail-soft)."""
    def _compute() -> pd.DataFrame:
        try:
            return compute(con)
        except Exception as exc:  # noqa: BLE001 - the guard must never break serving
            log.warning("data gap guard unavailable: %s", exc)
            return _empty()
    return db.cached("data_gaps.events", (), _compute)


def register(con: Any) -> None:
    """Register `gap_windows` on `con` (idempotent)."""
    con.register(RELATION, events(con))
