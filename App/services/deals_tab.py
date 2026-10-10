"""Deals tab (HarkPro/08-tab-deals.md through round 5.6, mockup v1.2).

Views: Today (verdict chips), Deal watch, History (5/10/20 deal sessions), Houses (+ fund spread by group),
By group; stock and house drawers; the Telegram digest preview. Plus two read-only cross-tab feeds:
per-symbol deal markers (chart deal candles) and per-symbol "has recent deal" flags (deal icon).

The verdict engine is Scripts/derived/deal_desk.py (shared with the Telegram sender). Classification is
deal_session_net / deal_rules, untouched. Everything is bounded to sessions <= as_of.
"""
from __future__ import annotations

import threading
from collections import Counter
from datetime import date
from typing import Any

import pandas as pd

from App.services import db
from App.services.common import Result, no_session, unavailable
from Scripts.derived import deal_desk as dd

SOURCES = ["deal_session_net", "deals", "indicators_daily", "stocks_master"]
MARKER_LOOKBACK = 250
WATCH_FILTERS = ("all", "best", "holding", "lost", "reclaimed")
_LOCK = threading.RLock()

RECORD_NOTE = ("House grades use finished trades only (exit on or before the as-of date), from the deal history "
               "in this database. FII/DII only, 5+ finished trades. Corporate and trading-firm buys are never graded.")
CLASS_NOTE = "Buyer-class evidence: NSE deal history Apr 2024 to Jul 2026, buys of ₹5 Cr or more, 20 sessions later vs the market."
GROUP_NOTE = "Transfers and churn excluded. Context only: 3+ buying names in one group beat the market by only 0.7% over 20 sessions."
MCAP_NOTE = "The ₹1,000 Cr floor uses the latest market cap (data gap 7: no point-in-time cap)."


def _core(con: Any, as_of: date) -> dict[str, Any]:
    with _LOCK:
        return db.cached("deals_tab.core", (as_of,), lambda: dd.build(con, as_of))


def _notes(core: dict[str, Any]) -> list[str]:
    notes = [MCAP_NOTE]
    gap = core.get("price_gap")
    if gap:
        notes.append(f"Price data gap: no sessions between {gap['from']} and {gap['to']}. "
                     "Holding / lost states and 'since the deal' moves span the gap.")
    if core.get("deal_session") != core.get("as_of"):
        notes.append(f"No deals stored for {core.get('as_of')}. Today shows the latest deal session, {core.get('deal_session')}.")
    return notes


def _with_core(as_of: date | None, fn) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        core = _core(con, resolved)
        if core.get("missing"):
            return unavailable(resolved, f"Deals data missing: {core['missing']}", SOURCES)
        return fn(con, resolved, core)


def _strip(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not k.startswith("_")}


# ----------------------------------------------------------------------------------------------- views
def today(as_of: date | None) -> Result:
    def go(con: Any, resolved: date, core: dict[str, Any]) -> Result:
        rows = dd.sort_by_verdict([_strip(x) for x in core["today"]])
        counts = Counter(x["verdict"] for x in rows)
        return Result(resolved, rows, sources=SOURCES, notes=_notes(core), extra={
            "deal_session": core["deal_session"], "skipped": core["skipped"], "above50_pct": core["above50_pct"],
            "verdict_counts": dict(counts), "noise_verdicts": list(dd.NOISE_VERDICTS), "verdict_order": dd.VERDICT_ORDER,
            "summary": {"confirms": counts["watch"] + counts["confirm"], "placements": counts["place"],
                        "supply": counts["supply"], "avoid": counts["avoid"],
                        "noise": counts["churn"] + counts["ignore"] + counts["none"]},
            "price_gap": core["price_gap"]})
    return _with_core(as_of, go)


def _watch_ok(x: dict[str, Any], f: str) -> bool:
    if f == "holding":
        return x["status"] == "holding"
    if f == "lost":
        return x["status"] in ("lost", "below seller")
    if f == "reclaimed":
        return x["status"] == "reclaimed"
    if f == "best":
        return x["verdict"] in ("confirm", "place", "absorbed")
    return True


