"""Momentum scanner (the user's main scanner) — v2 port of the old `/api/screener/momentum`.

Parity first: the predicate is the old endpoint's SQL, clause for clause (App/api/server.py at d871ff9),
with the same parameters and defaults:

* trigger clauses are evaluated on ANY session in the last `lookback_days` sessions (global calendar,
  sessions <= as_of); `trigger_date` is the latest such session;
* current clauses are evaluated on the latest session (as_of);
* coil bucket by `away_10ema_pct`: 0_2% / 2_5% / 5_10% / 10%+ / Below 10EMA, rows ordered by bucket then
  distance;
* `buckets_tv` = ``###0_2%,NSE:A,NSE:B,###2_5%,…`` (dash → underscore; "Below 10EMA" not exported);
* leaders: sectors / industries by stock count, ties by average strength rank, top 3, each with a
  TradingView string.

The old filters' own NULL semantics are kept on purpose (e.g. an unknown 200 EMA passes "close > 200 EMA",
an unknown % above the 52W low passes) because they define the user's proven list. What changed is output
honesty: values are never replaced by defaults (the old `_sanitize_float` turned a missing RVOL into 1.0,
a missing market cap / 52W distance into 0); missing taxonomy is NULL (shown "Unclassified") instead of
"General"; multi-session display metrics whose window spans an unexplained price gap are NULL with
`data_warning` (App/services/data_gaps.py). Every user value is a bound parameter; clause text is fixed.

Improvements on top: New / Dropped vs the previous session, Health zone + quadrant for each leader
(context.group_map), a per-clause breakdown for the debug symbol, and per-bucket forward-return evidence
(`evidence`, computed from 5 years of point-in-time history and cached per database file).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from App.services import context, data_gaps, db
from App.services.common import Result, no_session, unavailable

BUCKETS = ("0_2%", "2_5%", "5_10%", "10%+", "Below 10EMA")
TV_BUCKETS = BUCKETS[:4]
UNCLASSIFIED = "Unclassified"
LOOKBACK_CHOICES = (1, 3, 5, 10, 20, 30)
MOMENTUM_METRICS = ["away_10ema_pct", "rs_percentile", "change_1d_pct", "rvol", "delivery_pct", "away_52w_high_pct",
                    "away_52w_low_pct", "market_cap_cr"]
SOURCES = ["indicators_daily", "stocks_master"]

BUCKET_SQL = """CASE
    WHEN {a}.away_10ema_pct >= 0 AND {a}.away_10ema_pct <= 2 THEN '0_2%'
    WHEN {a}.away_10ema_pct > 2 AND {a}.away_10ema_pct <= 5 THEN '2_5%'
    WHEN {a}.away_10ema_pct > 5 AND {a}.away_10ema_pct <= 10 THEN '5_10%'
    WHEN {a}.away_10ema_pct > 10 THEN '10%+'
    ELSE 'Below 10EMA' END"""
BUCKET_RANK_SQL = """CASE
    WHEN {a}.away_10ema_pct >= 0 AND {a}.away_10ema_pct <= 2 THEN 1
    WHEN {a}.away_10ema_pct > 2 AND {a}.away_10ema_pct <= 5 THEN 2
    WHEN {a}.away_10ema_pct > 5 AND {a}.away_10ema_pct <= 10 THEN 3
    WHEN {a}.away_10ema_pct > 10 THEN 4
    ELSE 5 END"""


@dataclass(frozen=True)
class Params:
    """Old endpoint parameters and defaults (the old React UI sent limit=300)."""

    lookback_days: int = 20
    min_mcap_cr: float = 1000.0
    min_volume: float = 1_000_000.0
    min_avg_volume_20d: float = 0.0
    max_52w_away_pct: float = 25.0
    min_52w_low_pct: float = 50.0
    cmp_gt_10: bool = True
    cmp_gt_200: bool = True
    ohlc_gt_10: bool = False
    ohlc_gt_20: bool = False
    ema10_gt_20: bool = True
    ema20_gt_50: bool = True
    ema50_gt_100: bool = True
    ema100_gt_200: bool = True
    sma50_gt_150: bool = False
    sma150_gt_200: bool = False
    sma_cmp_gt_50: bool = False
    sma_cmp_gt_150_200: bool = False
    sma200_rising: bool = False
    delivery_thrust: bool = False
    coiling_nr7: bool = False
    weekly_rsi_60: bool = False

    def normalised(self) -> "Params":
        return Params(**{**asdict(self), "lookback_days": max(1, min(90, int(self.lookback_days)))})

    def is_default(self) -> bool:
        return self.normalised() == Params()


Clause = tuple[str, str, list[Any]]  # (label, SQL over alias {a} / m, bound params)


def _vol_label(v: float) -> str:
    return f"{v / 1e5:g}L" if v >= 1e5 else f"{v:,.0f}"


def trigger_clauses(p: Params) -> list[Clause]:
    """Old `trigger_where`, clause for clause (alias i)."""
    out: list[Clause] = [("Close > ₹15", "i.close_price > 15.0", [])]
    if p.min_mcap_cr > 0:
        out.append((f"Market cap ≥ ₹{p.min_mcap_cr:,.0f} Cr", "COALESCE(m.market_cap_cr, 0.0) >= ?", [float(p.min_mcap_cr)]))
    if p.min_volume > 0:
        out.append((f"Day volume ≥ {_vol_label(p.min_volume)}", "i.volume >= ?", [float(p.min_volume)]))
    elif p.min_avg_volume_20d > 0:
        # Old behaviour: the 20D-avg gate also requires that session's own volume to clear the threshold.
        out.append((f"Day volume ≥ {_vol_label(p.min_avg_volume_20d)} (20D-avg gate)", "i.volume >= ?",
                    [float(p.min_avg_volume_20d)]))
    if p.max_52w_away_pct < 99.0:
        out.append((f"Within {abs(p.max_52w_away_pct):g}% of 52W high", "i.away_52w_high_pct >= ?",
                    [-abs(float(p.max_52w_away_pct))]))
    if p.min_52w_low_pct > 0:
        out.append((f"≥ {p.min_52w_low_pct:g}% above 52W low (unknown passes)", "COALESCE(i.away_52w_low_pct, 999.0) >= ?",
                    [float(p.min_52w_low_pct)]))
    if p.cmp_gt_10:
        out.append(("Close ≥ 10 EMA", "(i.away_10ema_pct IS NOT NULL AND i.away_10ema_pct >= 0)", []))
    if p.cmp_gt_200:
        out.append(("Close > 200 EMA (unknown passes)", "(i.ema_200 IS NULL OR i.close_price > i.ema_200)", []))
    if p.ohlc_gt_10:
        out.append(("Whole bar > 10 EMA", "(i.ema_10 IS NOT NULL AND i.open_price > i.ema_10 AND i.high_price > i.ema_10 "
                                          "AND i.low_price > i.ema_10 AND i.close_price > i.ema_10)", []))
    if p.ohlc_gt_20:
        out.append(("Whole bar > 20 EMA", "(i.ema_20 IS NOT NULL AND i.open_price > i.ema_20 AND i.high_price > i.ema_20 "
                                          "AND i.low_price > i.ema_20 AND i.close_price > i.ema_20)", []))
    out.extend(_stack_clauses(p, "i"))
    if p.delivery_thrust:
        out.append(("Delivery spike with price up on rising delivery",
                    "(i.delivery_spike = true AND i.price_up_delivery_up = true)", []))
    return out


def _stack_clauses(p: Params, a: str) -> list[Clause]:
    out: list[Clause] = []
    for on, x, y in ((p.ema10_gt_20, "ema_10", "ema_20"), (p.ema20_gt_50, "ema_20", "ema_50"),
                     (p.ema50_gt_100, "ema_50", "ema_100"), (p.ema100_gt_200, "ema_100", "ema_200")):
        if on:
            out.append((f"{x.replace('_', ' ').upper()} > {y.replace('_', ' ').upper()} (unknown passes)",
                        f"({a}.{x} IS NULL OR {a}.{y} IS NULL OR {a}.{x} > {a}.{y})", []))
    if p.sma50_gt_150:
        out.append(("SMA 50 > SMA 150 (unknown passes)", f"({a}.sma_50 IS NULL OR {a}.sma_150 IS NULL OR {a}.sma_50 > {a}.sma_150)", []))
    if p.sma150_gt_200:
        out.append(("SMA 150 > SMA 200 (unknown passes)",
                    f"({a}.sma_150 IS NULL OR {a}.sma_200 IS NULL OR {a}.sma_150 > {a}.sma_200)", []))
    if p.sma_cmp_gt_50:
        out.append(("Close > SMA 50 (unknown passes)", f"({a}.sma_50 IS NULL OR {a}.close_price > {a}.sma_50)", []))
    if p.sma_cmp_gt_150_200:
        out.append(("Close > SMA 150 & 200 (unknown passes)",
                    f"(({a}.sma_150 IS NULL OR {a}.close_price > {a}.sma_150) AND "
                    f"({a}.sma_200 IS NULL OR {a}.close_price > {a}.sma_200))", []))
    if p.sma200_rising:
        out.append(("SMA 200 rising", f"({a}.sma_200_rising IS TRUE)", []))
    return out


def current_clauses(p: Params, vcp_col: str = "c.vcp_score", a: str = "c") -> list[Clause]:
    """Old `current_where`, clause for clause (alias c)."""
    out: list[Clause] = [("Close > ₹15", f"{a}.close_price > 15.0", [])]
    if p.min_mcap_cr > 0:
        out.append((f"Market cap ≥ ₹{p.min_mcap_cr:,.0f} Cr", "COALESCE(m.market_cap_cr, 0.0) >= ?", [float(p.min_mcap_cr)]))
    if p.min_avg_volume_20d > 0:
        out.append((f"20D avg volume ≥ {_vol_label(p.min_avg_volume_20d)}", f"{a}.avg_volume_20d >= ?",
                    [float(p.min_avg_volume_20d)]))
    if p.max_52w_away_pct < 99.0:
        out.append((f"Within {abs(p.max_52w_away_pct):g}% of 52W high", f"{a}.away_52w_high_pct >= ?",
                    [-abs(float(p.max_52w_away_pct))]))
    if p.min_52w_low_pct > 0:
        out.append((f"≥ {p.min_52w_low_pct:g}% above 52W low (unknown passes)",
                    f"COALESCE({a}.away_52w_low_pct, 999.0) >= ?", [float(p.min_52w_low_pct)]))
    if p.cmp_gt_10:
        out.append(("Close ≥ 10 EMA", f"({a}.away_10ema_pct IS NOT NULL AND {a}.away_10ema_pct >= 0)", []))
    if p.cmp_gt_200:
        out.append(("Close > 200 EMA (unknown passes)", f"({a}.ema_200 IS NULL OR {a}.close_price > {a}.ema_200)", []))
    out.extend(_stack_clauses(p, a))
    if p.delivery_thrust:
        out.append(("Close > 20 EMA", f"({a}.close_price > {a}.ema_20)", []))
    if p.coiling_nr7:
        out.append(("NR7 or inside bar with VCP score ≥ 40",
                    f"(({a}.nr7 = true OR {a}.inside_bar = true) AND COALESCE({vcp_col}, 0) >= 40)", []))
    if p.weekly_rsi_60:
        out.append(("Daily RSI ≥ 60 and weekly RSI ≥ 60 (unknown weekly = 50)",
                    f"({a}.rsi_14 >= 60 AND COALESCE({a}.rsi_14_w, 50) >= 60)", []))
    return out


def _joined(clauses: list[Clause]) -> tuple[str, list[Any]]:
    return " AND ".join(sql for _, sql, _ in clauses), [v for _, _, vals in clauses for v in vals]


def _opt_col(cols: set[str], name: str, alias: str = "c") -> str:
    return f"{alias}.{name}" if name in cols else "NULL"


def _scan(con: Any, as_of: date, p: Params, symbol: str | None = None) -> list[dict[str, Any]]:
    """Rows passing the old predicate on `as_of` (the old SQL, parameterised)."""
    cols = set(db.table_columns(con, "indicators_daily"))
    trig = trigger_clauses(p)
    cur = current_clauses(p, _opt_col(cols, "vcp_score"))
    if symbol:
        trig = [*trig, ("Symbol", "i.symbol = ?", [symbol])]
        cur = [*cur, ("Symbol", "c.symbol = ?", [symbol])]
    trig_sql, trig_params = _joined(trig)
    cur_sql, cur_params = _joined(cur)
    data_gaps.register(con)
    g = lambda expr, metric: data_gaps.guard(expr, metric, "c")  # noqa: E731 - local shorthand
    ret5 = _opt_col(cols, "return_5d_pct")
    sql = f"""
        WITH dates AS (
            SELECT DISTINCT trade_date FROM indicators_daily WHERE trade_date <= ?
            ORDER BY trade_date DESC LIMIT ?
        ),
        bounds AS (SELECT min(trade_date) AS min_d, max(trade_date) AS max_d FROM dates),
        trigger_hits AS (
            SELECT i.symbol, max(i.trade_date) AS trigger_date,
                   bool_or(COALESCE(i.delivery_spike, false)) AS trigger_delivery_spike
            FROM indicators_daily i
            JOIN bounds b ON i.trade_date BETWEEN b.min_d AND b.max_d
            JOIN stocks_master m USING (symbol)
            WHERE {trig_sql}
              AND upper(i.symbol) <> 'TOTAL'  -- aggregate row from the mcap file (never a stock)
            GROUP BY i.symbol
        )
        SELECT c.symbol, trigger_hits.trigger_date, trigger_hits.trigger_delivery_spike,
               m.security_name, m.broad_sector, m.sector, m.broad_industry, m.industry,
               c.trade_date, c.close_price AS close,
               {g('ROUND(((c.close_price - c.prev_close) / NULLIF(c.prev_close, 0)) * 100, 2)', 'change_1d_pct')} AS change_1d_pct,
               {g(ret5, 'return_1m_pct')} AS return_5d_pct,
               {g('c.return_1m_pct', 'return_1m_pct')} AS return_1m_pct,
               {g('c.return_3m_pct', 'return_3m_pct')} AS return_3m_pct,
               {g('c.rs_percentile', 'rs_percentile')} AS rs_percentile,
               c.rs_percentile AS rs_raw,
               ROUND(c.away_10ema_pct, 2) AS away_10ema_pct,
               {BUCKET_SQL.format(a='c')} AS bucket,
               {BUCKET_RANK_SQL.format(a='c')} AS bucket_rank,
               {g('c.away_52w_high_pct', 'away_52w_high_pct')} AS away_52w_high_pct,
               {g('c.away_52w_low_pct', 'away_52w_low_pct')} AS away_52w_low_pct,
               c.volume, c.avg_volume_20d, c.rvol, c.delivery_pct,
               m.market_cap_cr,
               c.ema_10, c.ema_20, c.ema_50, c.ema_200,
               c.delivery_spike, c.nr7, c.inside_bar,
               gw.data_warning
        FROM indicators_daily c
        JOIN trigger_hits USING (symbol)
        JOIN bounds b ON c.trade_date = b.max_d
        LEFT JOIN stocks_master m ON c.symbol = m.symbol
        {data_gaps.lateral_sql('c')}
        WHERE {cur_sql}
        ORDER BY {BUCKET_RANK_SQL.format(a='c')} ASC, c.away_10ema_pct ASC, c.symbol
    """
    params = [as_of, int(p.lookback_days), *trig_params, *cur_params]
    assert sql.count("?") == len(params), "momentum SQL placeholders out of sync"
    return db.records(con, sql, params)


def _bullish_stack(r: dict[str, Any]) -> bool | None:
    vals = [db.num(r.get(k)) for k in ("ema_10", "ema_20", "ema_50", "ema_200")]
    if any(v is None for v in vals):
        return None
    return bool(vals[0] > vals[1] > vals[2] > vals[3])


def _any_true(*vals: Any) -> bool | None:
    known = [db.boolean(v) for v in vals]
    if any(v is True for v in known):
        return True
    return False if all(v is not None for v in known) else None


def shape(r: dict[str, Any], prev_syms: set[str] | None) -> dict[str, Any]:
    sym = db.text(r.get("symbol"))
    return {
        "symbol": sym,
        "security_name": db.text(r.get("security_name")),
        "broad_sector": db.text(r.get("broad_sector")),
        "sector": db.text(r.get("sector")),
        "broad_industry": db.text(r.get("broad_industry")),
        "industry": db.text(r.get("industry")),
        "trigger_date": db.to_date(r.get("trigger_date")),
        "bucket": db.text(r.get("bucket")),
        "bucket_rank": db.integer(r.get("bucket_rank")),
        "close": db.num(r.get("close"), 2),
        "change_1d_pct": db.num(r.get("change_1d_pct"), 2),
        "return_5d_pct": db.num(r.get("return_5d_pct"), 2),
        "return_1m_pct": db.num(r.get("return_1m_pct"), 2),
        "return_3m_pct": db.num(r.get("return_3m_pct"), 2),
        "rs_percentile": db.num(r.get("rs_percentile"), 1),
        "away_10ema_pct": db.num(r.get("away_10ema_pct"), 2),
        "away_52w_high_pct": db.num(r.get("away_52w_high_pct"), 2),
        "away_52w_low_pct": db.num(r.get("away_52w_low_pct"), 2),
        "volume": db.integer(r.get("volume")),
        "avg_volume_20d": db.integer(r.get("avg_volume_20d")),
        "rvol": db.num(r.get("rvol"), 2),
        "delivery_pct": db.num(r.get("delivery_pct"), 1),
        "market_cap_cr": db.num(r.get("market_cap_cr"), 0),
        "bullish_stack": _bullish_stack(r),
        "delivery_spike": _any_true(r.get("delivery_spike"), r.get("trigger_delivery_spike")),
        "coiling": _any_true(r.get("nr7"), r.get("inside_bar")),
        "is_new": (sym not in prev_syms) if prev_syms is not None else None,
        "data_warning": db.text(r.get("data_warning")),
    }


def tv_symbol(sym: str) -> str:
    return f"NSE:{sym.strip().upper().replace('-', '_')}"


def tv_string(symbols: list[str]) -> str:
    return ",".join(tv_symbol(s) for s in symbols)


def buckets_tv(rows: list[dict[str, Any]]) -> str:
    parts = []
    for label in TV_BUCKETS:
        syms = list(dict.fromkeys(r["symbol"] for r in rows if r["bucket"] == label and r["symbol"]))
        if syms:
            parts.append(f"###{label}," + tv_string(syms))
    return ",".join(parts)


def bucket_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for label in BUCKETS:
        syms = [r["symbol"] for r in rows if r["bucket"] == label and r["symbol"]]
        out.append({"bucket": label, "count": len(syms), "symbols": syms, "tv_str": tv_string(syms),
                    "new_count": sum(1 for r in rows if r["bucket"] == label and r.get("is_new"))})
    return out


def _mean(vals: list[float | None]) -> float | None:
    xs = [v for v in vals if v is not None and not math.isnan(v)]
    return round(sum(xs) / len(xs), 1) if xs else None


def leaders(rows: list[dict[str, Any]], raw_rs: dict[str, float | None], key: str,
            ctx: dict[str, dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Groups by count desc, ties by average strength rank desc, then name (old ordering)."""
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for r in rows:
        sector = r["sector"] or UNCLASSIFIED
        name = r[key] or UNCLASSIFIED
        gkey = (sector,) if key == "sector" else (sector, name)
        groups.setdefault(gkey, []).append(r)
    out = []
    for gkey in sorted(groups):
        members = groups[gkey]
        syms = list(dict.fromkeys(m["symbol"] for m in members if m["symbol"]))
        name = gkey[-1]
        row = {
            key: name,
            "sector": gkey[0],
            "stock_count": len(syms),
            "avg_rs": _mean([raw_rs.get(s) for s in syms]),
            "symbols": syms,
            "tv_str": tv_string(syms),
            "new_count": sum(1 for m in members if m.get("is_new")),
            "group": (ctx or {}).get(name) if name != UNCLASSIFIED else None,
        }
        out.append(row)
    out.sort(key=lambda x: (x["stock_count"], x["avg_rs"] if x["avg_rs"] is not None else -1.0), reverse=True)
    return out


