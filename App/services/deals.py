"""Deals: session net, houses, follow-through (spec §7.5).

`deal_session_net` (data layer §4.5, Scripts/derived/deal_session_net.py) is the source
of truth for per-symbol session nets and event types. Until it exists the same frame is
**computed live** from the raw `deals` table with the builder's rules (status "partial"):

  * prints collapsed on (trade_date, symbol, client, side, quantity, price) — a print in
    both the bulk and block files counts once (spec §4.4)
  * PROP clients are excluded from the net used for events, ADV ratio and persistence
  * event type, first match wins: transfer_interse · placement · churn · accumulate ·
    fresh · distribute (rules in EVENT_RULES)
  * ADV = 20-day average traded value as of the previous session (deal day excluded)

Forward returns: entry at the next session's open after the deal (deals are disclosed
after the close), exits at the close T+5 / T+20; never past `as_of` (time travel safe).
Excess = stock return − NIFTY MIDSML 400 over the same entry/exit sessions.
"""
from __future__ import annotations

import threading
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from App.services import db, universe
from App.services.common import STATUS_PARTIAL, Result, no_session, unavailable
# Classification rules live in ONE module shared with the nightly deal_session_net builder, so the
# stored table and this live fallback can never label a session differently.
from Scripts.derived.deal_rules import (  # noqa: F401  (constants re-exported for callers/tests)
    CHURN_SHARE_MIN, EVENT_RULES, INSTITUTIONAL, MATCH_SHARE_MIN, PERSISTENCE_SESSIONS, RULE_TEXT,
    TRANSFER_PRICE_TOL, TRANSFER_QTY_TOL, classify_events, client_day_stats, matched_transfers, net_buy_sessions, net_sign,
)

DEAL_METRICS = ["deal_net_cr", "deal_vs_adv", "buying_houses", "persistence_days", "deal_vwap_vs_cmp",
                "deal_price_vs_close", "deal_event_type"]
MIN_HOUSE_BETS = 5
MIN_FOLLOW_N = 30
MIDSML400 = "NIFTY MIDSML 400"
_LOCK = threading.RLock()


def _cached(tag: str, key: tuple, fn: Any) -> Any:
    """Fingerprint cache with one computation at a time (concurrent requests wait, then hit the cache)."""
    with _LOCK:
        return db.cached(tag, key, fn)

# Frame column -> deal_session_net candidates (SCHEMA.md names first).
_DSN_FIELDS: dict[str, tuple[str, ...]] = {
    "prints": ("n_prints", "prints"),
    "deal_types": ("deal_types",),
    "buy_cr": ("buy_value_cr", "buy_cr"),
    "sell_cr": ("sell_value_cr", "sell_cr"),
    "net_cr": ("net_value_cr", "net_cr"),
    "net_ex_prop_cr": ("net_value_cr_ex_prop", "net_ex_prop_cr"),
    "fii_net_cr": ("net_value_cr_fii", "fii_net_cr", "fpi_net_cr"),
    "dii_net_cr": ("net_value_cr_dii", "dii_net_cr"),
    "prop_net_cr": ("net_value_cr_prop", "prop_net_cr"),
    "corporate_net_cr": ("net_value_cr_corporate", "corporate_net_cr"),
    "buying_houses": ("buying_houses", "unique_buying_houses", "n_buy_houses"),
    "selling_houses": ("selling_houses",),
    "buy_vwap": ("buy_vwap",),
    "vwap": ("vwap", "deal_vwap"),
    "deal_price_vs_close_pct": ("deal_price_vs_close_pct", "deal_price_vs_close"),
    "adv_cr": ("adv_cr",),
    "vs_adv": ("net_vs_adv", "vs_adv"),
    "deal_qty_pct_volume": ("deal_qty_pct_volume",),
    "round_trip_value_cr": ("round_trip_value_cr",),
    "prop_value_cr": ("prop_value_cr",),
    "matched_value_cr": ("matched_value_cr",),
    "persistence_days": ("net_buy_sessions_10", "persistence_days"),
    "event_type": ("event_type",),
    "event_rule": ("event_rule",),
}