def watch(as_of: date | None, status: str = "all") -> Result:
    if status not in WATCH_FILTERS:
        raise ValueError(f"status must be one of {', '.join(WATCH_FILTERS)}")

    def go(con: Any, resolved: date, core: dict[str, Any]) -> Result:
        base = [_strip(x) for x in core["watch"] if x["event_type"] not in dd.NOISE_EVENTS]
        counts = {f: sum(_watch_ok(x, f) for x in base) for f in WATCH_FILTERS}
        rows = dd.sort_by_verdict([x for x in base if _watch_ok(x, status)], key="age")
        return Result(resolved, rows, sources=SOURCES, notes=_notes(core), extra={
            "sessions": core["sessions10"], "filter_counts": counts, "price_gap": core["price_gap"]})
    return _with_core(as_of, go)


def history(as_of: date | None, sessions: int = 10, pattern: str = "all") -> Result:
    if sessions not in dd.HISTORY_WINDOWS:
        raise ValueError("sessions must be 5, 10 or 20")
    if pattern != "all" and pattern not in dd.PATTERNS:
        raise ValueError(f"pattern must be all or one of {', '.join(dd.PATTERNS)}")

    def go(con: Any, resolved: date, core: dict[str, Any]) -> Result:
        allrows = dd.history_rows(core, sessions)
        counts = Counter(x["pattern"] for x in allrows)
        rows = [x for x in allrows if pattern == "all" or x["pattern"] == pattern]
        s20 = core["sessions20"]
        return Result(resolved, rows, sources=SOURCES, notes=_notes(core), extra={
            "sessions": s20[-sessions:], "pattern_counts": {k: counts.get(k, 0) for k in dd.PATTERNS},
            "patterns": [{"key": k, "label": v[0], "note": v[1]} for k, v in dd.PATTERNS.items()], "total": len(allrows)})
    return _with_core(as_of, go)


def houses(as_of: date | None) -> Result:
    def go(con: Any, resolved: date, core: dict[str, Any]) -> Result:
        return Result(resolved, core["houses"], sources=SOURCES, notes=[RECORD_NOTE, CLASS_NOTE, *_notes(core)], extra={
            "class_evidence": dd.CLASS_EVIDENCE, "fund_groups": core["fund_groups"], "sessions": core["sessions10"],
            "graded_houses": core["graded_houses"], "finished_bets": core["finished_bets"], "first_deal": core["first_deal"],
            "record_note": RECORD_NOTE})
    return _with_core(as_of, go)


def groups(as_of: date | None) -> Result:
    def go(con: Any, resolved: date, core: dict[str, Any]) -> Result:
        return Result(resolved, core["groups"], sources=SOURCES, notes=[GROUP_NOTE, *_notes(core)],
                      extra={"sessions": core["sessions10"]})
    return _with_core(as_of, go)


def telegram(as_of: date | None) -> Result:
    from Scripts.telegram_deals import DIGEST_MAX_CHARS, format_deals_digest

    def go(con: Any, resolved: date, core: dict[str, Any]) -> Result:
        from App.services.deals_follow import followed_keys

        text = format_deals_digest(core, followed=followed_keys())
        return Result(resolved, [{"text": text, "chars": len(text), "max_chars": DIGEST_MAX_CHARS}], sources=SOURCES,
                      notes=_notes(core))
    return _with_core(as_of, go)


# ----------------------------------------------------------------------------------------------- drawers
def _ohlc(con: Any, symbol: str, start: Any, as_of: date) -> list[dict[str, Any]]:
    df = con.execute("""SELECT trade_date, open_price, high_price, low_price, close_price FROM indicators_daily
                        WHERE symbol = ? AND trade_date BETWEEN ? AND ? ORDER BY trade_date""", [symbol, start, as_of]).df()
    return [{"date": dd._iso(r.trade_date), "open": dd._f(r.open_price, 2), "high": dd._f(r.high_price, 2),
             "low": dd._f(r.low_price, 2), "close": dd._f(r.close_price, 2)} for r in df.itertuples()]


