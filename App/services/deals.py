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



# ==========================================================================
# Desk views restored from the old Deals workspace (d871ff9 /api/deals/institutional):
# Today prints · multi-session "repeated" window with the Play / churn / transfer tiers ·
# star-fund radar · fund leaderboard. Ported onto the correct rules above:
#   * collapsed prints (a bulk ∩ block duplicate counts once — the old desk double counted)
#   * PROP and the shared event types (transfer_interse / placement / churn) decide what is
#     real flow; the old ≥80 % same-day buy≈sell heuristic and "all prints PROP" test are replaced
#   * Play needs a positive net ex-PROP flow (the old desk took any stock with buy value > 0)
#   * house track records enter at the next session's open (deals are disclosed after the
#     close; the old desk "entered" at the deal price) and never look past as_of
# ==========================================================================
DESK_MIN_DEAL_CR = 5.0          # old attribution floor for a "bet"
STAR_TIERS = {"strong": ("Star Catalyst", "Strong Accumulator"),
              "steady": ("Star Catalyst", "Strong Accumulator", "Steady Value")}
PEAK_SESSIONS = 60
WIN_PCT = 5.0                   # old 20-day "win": T+20 return >= +5 %
FLOW_EVENTS = ("accumulate", "fresh", "distribute")
TRANSFER_EVENTS = ("transfer_interse", "placement")
INDIVIDUAL_CLASSES = {"HNI", "OTHER"}
SETUPS = ("ALL", "ABOVE_200", "TURNAROUND")


def _house_name(client: Any) -> str:
    """Old desk's fund-house normaliser (strips -FPI/-ODI, PVT LTD, …) so entities of one house merge."""
    from Scripts.institutional_attribution import clean_fund_name
    name = clean_fund_name(str(client or ""))
    return name.upper() if name else str(client or "").upper()


def _deal_sessions(con: Any, as_of: date, n: int) -> list[pd.Timestamp]:
    rows = con.execute("SELECT DISTINCT trade_date FROM deals WHERE trade_date <= ? ORDER BY 1 DESC LIMIT ?",
                       [as_of, int(n)]).fetchall()
    return sorted(pd.Timestamp(r[0]) for r in rows)


def _snap_full(con: Any, as_of: date) -> dict[str, dict[str, Any]]:
    def build() -> dict[str, dict[str, Any]]:
        df = con.execute(
            f"WITH s AS ({universe.snapshot_sql(con)}) SELECT symbol, security_name, sector, industry, close, "
            "market_cap_cr, rs_percentile, ema_200, away_52w_high_pct, adv_cr_20d, circuit_band FROM s", [as_of]).df()
        return df.set_index("symbol").to_dict("index") if not df.empty else {}
    return _cached("deals.snap_full", (as_of,), build)


def _mcap_ok(mcap: float | None, floor: float) -> bool:
    return floor <= 0 or (mcap is not None and mcap >= floor)


def _stock_cols(s: dict[str, Any]) -> dict[str, Any]:
    close, ema = db.num(s.get("close")), db.num(s.get("ema_200"))
    return {
        "security_name": db.text(s.get("security_name")), "sector": db.text(s.get("sector")),
        "industry": db.text(s.get("industry")), "close": db.num(close, 2), "ema_200": db.num(ema, 2),
        "above_200ema": (close >= ema) if close is not None and ema is not None else None,
        "away_52w_high_pct": db.num(s.get("away_52w_high_pct"), 1), "rs_percentile": db.num(s.get("rs_percentile"), 1),
        "market_cap_cr": db.num(s.get("market_cap_cr"), 0), "circuit_band": db.num(s.get("circuit_band"), 0),
    }


def _setup_ok(above: bool | None, setup: str) -> bool:
    if setup == "ABOVE_200":
        return above is True
    if setup == "TURNAROUND":
        return above is False
    return True


