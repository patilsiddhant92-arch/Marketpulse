"""Today: what moved, which groups trended, and why (Desk "Today" + Groups "Today" mode).

Every number is read from the warehouse for ONE session (as_of) and its recent history; nothing
is fabricated — a missing input stays NULL and every rule on it fails closed.

Sources
  * stock rows      universe.snapshot_sql (indicators_daily + stocks_master + security_reference_daily)
  * market strip    breadth_daily (advancers / decliners), index_daily (Nifty 50, NIFTY MIDSML 400,
                    NIFTY SMLCAP 250, India VIX), indicators_daily aggregates (turnover, delivery, 52W highs/lows)
  * queues          setup_daily (queues on as_of; the prior session's triggers for "breakouts")
  * deals today     deal_session_net (net value ex-PROP, event type, buying / selling houses)
  * catalysts       security_events (results board meetings / financial results, news types) and
                    corporate_actions (ex-dates), within ±5 sessions
  * group context   group_daily (5d / 21d EW return, rank, rank change) when built

Definitions (also in Scripts/data/metric_dictionary.yaml)
  * RVOL             = volume ÷ average volume of the prior 20 sessions (indicators_daily.rvol)
  * delivery×        = delivery % ÷ 20-day average delivery % (stock rows, `delivery_vs_20d`)
  * delivery spike   = delivered shares > 2 × their 20-day average (indicators_daily.delivery_spike)
  * turnover×        = turnover ÷ 20-day average traded value
  * group delivery×  = members' delivered shares ÷ their 20-day average delivered shares
  * group turnover×  = members' turnover ÷ their 20-day average traded value
  * contribution     = member 1D return ÷ members (points of the equal-weight group return)
The "quality of move", group breadth / participation / persistence labels and the "why" sentence
come from the rule tables below (served in meta.context so the UI shows the exact rules).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable

import numpy as np
import pandas as pd

from App.services import db, universe
from App.services.common import STATUS_PARTIAL, Result, no_session, unavailable
from App.services.groups import _GD_FLOOR_LABEL, SPLIT_DOWN, SPLIT_UP, _floor_mask, group_id

TODAY_METRICS = [
    "change_1d_pct", "rvol", "delivery_pct", "delivery_vs_20d", "delivery_spike", "turnover_vs_20d",
    "move_quality", "away_52w_high_pct", "market_cap_cr",
]
MARKET_METRICS = ["advance_pct", "new_52w_highs", "new_52w_lows", "market_turnover_vs_20d",
                  "market_delivery_vs_20d", "india_vix"]
GROUP_TODAY_METRICS = [
    "group_return_1d", "group_pct_up_today", "group_turnover_vs_20d", "group_delivery_vs_20d",
    "move_concentration", "group_move_persistence", "group_rank",
]

INDICES = [("Nifty 50", "Nifty 50"), ("NIFTY MIDSML 400", "MidSml 400"), ("NIFTY SMLCAP 250", "SmallCap 250")]
VIX = "India VIX"
TINY_CAP_CR = 500.0
EVENT_SESSIONS = 5            # catalysts within ±5 sessions (the evidence engine's window)
FORWARD_DAYS = 7              # ≈ 5 sessions ahead, calendar days
CIRCUIT_TOL = 0.0005          # the evidence engine's band tolerance
GAP_UP_PCT = 2.0
MOVERS_DEFAULT_N = 30
DEAL_MIN_NET_CR = 0.1          # a member counts as a net deal buyer / seller from ₹0.1 Cr net (ex-PROP)
CATALYST_ACTIONS = ("bonus", "split", "rights_issue", "merger_demerger", "dividend")

# --------------------------------------------------------------------------
# Rules as data
# --------------------------------------------------------------------------
# Clause = (field, op, value). A NULL field fails the clause. First matching rule wins.
QUALITY_RULES: list[dict[str, Any]] = [
    {"id": "operator", "label": "Operator-ish", "tone": "bad",
     "when": [("market_cap_cr", "lt", TINY_CAP_CR), ("at_circuit", "is_true", None)],
     "why": f"Tiny company (market cap < ₹{TINY_CAP_CR:,.0f} Cr) closing at its price band: moves like this are easy "
            "to push and often reverse; treat as a trap unless volume and delivery keep confirming."},
    {"id": "real", "label": "Real", "tone": "good",
     "when": [("rvol", "gte", 1.5), ("delivery_vs_20d", "gte", 1.2)],
     "why": "Heavy volume (RVOL >= 1.5) AND more shares taken into delivery than usual (delivery x >= 1.2): "
            "real buyers (or real sellers on a down day) are behind the move."},
    {"id": "churn", "label": "Churn", "tone": "caution",
     "when": [("rvol", "gte", 1.5), ("delivery_vs_20d", "lt", 1.2)],
     "why": "Heavy volume but delivery is not above normal: mostly intraday trading, not investors taking shares home."},
    {"id": "thin", "label": "Thin", "tone": "caution",
     "when": [("rvol", "lt", 1.0)],
     "why": "Below-average volume (RVOL < 1): few participants; thin moves reverse easily."},
    {"id": "normal", "label": "Normal", "tone": "neutral",
     "when": [("rvol", "gte", 1.0)],
     "why": "Ordinary volume (RVOL 1-1.5, or delivery unknown): no strong participation signal either way."},
]

BREAKOUT_RULES: list[dict[str, Any]] = [
    {"id": "new_52w_high", "label": "52W high", "rule": "session high reached the stored 52-week high"},
    {"id": "setup_trigger", "label": "Setup trigger", "rule": "close above the trigger the stock carried in a Desk queue "
                                                             "on the previous session (Darvas box top / prior high / VCP pivot)"},
    {"id": "high_20d_rvol", "label": "20D high + RVOL", "rule": "close at a 20-day high (>= prior 20-day high) on RVOL >= 1.5"},
    {"id": "gap_up", "label": "Gap-up", "rule": f"open >= {GAP_UP_PCT:g}% above the previous close and close >= open (gap held)"},
    {"id": "accumulation", "label": "Accumulation", "rule": "delivery x >= 1.5 on an up day (buyers taking delivery)"},
    {"id": "distribution", "label": "Distribution", "rule": "delivery x >= 1.5 on a down day (holders delivering out)"},
]

BREADTH_RULES = {"one_stock_share": 50.0, "broad_pct": 60.0, "min_members": 3}
PARTICIPATION_RULES: list[dict[str, Any]] = [
    {"id": "real", "phrase": "real participation", "when": [("turnover_vs_20d", "gte", 1.3), ("delivery_vs_20d", "gte", 1.2)]},
    {"id": "churn", "phrase": "volume without delivery (trading churn)", "when": [("turnover_vs_20d", "gte", 1.3), ("delivery_vs_20d", "lt", 1.0)]},
    {"id": "heavy", "phrase": "above-normal activity", "when": [("turnover_vs_20d", "gte", 1.3)]},
    {"id": "light", "phrase": "on light volume", "when": [("turnover_vs_20d", "lt", 0.8)]},
    {"id": "normal", "phrase": "normal participation", "when": [("turnover_vs_20d", "gte", 0.8)]},
]
PERSISTENCE_RULES: list[dict[str, Any]] = [
    {"id": "trend_up", "label": "Trend", "phrase": "part of an up-trend",
     "when": [("return_1d", "gt", 0), ("return_5d", "gt", 0), ("return_21d", "gt", 0)]},
    {"id": "bounce", "label": "One-day pop", "phrase": "a one-day pop inside a falling month",
     "when": [("return_1d", "gt", 0), ("return_21d", "lte", 0)]},
    {"id": "resume_up", "label": "Dip bought", "phrase": "a dip being bought inside a rising month",
     "when": [("return_1d", "gt", 0), ("return_5d", "lte", 0), ("return_21d", "gt", 0)]},
    {"id": "trend_down", "label": "Down-trend", "phrase": "part of a down-trend",
     "when": [("return_1d", "lte", 0), ("return_5d", "lte", 0), ("return_21d", "lte", 0)]},
    {"id": "pullback", "label": "Pullback", "phrase": "a pullback inside a rising month",
     "when": [("return_1d", "lte", 0), ("return_21d", "gt", 0)]},
    {"id": "fade", "label": "One-day drop", "phrase": "a one-day drop after a positive week",
     "when": [("return_1d", "lte", 0), ("return_5d", "gt", 0), ("return_21d", "lte", 0)]},
]
NEWS_LABELS = {
    "financial_results": "results", "board_meeting": "board meeting", "order_or_contract": "order/contract",
    "material_corporate_announcement": "corporate announcement", "investor_meeting": "investor meeting",
    "dividend": "dividend", "rights_issue": "rights issue", "regulatory_action": "regulatory action",
    "bonus": "bonus", "split": "split", "fund_raise": "fund raise",
}


def _clause(row: dict[str, Any], field: str, op: str, value: Any) -> bool:
    v = row.get(field)
    if op == "is_true":
        return v is True or (isinstance(v, (bool, np.bool_)) and bool(v))
    v = db.num(v)
    if v is None:
        return False
    return {"gt": v > value, "gte": v >= value, "lt": v < value, "lte": v <= value}[op]


def first_rule(row: dict[str, Any], rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    """First rule whose clauses all hold (NULL inputs fail closed)."""
    for rule in rules:
        if all(_clause(row, f, op, val) for f, op, val in rule["when"]):
            return rule
    return None


def rules_payload(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**{k: v for k, v in r.items() if k != "when"},
             "when": [{"field": f, "op": op, "value": val} for f, op, val in r.get("when", [])]} for r in rules]


# --------------------------------------------------------------------------
# Loaders
# --------------------------------------------------------------------------
_EXTRA = ("open_price", "high_price", "low_price", "turnover_cr", "delivery_qty", "avg_delivery_qty_20d",
          "delivery_spike", "high_52w", "low_52w", "new_20d_high")


def _extra_cols(con: Any) -> str:
    have = set(db.table_columns(con, "indicators_daily"))
    return "".join(f", i.{c} AS x_{c}" if c in have else f", NULL AS x_{c}" for c in _EXTRA)


def _in(values: Iterable[Any]) -> tuple[str, list[Any]]:
    vals = sorted({v for v in values if v is not None})
    return ",".join(["?"] * len(vals)), vals


def _queues(con: Any, d: date | None) -> pd.DataFrame:
    if d is None or not db.table_exists(con, "setup_daily"):
        return pd.DataFrame(columns=["symbol", "queue", "trigger_price"])
    return con.execute("SELECT symbol, queue, trigger_price FROM setup_daily WHERE trade_date = ?", [d]).df()


def _deals_today(con: Any, d: date) -> pd.DataFrame:
    if not db.table_exists(con, "deal_session_net"):
        return pd.DataFrame()
    cols = set(db.table_columns(con, "deal_session_net"))
    want = [c for c in ("symbol", "n_prints", "net_value_cr", "net_value_cr_ex_prop", "buying_houses",
                        "selling_houses", "event_type") if c in cols]
    return con.execute(f"SELECT {', '.join(want)} FROM deal_session_net WHERE trade_date = ?", [d]).df()


def _events(con: Any, symbols: list[str], as_of: date, start: date) -> tuple[dict[str, dict], dict[str, list], dict[str, dict]]:
    """(results nearby, news today, corporate action nearby) per symbol."""
    results: dict[str, dict] = {}
    news: dict[str, list] = {}
    actions: dict[str, dict] = {}
    end = as_of + timedelta(days=FORWARD_DAYS)
    ph, syms = _in(symbols)
    if not syms:
        return results, news, actions
    if db.table_exists(con, "security_events"):
        ev = db.records(con, f"""
            SELECT symbol, event_date, event_type, headline FROM security_events
            WHERE symbol IN ({ph}) AND event_date BETWEEN ? AND ?
            ORDER BY event_date""", [*syms, start, end])
        for e in ev:
            d = db.to_date(e["event_date"])
            et = db.text(e["event_type"]) or ""
            head = db.text(e.get("headline")) or ""
            is_results = et == "financial_results" or (et == "board_meeting" and "result" in head.lower())
            if is_results:
                prev = results.get(e["symbol"])
                # prefer the event closest to as_of
                if prev is None or abs((d - as_of).days) < abs((prev["event_date"] - as_of).days):
                    results[e["symbol"]] = {"event_type": et, "event_date": d,
                                            "when": "upcoming" if d > as_of else ("today" if d == as_of else "past"),
                                            "headline": head[:200] or None}
            if d == as_of and et and et != "other":
                news.setdefault(e["symbol"], []).append({"event_type": et, "label": NEWS_LABELS.get(et, et.replace("_", " ")),
                                                         "headline": head[:200] or None})
    if db.table_exists(con, "corporate_actions"):
        ph2 = ",".join(["?"] * len(CATALYST_ACTIONS))
        ca = db.records(con, f"""
            SELECT symbol, ex_date, action_type, description FROM corporate_actions
            WHERE symbol IN ({ph}) AND ex_date BETWEEN ? AND ? AND action_type IN ({ph2})
            ORDER BY ex_date""", [*syms, start, end, *CATALYST_ACTIONS])
        for a in ca:
            d = db.to_date(a["ex_date"])
            prev = actions.get(a["symbol"])
            if prev is None or abs((d - as_of).days) < abs((prev["event_date"] - as_of).days):
                actions[a["symbol"]] = {"event_type": db.text(a["action_type"]), "event_date": d,
                                        "when": "upcoming" if d > as_of else ("today" if d == as_of else "past"),
                                        "headline": (db.text(a.get("description")) or "")[:200] or None}
    return results, news, actions


def _stock_frame(con: Any, as_of: date) -> pd.DataFrame:
    """Every stock on as_of with today's enrichment (full universe; callers apply floors)."""
    snap = universe.snapshot_sql(con, extra_cols=_extra_cols(con))
    df = con.execute(f"WITH s AS ({snap}) SELECT * FROM s", [as_of]).df()
    if df.empty:
        return df
    for c in ("close", "prev_close", "change_1d_pct", "rvol", "delivery_pct", "delivery_vs_20d", "market_cap_cr",
              "adv_cr_20d", "circuit_band", "away_52w_high_pct", *(f"x_{c}" for c in _EXTRA if c not in ("delivery_spike", "new_20d_high"))):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    band = df["circuit_band"]
    prev = df["prev_close"]
    up_lim = prev * (1 + band / 100.0) * (1 - CIRCUIT_TOL)
    dn_lim = prev * (1 - band / 100.0) * (1 + CIRCUIT_TOL)
    known_band = band.notna() & prev.notna() & (band > 0)
    df["at_upper_circuit"] = np.where(known_band, df["close"] >= up_lim, None)
    df["at_lower_circuit"] = np.where(known_band, df["close"] <= dn_lim, None)
    df["at_circuit"] = np.where(known_band, (df["close"] >= up_lim) | (df["close"] <= dn_lim), None)
    df["turnover_vs_20d"] = df["x_turnover_cr"] / df["adv_cr_20d"].where(df["adv_cr_20d"] > 0)
    df["gap_pct"] = (df["x_open_price"] / prev.where(prev > 0) - 1) * 100
    h52, l52 = df["x_high_52w"], df["x_low_52w"]
    df["is_52w_high"] = np.where(h52.notna() & df["x_high_price"].notna(), df["x_high_price"] >= h52, None)
    df["is_52w_low"] = np.where(l52.notna() & (l52 > 0) & df["x_low_price"].notna(), df["x_low_price"] <= l52, None)

    # Queues today and the previous session's triggers.
    q_today = _queues(con, as_of)
    qmap = q_today.groupby("symbol")["queue"].apply(lambda s: sorted(set(s))).to_dict() if not q_today.empty else {}
    df["queues"] = df["symbol"].map(lambda s: qmap.get(s, []))
    prev_sess = db.session_back(con, as_of, 1)
    q_prev = _queues(con, prev_sess)
    trig: dict[str, tuple[str, float]] = {}
    for r in q_prev.to_dict("records"):
        t = db.num(r.get("trigger_price"))
        if t is None:
            continue
        cur = trig.get(r["symbol"])
        if cur is None or t < cur[1]:
            trig[r["symbol"]] = (str(r["queue"]), t)
    df["prev_setup_queue"] = df["symbol"].map(lambda s: trig.get(s, (None, None))[0])
    df["prev_trigger"] = pd.to_numeric(df["symbol"].map(lambda s: trig.get(s, (None, None))[1]), errors="coerce")

    # Deals today.
    deals = _deals_today(con, as_of)
    if not deals.empty:
        deals = deals.drop_duplicates("symbol").set_index("symbol")
        for c in ("n_prints", "net_value_cr", "net_value_cr_ex_prop", "buying_houses", "selling_houses", "event_type"):
            df[f"deal_{c}"] = df["symbol"].map(deals[c]) if c in deals.columns else None
    else:
        for c in ("n_prints", "net_value_cr", "net_value_cr_ex_prop", "buying_houses", "selling_houses", "event_type"):
            df[f"deal_{c}"] = None

    # Catalysts within ±5 sessions.
    back = db.session_back(con, as_of, EVENT_SESSIONS) or (as_of - timedelta(days=FORWARD_DAYS))
    results, news, actions = _events(con, df["symbol"].dropna().astype(str).tolist(), as_of, back)
    df["results_nearby"] = df["symbol"].map(lambda s: results.get(s))
    df["news_today"] = df["symbol"].map(lambda s: news.get(s, []))
    df["corp_action_nearby"] = df["symbol"].map(lambda s: actions.get(s))
    return df


