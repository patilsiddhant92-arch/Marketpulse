"""Shared per-stock snapshot SQL and enrichment used by desk, screener, groups and stock services.

Every value is taken as-is from the warehouse; missing inputs stay NULL.
Point-in-time: all reads are bounded to the requested session (`trade_date = as_of`
or `<= as_of`). Market cap uses the latest `security_reference_daily` row on or
before the session (history starts 2026-07-02) and falls back to the current
`stocks_master` value before that — flagged by `mcap_point_in_time`.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable

from App.services import data_gaps, db

LEVELS = {
    "broad_sector": ("broad_sector", "Broad Sector"),
    "sector": ("sector", "Sector"),
    "broad_industry": ("broad_industry", "Broad Industry"),
    "industry": ("industry", "Industry"),
}
LEVEL_BY_LABEL = {label.lower(): key for key, (_, label) in LEVELS.items()}

FLOORS = {"1000": 1000.0, "all": 0.0, "watch": 300.0}


def level_key(raw: str) -> str | None:
    s = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if s in LEVELS:
        return s
    return LEVEL_BY_LABEL.get(str(raw or "").strip().lower())


def snapshot_sql(con: Any, extra_where: str = "", extra_cols: str = "") -> str:
    """SELECT for one session of stock rows. Params: [as_of] + params for extra_where.

    `extra_where`/`extra_cols` must be built from whitelisted fragments only.
    Multi-session metrics whose window spans an unexplained price gap are NULL and the row carries
    `data_warning` (App/services/data_gaps.py); `extra_cols` can use `data_gaps.guard(...)` likewise.
    """
    data_gaps.register(con)
    g = data_gaps.guard
    has_ref = db.table_exists(con, "security_reference_daily")
    ref_join = (
        "ASOF LEFT JOIN security_reference_daily r ON r.symbol = i.symbol AND i.trade_date >= r.effective_date"
        if has_ref
        else ""
    )
    mcap = "COALESCE(r.market_cap_cr, m.market_cap_cr)" if has_ref else "m.market_cap_cr"
    pit = "(r.market_cap_cr IS NOT NULL)" if has_ref else "FALSE"
    band = "COALESCE(r.price_band, m.band)" if has_ref else "m.band"
    return f"""
        SELECT i.symbol,
               m.security_name,
               m.broad_sector, m.sector, m.broad_industry, m.industry,
               i.series,
               i.trade_date,
               i.close_price AS close,
               i.prev_close,
               {g('(i.close_price / nullif(i.prev_close, 0) - 1) * 100', 'change_1d_pct')} AS change_1d_pct,
               i.volume,
               i.avg_volume_20d,
               i.rvol,
               i.delivery_pct,
               i.delivery_pct / nullif(i.avg_delivery_pct_20d, 0) AS delivery_vs_20d,
               {g('i.rs_percentile', 'rs_percentile')} AS rs_percentile,
               {g('i.rs_percentile_ipo', 'rs_percentile_ipo')} AS rs_percentile_ipo,
               {g('i.rs_percentile - i.rs_rank_t5', 'rs_delta_5')} AS rs_delta_5,
               {g('i.rs_rank_t5', 'rs_rank_t5')} AS rs_rank_t5, {g('i.rs_rank_t15', 'rs_rank_t15')} AS rs_rank_t15,
               {g('i.rs_rank_t30', 'rs_rank_t30')} AS rs_rank_t30,
               {g('i.rs_vs_midsml400_21d', 'excess_vs_midsml400_21d')} AS excess_vs_midsml400_21d,
               {g('i.rs_vs_midsml400_63d', 'excess_vs_midsml400_63d')} AS excess_vs_midsml400_63d,
               {g('i.rs_vs_nifty50_21d', 'excess_vs_nifty50_21d')} AS excess_vs_nifty50_21d,
               {g('i.rs_vs_nifty50_63d', 'excess_vs_nifty50_63d')} AS excess_vs_nifty50_63d,
               {g('i.rs_vs_sector_index_63d', 'rs_vs_sector_index_63d')} AS rs_vs_sector_index_63d,
               i.sector_index_name,
               {g('i.trend_template_pass_n', 'trend_template_pass_n')} AS trend_template_pass_n,
               {g('i.trend_template_pass', 'trend_template_pass')} AS trend_template_pass,
               {g('i.away_52w_high_pct', 'away_52w_high_pct')} AS away_52w_high_pct,
               {g('i.away_52w_low_pct', 'away_52w_low_pct')} AS away_52w_low_pct,
               i.away_10ema_pct,
               i.high_52w_date,
               i.adr_20_pct,
               i.atr_pct,
               {g('i.trend_score', 'trend_score')} AS trend_score,
               {g('i.return_1m_pct', 'return_1m_pct')} AS return_1m_pct,
               {g('i.return_3m_pct', 'return_3m_pct')} AS return_3m_pct,
               {g('i.return_6m_pct', 'return_6m_pct')} AS return_6m_pct,
               i.ema_10, i.ema_20, i.ema_50, i.ema_200,
               i.avg_traded_value_cr_20d AS adv_cr_20d,
               {mcap} AS market_cap_cr,
               {pit} AS mcap_point_in_time,
               {band} AS circuit_band,
               gw.data_warning
               {extra_cols}
        FROM indicators_daily i
        LEFT JOIN stocks_master m ON m.symbol = i.symbol
        {ref_join}
        {data_gaps.lateral_sql()}
        WHERE i.trade_date = ?
          AND upper(i.symbol) <> 'TOTAL'
          {extra_where}
    """


def shape_stock(r: dict[str, Any]) -> dict[str, Any]:
    """Common stock columns (NULL stays NULL)."""
    return {
        "symbol": db.text(r.get("symbol")),
        "security_name": db.text(r.get("security_name")),
        "broad_sector": db.text(r.get("broad_sector")),
        "sector": db.text(r.get("sector")),
        "broad_industry": db.text(r.get("broad_industry")),
        "industry": db.text(r.get("industry")),
        "close": db.num(r.get("close"), 2),
        "change_1d_pct": db.num(r.get("change_1d_pct"), 2),
        "rvol": db.num(r.get("rvol"), 2),
        "delivery_pct": db.num(r.get("delivery_pct"), 1),
        "delivery_vs_20d": db.num(r.get("delivery_vs_20d"), 2),
        "rs_percentile": db.num(r.get("rs_percentile"), 1),
        "rs_delta_5": db.num(r.get("rs_delta_5"), 1),
        "excess_vs_midsml400_63d": db.num(r.get("excess_vs_midsml400_63d"), 2),
        "market_cap_cr": db.num(r.get("market_cap_cr"), 0),
        "adv_cr_20d": db.num(r.get("adv_cr_20d"), 2),
        "data_warning": db.text(r.get("data_warning")),
    }


def _in_list(symbols: Iterable[str]) -> tuple[str, list[str]]:
    syms = sorted({str(s) for s in symbols if s})
    return ",".join(["?"] * len(syms)), syms


def upcoming_events(con: Any, symbols: Iterable[str], as_of: date, days: int = 14) -> dict[str, dict[str, Any]]:
    """Next results / board meeting within `days` calendar days after as_of (≈10 sessions)."""
    ph, syms = _in_list(symbols)
    if not syms or not db.table_exists(con, "security_events"):
        return {}
    rows = db.records(
        con,
        f"""
        SELECT symbol, min(event_date) AS event_date, arg_min(event_type, event_date) AS event_type
        FROM security_events
        WHERE symbol IN ({ph})
          AND event_type IN ('financial_results', 'board_meeting')
          AND event_date > ? AND event_date <= ?
        GROUP BY symbol
        """,
        [*syms, as_of, as_of + timedelta(days=days)],
    )
    return {r["symbol"]: {"event_type": r["event_type"], "event_date": db.to_date(r["event_date"])} for r in rows}


def collapsed_prints_sql(where: str) -> str:
    """One row per print (bulk ∩ block duplicates collapsed, spec §4.4). `where` uses alias d."""
    return f"""
        SELECT trade_date, symbol, upper(trim(client_name)) AS client, upper(side) AS side, quantity, price,
               any_value(COALESCE(deal_value_cr, quantity * price / 1e7)) AS value_cr,
               string_agg(DISTINCT deal_type, '+') AS deal_types,
               any_value(clientele) AS clientele,
               bool_or(COALESCE(is_prop, FALSE)) AS is_prop,
               any_value(close_price) AS close_price
        FROM deals d
        WHERE upper(d.symbol) <> 'TOTAL' {where}
        GROUP BY trade_date, symbol, upper(trim(client_name)), upper(side), quantity, price
    """


def deal_net_recent(con: Any, symbols: Iterable[str], as_of: date, sessions: int = 10,
                    exclude_prop: bool = False) -> dict[str, float | None]:
    """Net (buy − sell) ₹Cr of collapsed deal prints over the last `sessions` sessions <= as_of.

    `exclude_prop` drops PROP (proprietary / churn) clients, as group_daily and deal_session_net do."""
    ph, syms = _in_list(symbols)
    if not syms or not db.table_exists(con, "deals"):
        return {}
    window = db.recent_sessions(con, as_of, sessions)
    if not window:
        return {}
    start = window[-1]
    rows = db.records(
        con,
        f"""
        WITH p AS ({collapsed_prints_sql("AND d.symbol IN (" + ph + ") AND d.trade_date BETWEEN ? AND ?")})
        SELECT symbol, sum(CASE WHEN side LIKE '%BUY%' THEN value_cr WHEN side LIKE '%SELL%' THEN -value_cr END) AS net_cr
        FROM p {"WHERE coalesce(upper(clientele), '') <> 'PROP' AND NOT is_prop" if exclude_prop else ""} GROUP BY symbol
        """,
        [*syms, start, as_of],
    )
    return {r["symbol"]: db.num(r["net_cr"], 2) for r in rows}


def industry_quadrants(con: Any, as_of: date) -> dict[str, dict[str, Any]]:
    """Industry-level RRG quadrant per industry name from group_daily (empty if not built)."""
    if not db.table_exists(con, "group_daily"):
        return {}
    cols = set(db.table_columns(con, "group_daily"))
    name_col = next((c for c in ("group_name", "name", "group_id") if c in cols), None)
    quad_col = next((c for c in ("rrg_quadrant", "quadrant") if c in cols), None)
    if not name_col or not quad_col or "level" not in cols or "trade_date" not in cols:
        return {}
    floor_clause = ""
    params: list[Any] = [as_of]
    if "floor" in cols:
        floor_clause = "AND CAST(floor AS VARCHAR) IN ('1000', '1000cr', 'default')"
    rows = db.records(
        con,
        f"""
        SELECT {db.quote_ident(name_col)} AS name, {db.quote_ident(quad_col)} AS quadrant
        FROM group_daily
        WHERE trade_date = (SELECT max(trade_date) FROM group_daily WHERE trade_date <= ?)
          AND lower(CAST(level AS VARCHAR)) = 'industry' {floor_clause}
        """,
        params,
    )
    return {str(r["name"]): {"quadrant": db.text(r["quadrant"])} for r in rows}