# --------------------------------------------------------------------------
# Today: every collapsed print of the deal session
# --------------------------------------------------------------------------
def prints(as_of: date | None, min_mcap_cr: float = 0.0) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        if not db.table_exists(con, "deals"):
            return unavailable(resolved, "no deals table", ["deals"])
        days = _deal_sessions(con, resolved, 1)
        if not days:
            return unavailable(resolved, "no deal prints on or before as_of", ["deals"])
        d = days[-1]
        p = _prints(con, resolved, "AND d.trade_date = ?", [d.to_pydatetime()])
        frame, _src = _frame(con, resolved)
        info = _snap_full(con, resolved)
    ev: dict[str, Any] = {}
    if not frame.empty:
        sub = frame[frame["trade_date"] == d]
        ev = dict(zip(sub["symbol"].astype(str), sub["event_type"]))
    rows, below = [], 0
    for r in (p.sort_values("value_cr", ascending=False).to_dict("records") if not p.empty else []):
        sym = str(r["symbol"])
        s = info.get(sym, {})
        mcap = db.num(s.get("market_cap_cr"))
        if not _mcap_ok(mcap, min_mcap_cr):
            below += 1
            continue
        close = db.num(r.get("close_price"))
        price = db.num(r.get("price"))
        rows.append({
            "trade_date": db.to_date(r["trade_date"]), "symbol": sym, "client": db.text(r.get("client")),
            "house": _house_name(r.get("client")), "side": db.text(r.get("side")), "quantity": db.integer(r.get("quantity")),
            "price": db.num(price, 2), "value_cr": db.num(r.get("value_cr"), 2), "deal_types": db.text(r.get("deal_types")),
            "clientele": db.text(r.get("clientele")), "is_prop": db.text(r.get("clientele")) == "PROP",
            "price_vs_close_pct": db.num((price / close - 1) * 100, 2) if price and close else None,
            "event_type": db.text(ev.get(sym)),
            **_stock_cols(s),
        })
    d_date = db.to_date(d)
    return Result(
        as_of=resolved, rows=rows, sources=["deals", "indicators_daily"],
        extra={"deal_session": d_date, "no_records_for_session": d_date is None or d_date < resolved,
               "min_mcap_cr": min_mcap_cr, "excluded_below_floor": below, "symbols": len({r["symbol"] for r in rows})},
        notes=["Every collapsed print of the deal session (a print in both the bulk and block files counts once).",
               "Event = the stock's session label (PROP excluded; transfer / placement / churn are not flow)."],
        metric_keys=["deal_event_type", "market_cap_cr"])