def stock_frame(con: Any, as_of: date) -> pd.DataFrame:
    return db.cached("today.stocks", (as_of,), lambda: _stock_frame(con, as_of))


# --------------------------------------------------------------------------
# Stock rows
# --------------------------------------------------------------------------
def _b(v: Any) -> bool | None:
    return db.boolean(v)


def traits(r: dict[str, Any]) -> list[str]:
    """Pre-move traits the evidence engine found strongest before upper-circuit moves."""
    out = []
    if _b(r.get("x_delivery_spike")):
        out.append("delivery_spike")
    rv = db.num(r.get("rvol"))
    if rv is not None and rv >= 1.5:
        out.append("rvol_1_5")
    if r.get("results_nearby"):
        out.append("results_5")
    return out


def shape_stock_row(r: dict[str, Any]) -> dict[str, Any]:
    row = universe.shape_stock(r)
    q = first_rule({**r, "at_circuit": _b(r.get("at_circuit"))}, QUALITY_RULES)
    row.update({
        "turnover_cr": db.num(r.get("x_turnover_cr"), 2),
        "turnover_vs_20d": db.num(r.get("turnover_vs_20d"), 2),
        "delivery_spike": _b(r.get("x_delivery_spike")),
        "away_52w_high_pct": db.num(r.get("away_52w_high_pct"), 2),
        "is_52w_high": _b(r.get("is_52w_high")),
        "circuit_band": db.num(r.get("circuit_band"), 0),
        "at_upper_circuit": _b(r.get("at_upper_circuit")),
        "at_lower_circuit": _b(r.get("at_lower_circuit")),
        "gap_pct": db.num(r.get("gap_pct"), 2),
        "queues": list(r.get("queues") or []),
        "deal_prints_today": db.integer(r.get("deal_n_prints")),
        "deal_net_cr_today": db.num(r.get("deal_net_value_cr_ex_prop"), 2),
        "deal_event_type": db.text(r.get("deal_event_type")),
        "results_nearby": r.get("results_nearby") or None,
        "corp_action_nearby": r.get("corp_action_nearby") or None,
        "news_today": list(r.get("news_today") or []),
        "quality": q["label"] if q else None,
        "quality_id": q["id"] if q else None,
        "quality_tone": q["tone"] if q else None,
        "traits": traits(r),
    })
    return row