def _group_ctx(con: Any, as_of: date, level: str) -> dict[str, dict[str, Any]] | None:
    try:
        gm, _ = context.group_map(con, as_of, level, "1000")
        return gm
    except Exception:  # noqa: BLE001 - leader context is decoration; the scan must not fail on it
        return None


def _debug(con: Any, as_of: date, p: Params, symbol: str) -> dict[str, Any]:
    """Per-clause breakdown for one symbol: trigger clauses (sessions passing in the window) + current clauses."""
    cols = set(db.table_columns(con, "indicators_daily"))
    sessions = db.recent_sessions(con, as_of, int(p.lookback_days))
    if not sessions:
        return {"symbol": symbol, "checks": []}
    start = sessions[-1]
    checks: list[dict[str, Any]] = []
    for label, sql, vals in trigger_clauses(p):
        n = con.execute(
            f"SELECT count(*) FILTER (WHERE ({sql}) IS TRUE), count(*) FROM indicators_daily i "
            f"LEFT JOIN stocks_master m USING (symbol) WHERE i.symbol = ? AND i.trade_date BETWEEN ? AND ?",
            [*vals, symbol, start, as_of]).fetchone()
        checks.append({"stage": "trigger", "label": label, "passed": bool(n and n[0]),
                       "detail": f"{n[0]} of {n[1]} sessions" if n else None})
    all_sql, all_vals = _joined(trigger_clauses(p))
    n_all = con.execute(
        f"SELECT count(*) FILTER (WHERE ({all_sql}) IS TRUE), max(i.trade_date) FILTER (WHERE ({all_sql}) IS TRUE) "
        f"FROM indicators_daily i JOIN stocks_master m USING (symbol) WHERE i.symbol = ? AND i.trade_date BETWEEN ? AND ?",
        [*all_vals, *all_vals, symbol, start, as_of]).fetchone()
    checks.append({"stage": "trigger", "label": f"All trigger conditions on one session (last {len(sessions)})",
                   "passed": bool(n_all and n_all[0]),
                   "detail": f"latest {db.to_date(n_all[1])}" if n_all and n_all[1] else "never in the window"})
    for label, sql, vals in current_clauses(p, _opt_col(cols, "vcp_score")):
        row = con.execute(
            f"SELECT ({sql}) IS TRUE FROM indicators_daily c LEFT JOIN stocks_master m USING (symbol) "
            f"WHERE c.symbol = ? AND c.trade_date = ?", [*vals, symbol, as_of]).fetchone()
        checks.append({"stage": "current", "label": label, "passed": bool(row and row[0]),
                       "detail": None if row else f"no row on {as_of.isoformat()}"})
    return {"symbol": symbol, "checks": checks}