# --------------------------------------------------------------------------
# Window: repeated deals, Play tiers, churn, transfers, distribution
# --------------------------------------------------------------------------
def _window_rows(con: Any, resolved: date, lookback: int) -> tuple[list[dict[str, Any]], list[pd.Timestamp], str]:
    days = _deal_sessions(con, resolved, lookback)
    frame, src = _frame(con, resolved)
    if not days or frame.empty:
        return [], days, src
    f = frame[frame["trade_date"].isin(days)].copy()
    # Rights entitlements (-RE / -RE1 / _RE) are not tradable positions: the old desk banned them too.
    f = f[~f["symbol"].astype(str).str.upper().str.contains(r"[-_]RE\d*$", regex=True)]
    if f.empty:
        return [], days, src
    for c in ("buy_cr", "sell_cr", "net_ex_prop_cr", "fii_net_cr", "dii_net_cr", "prop_value_cr", "matched_value_cr"):
        f[c] = pd.to_numeric(f[c], errors="coerce")
    et = f["event_type"].astype("string")
    f["is_flow"] = et.isin(FLOW_EVENTS).fillna(False).astype(bool)
    f["is_tr"] = et.isin(TRANSFER_EVENTS).fillna(False).astype(bool)
    f["is_churn"] = (et == "churn").fillna(False).astype(bool)
    f["flow_net"] = f["net_ex_prop_cr"].where(f["is_flow"], 0.0)
    f["flow_buy"] = f["buy_cr"].where(f["is_flow"], 0.0)
    f["tr_val"] = f["matched_value_cr"].where(f["is_tr"], 0.0)
    f["nb"] = (f["is_flow"] & (f["net_ex_prop_cr"] > 0)).astype(int)
    f["ns"] = (f["is_flow"] & (f["net_ex_prop_cr"] < 0)).astype(int)

    # Houses (non-PROP, merged by fund house) from the collapsed prints of the window.
    p = _prints(con, resolved, "AND d.trade_date >= ?", [days[0].to_pydatetime()])
    hstats: dict[str, dict[str, Any]] = {}
    if not p.empty:
        p = p[p["trade_date"].isin(days) & (p["clientele"] != "PROP")].copy()
        p["house"] = p["client"].map(_house_name)
        p["net"] = np.where(p["side"] == "BUY", p["value_cr"], -p["value_cr"])
        p["buy_day"] = p["trade_date"].where(p["side"] == "BUY")
        g = p.groupby(["symbol", "house"]).agg(net=("net", "sum"), buy_days=("buy_day", "nunique"))
        for sym, sub in g.groupby(level=0):
            sub = sub.droplevel(0)
            buyers = sub[sub["net"] > 0].sort_values("net", ascending=False)
            sellers = sub[sub["net"] < 0].sort_values("net")
            hstats[str(sym)] = {
                "n_houses": int(len(sub)), "n_buy_houses": int(len(buyers)), "n_sell_houses": int(len(sellers)),
                "repeat_house": bool((sub["buy_days"] >= 2).any()),
                "top_buyers": [f"{h} ({v:+.1f})" for h, v in buyers["net"].head(3).items()],
                "top_sellers": [f"{h} ({v:+.1f})" for h, v in sellers["net"].head(3).items()],
            }
    pos = {d: i for i, d in enumerate(days)}
    rows = []
    for sym, g in f.groupby("symbol"):
        g = g.sort_values("trade_date")
        strip: list[float | None] = [None] * len(days)
        for t, v, isf in zip(g["trade_date"], g["net_ex_prop_cr"], g["is_flow"]):
            if t in pos:
                strip[pos[t]] = db.num(v, 2) if isf else 0.0
        last = g.iloc[-1]
        rows.append({
            "symbol": str(sym), "deal_days": int(len(g)), "net_buy_days": int(g["nb"].sum()),
            "net_sell_days": int(g["ns"].sum()), "transfer_days": int(g["is_tr"].sum()), "churn_days": int(g["is_churn"].sum()),
            "buy_cr": db.num(g["buy_cr"].sum(), 2), "sell_cr": db.num(g["sell_cr"].sum(), 2),
            "net_ex_prop_cr": db.num(g["net_ex_prop_cr"].sum(min_count=1), 2),
            "flow_net_cr": db.num(g["flow_net"].sum(), 2), "flow_buy_cr": db.num(g["flow_buy"].sum(), 2),
            "transfer_cr": db.num(g["tr_val"].sum(), 2), "prop_value_cr": db.num(g["prop_value_cr"].sum(min_count=1), 2),
            "fii_net_cr": db.num(g["fii_net_cr"].sum(min_count=1), 2), "dii_net_cr": db.num(g["dii_net_cr"].sum(min_count=1), 2),
            "first_deal_date": db.to_date(g["trade_date"].iloc[0]), "last_deal_date": db.to_date(last["trade_date"]),
            "last_event_type": db.text(last["event_type"]), "net_by_session": strip,
            **hstats.get(str(sym), {"n_houses": 0, "n_buy_houses": 0, "n_sell_houses": 0, "repeat_house": False,
                                    "top_buyers": [], "top_sellers": []}),
        })
    return rows, days, src