def _floor(df: pd.DataFrame, min_mcap_cr: float) -> pd.DataFrame:
    if min_mcap_cr and min_mcap_cr > 0:
        return df[df["market_cap_cr"] >= float(min_mcap_cr)]
    return df


def _evidence_traits(con: Any) -> list[dict[str, Any]]:
    if not db.table_exists(con, "big_move_lift"):
        return []
    cols = set(db.table_columns(con, "big_move_lift"))
    if not {"feature", "lift", "subset"} <= cols:
        return []
    want = {"delivery_spike": "delivery_spike", "rvol": "rvol_1_5", "results_within_5": "results_5"}
    extra = ", lift_test" if "lift_test" in cols else ", NULL AS lift_test"
    extra += ", meaning" if "meaning" in cols else ", NULL AS meaning"
    rows = db.records(con, f"""
        SELECT feature, subset, lift {extra} FROM big_move_lift
        WHERE feature IN ('delivery_spike', 'rvol', 'results_within_5') AND subset IN ('upper_circuit', 'all')
        {'AND "offset" = 1' if 'offset' in cols else ''}""")
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = want[str(r["feature"])]
        e = out.setdefault(key, {"key": key, "meaning": db.text(r["meaning"])})
        e[f"lift_{r['subset']}"] = db.num(r["lift"], 2)
        if r["subset"] == "upper_circuit":
            e["lift_test_upper_circuit"] = db.num(r["lift_test"], 2)
    return [out[k] for k in ("delivery_spike", "rvol_1_5", "results_5") if k in out]