def run(as_of: date | None, p: Params, debug_symbol: str | None = None) -> Result:
    p = p.normalised()
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        if not db.table_exists(con, "stocks_master"):
            return unavailable(resolved, "stocks_master missing", SOURCES)

        def compute() -> tuple[list[dict[str, Any]], dict[str, float | None], list[dict[str, Any]], date | None]:
            recs = _scan(con, resolved, p)
            prev = db.session_back(con, resolved, 1)
            prev_recs = _scan(con, prev, p) if prev else None
            prev_syms = {str(r["symbol"]) for r in prev_recs} if prev_recs is not None else None
            shaped = [shape(r, prev_syms) for r in recs]
            raw_rs = {str(r["symbol"]): db.num(r.get("rs_raw")) for r in recs}
            today = {r["symbol"] for r in shaped}
            dropped = [{"symbol": db.text(r["symbol"]), "bucket": db.text(r["bucket"]),
                        "industry": db.text(r.get("industry")), "close": db.num(r.get("close"), 2),
                        "rs_percentile": db.num(r.get("rs_percentile"), 1)}
                       for r in (prev_recs or []) if r["symbol"] not in today]
            return shaped, raw_rs, sorted(dropped, key=lambda d: d["symbol"] or ""), prev

        rows, raw_rs, dropped, prev_session = db.cached("momentum.run", (resolved, p), compute)
        sec_ctx = _group_ctx(con, resolved, "sector")
        ind_ctx = _group_ctx(con, resolved, "industry")
        debug = None
        if debug_symbol:
            debug = _debug(con, resolved, p, debug_symbol)
            debug["in_list"] = any(r["symbol"] == debug_symbol for r in rows)
    shown = [r for r in rows if r["symbol"] == debug_symbol] if debug_symbol else rows
    sectors = leaders(shown, raw_rs, "sector", sec_ctx)
    industries = leaders(shown, raw_rs, "industry", ind_ctx)
    return Result(
        as_of=resolved,
        rows=shown,
        sources=SOURCES + ["group_daily"],
        metric_keys=MOMENTUM_METRICS,
        extra={
            "params": {**asdict(p), "debug_symbol": debug_symbol},
            "is_default": p.is_default(),
            "buckets": bucket_summary(shown),
            "buckets_tv": buckets_tv(shown),
            "top_sectors": sectors[:3],
            "top_industries": industries[:3],
            "sector_distribution": sectors,
            "industry_distribution": industries,
            "previous_session": prev_session,
            "new_count": sum(1 for r in shown if r.get("is_new")),
            "dropped": [] if debug_symbol else dropped,
            "debug": debug,
        },
        notes=[
            f"Trigger conditions held on at least one of the last {p.lookback_days} sessions; current conditions on as_of.",
            "Filters keep the scanner's original NULL rules (an unknown 200 EMA / EMA pair / 52W-low distance passes).",
            "Market cap is the current stocks_master value (as in the original scanner).",
        ],
    )