def desk_tier(r: dict[str, Any]) -> tuple[str, str | None]:
    """Mutually exclusive desk tier + play reason (old 3-tier desk on the corrected inputs)."""
    band = r.get("circuit_band")
    if band is not None and band <= 5:
        return "quarantined", None
    flow_days = r["deal_days"] - r["transfer_days"] - r["churn_days"]
    net = r.get("flow_net_cr") or 0.0
    if flow_days <= 0:
        return ("transfer", "Transfer") if r["transfer_days"] > 0 else ("churn", None)
    if net > 0:
        size = r.get("net_vs_adv")
        big = (size is not None and size >= 0.5) or (r.get("flow_buy_cr") or 0) >= 25 or net >= 20
        if r["repeat_house"] or r["net_buy_days"] >= 2:
            reason = "Repeat"
        elif r["n_buy_houses"] >= 2:
            reason = "Cluster"
        elif big:
            reason = "Size"
        else:
            reason = "Single"
        return ("conviction" if reason != "Single" else "fresh"), reason
    if net < 0:
        return "distribution", None
    return "churn", None


def window(as_of: date | None, lookback: int = 20, min_mcap_cr: float = 1000.0, setup: str = "ALL") -> Result:
    if setup not in SETUPS:
        raise ValueError(f"setup must be one of {SETUPS}")
    lookback = max(2, min(int(lookback), 60))
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        if not db.table_exists(con, "deals"):
            return unavailable(resolved, "no deals table", ["deals"])
        base, days, src = _cached("deals.window", (resolved, lookback), lambda: _window_rows(con, resolved, lookback))
        info = _snap_full(con, resolved)
    rows, below, off_setup = [], 0, 0
    counts: dict[str, int] = {}
    for b in base:
        s = info.get(b["symbol"], {})
        mcap = db.num(s.get("market_cap_cr"))
        if not _mcap_ok(mcap, min_mcap_cr):
            below += 1
            continue
        r = {**b, **_stock_cols(s)}
        adv = db.num(s.get("adv_cr_20d"))
        r["adv_cr"] = db.num(adv, 2)
        r["net_vs_adv"] = db.num(r["flow_net_cr"] / adv, 3) if adv and r["flow_net_cr"] is not None else None
        if not _setup_ok(r["above_200ema"], setup):
            off_setup += 1
            continue
        r["tier"], r["play_reason"] = desk_tier(r)
        counts[r["tier"]] = counts.get(r["tier"], 0) + 1
        rows.append(r)
    rows.sort(key=lambda x: (-x["deal_days"], -(x["flow_net_cr"] or 0)))
    return Result(
        as_of=resolved, rows=rows, status="ok" if src == "deal_session_net" else STATUS_PARTIAL,
        reason=None if src == "deal_session_net" else LIVE_REASON,
        sources=["deal_session_net" if src == "deal_session_net" else "deals", "deals", "indicators_daily"],
        extra={"lookback": lookback, "window_dates": [db.to_date(d) for d in days], "min_mcap_cr": min_mcap_cr,
               "setup": setup, "excluded_below_floor": below, "excluded_by_setup": off_setup, "tier_counts": counts,
               "deal_session": db.to_date(days[-1]) if days else None},
        notes=[f"Window = the last {lookback} sessions with stored deals up to as_of. deal_days counts sessions with any "
               "print; flow = accumulate / fresh / distribute sessions only (transfers, placements and churn are not flow).",
               "Tiers: quarantined (circuit band ≤ 5 %) · transfer (only transfer / placement sessions) · churn (only churn "
               "sessions) · conviction (flow net > 0 with a repeat buyer, ≥ 2 net-buy sessions, ≥ 2 buying houses, or size: "
               "net ≥ ₹20 Cr, flow buys ≥ ₹25 Cr or ≥ 0.5× ADV) · fresh (other flow net > 0) · distribution (flow net < 0).",
               "Houses merge entities of one fund house (-FPI / -ODI / PVT LTD suffixes); PROP desks are excluded."],
        metric_keys=["deal_net_cr", "deal_vs_adv", "persistence_days", "market_cap_cr", "rs_percentile"])


