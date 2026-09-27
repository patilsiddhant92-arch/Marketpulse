"""Deals: session net, house pages, follow-through (spec §7.5).

`deal_session_net` (data layer §4.5) is the source of truth for per-symbol
session nets and event types. Until it exists, `session` aggregates the raw
`deals` table with duplicate bulk ∩ block prints collapsed (spec §4.4) —
status "partial", event_type NULL. House pages always read collapsed prints.
Forward returns are next-open entries with exits bounded to `as_of`
(no look-ahead in time travel).
"""
from __future__ import annotations

from datetime import date
from typing import Any

from App.services import db, universe
from App.services.common import STATUS_PARTIAL, Result, no_session, unavailable

DEAL_METRICS = ["deal_net_cr", "deal_vs_adv", "buying_houses", "persistence_days", "deal_vwap_vs_cmp",
                "deal_price_vs_close", "deal_event_type"]
MIN_HOUSE_BETS = 5

_DSN_FIELDS: dict[str, tuple[str, ...]] = {
    "buy_cr": ("buy_cr", "buy_value_cr"),
    "sell_cr": ("sell_cr", "sell_value_cr"),
    "net_cr": ("net_cr", "net_value_cr"),
    "buying_houses": ("buying_houses", "unique_buying_houses", "n_buy_houses"),
    "vwap": ("vwap", "deal_vwap"),
    "vs_adv": ("vs_adv", "net_vs_adv"),
    "deal_price_vs_close_pct": ("deal_price_vs_close_pct", "deal_price_vs_close"),
    "event_type": ("event_type",),
    "persistence_days": ("persistence_days",),
    "fii_net_cr": ("fii_net_cr", "fpi_net_cr"),
    "dii_net_cr": ("dii_net_cr",),
    "prop_net_cr": ("prop_net_cr",),
}


def _latest_deal_session(con: Any, as_of: date) -> date | None:
    return db.to_date(con.execute("SELECT max(trade_date) FROM deals WHERE trade_date <= ?", [as_of]).fetchone()[0])


def _from_session_net(con: Any, as_of: date, min_mcap: float) -> tuple[list[dict[str, Any]], date | None]:
    cols = set(db.table_columns(con, "deal_session_net"))
    fmap = {k: next((c for c in names if c in cols), "") for k, names in _DSN_FIELDS.items()}
    d = db.to_date(con.execute("SELECT max(trade_date) FROM deal_session_net WHERE trade_date <= ?", [as_of]).fetchone()[0])
    if d is None:
        return [], None
    snap = universe.snapshot_sql(con)
    raws = db.records(
        con,
        f"""
        WITH s AS ({snap})
        SELECT n.*, s.close, s.market_cap_cr, s.security_name, s.industry, s.rs_percentile, s.ema_200,
               s.away_52w_high_pct
        FROM deal_session_net n LEFT JOIN s ON s.symbol = n.symbol
        WHERE n.trade_date = ? AND (? <= 0 OR s.market_cap_cr >= ?)
        """,
        [d, d, min_mcap, min_mcap],
    )
    rows = []
    for r in raws:
        row = {k: (db.text(r.get(c)) if k == "event_type" else db.num(r.get(c), 2)) if c else None for k, c in fmap.items()}
        row["buying_houses"] = db.integer(row["buying_houses"])
        row["persistence_days"] = db.integer(row["persistence_days"])
        rows.append({**_base(r, d), **row, **_alignment(r)})
    return rows, d


def _base(r: dict[str, Any], d: date | None) -> dict[str, Any]:
    return {
        "symbol": db.text(r.get("symbol")),
        "security_name": db.text(r.get("security_name")),
        "industry": db.text(r.get("industry")),
        "trade_date": db.to_date(r.get("trade_date")) or d,
        "close": db.num(r.get("close"), 2),
        "market_cap_cr": db.num(r.get("market_cap_cr"), 0),
        "rs_percentile": db.num(r.get("rs_percentile"), 1),
    }