def _resolve(con: Any, as_of: date | None) -> date | None:
    return db.resolve_as_of(con, as_of)


def movers(as_of: date | None, min_mcap_cr: float = 1000.0, n: int = MOVERS_DEFAULT_N) -> Result:
    with db.market_conn() as con:
        resolved = _resolve(con, as_of)
        if resolved is None:
            return no_session(as_of)
        df = stock_frame(con, resolved)
        ev = _evidence_traits(con)
        has_setup = db.table_exists(con, "setup_daily")
        has_deals = db.table_exists(con, "deal_session_net")
    if df.empty:
        return unavailable(resolved, "no stock rows on this session", ["indicators_daily"])
    f = _floor(df, min_mcap_cr)
    f = f[f["change_1d_pct"].notna()]
    gain = f[f["change_1d_pct"] > 0].sort_values("change_1d_pct", ascending=False).head(n)
    lose = f[f["change_1d_pct"] < 0].sort_values("change_1d_pct", ascending=True).head(n)
    rows = []
    for side, part in (("gainer", gain), ("loser", lose)):
        for i, r in enumerate(part.to_dict("records"), start=1):
            rows.append({"side": side, "rank": i, **shape_stock_row(r)})
    notes = ["Quality of move uses the rule table in meta.context.quality_rules (first match wins; NULL inputs fail)."]
    if not has_setup:
        notes.append("setup_daily not built: Desk-queue membership unknown.")
    if not has_deals:
        notes.append("deal_session_net not built: deals today unknown.")
    return Result(
        as_of=resolved, rows=rows,
        status="ok" if has_setup and has_deals else STATUS_PARTIAL,
        reason=None if has_setup and has_deals else "some context tables are not built",
        sources=["indicators_daily", "setup_daily", "deal_session_net", "security_events", "corporate_actions"],
        notes=notes, metric_keys=TODAY_METRICS,
        extra={"min_mcap_cr": min_mcap_cr, "n": n, "universe": int(len(f)),
               "up": int((f["change_1d_pct"] > 0).sum()), "down": int((f["change_1d_pct"] < 0).sum()),
               "quality_rules": rules_payload(QUALITY_RULES), "evidence_traits": ev,
               "tiny_cap_cr": TINY_CAP_CR},
    )