# --------------------------------------------------------------------------
# House attribution: leaderboard + star-fund radar
# --------------------------------------------------------------------------
_BETS_SQL = r"""
    SELECT trade_date, symbol, upper(trim(client_name)) AS client, quantity, price,
           any_value(COALESCE(deal_value_cr, quantity * price / 1e7)) AS value_cr,
           any_value(upper(trim(clientele))) AS clientele,
           bool_or(COALESCE(is_prop, FALSE)) AS is_prop, {hft} AS is_hft
    FROM deals d
    WHERE upper(symbol) <> 'TOTAL' AND upper(side) = 'BUY' AND trade_date <= ? AND quantity > 0 AND price > 0
      AND NOT (upper(symbol) LIKE '%-RE' OR upper(symbol) LIKE '%!_RE' ESCAPE '!')
    GROUP BY trade_date, symbol, upper(trim(client_name)), quantity, price
"""


def _bets(con: Any, as_of: date) -> pd.DataFrame:
    """Every non-PROP, non-HFT buy print >= ₹5 Cr with entry (next open), T+20, peak run-up, holding (≤ as_of)."""
    from Scripts.price_views import ohlcv_columns
    cols = ohlcv_columns(con, alias="p.")
    hft = "bool_or(COALESCE(is_hft, FALSE))" if "is_hft" in set(db.table_columns(con, "deals")) else "FALSE"
    b = con.execute(_BETS_SQL.replace("{hft}", hft), [as_of]).df()
    if b.empty:
        return b
    b = b[~b["is_prop"].astype(bool) & ~b["is_hft"].astype(bool) & (b["clientele"].fillna("") != "PROP")]
    b = b[pd.to_numeric(b["value_cr"], errors="coerce") >= DESK_MIN_DEAL_CR].copy()
    if b.empty:
        return b
    b["trade_date"] = pd.to_datetime(b["trade_date"])
    keys = b[["symbol", "trade_date"]].drop_duplicates()
    con.register("bet_keys", keys)
    try:
        px = con.execute(
            f"""
            WITH px AS (
                SELECT p.symbol, p.trade_date, {cols['open_price']} AS o, {cols['high_price']} AS h,
                       {cols['close_price']} AS c,
                       row_number() OVER (PARTITION BY p.symbol ORDER BY p.trade_date) AS rn
                FROM prices_daily p
                WHERE p.trade_date <= ? AND p.symbol IN (SELECT DISTINCT symbol FROM bet_keys)
                  AND coalesce(p.series, 'EQ') IN ('EQ', 'BE', 'BZ')
            ),
            k AS (
                SELECT bk.symbol, bk.trade_date, px.rn AS rn0
                FROM bet_keys bk ASOF JOIN px ON bk.symbol = px.symbol AND bk.trade_date >= px.trade_date
            ),
            lastp AS (SELECT symbol, max(rn) AS rn_last, arg_max(c, rn) AS cmp FROM px GROUP BY symbol)
            SELECT k.symbol, k.trade_date, l.cmp, l.rn_last - k.rn0 AS holding_days,
                   max(CASE WHEN px.rn = k.rn0 + 1 THEN px.o END) AS entry_open,
                   max(CASE WHEN px.rn = k.rn0 + 20 THEN px.c END) AS c20,
                   max(px.h) AS peak_high,
                   arg_max(px.rn - k.rn0, px.h) AS days_to_peak
            FROM k JOIN lastp l USING (symbol)
            LEFT JOIN px ON px.symbol = k.symbol AND px.rn BETWEEN k.rn0 + 1 AND k.rn0 + {PEAK_SESSIONS}
            GROUP BY k.symbol, k.trade_date, l.cmp, l.rn_last, k.rn0
            """, [as_of]).df()
    finally:
        con.unregister("bet_keys")
    px["trade_date"] = pd.to_datetime(px["trade_date"])
    b = b.merge(px, on=["symbol", "trade_date"], how="left")
    fwd = _fwd_cached(con, as_of)
    if not fwd.empty:
        bench = fwd[["trade_date", "bench_t20"]].dropna().drop_duplicates("trade_date")
        b = b.merge(bench, on="trade_date", how="left")
    else:
        b["bench_t20"] = np.nan
    e = pd.to_numeric(b["entry_open"], errors="coerce")
    e = e.where(e > 0)
    b["ret_20d"] = (pd.to_numeric(b["c20"], errors="coerce") / e - 1) * 100
    b["excess_20d"] = b["ret_20d"] - pd.to_numeric(b["bench_t20"], errors="coerce")
    b["peak_runup"] = (pd.to_numeric(b["peak_high"], errors="coerce") / e - 1) * 100
    b["ret_current"] = (pd.to_numeric(b["cmp"], errors="coerce") / e - 1) * 100
    b["house"] = b["client"].map(_house_name)
    return b