def _alignment(r: dict[str, Any]) -> dict[str, Any]:
    close, ema200 = db.num(r.get("close")), db.num(r.get("ema_200"))
    rs, away = db.num(r.get("rs_percentile")), db.num(r.get("away_52w_high_pct"))
    return {
        "above_200ema": (close > ema200) if close is not None and ema200 is not None else None,
        "rs_ge_70": (rs >= 70) if rs is not None else None,
        "within_15pct_of_high": (away >= -15) if away is not None else None,
    }


def _from_prints(con: Any, as_of: date, min_mcap: float) -> tuple[list[dict[str, Any]], date | None]:
    d = _latest_deal_session(con, as_of)
    if d is None:
        return [], None
    snap = universe.snapshot_sql(con)
    raws = db.records(
        con,
        f"""
        WITH p AS ({universe.collapsed_prints_sql("AND d.trade_date = ?")}),
        agg AS (
            SELECT symbol,
                   sum(value_cr) FILTER (WHERE side LIKE '%BUY%') AS buy_cr,
                   sum(value_cr) FILTER (WHERE side LIKE '%SELL%') AS sell_cr,
                   count(DISTINCT client) FILTER (WHERE side LIKE '%BUY%') AS buying_houses,
                   count(DISTINCT client) FILTER (WHERE side LIKE '%SELL%') AS selling_houses,
                   count(*) AS prints,
                   sum(price * quantity) FILTER (WHERE side LIKE '%BUY%')
                       / nullif(sum(quantity) FILTER (WHERE side LIKE '%BUY%'), 0) AS buy_vwap,
                   sum(price * quantity) / nullif(sum(quantity), 0) AS vwap,
                   sum(value_cr) FILTER (WHERE side LIKE '%BUY%' AND clientele IN ('FII', 'DII'))
                     - coalesce(sum(value_cr) FILTER (WHERE side LIKE '%SELL%' AND clientele IN ('FII', 'DII')), 0)
                       AS institutional_net_cr,
                   bool_and(is_prop) AS all_prop
            FROM p GROUP BY symbol
        ),
        s AS ({snap})
        SELECT agg.*, s.close, s.market_cap_cr, s.security_name, s.industry, s.rs_percentile, s.ema_200,
               s.away_52w_high_pct, s.adv_cr_20d
        FROM agg LEFT JOIN s ON s.symbol = agg.symbol
        WHERE (? <= 0 OR s.market_cap_cr >= ?)
        """,
        [d, d, min_mcap, min_mcap],
    )
    rows = []
    for r in raws:
        buy, sell = db.num(r.get("buy_cr")), db.num(r.get("sell_cr"))
        net = (buy or 0.0) - (sell or 0.0) if (buy is not None or sell is not None) else None
        adv = db.num(r.get("adv_cr_20d"))
        vwap, close = db.num(r.get("vwap")), db.num(r.get("close"))
        rows.append({
            **_base(r, d),
            "buy_cr": db.num(buy, 2),
            "sell_cr": db.num(sell, 2),
            "net_cr": db.num(net, 2),
            "institutional_net_cr": db.num(r.get("institutional_net_cr"), 2),
            "buying_houses": db.integer(r.get("buying_houses")),
            "selling_houses": db.integer(r.get("selling_houses")),
            "prints": db.integer(r.get("prints")),
            "vwap": db.num(vwap, 2),
            "vs_adv": db.num(net / adv, 3) if net is not None and adv else None,
            "deal_price_vs_close_pct": db.num((vwap / close - 1) * 100, 2) if vwap and close else None,
            "all_prop": db.boolean(r.get("all_prop")),
            "event_type": None,
            "persistence_days": None,
            **_alignment(r),
        })
    rows.sort(key=lambda x: -(x["net_cr"] or 0))
    return rows, d


