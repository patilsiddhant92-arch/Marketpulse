"""Parity restorations from the pre-rebuild React workspaces (audit 2026-09-27).

- `stock_profile`  : the Inspector's Minervini 8-point checklist, institutional footprint
                     (turnover / delivery / order ticket vs their 20-day baselines, tags) and the
                     5-session activity trail.
- `stock_peers`    : the Inspector's industry peer leaderboard (rank, members, stronger names near
                     their 10 EMA).
- `accumulators`   : the Capital Flow "Top stock capital accumulators" table (liquid names with a
                     turnover surge on an up day), without the old silent top-25 cap.

Every value is read from `indicators_daily` / `stocks_master` as stored; missing inputs stay NULL,
multi-session metrics over an unexplained price gap are NULL (App/services/data_gaps.py). All SQL
is parameterised; column fragments come from whitelists below.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from App.services import data_gaps, db, universe
from App.services.common import Result, no_session, unavailable

# Trend-template criteria: exactly the eight terms of Scripts/build_database.finalize_indicator_scores.
TT_CRITERIA: list[tuple[str, str, str]] = [
    ("price_above_150_200_sma", "Price > 150 & 200 SMA", "i.close_price > i.sma_150 AND i.close_price > i.sma_200"),
    ("sma150_above_sma200", "150 SMA > 200 SMA", "i.sma_150 > i.sma_200"),
    ("sma200_rising", "200 SMA rising", "i.sma_200_rising"),
    ("sma50_above_150_200", "50 SMA > 150 & 200 SMA", "i.sma_50 > i.sma_150 AND i.sma_50 > i.sma_200"),
    ("price_above_sma50", "Price > 50 SMA", "i.close_price > i.sma_50"),
    ("above_52w_low_30", "≥ 30% above 52W low", "i.away_52w_low_pct >= 30"),
    ("within_25_of_52w_high", "Within 25% of 52W high", "{near_high}"),
    ("rs_at_least_70", "Strength rank ≥ 70", "i.rs_percentile >= 70"),
]
WHALE_TICKET_X = 1.25  # average trade size vs its 20-day average (old Inspector "Whale" tag)
NEAR_10EMA_PCT = 3.0   # peers: "stronger and near its 10 EMA" = higher rank and |close vs 10 EMA| <= 3 %

# Accumulators defaults = the old Capital Flow radar (mcap >= 1,000 Cr, T/O >= 10 Cr, +30 % surge,
# ADV >= 3 Cr, CMP >= 10, up day).
ACC_MIN_TURNOVER_CR = 10.0
ACC_MIN_SURGE_PCT = 30.0
ACC_MIN_ADV_CR = 3.0
ACC_MIN_PRICE = 10.0


def _col(cols: set[str], name: str, alias: str = "i") -> str:
    """`alias.name` when the column exists, else a typed NULL (never a default)."""
    return f"{alias}.{name}" if name in cols else "CAST(NULL AS DOUBLE)"


def _near_high_expr(cols: set[str]) -> str:
    if "distance_below_52w" in cols:
        return "i.distance_below_52w <= 25"
    return "i.away_52w_high_pct >= -25"


def _needs(cols: set[str], *names: str) -> bool:
    return all(n in cols for n in names)


# --------------------------------------------------------------------------
# Stock profile: trend template + footprint + 5-session trail
# --------------------------------------------------------------------------
def stock_profile(as_of: date | None, symbol: str) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        cols = set(db.table_columns(con, "indicators_daily"))
        near_high = _near_high_expr(cols)
        tt_cols = []
        for key, _label, expr in TT_CRITERIA:
            expr = expr.format(near_high=near_high)
            needed = {"sma_150", "sma_200", "sma_50", "sma_200_rising", "away_52w_low_pct", "rs_percentile"}
            if not _needs(cols, *[c for c in needed if f"i.{c}" in expr]):
                tt_cols.append(f", CAST(NULL AS BOOLEAN) AS tt_{key}")
            else:
                tt_cols.append(f", {data_gaps.guard(f'({expr})', 'trend_template_pass')} AS tt_{key}")
        extra = "".join(tt_cols) + (
            f", {_col(cols, 'turnover_cr')} AS turnover_cr"
            f", {_col(cols, 'avg_trade_size')} AS avg_trade_size"
            f", {_col(cols, 'avg_trade_size_20d')} AS avg_trade_size_20d"
            f", {_col(cols, 'avg_delivery_pct_20d')} AS avg_delivery_pct_20d"
            f", {_col(cols, 'delivery_spike')} AS delivery_spike"
            f", {_col(cols, 'price_up_delivery_up')} AS price_up_delivery_up"
            f", {_col(cols, 'nr7')} AS nr7"
        )
        snap = universe.snapshot_sql(con, extra_where="AND i.symbol = ?", extra_cols=extra)
        recs = db.records(con, f"WITH s AS ({snap}) SELECT * FROM s", [resolved, symbol])
        if not recs:
            return unavailable(resolved, f"{symbol} has no indicators row on {resolved.isoformat()}", ["indicators_daily"])
        r = recs[0]
        data_gaps.register(con)
        trail = db.records(
            con,
            f"""
            SELECT i.trade_date,
                   {data_gaps.guard('(i.close_price / nullif(i.prev_close, 0) - 1) * 100', 'change_1d_pct')} AS change_pct,
                   i.rvol, i.delivery_pct, {_col(cols, 'turnover_cr')} AS turnover_cr
            FROM indicators_daily i
            {data_gaps.lateral_sql()}
            WHERE i.symbol = ? AND i.trade_date <= ?
            ORDER BY i.trade_date DESC
            LIMIT 5
            """,
            [symbol, resolved],
        )
    turnover = db.num(r.get("turnover_cr"))
    adv = db.num(r.get("adv_cr_20d"))
    ats, ats20 = db.num(r.get("avg_trade_size")), db.num(r.get("avg_trade_size_20d"))
    ticket = ats / ats20 if ats is not None and ats20 else None
    criteria = [{"key": key, "label": label, "passed": db.boolean(r.get(f"tt_{key}"))} for key, label, _ in TT_CRITERIA]
    row = {
        **universe.shape_stock(r),
        "trade_date": db.to_date(r.get("trade_date")),
        "trend_template_pass_n": db.integer(r.get("trend_template_pass_n")),
        "trend_template_pass": db.boolean(r.get("trend_template_pass")),
        "criteria": criteria,
        "turnover_cr": db.num(turnover, 2),
        "turnover_surge_pct": db.num((turnover / adv - 1) * 100, 1) if turnover is not None and adv else None,
        "avg_delivery_pct_20d": db.num(r.get("avg_delivery_pct_20d"), 1),
        "ticket_ratio": db.num(ticket, 2),
        "whale_ticket": (ticket >= WHALE_TICKET_X) if ticket is not None else None,
        "delivery_spike": db.boolean(r.get("delivery_spike")),
        "price_up_delivery_up": db.boolean(r.get("price_up_delivery_up")),
        "nr7": db.boolean(r.get("nr7")),
        "trail": [
            {
                "trade_date": db.to_date(t.get("trade_date")),
                "change_pct": db.num(t.get("change_pct"), 2),
                "rvol": db.num(t.get("rvol"), 2),
                "delivery_pct": db.num(t.get("delivery_pct"), 1),
                "turnover_cr": db.num(t.get("turnover_cr"), 2),
            }
            for t in reversed(trail)
        ],
    }
    return Result(
        as_of=resolved, rows=[row], sources=["indicators_daily", "stocks_master"],
        notes=[
            "Trend template = the eight stored terms behind trend_template_pass_n (SMA 50/150/200, 52W range, strength rank).",
            f"Whale ticket = average trade size >= {WHALE_TICKET_X}x its 20-day average.",
        ],
        metric_keys=["rs_percentile", "rvol", "delivery_pct", "change_1d_pct"],
    )


# --------------------------------------------------------------------------
# Industry peers
# --------------------------------------------------------------------------
def stock_peers(as_of: date | None, symbol: str) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        found = con.execute("SELECT industry, sector FROM stocks_master WHERE symbol = ?", [symbol]).fetchone()
        industry = db.text(found[0]) if found else None
        if not industry:
            return unavailable(resolved, f"{symbol} has no industry in stocks_master (Unclassified)", ["stocks_master"],
                               symbol=symbol)
        snap = universe.snapshot_sql(con, extra_where="AND m.industry = ?")
        recs = db.records(con, f"WITH s AS ({snap}) SELECT * FROM s", [resolved, industry])
    recs.sort(key=lambda x: (db.num(x.get("rs_percentile")) is None, -(db.num(x.get("rs_percentile")) or 0.0),
                             str(x.get("symbol"))))
    target = next((x for x in recs if x.get("symbol") == symbol), None)
    target_rs = db.num(target.get("rs_percentile")) if target else None
    rows: list[dict[str, Any]] = []
    rank = 0
    for x in recs:
        rs = db.num(x.get("rs_percentile"))
        if rs is not None:
            rank += 1
        away = db.num(x.get("away_10ema_pct"), 2)
        rows.append({
            **universe.shape_stock(x),
            "rank": rank if rs is not None else None,
            "away_10ema_pct": away,
            "is_target": x.get("symbol") == symbol,
            "stronger_near_10ema": (
                rs is not None and target_rs is not None and rs > target_rs and away is not None and abs(away) <= NEAR_10EMA_PCT
            ),
        })
    ranked = sum(1 for x in rows if x["rank"] is not None)
    target_row = next((x for x in rows if x["is_target"]), None)
    return Result(
        as_of=resolved, rows=rows, sources=["indicators_daily", "stocks_master"],
        extra={
            "symbol": symbol, "industry": industry, "sector": db.text(found[1]) if found else None,
            "target_rank": target_row["rank"] if target_row else None, "ranked": ranked,
            "near_10ema_pct": NEAR_10EMA_PCT,
        },
        notes=["Ranked by strength rank (RS percentile, all market caps); names without a rank are listed last, unranked."],
        metric_keys=["rs_percentile", "change_1d_pct", "market_cap_cr"],
    )


# --------------------------------------------------------------------------
# Capital accumulators
# --------------------------------------------------------------------------
def accumulators(as_of: date | None, min_mcap_cr: float = 1000.0, min_turnover_cr: float = ACC_MIN_TURNOVER_CR,
                 min_surge_pct: float = ACC_MIN_SURGE_PCT) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        cols = set(db.table_columns(con, "indicators_daily"))
        if "turnover_cr" not in cols or "avg_traded_value_cr_20d" not in cols:
            return unavailable(resolved, "indicators_daily has no turnover / 20-day traded value columns", ["indicators_daily"])
        extra = (
            ", i.turnover_cr AS turnover_cr"
            f", {_col(cols, 'avg_trade_size')} AS avg_trade_size"
            f", {_col(cols, 'avg_trade_size_20d')} AS avg_trade_size_20d"
            f", {_col(cols, 'delivery_spike')} AS delivery_spike"
            f", {_col(cols, 'price_up_delivery_up')} AS price_up_delivery_up"
        )
        snap = universe.snapshot_sql(con, extra_cols=extra)
        recs = db.records(
            con,
            f"""
            WITH s AS ({snap})
            SELECT * FROM s
            WHERE market_cap_cr >= ? AND close >= ? AND adv_cr_20d >= ? AND change_1d_pct > 0
              AND turnover_cr >= ? AND (turnover_cr / nullif(adv_cr_20d, 0) - 1) * 100 >= ?
            ORDER BY turnover_cr DESC, symbol
            """,
            [resolved, float(min_mcap_cr), ACC_MIN_PRICE, ACC_MIN_ADV_CR, float(min_turnover_cr), float(min_surge_pct)],
        )
    rows = []
    for x in recs:
        turnover, adv = db.num(x.get("turnover_cr")), db.num(x.get("adv_cr_20d"))
        ats, ats20 = db.num(x.get("avg_trade_size")), db.num(x.get("avg_trade_size_20d"))
        ticket = ats / ats20 if ats is not None and ats20 else None
        rows.append({
            **universe.shape_stock(x),
            "turnover_cr": db.num(turnover, 2),
            "turnover_surge_pct": db.num((turnover / adv - 1) * 100, 1) if turnover is not None and adv else None,
            "ticket_ratio": db.num(ticket, 2),
            "whale_ticket": (ticket >= WHALE_TICKET_X) if ticket is not None else None,
            "delivery_spike": db.boolean(x.get("delivery_spike")),
            "price_up_delivery_up": db.boolean(x.get("price_up_delivery_up")),
        })
    return Result(
        as_of=resolved, rows=rows, sources=["indicators_daily", "stocks_master", "security_reference_daily"],
        extra={"min_mcap_cr": min_mcap_cr, "min_turnover_cr": min_turnover_cr, "min_surge_pct": min_surge_pct,
               "min_adv_cr": ACC_MIN_ADV_CR, "min_price": ACC_MIN_PRICE},
        notes=[f"Up day, market cap >= {min_mcap_cr:,.0f} Cr, CMP >= {ACC_MIN_PRICE:.0f}, 20-day ADV >= {ACC_MIN_ADV_CR:.0f} Cr, "
               f"turnover >= {min_turnover_cr:.0f} Cr and >= {min_surge_pct:.0f}% above its 20-day average. Ranked by rupees."],
        metric_keys=["rs_percentile", "delivery_pct", "change_1d_pct", "market_cap_cr"],
    )