def breakout_kinds(r: dict[str, Any]) -> list[str]:
    kinds = []
    chg = db.num(r.get("change_1d_pct"))
    close = db.num(r.get("close"))
    if _b(r.get("is_52w_high")):
        kinds.append("new_52w_high")
    trig = db.num(r.get("prev_trigger"))
    if trig is not None and close is not None and close > trig:
        kinds.append("setup_trigger")
    rv = db.num(r.get("rvol"))
    if _b(r.get("x_new_20d_high")) and rv is not None and rv >= 1.5:
        kinds.append("high_20d_rvol")
    gap = db.num(r.get("gap_pct"))
    op = db.num(r.get("x_open_price"))
    if gap is not None and gap >= GAP_UP_PCT and close is not None and op is not None and close >= op:
        kinds.append("gap_up")
    dx = db.num(r.get("delivery_vs_20d"))
    if dx is not None and dx >= 1.5 and chg is not None:
        if chg > 0:
            kinds.append("accumulation")
        elif chg < 0:
            kinds.append("distribution")
    return kinds


def breakouts(as_of: date | None, min_mcap_cr: float = 1000.0) -> Result:
    with db.market_conn() as con:
        resolved = _resolve(con, as_of)
        if resolved is None:
            return no_session(as_of)
        df = stock_frame(con, resolved)
        ev = _evidence_traits(con)
        has_setup = db.table_exists(con, "setup_daily")
    if df.empty:
        return unavailable(resolved, "no stock rows on this session", ["indicators_daily"])
    f = _floor(df, min_mcap_cr)
    rows = []
    counts: dict[str, int] = {r["id"]: 0 for r in BREAKOUT_RULES}
    for r in f.to_dict("records"):
        kinds = breakout_kinds(r)
        if not kinds:
            continue
        for k in kinds:
            counts[k] += 1
        row = shape_stock_row(r)
        row.update({"kinds": kinds, "setup_queue": db.text(r.get("prev_setup_queue")) if "setup_trigger" in kinds else None,
                    "setup_trigger": db.num(r.get("prev_trigger"), 2) if "setup_trigger" in kinds else None})
        rows.append(row)
    rows.sort(key=lambda x: (-(x["change_1d_pct"] if x["change_1d_pct"] is not None else -1e9)))
    return Result(
        as_of=resolved, rows=rows,
        status="ok" if has_setup else STATUS_PARTIAL,
        reason=None if has_setup else "setup_daily not built: setup triggers unknown",
        sources=["indicators_daily", "setup_daily"], metric_keys=TODAY_METRICS,
        extra={"min_mcap_cr": min_mcap_cr, "rules": BREAKOUT_RULES, "counts": counts, "evidence_traits": ev,
               "quality_rules": rules_payload(QUALITY_RULES)},
    )


# --------------------------------------------------------------------------
# Market strip
# --------------------------------------------------------------------------
def _index_rows(con: Any, as_of: date) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    names = [n for n, _ in INDICES] + [VIX]
    if not db.table_exists(con, "index_daily"):
        return [], {}
    ph = ",".join(["?"] * len(names))
    df = con.execute(f"""
        SELECT index_name, trade_date, close_price, previous_close FROM index_daily
        WHERE index_name IN ({ph}) AND trade_date <= ? AND trade_date >= ?
        ORDER BY index_name, trade_date""", [*names, as_of, as_of - timedelta(days=45)]).df()
    out, vix = [], {}
    for name, label in INDICES + [(VIX, "India VIX")]:
        g = df[df["index_name"] == name]
        g = g[pd.to_datetime(g["trade_date"]).dt.date <= as_of]
        if g.empty or db.to_date(g["trade_date"].iloc[-1]) != as_of:
            rec = {"name": name, "label": label, "close": None, "return_1d_pct": None, "return_5d_pct": None,
                   "return_20d_pct": None}
        else:
            c = pd.to_numeric(g["close_price"], errors="coerce").to_numpy()
            pc = db.num(g["previous_close"].iloc[-1])
            base1 = pc if pc else (c[-2] if len(c) >= 2 else None)

            def ret(base: Any) -> float | None:
                b = db.num(base)
                return db.num((c[-1] / b - 1) * 100, 2) if b and db.num(c[-1]) is not None else None

            rec = {"name": name, "label": label, "close": db.num(c[-1], 2), "return_1d_pct": ret(base1),
                   "return_5d_pct": ret(c[-6]) if len(c) >= 6 else None,
                   "return_20d_pct": ret(c[-21]) if len(c) >= 21 else None}
        if name == VIX:
            vix = rec
        else:
            out.append(rec)
    return out, vix