def _marker_rows(con: Any, symbol: str, as_of: date, lookback: int) -> list[dict[str, Any]]:
    if not db.table_exists(con, "deal_session_net"):
        return []
    sess = db.recent_sessions(con, as_of, lookback)
    if not sess:
        return []
    df = con.execute("""SELECT trade_date, event_type, buy_vwap, sell_vwap, vwap, net_value_cr_ex_prop, gross_ex_prop_cr
                        FROM deal_session_net WHERE symbol = ? AND trade_date BETWEEN ? AND ? ORDER BY trade_date""",
                     [symbol, sess[-1], as_of]).df()
    out = []
    for r in df.itertuples():
        e = str(r.event_type)
        lvl = r.sell_vwap if e == "distribute" else r.buy_vwap
        if lvl is None or pd.isna(lvl):
            lvl = r.vwap
        out.append({"date": dd._iso(r.trade_date), "side": dd.SIDE.get(e), "event_type": e, "price": dd._f(lvl, 2),
                    "net_cr": dd._f(r.net_value_cr_ex_prop), "gross_cr": dd._f(r.gross_ex_prop_cr)})
    return out


def stock(as_of: date | None, symbol: str) -> Result:
    """Stock drawer: verdict + what usually follows, deal-candle chart data, buyers/sellers with grades, status."""
    def go(con: Any, resolved: date, core: dict[str, Any]) -> Result:
        mine = [x for x in core["rows"] if x["symbol"] == symbol]
        deal = _strip(mine[0]) if mine else None
        if deal is not None:
            deal["earlier"] = [{"deal_date": x["deal_date"], "event_type": x["event_type"], "side": x["side"],
                                "net_cr": x["net_cr"], "deal_price": x["deal_price"], "verdict": x["verdict"]} for x in mine[1:]]
        start = (pd.Timestamp(deal["deal_date"]) if deal else pd.Timestamp(resolved)) - pd.Timedelta(days=dd.SPARK_DAYS)
        candles = _ohlc(con, symbol, start.date(), resolved)
        if not candles and deal is None:
            raise KeyError(symbol)
        first = candles[0]["date"] if candles else dd._iso(resolved)
        markers = [m for m in _marker_rows(con, symbol, resolved, MARKER_LOOKBACK) if m["date"] >= first]
        # Price lines only for the 3 latest buy / sell / placement deals (mockup v1.1).
        lines = [m for m in reversed(markers) if m["side"] in ("B", "S", "P") and m["price"]][:3]
        return Result(resolved, [{"symbol": symbol, "deal": deal, "candles": candles, "markers": markers,
                                  "price_lines": lines}], sources=SOURCES, notes=_notes(core))
    return _with_core(as_of, go)


def house(as_of: date | None, house_key: str) -> Result:
    """House drawer: class, out-of-sample grade, recent buys vs the market since entry, follow-ready id."""
    key = dd.house_key(house_key)

    def go(con: Any, resolved: date, core: dict[str, Any]) -> Result:
        h = next((x for x in core["houses"] if x["house"] == key), None)
        rows = _house_positions(con, resolved, key, core)
        if h is None and not rows:
            raise KeyError(house_key)
        if h is None:
            h = {"house": key, "name": key.title(), "buyer_class": rows[0]["buyer_class"], "bought_cr": None, "symbols": [],
                 "grade": "ungraded", "record_n": 0, "record_avg_pct": None, "record_beat_pct": None, "spread": []}
        cls = h["buyer_class"]
        if h["grade"] == "good":
            alert = "Follow it to get a Telegram alert when it buys a strong chart, and on day 3 (holding or lost)."
        elif cls in ("FII", "DII"):
            alert = "Follow it. Alerts fire once its record grades good and it buys a strong chart."
        else:
            alert = "No grade. Corporate and trading-firm buys lagged the market as a group (−2.6% and −2.7%)."
        return Result(resolved, rows, sources=SOURCES, notes=[RECORD_NOTE, *_notes(core)],
                      extra={"house": h, "advice": alert})
    return _with_core(as_of, go)