def session(as_of: date | None, min_mcap_cr: float = 1000.0) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        if db.table_exists(con, "deal_session_net"):
            rows, d = _from_session_net(con, resolved, min_mcap_cr)
            src, status, reason = ["deal_session_net"], "ok", None
        elif db.table_exists(con, "deals"):
            rows, d = _from_prints(con, resolved, min_mcap_cr)
            src, status = ["deals"], STATUS_PARTIAL
            reason = "deal_session_net not built yet; nets aggregated from collapsed prints — event type / persistence unavailable"
        else:
            return unavailable(resolved, "no deals table", ["deals"])
    no_records = d is None or d < resolved
    return Result(
        as_of=resolved, rows=rows, status=status, reason=reason, sources=src,
        extra={"deal_session": d, "no_records_for_session": no_records, "min_mcap_cr": min_mcap_cr},
        notes=(["NO RECORDS: no bulk/block deals were stored for the as_of session; showing the latest earlier session."]
               if no_records and d is not None else []),
        metric_keys=DEAL_METRICS,
    )


def _prints_with_forward(con: Any, as_of: date, where: str, params: list[Any]) -> list[dict[str, Any]]:
    return db.records(
        con,
        f"""
        WITH p AS ({universe.collapsed_prints_sql(where)}),
        px AS (
            SELECT symbol, trade_date,
                   lead(open_price, 1) OVER w AS entry_open,
                   lead(close_price, 5) OVER w AS close_t5,
                   lead(close_price, 20) OVER w AS close_t20
            FROM prices_daily
            WHERE trade_date <= ? AND symbol IN (SELECT DISTINCT symbol FROM p)
            WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
        )
        SELECT p.*, px.entry_open,
               (px.close_t5 / nullif(px.entry_open, 0) - 1) * 100 AS fwd_t5_pct,
               (px.close_t20 / nullif(px.entry_open, 0) - 1) * 100 AS fwd_t20_pct
        FROM p LEFT JOIN px ON px.symbol = p.symbol AND px.trade_date = p.trade_date
        ORDER BY p.trade_date DESC, p.value_cr DESC
        """,
        [*params, as_of],
    )


def house(as_of: date | None, house_id: str) -> Result:
    client = " ".join(str(house_id or "").upper().split())
    if not client or len(client) > 200:
        raise ValueError("invalid house id")
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        if not db.table_exists(con, "deals"):
            return unavailable(resolved, "no deals table", ["deals"])
        raws = _prints_with_forward(con, resolved, "AND upper(trim(d.client_name)) = ? AND d.trade_date <= ?",
                                    [client, resolved])
    rows = [{
        "trade_date": db.to_date(r["trade_date"]),
        "symbol": db.text(r["symbol"]),
        "side": db.text(r["side"]),
        "quantity": db.integer(r["quantity"]),
        "price": db.num(r["price"], 2),
        "value_cr": db.num(r["value_cr"], 2),
        "deal_types": db.text(r["deal_types"]),
        "clientele": db.text(r["clientele"]),
        "is_prop": db.boolean(r["is_prop"]),
        "entry_open": db.num(r["entry_open"], 2),
        "fwd_t5_pct": db.num(r["fwd_t5_pct"], 2),
        "fwd_t20_pct": db.num(r["fwd_t20_pct"], 2),
    } for r in raws]
    buys = [r for r in rows if (r["side"] or "").startswith("BUY") and r["fwd_t20_pct"] is not None]
    n = len(buys)
    classes = {r["clientele"] for r in rows if r["clientele"]}
    summary = {
        "house": client,
        "prints": len(rows),
        "buy_bets_with_t20": n,
        "ranked": n >= MIN_HOUSE_BETS and not classes <= {"HNI", "OTHER"},
        "hit_rate_t20": round(sum(1 for r in buys if r["fwd_t20_pct"] > 0) / n * 100, 1) if n >= MIN_HOUSE_BETS else None,
        "avg_fwd_t20_pct": round(sum(r["fwd_t20_pct"] for r in buys) / n, 2) if n >= MIN_HOUSE_BETS else None,
        "clientele": sorted(classes),
    }
    return Result(
        as_of=resolved, rows=rows, sources=["deals", "prices_daily"],
        extra={"summary": summary},
        notes=[f"Track record needs ≥ {MIN_HOUSE_BETS} buy prints with a completed T+20 window; individuals are not ranked as funds.",
               "Entry = next session open after the deal; exits never look past as_of."],
        metric_keys=["deal_net_cr", "sample_n", "hit_rate_2r"],
    )