def _market_aggregates(con: Any, as_of: date) -> pd.DataFrame:
    sessions = db.recent_sessions(con, as_of, 26)
    if not sessions:
        return pd.DataFrame()
    have = set(db.table_columns(con, "indicators_daily"))
    deliv = ("sum(delivery_qty * close_price) FILTER (WHERE delivery_qty IS NOT NULL AND turnover_cr IS NOT NULL) / 1e7"
             if "delivery_qty" in have else "NULL")
    deliv_to = "sum(turnover_cr) FILTER (WHERE delivery_qty IS NOT NULL)" if "delivery_qty" in have else "NULL"
    return con.execute(f"""
        SELECT trade_date,
               sum(turnover_cr) AS turnover_cr,
               {deliv} AS delivery_value_cr,
               {deliv_to} AS delivery_base_turnover_cr,
               count(*) FILTER (WHERE high_52w IS NOT NULL AND high_price >= high_52w) AS new_52w_highs,
               count(*) FILTER (WHERE low_52w IS NOT NULL AND low_52w > 0 AND low_price <= low_52w) AS new_52w_lows,
               count(*) FILTER (WHERE close_price >= prev_close * 1.05) AS up_5pct,
               count(*) FILTER (WHERE close_price <= prev_close * 0.95) AS down_5pct
        FROM indicators_daily
        WHERE trade_date >= ? AND trade_date <= ? AND upper(symbol) <> 'TOTAL'
        GROUP BY trade_date ORDER BY trade_date""", [sessions[-1], as_of]).df()


def market(as_of: date | None) -> Result:
    with db.market_conn() as con:
        resolved = _resolve(con, as_of)
        if resolved is None:
            return no_session(as_of)
        agg = db.cached("today.market_agg", (resolved,), lambda: _market_aggregates(con, resolved))
        idx, vix = _index_rows(con, resolved)
        breadth = None
        if db.table_exists(con, "breadth_daily"):
            b = db.records(con, "SELECT advancers, decliners, unchanged, advance_pct, stocks FROM breadth_daily WHERE trade_date = ?", [resolved])
            breadth = b[0] if b else None
    if agg.empty:
        return unavailable(resolved, "no indicators_daily rows", ["indicators_daily"])
    agg = agg.copy()
    agg["trade_date"] = pd.to_datetime(agg["trade_date"]).dt.date
    agg["delivery_pct"] = agg["delivery_value_cr"] / agg["delivery_base_turnover_cr"].where(agg["delivery_base_turnover_cr"] > 0) * 100
    today = agg[agg["trade_date"] == resolved]
    prior = agg[agg["trade_date"] < resolved]
    if today.empty:
        return unavailable(resolved, "no indicators_daily rows on this session", ["indicators_daily"])
    t = today.iloc[0]
    p20, p5 = prior.tail(20), prior.tail(5)

    def avg(s: pd.Series, need: int) -> float | None:
        s = pd.to_numeric(s, errors="coerce").dropna()
        return float(s.mean()) if len(s) >= need else None

    to_avg = avg(p20["turnover_cr"], 15)
    dl_avg = avg(p20["delivery_pct"], 15)
    to = db.num(t["turnover_cr"])
    dl = db.num(t["delivery_pct"])
    row = {
        "trade_date": resolved,
        "indices": idx,
        "india_vix": vix.get("close"),
        "vix_change_1d_pct": vix.get("return_1d_pct"),
        "advancers": db.integer(breadth["advancers"]) if breadth else None,
        "decliners": db.integer(breadth["decliners"]) if breadth else None,
        "unchanged": db.integer(breadth["unchanged"]) if breadth else None,
        "advance_pct": db.num(breadth["advance_pct"], 1) if breadth else None,
        "new_52w_highs": db.integer(t["new_52w_highs"]),
        "new_52w_lows": db.integer(t["new_52w_lows"]),
        "new_52w_highs_5d_avg": db.num(avg(p5["new_52w_highs"], 5), 1),
        "new_52w_lows_5d_avg": db.num(avg(p5["new_52w_lows"], 5), 1),
        "up_5pct": db.integer(t["up_5pct"]),
        "down_5pct": db.integer(t["down_5pct"]),
        "turnover_cr": db.num(to, 0),
        "turnover_20d_avg_cr": db.num(to_avg, 0),
        "turnover_vs_20d": db.num(to / to_avg, 2) if to is not None and to_avg else None,
        "delivery_pct": db.num(dl, 1),
        "delivery_pct_20d_avg": db.num(dl_avg, 1),
        "delivery_vs_20d": db.num(dl / dl_avg, 2) if dl is not None and dl_avg else None,
    }
    return Result(
        as_of=resolved, rows=[row], sources=["breadth_daily", "index_daily", "indicators_daily"],
        notes=["Turnover = sum of every stock's traded value that session; the average is over the prior 20 sessions.",
               "Market delivery % = delivered value ÷ traded value of stocks that report delivery (EQ series).",
               "52W highs/lows count stocks whose session high/low reached the stored 52-week high/low; "
               "the comparison is the average of the prior 5 sessions."],
        metric_keys=MARKET_METRICS,
    )


# --------------------------------------------------------------------------
# Groups today + why
# --------------------------------------------------------------------------
def _gd_context(con: Any, as_of: date, level_key: str, floor: str) -> dict[str, dict[str, Any]]:
    if not db.table_exists(con, "group_daily"):
        return {}
    cols = set(db.table_columns(con, "group_daily"))
    need = {"trade_date", "level", "group_name", "ret_ew_5d", "ret_ew_21d"}
    if not need <= cols:
        return {}
    opt = [c for c in ("rank", "rank_chg_5d", "rank_n", "ret_ew_1d") if c in cols]
    floor_clause, params = "", [as_of, universe.LEVELS[level_key][1]]
    if "floor" in cols:
        floor_clause = "AND CAST(floor AS VARCHAR) = ?"
        params.append(_GD_FLOOR_LABEL.get(floor, "1000cr"))
    rows = db.records(con, f"""
        SELECT group_name, ret_ew_5d, ret_ew_21d {''.join(', ' + c for c in opt)} FROM group_daily
        WHERE trade_date = ? AND lower(CAST(level AS VARCHAR)) = lower(?) {floor_clause}""", params)
    return {str(r["group_name"]): r for r in rows}


def _pct(a: float, b: float) -> float | None:
    return round(a / b * 100.0, 1) if b else None