# --------------------------------------------------------------------------
# Prints and the per symbol-session frame
# --------------------------------------------------------------------------
def _prints(con: Any, as_of: date, where: str = "", params: list[Any] | None = None) -> pd.DataFrame:
    p = con.execute(
        f"SELECT * FROM ({universe.collapsed_prints_sql('AND d.trade_date <= ? ' + where)}) q "
        "WHERE side IN ('BUY', 'SELL') AND quantity > 0 AND price > 0",
        [as_of, *(params or [])]).df()
    if p.empty:
        return p
    p["trade_date"] = pd.to_datetime(p["trade_date"])
    cl = p["clientele"].astype("string").str.strip().str.upper().fillna("OTHER")
    prop = p["is_prop"].fillna(False).astype(bool) | (cl == "PROP")
    p["clientele"] = cl.where(~prop, "PROP").astype(str)
    p["value_cr"] = pd.to_numeric(p["value_cr"], errors="coerce")
    p["quantity"] = pd.to_numeric(p["quantity"], errors="coerce").astype(float)
    p["price"] = pd.to_numeric(p["price"], errors="coerce").astype(float)
    return p


def _sessions(con: Any, start: Any, as_of: date) -> list[pd.Timestamp]:
    rows = con.execute("SELECT DISTINCT trade_date FROM indicators_daily WHERE trade_date BETWEEN ? AND ? ORDER BY 1",
                       [start, as_of]).fetchall()
    return [pd.Timestamp(r[0]) for r in rows]


