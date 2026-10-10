"""Charts tab services (HarkPro/09-tab-charts.md §5, 08-tab-deals.md §5.5-5.6).

Deal candles: one row per stock-session from `deal_session_net` (read-only), mapped to the
one-colour deal-day candle (B net buy · S net sell · P placement · T transfer · C churn) plus a
deal-price level. The Deals tab owns the classification rules (Scripts/derived/deal_rules.py);
this module only maps the stored `event_type` onto a letter and never re-classifies a session.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from App.services import db
from App.services.common import Result, no_session, unavailable

# event_type (deal_rules.EVENT_TYPES) -> candle letter
EVENT_LETTER: dict[str, str] = {
    "accumulate": "B",
    "fresh": "B",
    "distribute": "S",
    "placement": "P",
    "transfer_interse": "T",
    "churn": "C",
}
LETTER_KIND = {"B": "buy", "S": "sell", "P": "placement", "T": "transfer", "C": "churn"}
LETTER_LABEL = {"B": "Net buy", "S": "Net sell", "P": "Placement", "T": "Transfer", "C": "Churn"}
# Deal-price lines: only real levels (a net buy, a net sell, a placement), the 3 latest (08-tab-deals §5.5).
LINE_LETTERS = ("B", "S", "P")
MAX_LINES = 3
LINE_SESSIONS = 20


def classify(event_type: str | None, net_ex_prop_cr: float | None) -> str | None:
    """Stored event_type -> letter. An unknown or NULL type falls back on the sign of the net ex-PROP;
    a zero / NULL net with no type is churn-like noise (C). Never invents a buy from nothing."""
    et = (event_type or "").strip().lower()
    if et in EVENT_LETTER:
        return EVENT_LETTER[et]
    if net_ex_prop_cr is None:
        return None
    if round(net_ex_prop_cr, 6) > 0:
        return "B"
    if round(net_ex_prop_cr, 6) < 0:
        return "S"
    return "C"


def deal_price(letter: str, buy_vwap: float | None, sell_vwap: float | None, vwap: float | None) -> float | None:
    """The level a trader watches: buyers' VWAP for a net buy, sellers' VWAP for a net sell, else the session VWAP."""
    if letter == "B":
        return buy_vwap if buy_vwap is not None else vwap
    if letter == "S":
        return sell_vwap if sell_vwap is not None else vwap
    return vwap


def line_status(letter: str, price: float | None, close: float | None) -> str | None:
    """Holding / lost for buys and placements (close vs deal price); reclaimed / below for a net sell."""
    if price is None or close is None:
        return None
    if letter in ("B", "P"):
        return "holding" if close >= price else "lost"
    if letter == "S":
        return "reclaimed" if close > price else "below"
    return None


def mark_lines(rows: list[dict[str, Any]], n: int = MAX_LINES) -> None:
    """Flag the n latest B/S/P sessions (rows sorted oldest first) for a deal-price line."""
    left = n
    for r in reversed(rows):
        r["show_line"] = False
        if left > 0 and r["letter"] in LINE_LETTERS and r.get("deal_price") is not None:
            r["show_line"] = True
            left -= 1


def _top_clients(con: Any, symbol: str, as_of: date) -> dict[tuple[date, str], dict[str, Any]]:
    """Largest non-PROP client per (session, side), from collapsed prints (bulk ∩ block counted once)."""
    if not db.table_exists(con, "deals"):
        return {}
    cols = set(db.table_columns(con, "deals"))
    clientele = "clientele" if "clientele" in cols else "NULL"
    value = "deal_value_cr" if "deal_value_cr" in cols else "quantity * price / 1e7"
    rows = db.records(
        con,
        f"""
        WITH prints AS (
            SELECT DISTINCT CAST(trade_date AS DATE) AS d, client_name, UPPER(side) AS side, quantity, price,
                   {value} AS value_cr, {clientele} AS clientele
            FROM deals
            WHERE symbol = ? AND CAST(trade_date AS DATE) <= ?
        ), by_client AS (
            SELECT d, side, client_name, MAX(clientele) AS clientele, SUM(value_cr) AS value_cr
            FROM prints WHERE COALESCE(clientele, '') <> 'PROP'
            GROUP BY 1, 2, 3
        )
        SELECT d, side, client_name, clientele, value_cr,
               ROW_NUMBER() OVER (PARTITION BY d, side ORDER BY value_cr DESC NULLS LAST, client_name) AS rk
        FROM by_client
        """,
        [symbol, as_of],
    )
    out: dict[tuple[date, str], dict[str, Any]] = {}
    for r in rows:
        if r["rk"] != 1:
            continue
        d = db.to_date(r["d"])
        side = db.text(r["side"])
        if d is None or side not in ("BUY", "SELL"):
            continue
        out[(d, side)] = {"client": db.text(r["client_name"]), "clientele": db.text(r["clientele"]),
                          "value_cr": db.num(r["value_cr"], 2)}
    return out


def _price_frame(con: Any, symbol: str, as_of: date) -> tuple[dict[date, float], float | None]:
    """Adjustment factor per session (adj_close / close; 1.0 without adj columns) and the as-of adjusted close."""
    cols = set(db.table_columns(con, "prices_daily"))
    adj = "COALESCE(adj_close_price, close_price)" if "adj_close_price" in cols else "close_price"
    rows = db.records(
        con,
        f"SELECT CAST(trade_date AS DATE) AS d, close_price AS raw, {adj} AS adj FROM prices_daily "
        "WHERE symbol = ? AND trade_date <= ? ORDER BY trade_date",
        [symbol, as_of],
    )
    factors: dict[date, float] = {}
    last: float | None = None
    for r in rows:
        d = db.to_date(r["d"])
        raw, a = db.num(r["raw"]), db.num(r["adj"])
        if d is None:
            continue
        if raw and a:
            factors[d] = a / raw
        if a is not None:
            last = a
    return factors, last


def deal_candles(as_of: date | None, symbol: str) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        if not db.table_exists(con, "deal_session_net"):
            return unavailable(resolved, "deal_session_net is not built yet (Scripts/derived/deal_session_net.py)",
                               ["deal_session_net"])
        sess = db.records(
            con,
            """
            SELECT CAST(trade_date AS DATE) AS d, event_type, event_rule, net_value_cr_ex_prop, buy_value_cr,
                   sell_value_cr, gross_value_cr, prop_value_cr, buying_houses, selling_houses,
                   buy_vwap, sell_vwap, vwap, close_price, deal_types, net_value_cr_fii, net_value_cr_dii
            FROM deal_session_net
            WHERE symbol = ? AND CAST(trade_date AS DATE) <= ?
            ORDER BY trade_date
            """,
            [symbol, resolved],
        )
        tops = _top_clients(con, symbol, resolved)
        factors, last_close = _price_frame(con, symbol, resolved)

    rows: list[dict[str, Any]] = []
    for s in sess:
        d = db.to_date(s["d"])
        net = db.num(s["net_value_cr_ex_prop"])
        letter = classify(db.text(s["event_type"]), net)
        if d is None or letter is None:
            continue
        price = db.num(deal_price(letter, db.num(s["buy_vwap"]), db.num(s["sell_vwap"]), db.num(s["vwap"])), 2)
        factor = factors.get(d)
        price_adj = db.num(price * factor, 2) if price is not None and factor is not None else price
        buyer = tops.get((d, "BUY"), {})
        seller = tops.get((d, "SELL"), {})
        rows.append({
            "trade_date": d,
            "letter": letter,
            "kind": LETTER_KIND[letter],
            "label": LETTER_LABEL[letter],
            "event_type": db.text(s["event_type"]),
            "event_rule": db.text(s["event_rule"]),
            "net_cr": db.num(net, 2),
            "buy_cr": db.num(s["buy_value_cr"], 2),
            "sell_cr": db.num(s["sell_value_cr"], 2),
            "gross_cr": db.num(s["gross_value_cr"], 2),
            "prop_cr": db.num(s["prop_value_cr"], 2),
            "fii_net_cr": db.num(s["net_value_cr_fii"], 2),
            "dii_net_cr": db.num(s["net_value_cr_dii"], 2),
            "buying_houses": db.integer(s["buying_houses"]),
            "selling_houses": db.integer(s["selling_houses"]),
            "deal_types": db.text(s["deal_types"]),
            "deal_price": price,
            "deal_price_adj": price_adj,
            "top_buyer": buyer.get("client"),
            "top_buyer_class": buyer.get("clientele"),
            "top_buyer_cr": buyer.get("value_cr"),
            "top_seller": seller.get("client"),
            "top_seller_class": seller.get("clientele"),
            "top_seller_cr": seller.get("value_cr"),
            "close_as_of": db.num(last_close, 2),
            "status": line_status(letter, price_adj, db.num(last_close, 2)),
            "show_line": False,
        })
    mark_lines(rows)
    return Result(
        as_of=resolved, rows=rows, sources=["deal_session_net", "deals", "prices_daily"],
        extra={"symbol": symbol, "line_sessions": LINE_SESSIONS, "max_lines": MAX_LINES,
               "letters": LETTER_LABEL},
        notes=["Letters map the stored deal_session_net.event_type (rules: Scripts/derived/deal_rules.py): "
               "accumulate/fresh → B, distribute → S, placement → P, transfer_interse → T, churn → C.",
               "deal_price is the buyers' VWAP (B), sellers' VWAP (S) or session VWAP (P/T/C); deal_price_adj "
               "is on the adjusted price scale of /stock/{sym}/bars.",
               "Top buyer / seller exclude PROP desks; bulk ∩ block duplicate prints count once."],
        metric_keys=["deal_net_cr"],
    )


SEARCH_MAX = 25


def search_symbols(as_of: date | None, q: str, limit: int = 12) -> Result:
    """Symbol / company-name search for the chart's symbol box (stocks_master, read-only).
    Order: exact symbol, symbol prefix, name word prefix, then anything containing q; ties by market cap."""
    q = (q or "").strip()
    limit = max(1, min(int(limit), SEARCH_MAX))
    if not q:
        return Result(as_of=None, rows=[], sources=["stocks_master"])
    if len(q) > 40:
        raise ValueError("q is too long (max 40 characters)")
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if not db.table_exists(con, "stocks_master"):
            return unavailable(resolved, "no stocks_master table", ["stocks_master"])
        cols = set(db.table_columns(con, "stocks_master"))
        mcap = "market_cap_cr" if "market_cap_cr" in cols else "NULL"
        ind = "industry" if "industry" in cols else "NULL"
        uq = q.upper()
        rows = db.records(
            con,
            f"""
            SELECT symbol, security_name, {ind} AS industry, {mcap} AS market_cap_cr,
                   CASE WHEN UPPER(symbol) = ? THEN 0
                        WHEN UPPER(symbol) LIKE ? THEN 1
                        WHEN UPPER(security_name) LIKE ? OR UPPER(security_name) LIKE ? THEN 2
                        ELSE 3 END AS rk
            FROM stocks_master
            WHERE symbol IS NOT NULL AND UPPER(symbol) <> 'TOTAL'
              AND (UPPER(symbol) LIKE ? OR UPPER(COALESCE(security_name, '')) LIKE ?)
            ORDER BY rk, market_cap_cr DESC NULLS LAST, symbol
            LIMIT ?
            """,
            [uq, f"{uq}%", f"{uq}%", f"% {uq}%", f"%{uq}%", f"%{uq}%", limit],
        )
    out = [{"symbol": db.text(r["symbol"]), "security_name": db.text(r["security_name"]),
            "industry": db.text(r["industry"]), "market_cap_cr": db.num(r["market_cap_cr"], 0)} for r in rows]
    return Result(as_of=resolved, rows=out, sources=["stocks_master"], extra={"q": q},
                  notes=["Market cap is the latest value in stocks_master (data gap #7)."])