def why_sentence(g: dict[str, Any]) -> str | None:
    """Plain-language 'why' built ONLY from the group's facts (skips any clause whose facts are NULL)."""
    ret = g.get("return_1d")
    n = g.get("stocks") or 0
    if ret is None or not n:
        return None
    up = ret >= 0
    name = g.get("group_name") or "Group"
    s = f"{name} {ret:+.1f}% today"
    tops = g.get("top_contributors") or []
    pct_dir = g.get("pct_up") if up else g.get("pct_down")
    if g.get("breadth_label") == "one-stock" and tops:
        s += f", driven by one stock ({tops[0]['symbol']} {tops[0]['change_1d_pct']:+.1f}% = {g['top1_share_pct']:.0f}% of the move)"
    elif pct_dir is not None:
        word = {"broad": "broad", "mixed": "mixed", "thin": "thin group"}.get(g.get("breadth_label") or "", "mixed")
        s += f", {word} ({pct_dir:.0f}% of {n} stock{'s' if n != 1 else ''} {'up' if up else 'down'})"
        if tops:
            s += ", led by " + ", ".join(f"{c['symbol']} {c['change_1d_pct']:+.1f}%" for c in tops[:3])
    s += "."
    tv, dv = g.get("turnover_vs_20d"), g.get("delivery_vs_20d")
    part = g.get("participation")
    if tv is not None and dv is not None:
        s += f" Turnover {tv:.2f}× normal with delivery {dv:.2f}×" + (f" — {part}." if part else ".")
    elif tv is not None:
        s += f" Turnover {tv:.2f}× normal" + (f" — {part}." if part else ".")
    b, sl = g.get("deal_buyers") or 0, g.get("deal_sellers") or 0
    if b or sl:
        bits = []
        if b:
            bits.append(f"{b} net buyer{'s' if b != 1 else ''}")
        if sl:
            bits.append(f"{sl} net seller{'s' if sl != 1 else ''}")
        net = g.get("deal_net_cr")
        sign = "+" if (net or 0) >= 0 else "−"
        s += " Deals: " + " and ".join(bits) + (f" (net {sign}₹{abs(net):,.1f} Cr, PROP excluded)." if net is not None else ".")
    rn = g.get("results_nearby_n") or 0
    if rn:
        s += f" {rn} member{'s' if rn != 1 else ''} with results within 5 sessions."
    news = g.get("news_types") or {}
    if news:
        s += " News today: " + ", ".join(f"{k} ×{v}" if v > 1 else k for k, v in sorted(news.items(), key=lambda kv: -kv[1])[:3]) + "."
    r5, r21, pers = g.get("return_5d"), g.get("return_21d"), g.get("persistence_phrase")
    if r5 is not None and r21 is not None:
        s += f" 5d {r5:+.1f}%, 21d {r21:+.1f}%" + (f" — {pers}." if pers else ".")
    return s


def _contrib(sub: pd.DataFrame, n: int) -> pd.DataFrame:
    c = sub[["symbol", "change_1d_pct", "rvol", "delivery_vs_20d"]].copy()
    c["contribution"] = c["change_1d_pct"] / n
    return c