def _house_positions(con: Any, as_of: date, key: str, core: dict[str, Any]) -> list[dict[str, Any]]:
    """The house's non-PROP buys over the last 20 deal sessions: entry next open, now close, vs the market."""
    s20 = core["sessions20"]
    p = con.execute("""SELECT trade_date, symbol, upper(trim(client_name)) client, any_value(upper(coalesce(clientele,'OTHER'))) clientele,
                              sum(COALESCE(deal_value_cr, quantity * price / 1e7)) v,
                              sum(quantity * price) / nullif(sum(quantity), 0) px
                       FROM (SELECT DISTINCT trade_date, symbol, client_name, side, quantity, price, deal_value_cr, clientele, is_prop
                             FROM deals WHERE trade_date BETWEEN ? AND ? AND upper(side) = 'BUY'
                               AND NOT coalesce(is_prop, FALSE) AND upper(coalesce(clientele,'')) <> 'PROP')
                       GROUP BY 1, 2, 3""", [s20[0], as_of]).df()
    if p.empty:
        return []
    p = p[[dd.house_key(c) == key for c in p.client]]
    if p.empty:
        return []
    p = p.groupby(["trade_date", "symbol"]).agg(v=("v", "sum"), px=("px", "mean"), clientele=("clientele", "first")).reset_index()
    sessions = [pd.Timestamp(d) for d in con.execute(
        "SELECT DISTINCT trade_date FROM indicators_daily WHERE trade_date BETWEEN ? AND ? ORDER BY 1", [s20[0], as_of]).df().trade_date]
    def entry_of(d: Any) -> pd.Timestamp | None:
        later = [s for s in sessions if s > pd.Timestamp(d)]
        return later[0] if later else None
    p["entry"] = [entry_of(d) for d in p.trade_date]
    entries = sorted({pd.Timestamp(e) for e in p.entry if e is not None and not pd.isna(e)})
    mkt: dict[pd.Timestamp, float] = {}
    opens: dict[tuple[str, pd.Timestamp], float] = {}
    if entries:
        ph = ",".join("?" * len(entries))
        bench = con.execute(f"""
            WITH o AS (SELECT symbol, trade_date, open_price FROM indicators_daily WHERE trade_date IN ({ph})),
                 n AS (SELECT symbol, close_price FROM indicators_daily WHERE trade_date = ?)
            SELECT o.trade_date, avg(n.close_price / o.open_price - 1) * 100 r
            FROM o JOIN n USING (symbol) JOIN stocks_master m USING (symbol)
            WHERE m.market_cap_cr >= ? AND o.open_price > 0 AND abs(n.close_price / o.open_price - 1) <= 0.6
            GROUP BY 1""", [*entries, as_of, dd.FLOOR_CR]).df()
        mkt = {pd.Timestamp(r.trade_date): float(r.r) for r in bench.itertuples()}
        syms = sorted(set(p.symbol))
        sp = ",".join("?" * len(syms))
        od = con.execute(f"SELECT symbol, trade_date, open_price FROM indicators_daily WHERE trade_date IN ({ph}) AND symbol IN ({sp})",
                         [*entries, *syms]).df()
        opens = {(r.symbol, pd.Timestamp(r.trade_date)): float(r.open_price) for r in od.itertuples()}
    closes = dict(con.execute("SELECT symbol, close_price FROM indicators_daily WHERE trade_date = ?", [as_of]).fetchall())
    verdicts = {x["symbol"]: x for x in core["watch"]}
    out = []
    for r in p.sort_values("trade_date", ascending=False).itertuples():
        entry = None if r.entry is None or pd.isna(r.entry) else pd.Timestamp(r.entry)
        o = opens.get((r.symbol, entry)) if entry is not None else None
        c = closes.get(r.symbol)
        ret = (c / o - 1) * 100 if o and c else None
        m = mkt.get(entry) if entry is not None else None
        w = verdicts.get(r.symbol)
        out.append({"symbol": r.symbol, "deal_date": dd._iso(r.trade_date), "bought_cr": dd._f(r.v), "deal_price": dd._f(r.px, 2),
                    "buyer_class": r.clientele, "entry_date": dd._iso(entry) if entry is not None else None,
                    "since_entry_pct": dd._f(ret), "market_pct": dd._f(m), "vs_market_pct": dd._f(ret - m) if ret is not None and m is not None else None,
                    "verdict": w["verdict"] if w else None, "verdict_title": w["verdict_title"] if w else None,
                    "status": w["status"] if w else None})
    return out