def _live_frame(con: Any, as_of: date) -> pd.DataFrame:
    p = _prints(con, as_of)
    if p.empty:
        return pd.DataFrame()
    keys = ["trade_date", "symbol"]
    buy = p["side"] == "BUY"
    p["buy_val"] = np.where(buy, p["value_cr"], 0.0)
    p["sell_val"] = np.where(~buy, p["value_cr"], 0.0)
    p["buy_qty"] = np.where(buy, p["quantity"], 0.0)
    p["sell_qty"] = np.where(~buy, p["quantity"], 0.0)
    p["net_val"] = p["buy_val"] - p["sell_val"]
    p["qpx"] = p["quantity"] * p["price"]
    p["bqpx"] = np.where(buy, p["qpx"], 0.0)

    houses = client_day_stats(p).drop(columns=["n_clients"])
    s = p.groupby(keys).agg(prints=("side", "size"), buy_cr=("buy_val", "sum"), sell_cr=("sell_val", "sum"),
                            buy_qty=("buy_qty", "sum"), sell_qty=("sell_qty", "sum"), qty=("quantity", "sum"),
                            qpx=("qpx", "sum"), bqpx=("bqpx", "sum"),
                            deal_types=("deal_types", lambda v: "+".join(sorted({t for x in v for t in str(x).split("+") if t}))))
    by_class = p.pivot_table(index=keys, columns="clientele", values="net_val", aggfunc="sum", fill_value=0.0)
    for c in ("FII", "DII", "PROP", "CORPORATE"):
        s[f"{c.lower()}_net_cr"] = by_class[c].reindex(s.index).fillna(0.0) if c in by_class.columns else 0.0
    s["prop_value_cr"] = p[p["clientele"] == "PROP"].groupby(keys)["value_cr"].sum().reindex(s.index).fillna(0.0)
    s = s.join(houses).reset_index()
    s["net_cr"] = s["buy_cr"] - s["sell_cr"]
    s["net_ex_prop_cr"] = s["net_cr"] - s["prop_net_cr"]
    s["gross"] = s["buy_cr"] + s["sell_cr"]
    s["vwap"] = (s["qpx"] / s["qty"]).where(s["qty"] > 0)
    s["buy_vwap"] = (s["bqpx"] / s["buy_qty"]).where(s["buy_qty"] > 0)
    s = s.merge(matched_transfers(p), on=keys, how="left")
    s["matched_value_cr"] = pd.to_numeric(s["matched_value_cr"], errors="coerce").fillna(0.0)

    # Close on the deal day and ADV as of the previous session.
    start = s["trade_date"].min()
    con.register("deal_syms", pd.DataFrame({"symbol": s["symbol"].unique()}))
    try:
        px = con.execute(
            """
            SELECT symbol, trade_date, close_price, volume,
                   lag(avg_traded_value_cr_20d) OVER (PARTITION BY symbol ORDER BY trade_date) AS adv_prev
            FROM indicators_daily JOIN deal_syms USING (symbol)
            WHERE trade_date BETWEEN ? - INTERVAL 20 DAY AND ?
            """, [start, as_of]).df()
    finally:
        con.unregister("deal_syms")
    px["trade_date"] = pd.to_datetime(px["trade_date"])
    s = s.merge(px, on=keys, how="left")
    close = pd.to_numeric(s["close_price"], errors="coerce")
    s["adv_cr"] = pd.to_numeric(s["adv_prev"], errors="coerce")
    s["vs_adv"] = (s["net_ex_prop_cr"] / s["adv_cr"]).where(s["adv_cr"] > 0)
    s["deal_price_vs_close_pct"] = ((s["vwap"] / close - 1.0) * 100.0).where(close > 0)
    vol = pd.to_numeric(s["volume"], errors="coerce")
    s["deal_qty_pct_volume"] = (s[["buy_qty", "sell_qty"]].max(axis=1) / vol * 100.0).where(vol > 0)

    # Persistence: net-buy (ex-PROP) sessions among the last 10 market sessions incl. t.
    cal = _sessions(con, start, as_of)
    si_map = {d: i for i, d in enumerate(cal)}
    s["_si"] = s["trade_date"].map(si_map)
    s = s[s["_si"].notna()].copy()
    s["_si"] = s["_si"].astype(int)
    s = s.sort_values(["symbol", "_si"]).reset_index(drop=True)
    s["persistence_days"] = net_buy_sessions(s["symbol"], s["_si"], s["net_ex_prop_cr"])
    prior = s["persistence_days"] - (net_sign(s["net_ex_prop_cr"]) > 0).astype(float)

    # Shared rules (Scripts/derived/deal_rules.py): aggregate transfer match; PROP stripped before churn.
    s["event_type"] = classify_events(
        matched_value_cr=s["matched_value_cr"], buy_value_cr=s["buy_cr"], matched_inst=s["matched_inst"],
        round_trip_ex_prop_cr=s["round_trip_ex_prop_cr"], gross_ex_prop_cr=s["gross_ex_prop_cr"],
        net_ex_prop_cr=s["net_ex_prop_cr"], prior_net_buy_sessions=prior)
    s["event_rule"] = s["event_type"].map(RULE_TEXT)
    return s[["trade_date", "symbol", *_DSN_FIELDS.keys()]]


def _table_frame(con: Any, as_of: date) -> pd.DataFrame:
    cols = set(db.table_columns(con, "deal_session_net"))
    raw = con.execute("SELECT * FROM deal_session_net WHERE trade_date <= ? AND upper(symbol) <> 'TOTAL'", [as_of]).df()
    out = pd.DataFrame({"trade_date": pd.to_datetime(raw["trade_date"]), "symbol": raw["symbol"].astype(str)})
    for field, names in _DSN_FIELDS.items():
        col = next((c for c in names if c in cols), None)
        out[field] = raw[col] if col else None
    if out["event_rule"].isna().all():
        out["event_rule"] = out["event_type"].map(RULE_TEXT)
    return out