# --------------------------------------------------------------------------
# Evidence: forward returns per coil bucket for past scanner hits (default params)
# --------------------------------------------------------------------------
EVIDENCE_YEARS = 5
HORIZONS = (5, 10, 20)
MIN_N = 30


def _evidence_sql(con: Any, p: Params) -> tuple[str, list[Any]]:
    """Aggregated forward returns for every (symbol, session) the scanner would have listed, point-in-time.

    Trigger window = the same global-session window as the live scan (session-index range); market cap
    scaled point-in-time as current mcap × close_then / close_latest (constant share count on adjusted
    prices); forward returns on the (adjusted) indicators close; forward windows spanning an unexplained
    price gap dropped. Aggregated in SQL so only a handful of rows leave DuckDB.
    Params: [as_of, as_of, *trigger, *current, min_mcap, start_read, as_of, start_eval].
    """
    cols = set(db.table_columns(con, "indicators_daily"))
    pit = "(m.market_cap_cr * i.close_price / NULLIF(lc.close_latest, 0))"
    trig_sql, trig_params = _joined(trigger_clauses(p))
    cur_sql, cur_params = _joined(current_clauses(p, _opt_col(cols, "vcp_score", "i"), a="i"))
    trig_sql = trig_sql.replace("m.market_cap_cr", pit)
    cur_sql = cur_sql.replace("m.market_cap_cr", pit)
    leads = ", ".join(f"lead(i.close_price, {h}) OVER w AS close_f{h}, lead(i.trade_date, {h}) OVER w AS date_f{h}"
                      for h in HORIZONS)
    hmax = max(HORIZONS)
    lookback = int(p.lookback_days)  # a validated int from Params, not request text
    gap_flags = ", ".join(f"bool_or(g.gap_date <= x.date_f{h}) AS gap_{h}" for h in HORIZONS)
    cells = " UNION ALL ".join(
        f"SELECT {label_sql} AS bucket, {h} AS h, symbol, trade_date, (close_f{h} / NULLIF(close, 0) - 1) * 100 AS fwd "
        f"FROM xg WHERE {cond} AND close_f{h} IS NOT NULL AND gap_{h} IS NOT TRUE"
        for h in HORIZONS
        for label_sql, cond in (("bucket", "hit"), ("'All hits'", "hit"), ("'Universe'", "in_universe")))
    sql = f"""
        WITH cal AS (
            SELECT trade_date, row_number() OVER (ORDER BY trade_date) AS sidx
            FROM (SELECT DISTINCT trade_date FROM indicators_daily WHERE trade_date <= ?)
        ),
        lc AS (
            SELECT symbol, arg_max(close_price, trade_date) AS close_latest
            FROM indicators_daily WHERE trade_date <= ? GROUP BY symbol
        ),
        base AS (
            SELECT i.symbol, i.trade_date, cal.sidx, i.close_price AS close, i.away_10ema_pct,
                   ({trig_sql}) IS TRUE AS trig,
                   ({cur_sql}) IS TRUE AS cur,
                   ({pit} >= ? AND i.close_price > 15.0) IS TRUE AS in_universe,
                   {leads}
            FROM indicators_daily i
            JOIN cal USING (trade_date)
            JOIN stocks_master m USING (symbol)
            JOIN lc USING (symbol)
            WHERE i.trade_date >= ? AND i.trade_date <= ? AND upper(i.symbol) <> 'TOTAL'
            WINDOW w AS (PARTITION BY i.symbol ORDER BY i.trade_date)
        ),
        flagged AS (
            SELECT *, max(CASE WHEN trig THEN sidx END) OVER (
                       PARTITION BY symbol ORDER BY sidx RANGE BETWEEN {lookback - 1} PRECEDING AND CURRENT ROW
                   ) AS last_trig
            FROM base
        ),
        x AS (
            SELECT symbol, trade_date, close, {', '.join(f'close_f{h}, date_f{h}' for h in HORIZONS)},
                   {BUCKET_SQL.format(a='flagged')} AS bucket,
                   (cur AND last_trig IS NOT NULL) AS hit, in_universe
            FROM flagged
            WHERE trade_date >= ? AND ((cur AND last_trig IS NOT NULL) OR in_universe)
        ),
        gaps AS (
            SELECT x.symbol, x.trade_date, {gap_flags}
            FROM x JOIN {data_gaps.RELATION} g
              ON g.symbol = x.symbol AND g.gap_date > x.trade_date
             AND g.gap_date <= COALESCE(x.date_f{hmax}, TIMESTAMP '2262-01-01')
            GROUP BY x.symbol, x.trade_date
        ),
        xg AS (SELECT x.*, {', '.join(f'gaps.gap_{h}' for h in HORIZONS)} FROM x LEFT JOIN gaps USING (symbol, trade_date)),
        cells AS ({cells})
        SELECT bucket, h, count(*) AS n, count(DISTINCT trade_date) AS sessions, count(DISTINCT symbol) AS stocks,
               avg(CASE WHEN fwd > 0 THEN 1.0 ELSE 0.0 END) * 100 AS hit_rate, avg(fwd) AS avg,
               quantile_cont(fwd, 0.5) AS median
        FROM cells GROUP BY bucket, h
    """
    return sql, [*trig_params, *cur_params]