# ----------------------------------------------------------------------------------------------- cross-tab feeds
def markers(as_of: date | None, symbol: str, lookback: int = MARKER_LOOKBACK) -> Result:
    """Per-symbol deal markers for chart deal candles: date, side B/S/P/T/C, price (deal level). Light: no verdict engine."""
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        if not db.table_exists(con, "deal_session_net"):
            return unavailable(resolved, "deal_session_net not built", ["deal_session_net"])
        rows = _marker_rows(con, symbol, resolved, lookback)
        return Result(resolved, rows, sources=["deal_session_net"], extra={
            "symbol": symbol, "lookback_sessions": lookback,
            "sides": {"B": "net buy", "S": "net sell", "P": "placement", "T": "transfer", "C": "churn"},
            "price_rule": "Sell VWAP for net sells, buy VWAP otherwise, deal VWAP when missing."})


def flags(as_of: date | None, symbols: list[str] | None = None) -> Result:
    """Per-symbol 'has recent deal' flag for the cross-tab deal icon: a deal within the last 10 deal sessions."""
    def go(con: Any, resolved: date, core: dict[str, Any]) -> Result:
        s10 = core["sessions10"]
        want = set(symbols) if symbols else None
        params: list[Any] = [s10[0], resolved]
        sql = """SELECT symbol, trade_date, event_type FROM deal_session_net WHERE trade_date BETWEEN ? AND ?"""
        if want:
            sql += f" AND symbol IN ({','.join('?' * len(want))})"
            params += sorted(want)
        df = con.execute(sql + " ORDER BY symbol, trade_date DESC", params).df()
        latest = df.drop_duplicates("symbol", keep="first") if not df.empty else df
        counts = df.groupby("symbol").size().to_dict() if not df.empty else {}
        pos = {d: i for i, d in enumerate(s10)}
        verdict = {x["symbol"]: x for x in core["watch"]}
        out: dict[str, dict[str, Any]] = {}
        for r in latest.itertuples():
            d = dd._iso(r.trade_date)
            v = verdict.get(r.symbol)
            e = str(r.event_type)
            out[r.symbol] = {"symbol": r.symbol, "has_recent_deal": True, "last_deal_date": d,
                             "deal_sessions_ago": len(s10) - 1 - pos[d] if d in pos else None,
                             "side": dd.SIDE.get(e), "event_type": e, "deal_sessions_in_window": int(counts.get(r.symbol, 1)),
                             "verdict": v["verdict"] if v else None, "verdict_title": v["verdict_title"] if v else None,
                             "deal_price": v["deal_price"] if v else None, "status": v["status"] if v else None,
                             "vs_deal_pct": v["vs_deal_pct"] if v else None}
        if want:
            for s in sorted(want - set(out)):
                out[s] = {"symbol": s, "has_recent_deal": False, "last_deal_date": None, "deal_sessions_ago": None,
                          "side": None, "event_type": None, "deal_sessions_in_window": 0, "verdict": None,
                          "verdict_title": None, "deal_price": None, "status": None, "vs_deal_pct": None}
        rows = [out[k] for k in sorted(out)]
        return Result(resolved, rows, sources=SOURCES, extra={
            "window_sessions": s10, "rule": "Icon shows only within 10 deal sessions of the deal. Verdict is null below ₹1,000 Cr.",
            "verdict_colours": {"confirm": "green", "place": "blue", "absorbed": "teal", "watch": "amber",
                                "supply": "amber", "churn": "grey", "ignore": "grey", "none": "grey", "avoid": "red"}})
    return _with_core(as_of, go)