def _bets_cached(con: Any, as_of: date) -> pd.DataFrame:
    return _cached("deals.bets", (as_of,), lambda: _bets(con, as_of))


def catalyst_score(win: float | None, runup: float | None, ret20: float | None, dtp: float | None) -> float | None:
    """Old composite (0-100): 40 % win rate, 30 % avg peak run-up, 15 % avg T+20, 15 % velocity."""
    if runup is None:
        return None
    w = min(max(win if win is not None else 50.0, 0.0), 100.0)
    ru = min(max(runup, 0.0), 50.0) / 50.0 * 100
    r20 = min(max((ret20 or 0.0) + 10, 0.0), 30.0) / 30.0 * 100
    vel = min(max(100 - min(max(dtp if dtp is not None else 45.0, 5.0), 45.0) * 2, 20.0), 100.0)
    return round(w * 0.40 + ru * 0.30 + r20 * 0.15 + vel * 0.15, 1)


def fund_tier(score: float | None, win: float | None, runup: float | None, enough: bool) -> str:
    if not enough or score is None:
        return "Insufficient sample"
    wr, ru = win or 0.0, runup or 0.0
    if (wr >= 75 or score >= 75) and ru >= 15:
        return "Star Catalyst"
    if (wr >= 60 or score >= 60) and ru >= 10:
        return "Strong Accumulator"
    if wr >= 45 or score >= 45:
        return "Steady Value"
    return "Low Alpha / Laggard"