def evidence(as_of: date | None) -> Result:
    """Forward 5/10/20-session returns and hit rate (> 0) per coil bucket for past default-param hits."""
    p = Params()
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        if not db.table_exists(con, "stocks_master"):
            return unavailable(resolved, "stocks_master missing", SOURCES)

        def compute() -> dict[str, Any]:
            data_gaps.register(con)
            window = 252 * EVIDENCE_YEARS
            sessions = db.recent_sessions(con, resolved, window + p.lookback_days)
            if len(sessions) < p.lookback_days + max(HORIZONS) + 1:
                return {"cells": [], "start": None, "end": resolved}
            start_eval = sessions[min(window - 1, len(sessions) - p.lookback_days)]
            sql, clause_params = _evidence_sql(con, p)
            params = [resolved, resolved, *clause_params, float(p.min_mcap_cr), sessions[-1], resolved, start_eval]
            assert sql.count("?") == len(params), "evidence SQL placeholders out of sync"
            return {"cells": db.records(con, sql, params), "start": start_eval, "end": resolved}

        res = db.cached("momentum.evidence", (resolved,), compute)
    cells = res["cells"]
    if not cells:
        return unavailable(resolved, "not enough history for momentum evidence", SOURCES)
    by = {(c["bucket"], int(c["h"])): c for c in cells}
    rows = []
    for label in (*BUCKETS, "All hits", "Universe"):
        row: dict[str, Any] = {"bucket": label, "sessions": None, "stocks": None}
        for h in HORIZONS:
            c = by.get((label, h))
            row[f"n_{h}"] = int(c["n"]) if c else 0
            row[f"hit_rate_{h}"] = db.num(c["hit_rate"], 1) if c else None
            row[f"avg_{h}"] = db.num(c["avg"], 2) if c else None
            row[f"median_{h}"] = db.num(c["median"], 2) if c else None
            if c and h == HORIZONS[0]:
                row["sessions"] = db.integer(c["sessions"])
                row["stocks"] = db.integer(c["stocks"])
        row["insufficient_sample"] = row["n_10"] < MIN_N
        rows.append(row)
    return Result(
        as_of=resolved,
        rows=rows,
        sources=["indicators_daily", "stocks_master"],
        extra={"start": res["start"], "end": res["end"], "horizons": list(HORIZONS), "min_n": MIN_N,
               "params": asdict(p)},
        notes=[
            "Default scanner settings only; every stock-session the scanner would have listed (overlapping: a stock "
            "listed 10 days running counts 10 times).",
            "Hit rate = share of forward returns above 0. Universe = every stock >= Rs 1,000 Cr (point-in-time) above Rs 15.",
            "Point-in-time indicators; market cap scaled by price from today's value (constant share count). "
            "Stocks no longer in stocks_master are missing (survivorship).",
            "Forward windows that span an unexplained price gap are dropped.",
        ],
    )