def _frame(con: Any, as_of: date) -> tuple[pd.DataFrame, str]:
    if db.table_exists(con, "deal_session_net"):
        return _cached("deals.table", (as_of,), lambda: _table_frame(con, as_of)), "deal_session_net"
    if db.table_exists(con, "deals"):
        return _cached("deals.live", (as_of,), lambda: _live_frame(con, as_of)), "live"
    return pd.DataFrame(), "none"


LIVE_REASON = ("deal_session_net not built yet; computed live from collapsed prints with the deal_session_net rules "
               "(PROP excluded from net, events and persistence).")


def _alignment(r: dict[str, Any]) -> dict[str, Any]:
    close, ema200 = db.num(r.get("close")), db.num(r.get("ema_200"))
    rs, away = db.num(r.get("rs_percentile")), db.num(r.get("away_52w_high_pct"))
    return {
        "above_200ema": (close > ema200) if close is not None and ema200 is not None else None,
        "rs_ge_70": (rs >= 70) if rs is not None else None,
        "within_15pct_of_high": (away >= -15) if away is not None else None,
    }


def _clean(field: str, v: Any) -> Any:
    if field in ("deal_types", "event_type", "event_rule"):
        return db.text(v)
    if field in ("prints", "buying_houses", "selling_houses", "persistence_days"):
        return db.integer(v)
    if field == "vs_adv":
        return db.num(v, 3)
    return db.num(v, 2)


def session(as_of: date | None, min_mcap_cr: float = 1000.0) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        df, src = _frame(con, resolved)
        if src == "none":
            return unavailable(resolved, "no deals table", ["deals"])
        snap = _cached("deals.snap", (resolved,), lambda: con.execute(
            f"WITH s AS ({universe.snapshot_sql(con)}) SELECT symbol, security_name, industry, close, market_cap_cr, "
            "rs_percentile, ema_200, away_52w_high_pct FROM s", [resolved]).df())
        cal = [pd.Timestamp(d) for d in reversed(db.recent_sessions(con, resolved, 60))]
    d = df["trade_date"].max() if not df.empty else None
    d = None if d is None or pd.isna(d) else d
    day = df[df["trade_date"] == d] if d is not None else df.iloc[0:0]
    info = snap.set_index("symbol").to_dict("index") if not snap.empty else {}
    days10 = [x for x in cal if d is not None and x <= d][-PERSISTENCE_SESSIONS:]
    recent = df[df["trade_date"].isin(days10)] if days10 else df.iloc[0:0]
    hist = {(str(r.symbol), r.trade_date): r.net_ex_prop_cr for r in recent.itertuples()}
    rows, below = [], 0
    for r in day.to_dict("records"):
        sym = str(r["symbol"])
        s = info.get(sym, {})
        mcap = db.num(s.get("market_cap_cr"))
        if min_mcap_cr > 0 and (mcap is None or mcap < min_mcap_cr):
            below += 1
            continue
        close = db.num(s.get("close"))
        ref = db.num(r.get("buy_vwap")) or db.num(r.get("vwap"))
        row = {k: _clean(k, r.get(k)) for k in _DSN_FIELDS}
        row.update({
            "symbol": sym, "trade_date": db.to_date(r["trade_date"]), "security_name": db.text(s.get("security_name")),
            "industry": db.text(s.get("industry")), "close": db.num(close, 2), "market_cap_cr": db.num(mcap, 0),
            "rs_percentile": db.num(s.get("rs_percentile"), 1),
            "vwap_vs_cmp_pct": db.num((close / ref - 1) * 100, 2) if close and ref else None,
            "institutional_net_cr": (db.num((db.num(r.get("fii_net_cr")) or 0) + (db.num(r.get("dii_net_cr")) or 0), 2)
                                     if r.get("fii_net_cr") is not None or r.get("dii_net_cr") is not None else None),
            "net_10s": [db.num(hist.get((sym, x)), 2) for x in days10],
            **_alignment({**s, "close": close}),
        })
        rows.append(row)
    rows.sort(key=lambda x: -(x["net_ex_prop_cr"] if x["net_ex_prop_cr"] is not None else (x["net_cr"] or 0)))
    d_date = db.to_date(d)
    no_records = d_date is None or d_date < resolved
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["event_type"] or "unclassified"] = counts.get(r["event_type"] or "unclassified", 0) + 1
    return Result(
        as_of=resolved, rows=rows, status="ok" if src == "deal_session_net" else STATUS_PARTIAL,
        reason=None if src == "deal_session_net" else LIVE_REASON,
        sources=["deal_session_net"] if src == "deal_session_net" else ["deals", "indicators_daily"],
        extra={"deal_session": d_date, "no_records_for_session": no_records, "min_mcap_cr": min_mcap_cr,
               "excluded_below_floor": below, "source": src, "event_counts": counts, "event_rules": EVENT_RULES,
               "net_10s_dates": [db.to_date(x) for x in days10]},
        notes=(["NO RECORDS: no bulk/block deals were stored for the as_of session; showing the latest earlier session."]
               if no_records and d_date is not None else []),
        metric_keys=DEAL_METRICS,
    )