def _leader_rows(con: Any, resolved: date, lookback: int, min_bets: int = MIN_HOUSE_BETS) -> list[dict[str, Any]]:
    b = _bets_cached(con, resolved)
    if b.empty:
        return []
    # Holdings book: every non-PROP print (both sides, >= ₹5 Cr) per house x symbol in the window.
    days = _deal_sessions(con, resolved, lookback)
    p = _prints(con, resolved, "AND d.trade_date >= ?", [days[0].to_pydatetime()]) if days else pd.DataFrame()
    book: dict[str, list[dict[str, Any]]] = {}
    if not p.empty:
        p = p[(p["clientele"] != "PROP") & (p["value_cr"] >= DESK_MIN_DEAL_CR)].copy()
        p["house"] = p["client"].map(_house_name)
        p["bv"] = np.where(p["side"] == "BUY", p["value_cr"], 0.0)
        p["sv"] = np.where(p["side"] == "SELL", p["value_cr"], 0.0)
        p = p.sort_values("trade_date")
        g = p.groupby(["house", "symbol"]).agg(buy=("bv", "sum"), sell=("sv", "sum"), prints=("side", "size"),
                                               last_date=("trade_date", "last"), last_side=("side", "last"),
                                               last_price=("price", "last"))
        for (h, sym), r in g.iterrows():
            book.setdefault(str(h), []).append({
                "symbol": str(sym), "buy_cr": db.num(r["buy"], 1), "sell_cr": db.num(r["sell"], 1),
                "net_cr": db.num(r["buy"] - r["sell"], 1), "prints": int(r["prints"]),
                "last_date": db.to_date(r["last_date"]), "last_side": db.text(r["last_side"]),
                "last_price": db.num(r["last_price"], 2)})
        for items in book.values():
            items.sort(key=lambda x: -abs(x["net_cr"] or 0))
    rows = []
    for h, g in b.groupby("house"):
        done = g[g["ret_20d"].notna()]
        n20 = int(len(done))
        enough = n20 >= min_bets
        classes = sorted({c for c in g["clientele"].dropna().astype(str) if c})
        win = float((done["ret_20d"] >= WIN_PCT).mean() * 100) if n20 else None
        runup = db.num(g["peak_runup"].mean())
        r20 = db.num(done["ret_20d"].mean()) if n20 else None
        dtp = db.num(g["days_to_peak"].mean())
        score = catalyst_score(win, runup, r20, dtp)
        holdings = book.get(str(h), [])
        individual = (not classes) or set(classes) <= INDIVIDUAL_CLASSES
        rows.append({
            "house": str(h), "clientele": "/".join(classes) or None, "individual": individual,
            "clients": sorted(set(g["client"].astype(str)))[:8],
            "bets": int(len(g)), "bets_t20": n20, "names": int(g["symbol"].nunique()),
            "total_cr": db.num(g["value_cr"].sum(), 1),
            "win_rate_20d": db.num(win, 1) if enough else None,
            "hit_rate_20d": db.num((done["ret_20d"] > 0).mean() * 100, 1) if enough else None,
            "avg_ret_20d": db.num(r20, 2) if enough else None,
            "avg_excess_20d": db.num(done["excess_20d"].mean(), 2) if enough else None,
            "avg_peak_runup": db.num(runup, 1), "avg_days_to_peak": db.num(dtp, 1),
            "baggers": int((g["peak_runup"] >= 25).sum()), "best_gain": db.num(g["peak_runup"].max(), 1),
            "latest_buy_date": db.to_date(g["trade_date"].max()),
            "catalyst_score": score if enough else None,
            "tier": fund_tier(score, win, runup, enough),
            "ranked": enough,
            "names_in_window": len(holdings), "net_long_count": sum(1 for x in holdings if (x["net_cr"] or 0) > 0),
            "holdings": holdings[:40],
        })
    rows.sort(key=lambda r: (not r["ranked"], -(r["catalyst_score"] or 0), -(r["total_cr"] or 0)))
    return rows


LEADER_NOTES = [
    f"A bet = a non-PROP, non-HFT buy print ≥ ₹{DESK_MIN_DEAL_CR:.0f} Cr (collapsed). Entry = next session open (deals are "
    "disclosed after the close); T+20 = close 20 sessions later; peak run-up = highest high within "
    f"{PEAK_SESSIONS} sessions after entry. Nothing looks past as_of.",
    f"Win = T+20 ≥ +{WIN_PCT:.0f} %. Score / tier need ≥ {MIN_HOUSE_BETS} bets with a finished T+20 window by default "
    "(the old desk ranked houses on 2 bets; 3 is allowed but flagged as a small sample).",
    "Catalyst score = 40 % win rate + 30 % avg peak run-up + 15 % avg T+20 + 15 % speed to peak (old desk formula).",
    "Houses merge entities of one fund house; individuals (HNI / OTHER) are hidden unless asked for.",
]


def _min_bets(v: int) -> int:
    return max(3, min(int(v), 50))