def group_rows(df: pd.DataFrame, level_key: str, floor: str, gd: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    col = universe.LEVELS[level_key][0]
    m = df[_floor_mask(df["market_cap_cr"], floor).to_numpy(dtype=bool)].copy()
    m = m[m[col].notna()]
    r1 = m["change_1d_pct"] / 100.0
    m.loc[(r1 <= SPLIT_DOWN) | (r1 >= SPLIT_UP), "change_1d_pct"] = np.nan  # unadjusted corporate action
    out: list[dict[str, Any]] = []
    for name, sub in m.groupby(col, sort=False):
        valid = sub[sub["change_1d_pct"].notna()]
        n = int(len(valid))
        g: dict[str, Any] = {"id": group_id(level_key, str(name)), "level": level_key, "group_name": str(name),
                             "stocks": int(len(sub)), "stocks_with_return": n}
        ret = float(valid["change_1d_pct"].mean()) if n else None
        g["return_1d"] = db.num(ret, 2)
        chg = valid["change_1d_pct"]
        g["advancers"], g["decliners"] = int((chg > 0).sum()), int((chg < 0).sum())
        g["pct_up"] = _pct((chg > 0).sum(), n)
        g["pct_down"] = _pct((chg < 0).sum(), n)
        g["pct_up_2"] = _pct((chg > 2).sum(), n)
        g["pct_down_2"] = _pct((chg < -2).sum(), n)
        to = sub[["x_turnover_cr", "adv_cr_20d"]].dropna()
        g["turnover_cr"] = db.num(sub["x_turnover_cr"].sum(min_count=1), 1)
        g["turnover_vs_20d"] = db.num(to["x_turnover_cr"].sum() / to["adv_cr_20d"].sum(), 2) if len(to) and to["adv_cr_20d"].sum() > 0 else None
        dq = sub[["x_delivery_qty", "x_avg_delivery_qty_20d"]].dropna()
        g["delivery_vs_20d"] = db.num(dq["x_delivery_qty"].sum() / dq["x_avg_delivery_qty_20d"].sum(), 2) if len(dq) and dq["x_avg_delivery_qty_20d"].sum() > 0 else None

        tops: list[dict[str, Any]] = []
        det: list[dict[str, Any]] = []
        top1_share = None
        if n and ret is not None:
            c = _contrib(valid, n)
            same = c[np.sign(c["contribution"]) == (1 if ret >= 0 else -1)].sort_values("contribution", ascending=ret < 0)
            opp = c[np.sign(c["contribution"]) == (-1 if ret >= 0 else 1)].sort_values("contribution", ascending=ret >= 0)

            def item(x: dict[str, Any]) -> dict[str, Any]:
                return {"symbol": x["symbol"], "change_1d_pct": db.num(x["change_1d_pct"], 2),
                        "contribution": db.num(x["contribution"], 3),
                        "share_of_move_pct": db.num(x["contribution"] / ret * 100, 0) if ret else None,
                        "weight_pct": db.num(100.0 / n, 1), "rvol": db.num(x["rvol"], 2),
                        "delivery_vs_20d": db.num(x["delivery_vs_20d"], 2)}

            tops = [item(x) for x in same.head(5).to_dict("records")]
            det = [item(x) for x in opp.head(3).to_dict("records")]
            if tops and ret:
                top1_share = tops[0]["share_of_move_pct"]
        g["top_contributors"], g["top_detractors"] = tops, det
        g["top1_share_pct"] = top1_share
        pct_dir = g["pct_up"] if (ret or 0) >= 0 else g["pct_down"]
        if n < BREADTH_RULES["min_members"]:
            g["breadth_label"] = "thin"
        elif top1_share is not None and top1_share >= BREADTH_RULES["one_stock_share"]:
            g["breadth_label"] = "one-stock"
        elif pct_dir is not None and pct_dir >= BREADTH_RULES["broad_pct"]:
            g["breadth_label"] = "broad"
        else:
            g["breadth_label"] = "mixed"
        pr = first_rule(g, PARTICIPATION_RULES)
        g["participation_id"] = pr["id"] if pr else None
        g["participation"] = pr["phrase"] if pr else None

        # deals today
        net = pd.to_numeric(sub["deal_net_value_cr_ex_prop"], errors="coerce")
        g["deal_stocks"] = int(pd.to_numeric(sub["deal_n_prints"], errors="coerce").fillna(0).gt(0).sum())
        g["deal_buyers"] = int((net >= DEAL_MIN_NET_CR).sum())
        g["deal_sellers"] = int((net <= -DEAL_MIN_NET_CR).sum())
        g["deal_net_cr"] = db.num(net.sum(min_count=1), 1)
        # catalysts
        g["results_nearby_n"] = int(sub["results_nearby"].map(bool).sum())
        news: dict[str, int] = {}
        for items in sub["news_today"]:
            for it in items or []:
                news[it["label"]] = news.get(it["label"], 0) + 1
        g["news_types"] = news
        g["news_today_n"] = int(sub["news_today"].map(lambda x: bool(x)).sum())

        # persistence (group_daily first, then members' own 5d / 21d returns)
        ctx = gd.get(str(name))
        if ctx:
            g["return_5d"], g["return_21d"] = db.num(ctx.get("ret_ew_5d"), 2), db.num(ctx.get("ret_ew_21d"), 2)
            g["rank"], g["rank_delta_5"], g["rank_n"] = db.integer(ctx.get("rank")), db.integer(ctx.get("rank_chg_5d")), db.integer(ctx.get("rank_n"))
            g["context_source"] = "group_daily"
        else:
            g["return_5d"] = None
            g["return_21d"] = db.num(pd.to_numeric(sub["return_1m_pct"], errors="coerce").mean(), 2) if "return_1m_pct" in sub else None
            g["rank"] = g["rank_delta_5"] = g["rank_n"] = None
            g["context_source"] = "live"
        pe = first_rule(g, PERSISTENCE_RULES)
        g["persistence_id"] = pe["id"] if pe else None
        g["persistence"] = pe["label"] if pe else None
        g["persistence_phrase"] = pe["phrase"] if pe else None
        g["symbols"] = [s for s in valid.sort_values("change_1d_pct", ascending=(ret or 0) < 0)["symbol"].astype(str).tolist()]
        out.append(g)
    ranked = sorted([g for g in out if g["return_1d"] is not None and g["stocks_with_return"] >= BREADTH_RULES["min_members"]],
                    key=lambda g: -g["return_1d"])
    for i, g in enumerate(ranked, start=1):
        g["rank_1d"] = i
    for g in out:
        g.setdefault("rank_1d", None)
        g["rank_1d_n"] = len(ranked)
        g["why"] = why_sentence(g)
    out.sort(key=lambda g: (g["return_1d"] is None, -(g["return_1d"] or 0)))
    return out


def groups_today(as_of: date | None, level: str = "industry", floor: str = "1000") -> Result:
    level_key = universe.level_key(level)
    if level_key is None:
        raise ValueError(f"level must be one of {sorted(universe.LEVELS)}")
    floor = str(floor or "1000").lower()
    if floor not in _GD_FLOOR_LABEL:
        raise ValueError("floor must be one of 1000, all, watch")
    with db.market_conn() as con:
        resolved = _resolve(con, as_of)
        if resolved is None:
            return no_session(as_of)
        df = stock_frame(con, resolved)
        gd = _gd_context(con, resolved, level_key, floor)
    if df.empty:
        return unavailable(resolved, "no stock rows on this session", ["indicators_daily"])
    rows = db.cached("today.groups", (resolved, level_key, floor, bool(gd)), lambda: group_rows(df, level_key, floor, gd))
    return Result(
        as_of=resolved, rows=rows,
        status="ok" if gd else STATUS_PARTIAL,
        reason=None if gd else "group_daily not built for this session/floor: 5d return and rank unavailable",
        sources=["indicators_daily", "group_daily", "deal_session_net", "security_events"],
        notes=["1D return = equal-weight mean of members' close-to-close change; a move <= -35% or >= +100% is "
               "treated as an unadjusted corporate action and left out.",
               "Contribution = member change ÷ members (points of the group return); share of move = contribution ÷ group return."],
        metric_keys=GROUP_TODAY_METRICS,
        extra={"level": level_key, "floor": floor,
               "breadth_rules": BREADTH_RULES, "participation_rules": rules_payload(PARTICIPATION_RULES),
               "persistence_rules": rules_payload(PERSISTENCE_RULES)},
    )