# --------------------------------------------------------------------------
# Forward returns (next open → close T+h), bounded to as_of
# --------------------------------------------------------------------------
def _forward(con: Any, as_of: date) -> pd.DataFrame:
    """Forward returns on every stored deal date for every stock (for events, houses and baseline)."""
    if not db.table_exists(con, "deals"):
        return pd.DataFrame()
    start = con.execute("SELECT min(trade_date) FROM deals").fetchone()[0]
    if start is None:
        return pd.DataFrame()
    idx_cols = set(db.table_columns(con, "index_daily")) if db.table_exists(con, "index_daily") else set()
    bopen = "open_price" if "open_price" in idx_cols else "close_price"
    has_ref = db.table_exists(con, "security_reference_daily")
    mcap = "COALESCE(r.market_cap_cr, m.market_cap_cr)" if has_ref else "m.market_cap_cr"
    ref_join = ("ASOF LEFT JOIN security_reference_daily r ON r.symbol = f.symbol AND f.trade_date >= r.effective_date"
                if has_ref else "")
    bench = (f"""SELECT trade_date, lead({bopen}, 1) OVER w AS bo1, lead(close_price, 5) OVER w AS bc5,
                        lead(close_price, 20) OVER w AS bc20
                 FROM index_daily WHERE index_name = '{MIDSML400}' AND trade_date <= ?
                 WINDOW w AS (ORDER BY trade_date)""" if idx_cols else
             "SELECT NULL::TIMESTAMP AS trade_date, NULL AS bo1, NULL AS bc5, NULL AS bc20 WHERE ? IS NULL")
    df = con.execute(
        f"""
        WITH px AS (
            SELECT symbol, trade_date, close_price,
                   lead(open_price, 1) OVER w AS o1, lead(close_price, 5) OVER w AS c5, lead(close_price, 20) OVER w AS c20
            FROM prices_daily
            WHERE trade_date BETWEEN ? AND ? AND upper(symbol) <> 'TOTAL' AND coalesce(series, 'EQ') IN ('EQ', 'BE', 'BZ')
            WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
        ),
        dd AS (SELECT DISTINCT trade_date FROM deals WHERE trade_date BETWEEN ? AND ?),
        f AS (SELECT px.* FROM px JOIN dd USING (trade_date)),
        b AS ({bench})
        SELECT f.symbol, f.trade_date, f.o1, f.c5, f.c20, b.bo1, b.bc5, b.bc20, {mcap} AS mcap
        FROM f LEFT JOIN b ON b.trade_date = f.trade_date LEFT JOIN stocks_master m ON m.symbol = f.symbol
        {ref_join}
        """, [start, as_of, start, as_of, as_of]).df()
    if df.empty:
        return df
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    for c in ("o1", "c5", "c20", "bo1", "bc5", "bc20", "mcap"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for h in (5, 20):
        df[f"fwd_t{h}"] = (df[f"c{h}"] / df["o1"].where(df["o1"] > 0) - 1) * 100
        df[f"bench_t{h}"] = (df[f"bc{h}"] / df["bo1"].where(df["bo1"] > 0) - 1) * 100
        df[f"excess_t{h}"] = df[f"fwd_t{h}"] - df[f"bench_t{h}"]
    return df[["symbol", "trade_date", "o1", "mcap", "fwd_t5", "fwd_t20", "bench_t5", "bench_t20", "excess_t5", "excess_t20"]]


def _fwd_cached(con: Any, as_of: date) -> pd.DataFrame:
    return _cached("deals.forward", (as_of,), lambda: _forward(con, as_of))


def _stats(sub: pd.DataFrame) -> dict[str, Any]:
    t20 = sub["fwd_t20"].dropna()
    n = int(len(t20))
    ok = n >= MIN_FOLLOW_N
    return {
        "n": n, "n_t5": int(sub["fwd_t5"].notna().sum()), "insufficient_sample": not ok,
        "avg_fwd_t5_pct": db.num(sub["fwd_t5"].mean(), 2) if ok else None,
        "avg_fwd_t20_pct": db.num(t20.mean(), 2) if ok else None,
        "median_fwd_t20_pct": db.num(t20.median(), 2) if ok else None,
        "hit_rate_t20": db.num((t20 > 0).mean() * 100, 1) if ok else None,
        "avg_excess_t5_pct": db.num(sub["excess_t5"].mean(), 2) if ok else None,
        "avg_excess_t20_pct": db.num(sub["excess_t20"].mean(), 2) if ok else None,
    }


def followthrough(as_of: date | None, min_mcap_cr: float = 1000.0) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        df, src = _frame(con, resolved)
        if src == "none" or df.empty:
            return unavailable(resolved, "no deal events on or before as_of", ["deals"])
        fwd = _fwd_cached(con, resolved)
    if fwd.empty:
        return unavailable(resolved, "no prices for forward returns", ["prices_daily"])
    ev = df[["trade_date", "symbol", "event_type"]].merge(fwd, on=["symbol", "trade_date"], how="left")
    if min_mcap_cr > 0:
        ev = ev[ev["mcap"] >= min_mcap_cr]
    rows = []
    for rule in EVENT_RULES:
        et = rule["event_type"]
        rows.append({"event_type": et, "label": et.replace("_", " "), "rule": rule["rule"], "is_baseline": False,
                     **_stats(ev[ev["event_type"] == et])})
    base = fwd[fwd["trade_date"].isin(ev["trade_date"].unique())]
    if min_mcap_cr > 0:
        base = base[base["mcap"] >= min_mcap_cr]
    rows.append({"event_type": "baseline", "label": "all stocks, same dates", "is_baseline": True,
                 "rule": f"Every stock with market cap ≥ ₹{min_mcap_cr:,.0f} Cr, entered at the next open on the same "
                         "dates as the events (the bar to beat).", **_stats(base)})
    return Result(
        as_of=resolved, rows=rows, status="ok" if src == "deal_session_net" else STATUS_PARTIAL,
        reason=None if src == "deal_session_net" else LIVE_REASON,
        sources=["deal_session_net" if src == "deal_session_net" else "deals", "prices_daily", "index_daily"],
        extra={"min_mcap_cr": min_mcap_cr, "min_n": MIN_FOLLOW_N, "source": src,
               "first_event": db.to_date(df["trade_date"].min()), "last_event": db.to_date(df["trade_date"].max())},
        notes=[f"n < {MIN_FOLLOW_N} shows 'insufficient sample' instead of numbers.",
               "Entry = next session open after the deal; exit = close T+5 / T+20; never past as_of.",
               "Excess = return minus NIFTY MIDSML 400 over the same sessions."],
        metric_keys=["sample_n", "deal_event_type", "deal_fwd_excess_t20"])


# --------------------------------------------------------------------------
# Houses
# --------------------------------------------------------------------------
def _house_frame(con: Any, as_of: date) -> pd.DataFrame:
    p = _prints(con, as_of)
    if p.empty:
        return p
    fwd = _fwd_cached(con, as_of)
    if not fwd.empty:
        p = p.merge(fwd, on=["symbol", "trade_date"], how="left")
    else:
        for c in ("o1", "fwd_t5", "fwd_t20", "bench_t5", "bench_t20", "excess_t5", "excess_t20"):
            p[c] = np.nan
    return p


def houses(as_of: date | None, session_only: bool = False) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        if not db.table_exists(con, "deals"):
            return unavailable(resolved, "no deals table", ["deals"])
        p = _cached("deals.house_frame", (resolved,), lambda: _house_frame(con, resolved))
    if p.empty:
        return unavailable(resolved, "no deal prints on or before as_of", ["deals"])
    rows = _cached("deals.houses", (resolved,), lambda: _house_rows(p))
    if session_only:
        rows = [r for r in rows if r["active_in_session"]]
    return Result(
        as_of=resolved, rows=rows, sources=["deals", "prices_daily", "index_daily"],
        extra={"deal_session": db.to_date(p["trade_date"].max()), "min_bets": MIN_HOUSE_BETS},
        notes=[f"Track record needs ≥ {MIN_HOUSE_BETS} buy prints with a completed T+20 window; individuals (HNI/OTHER) "
               "and PROP desks are never ranked as funds.",
               "Churner = same-day buy and sell of the same stock on ≥ 50% of its active stock-days (or a PROP desk).",
               "Entry = next session open after the deal; exits never look past as_of."],
        metric_keys=["deal_net_cr", "sample_n", "house_hit_rate_t20", "deal_fwd_excess_t20"])


def _house_rows(p: pd.DataFrame) -> list[dict[str, Any]]:
    d = p["trade_date"].max()
    q = p.copy()
    buy = q["side"] == "BUY"
    q["bv"] = np.where(buy, q["value_cr"], 0.0)
    q["sv"] = np.where(~buy, q["value_cr"], 0.0)
    q["isbuy"] = buy.astype(float)
    q["bet"] = q["fwd_t20"].where(buy)
    q["bet_ex"] = q["excess_t20"].where(buy & q["fwd_t20"].notna())
    q["win"] = (q["bet"] > 0).astype(float).where(q["bet"].notna())
    q["in_sess"] = q["trade_date"] == d
    q["snet"] = np.where(q["in_sess"], q["bv"] - q["sv"], 0.0)
    a = q.groupby("client").agg(
        prints=("side", "size"), buy_prints=("isbuy", "sum"), buy_value_cr=("bv", "sum"), sell_value_cr=("sv", "sum"),
        symbols=("symbol", "nunique"), first_date=("trade_date", "min"), last_date=("trade_date", "max"),
        buy_bets_t20=("bet", "count"), avg_fwd_t20_pct=("bet", "mean"), avg_excess_t20_pct=("bet_ex", "mean"),
        hit=("win", "mean"), active_in_session=("in_sess", "any"), session_net_cr=("snet", "sum"))
    a["clientele"] = q.groupby("client")["clientele"].agg(lambda v: "/".join(sorted(set(v))))
    sd = q.groupby(["client", "trade_date", "symbol"])["side"].nunique()
    rt = (sd > 1).groupby(level=0).agg(["mean", "size"])
    a["round_trip_pct"] = rt["mean"] * 100
    a["churner"] = ((rt["size"] >= 3) & (rt["mean"] >= 0.5)) | (a["clientele"] == "PROP")
    sess_syms = q[q["in_sess"]].groupby("client")["symbol"].agg(lambda v: sorted(set(v)))
    rows = []
    for client, r in a.iterrows():
        n = int(r["buy_bets_t20"])
        enough = n >= MIN_HOUSE_BETS
        classes = set(str(r["clientele"]).split("/"))
        active = bool(r["active_in_session"])
        rows.append({
            "house": str(client), "clientele": r["clientele"], "prints": int(r["prints"]),
            "buy_prints": int(r["buy_prints"]), "sell_prints": int(r["prints"] - r["buy_prints"]),
            "buy_value_cr": db.num(r["buy_value_cr"], 2), "sell_value_cr": db.num(r["sell_value_cr"], 2),
            "net_cr": db.num(r["buy_value_cr"] - r["sell_value_cr"], 2), "symbols": int(r["symbols"]),
            "first_date": db.to_date(r["first_date"]), "last_date": db.to_date(r["last_date"]),
            "buy_bets_t20": n,
            "avg_fwd_t20_pct": db.num(r["avg_fwd_t20_pct"], 2) if enough else None,
            "avg_excess_t20_pct": db.num(r["avg_excess_t20_pct"], 2) if enough else None,
            "hit_rate_t20": db.num(r["hit"] * 100, 1) if enough else None,
            "ranked": enough and not classes <= {"HNI", "OTHER", "PROP"},
            "round_trip_pct": db.num(r["round_trip_pct"], 1), "churner": bool(r["churner"]),
            "active_in_session": active, "session_net_cr": db.num(r["session_net_cr"], 2) if active else None,
            "session_symbols": sess_syms.get(client) if active else None,
        })
    rows.sort(key=lambda r: (not r["active_in_session"], -(abs(r["session_net_cr"] or 0)), -(r["buy_value_cr"] or 0)))
    return rows


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
        p = _cached("deals.house_frame", (resolved,), lambda: _house_frame(con, resolved))
    g = p[p["client"] == client].sort_values(["trade_date", "value_cr"], ascending=[False, False]) if not p.empty else p
    rows = [{
        "trade_date": db.to_date(r["trade_date"]), "symbol": db.text(r["symbol"]), "side": db.text(r["side"]),
        "quantity": db.integer(r["quantity"]), "price": db.num(r["price"], 2), "value_cr": db.num(r["value_cr"], 2),
        "deal_types": db.text(r["deal_types"]), "clientele": db.text(r["clientele"]), "is_prop": db.boolean(r["is_prop"]),
        "entry_open": db.num(r.get("o1"), 2), "fwd_t5_pct": db.num(r.get("fwd_t5"), 2),
        "fwd_t20_pct": db.num(r.get("fwd_t20"), 2), "excess_t20_pct": db.num(r.get("excess_t20"), 2),
    } for r in g.to_dict("records")]
    buys = [r for r in rows if (r["side"] or "").startswith("BUY") and r["fwd_t20_pct"] is not None]
    n = len(buys)
    classes = {r["clientele"] for r in rows if r["clientele"]}
    enough = n >= MIN_HOUSE_BETS
    ex = [r["excess_t20_pct"] for r in buys if r["excess_t20_pct"] is not None]
    summary = {
        "house": client,
        "prints": len(rows),
        "buy_bets_with_t20": n,
        "ranked": enough and not classes <= {"HNI", "OTHER", "PROP"},
        "hit_rate_t20": round(sum(1 for r in buys if r["fwd_t20_pct"] > 0) / n * 100, 1) if enough else None,
        "avg_fwd_t20_pct": round(sum(r["fwd_t20_pct"] for r in buys) / n, 2) if enough else None,
        "avg_excess_t20_pct": round(sum(ex) / len(ex), 2) if enough and ex else None,
        "clientele": sorted(classes),
    }
    return Result(
        as_of=resolved, rows=rows, sources=["deals", "prices_daily"],
        extra={"summary": summary},
        notes=[f"Track record needs ≥ {MIN_HOUSE_BETS} buy prints with a completed T+20 window; individuals are not ranked as funds.",
               "Entry = next session open after the deal; exits never look past as_of."],
        metric_keys=["deal_net_cr", "sample_n", "hit_rate_2r"],
    )


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