def leaderboard(as_of: date | None, lookback: int = 20, include_individuals: bool = False,
                ranked_only: bool = False, min_bets: int = MIN_HOUSE_BETS) -> Result:
    lookback, min_bets = max(2, min(int(lookback), 60)), _min_bets(min_bets)
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        if not db.table_exists(con, "deals"):
            return unavailable(resolved, "no deals table", ["deals"])
        rows = _cached("deals.leader", (resolved, lookback, min_bets),
                       lambda: _leader_rows(con, resolved, lookback, min_bets))
    total = len(rows)
    rows = [r for r in rows if (include_individuals or not r["individual"]) and (not ranked_only or r["ranked"])]
    return Result(as_of=resolved, rows=rows, sources=["deals", "prices_daily", "index_daily"],
                  extra={"lookback": lookback, "min_bets": min_bets, "small_sample": min_bets < MIN_HOUSE_BETS, "win_pct": WIN_PCT,
                         "houses_total": total, "ranked_total": sum(1 for r in rows if r["ranked"])},
                  notes=LEADER_NOTES, metric_keys=["sample_n", "house_hit_rate_t20", "deal_fwd_excess_t20"])


def star_radar(as_of: date | None, lookback: int = 20, include_individuals: bool = False,
               stars_from: str = "strong", min_bets: int = MIN_HOUSE_BETS) -> Result:
    if stars_from not in STAR_TIERS:
        raise ValueError(f"stars_from must be one of {tuple(STAR_TIERS)}")
    lookback, min_bets = max(2, min(int(lookback), 60)), _min_bets(min_bets)
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        if not db.table_exists(con, "deals"):
            return unavailable(resolved, "no deals table", ["deals"])
        leaders = _cached("deals.leader", (resolved, lookback, min_bets),
                          lambda: _leader_rows(con, resolved, lookback, min_bets))
        b = _bets_cached(con, resolved)
        days = _deal_sessions(con, resolved, lookback)
        info = _snap_full(con, resolved)
    tiers = STAR_TIERS[stars_from]
    stars = {r["house"]: r for r in leaders if r["ranked"] and r["tier"] in tiers
             and (include_individuals or not r["individual"])}
    rows = []
    if not b.empty and stars and days:
        rec = b[b["trade_date"].isin(days) & b["house"].isin(list(stars))]
        rec = rec.sort_values(["trade_date", "value_cr"], ascending=[False, False])
        for r in rec.to_dict("records"):
            f = stars[r["house"]]
            s = info.get(str(r["symbol"]), {})
            rows.append({
                "symbol": str(r["symbol"]), "house": r["house"], "client": db.text(r["client"]),
                "clientele": db.text(r["clientele"]), "tier": f["tier"], "catalyst_score": f["catalyst_score"],
                "win_rate_20d": f["win_rate_20d"], "deal_date": db.to_date(r["trade_date"]),
                "deal_price": db.num(r["price"], 2), "entry_open": db.num(r["entry_open"], 2), "cmp": db.num(r["cmp"], 2),
                "gain_pct": db.num(r["ret_current"], 1), "peak_runup_pct": db.num(r["peak_runup"], 1),
                "holding_days": db.integer(r["holding_days"]), "deal_cr": db.num(r["value_cr"], 1),
                "rs_percentile": db.num(s.get("rs_percentile"), 1), "away_52w_high_pct": db.num(s.get("away_52w_high_pct"), 1),
                "market_cap_cr": db.num(s.get("market_cap_cr"), 0), "sector": db.text(s.get("sector")),
            })
    return Result(as_of=resolved, rows=rows, sources=["deals", "prices_daily"],
                  extra={"lookback": lookback, "star_houses": len(stars), "stars_from": stars_from, "star_tiers": list(tiers),
                         "min_bets": min_bets, "small_sample": min_bets < MIN_HOUSE_BETS,
                         "star_house_names": sorted(stars), "window_dates": [db.to_date(d) for d in days]},
                  notes=[f"Star house = ranked house (≥ {min_bets} finished T+20 bets) in tier {' / '.join(tiers)}; rows are its buy prints in the "
                         f"last {lookback} deal sessions. Gain and peak run-up are measured from the next open after the deal.",
                         *LEADER_NOTES[:2]],
                  metric_keys=["sample_n", "house_hit_rate_t20"])