def followthrough(as_of: date | None) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if not db.table_exists(con, "deal_session_net"):
            return unavailable(resolved, "deal_session_net not built yet (needs deal event types)", ["deal_session_net"])
        if resolved is None:
            return no_session(as_of)
        cols = set(db.table_columns(con, "deal_session_net"))
        if "event_type" not in cols:
            return unavailable(resolved, "deal_session_net has no event_type column", ["deal_session_net"])
        raws = db.records(
            con,
            """
            WITH ev AS (SELECT symbol, trade_date, event_type FROM deal_session_net WHERE trade_date <= ?),
            px AS (
                SELECT symbol, trade_date,
                       lead(open_price, 1) OVER w AS entry_open,
                       lead(close_price, 5) OVER w AS close_t5,
                       lead(close_price, 20) OVER w AS close_t20
                FROM prices_daily WHERE trade_date <= ? AND symbol IN (SELECT DISTINCT symbol FROM ev)
                WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
            ),
            j AS (
                SELECT ev.event_type,
                       (px.close_t5 / nullif(px.entry_open, 0) - 1) * 100 AS t5,
                       (px.close_t20 / nullif(px.entry_open, 0) - 1) * 100 AS t20
                FROM ev JOIN px USING (symbol, trade_date)
            )
            SELECT event_type, count(t20) AS n, avg(t5) AS avg_t5, avg(t20) AS avg_t20, median(t20) AS median_t20,
                   avg(CASE WHEN t20 > 0 THEN 1.0 ELSE 0.0 END) FILTER (WHERE t20 IS NOT NULL) * 100 AS hit_t20
            FROM j GROUP BY event_type ORDER BY event_type
            """,
            [resolved, resolved],
        )
    rows = []
    for r in raws:
        n = int(r["n"] or 0)
        ok = n >= 30
        rows.append({
            "event_type": db.text(r["event_type"]),
            "n": n,
            "insufficient_sample": not ok,
            "avg_fwd_t5_pct": db.num(r["avg_t5"], 2) if ok else None,
            "avg_fwd_t20_pct": db.num(r["avg_t20"], 2) if ok else None,
            "median_fwd_t20_pct": db.num(r["median_t20"], 2) if ok else None,
            "hit_rate_t20": db.num(r["hit_t20"], 1) if ok else None,
        })
    return Result(as_of=resolved, rows=rows, sources=["deal_session_net", "prices_daily"],
                  notes=["n < 30 shows 'insufficient sample' instead of numbers."], metric_keys=["sample_n"])


def stock_prints(con: Any, symbol: str, as_of: date, limit_days: int | None = None) -> list[dict[str, Any]]:
    raws = db.records(
        con,
        f"""
        WITH p AS ({universe.collapsed_prints_sql("AND d.symbol = ? AND d.trade_date <= ?")})
        SELECT * FROM p ORDER BY trade_date DESC, value_cr DESC
        """,
        [symbol, as_of],
    )
    return [{
        "trade_date": db.to_date(r["trade_date"]),
        "client": db.text(r["client"]),
        "side": db.text(r["side"]),
        "quantity": db.integer(r["quantity"]),
        "price": db.num(r["price"], 2),
        "value_cr": db.num(r["value_cr"], 2),
        "deal_types": db.text(r["deal_types"]),
        "clientele": db.text(r["clientele"]),
        "is_prop": db.boolean(r["is_prop"]),
        "institutional": (db.text(r["clientele"]) in ("FII", "DII")) if r["clientele"] is not None else None,
    } for r in raws]
