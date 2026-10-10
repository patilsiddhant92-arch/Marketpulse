"""Deals desk: evidence verdicts, deal watch, history patterns, houses and groups.

Spec: HarkPro/08-tab-deals.md (rounds 1-2, mockup v1.2). The calculations port
HarkPro/tools/deals_mockup/extract.py so the app and the mockup agree. ONE module feeds both the
API (App/services/deals_tab.py) and the Telegram sender (Scripts/telegram_deals.py), so the Deals
tab and the nightly message can never disagree.

Inputs (read-only): deal_session_net (event classification stays in Scripts/derived/deal_rules.py,
untouched), collapsed `deals` prints, indicators_daily, stocks_master.

Rules (evidence in 08-tab-deals.md: T+20 excess vs the equal-weight >= 1,000 Cr market):
  strong chart  = close > 200 EMA, RS >= 70, within 15% of the 52W high (deal day).
  net buy       : prior month > +30% -> Extended; < -10% -> Falling knife; poor-record buyer -> avoid;
                  strong -> "Confirms setup: check day 3"; weak -> No edge.
  placement     -> Placement (+ strong chart = best reading).   distribute -> Supply at the seller's price.
  churn         -> Churn (quiet day RVOL < 3 = avoid).          transfer -> ignore.
Deal watch (last 10 deal sessions): level = buy VWAP (buys / placements) or sell VWAP (distribution).
  holding = never closed below the level since; lost = last close below; reclaimed = closed below, now above.
  Day 3+: holding upgrades a strong-chart buy to Confirmed, lost downgrades it; a reclaimed seller level = Absorbed.
House record (out of sample): a bet = one house's non-PROP buys >= Rs 5 Cr in one stock-session. Entry next
  open, exit close T+20, minus the equal-weight >= 1,000 Cr market over the same sessions. Only bets whose exit
  is on or before as_of count. Grade (FII/DII only, >= 5 finished bets): good = avg > 0 and beat >= 50%,
  poor = avg < 0, else mixed. Corporate / Other houses are never graded.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

FLOOR_CR = 1000.0
WATCH_SESSIONS = 10
HISTORY_SESSIONS = 20
HISTORY_WINDOWS = (5, 10, 20)
BET_MIN_CR = 5.0
GRADE_MIN_BETS = 5
FWD_SESSIONS = 20
RET_CAP_PCT = 60.0          # |T+20 return| above this = unadjusted corporate action -> dropped
CONFIRM_DAY = 3
STRONG_RS, STRONG_FROM_HIGH = 70.0, -15.0
EXTENDED_R21, FALLING_R21 = 30.0, -10.0
QUIET_RVOL = 3.0
RECORD_LOOKBACK_DAYS = 800  # house record: ~2 years of sessions before as_of
SPARK_DAYS = 45

SIDE = {"fresh": "B", "accumulate": "B", "placement": "P", "distribute": "S", "churn": "C", "transfer_interse": "T"}
EVENT_LABEL = {"fresh": "Net buy (new)", "accumulate": "Net buy (repeat)", "placement": "Placement",
               "distribute": "Net sell", "churn": "Churn", "transfer_interse": "Transfer"}
BUY_EVENTS = ("fresh", "accumulate", "placement")
NOISE_EVENTS = ("churn", "transfer_interse")
VERDICT_ORDER = ["confirm", "place", "absorbed", "watch", "supply", "none", "churn", "avoid", "ignore"]
NOISE_VERDICTS = ("churn", "ignore", "none")

# Buyer-class evidence (study3_funds.py, NSE history Apr 2024 - Jul 2026; buys >= Rs 5 Cr, T+20 vs market).
CLASS_EVIDENCE = [
    {"buyer_class": "FII", "n": 947, "vs_market_pct": 1.2, "beat_pct": 53},
    {"buyer_class": "DII", "n": 825, "vs_market_pct": 0.9, "beat_pct": 46},
    {"buyer_class": "Corporate", "n": 1373, "vs_market_pct": -2.6, "beat_pct": 38},
    {"buyer_class": "Trading firms / HNI", "n": 2374, "vs_market_pct": -2.7, "beat_pct": 41},
]

# History patterns (mockup v1.1): key -> (label, evidence note).
PATTERNS: dict[str, tuple[str, str]] = {
    "repeat_buy": ("Repeated buying", "Buying in 2+ sessions, no selling. Repeat buying alone showed no edge. Use the chart and the deal price."),
    "single_buy": ("Single buy", "One net-buy session."),
    "selling_only": ("Selling only", "Net selling, no buying. Supply stays until price closes above the sellers' price."),
    "mixed": ("Buying and selling", "Both sides in the window. Read the latest session and the deal price."),
    "churn_only": ("Prop desk / churn only", "Same desks in and out. Churn lagged the market by 2.0%. On quiet days it lagged by 3.7%."),
    "transfers_only": ("Transfers only", "Shares changed hands between holders. No new money came in."),
}
PATTERN_ORDER = list(PATTERNS)

_HOUSE_STRIP = re.compile(r"\b(PVT|PRIVATE|LTD|LIMITED|FPI|ODI|-)\b")


def house_key(name: Any) -> str:
    """Crude house merge (as the mockup): drop PVT/LTD/FPI/ODI and lone dashes, keep the first three words."""
    s = _HOUSE_STRIP.sub("", str(name or "").upper())
    return " ".join([w for w in s.split() if w.strip("-")][:3])


def _f(v: Any, nd: int = 1) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if np.isnan(x) or np.isinf(x):
        return None
    x = round(x, nd)
    return 0.0 if x == 0 else x


def _iso(d: Any) -> str:
    return pd.Timestamp(d).date().isoformat()


# ----------------------------------------------------------------------------------------------- loading
def _table_exists(con: Any, name: str) -> bool:
    try:
        con.execute(f"SELECT 1 FROM {name} LIMIT 0")
        return True
    except Exception:  # noqa: BLE001 - duckdb raises CatalogException
        return False


def load_inputs(con: Any, as_of: date) -> dict[str, Any]:
    """Every frame the desk needs, bounded to sessions <= as_of (time-travel safe)."""
    for t in ("deal_session_net", "indicators_daily", "stocks_master", "deals"):
        if not _table_exists(con, t):
            return {"missing": t}
    dsn = con.execute("SELECT * FROM deal_session_net WHERE trade_date <= ?", [as_of]).df()
    if dsn.empty:
        return {"missing": "deal sessions on or before as_of"}
    dsn["trade_date"] = pd.to_datetime(dsn["trade_date"])
    deal_days = sorted(pd.Timestamp(d) for d in dsn["trade_date"].unique())
    last20 = deal_days[-HISTORY_SESSIONS:]
    rec_start = (pd.Timestamp(as_of) - pd.Timedelta(days=RECORD_LOOKBACK_DAYS)).date()
    px_start = min(rec_start, (last20[0] - pd.Timedelta(days=SPARK_DAYS + 10)).date())
    ind = con.execute(
        """SELECT i.symbol, i.trade_date d, i.open_price o, i.high_price h, i.low_price l, i.close_price c,
                  i.ema_50 e50, i.ema_200 e200, i.rs_percentile rs, i.away_52w_high_pct a52, i.return_1m_pct r21,
                  i.rvol, m.security_name nm, m.market_cap_cr mcap, m.sector, m.industry
           FROM indicators_daily i JOIN stocks_master m USING (symbol)
           WHERE i.trade_date BETWEEN ? AND ?""", [px_start, as_of]).df()
    ind["d"] = pd.to_datetime(ind["d"])
    ind = ind.sort_values(["symbol", "d"]).reset_index(drop=True)
    ind["strong"] = (ind.c > ind.e200) & (ind.rs >= STRONG_RS) & (ind.a52 >= STRONG_FROM_HIGH)
    prints = con.execute(
        """SELECT trade_date, symbol, upper(trim(client_name)) AS client, upper(side) AS side,
                  any_value(COALESCE(deal_value_cr, quantity * price / 1e7)) AS v,
                  any_value(price) AS price, any_value(upper(coalesce(clientele, 'OTHER'))) AS clientele,
                  bool_or(COALESCE(is_prop, FALSE)) AS is_prop
           FROM deals
           WHERE upper(symbol) <> 'TOTAL' AND trade_date BETWEEN ? AND ? AND quantity > 0 AND price > 0
           GROUP BY trade_date, symbol, upper(trim(client_name)), upper(side), quantity, price""",
        [rec_start, as_of]).df()
    if not prints.empty:
        prints["trade_date"] = pd.to_datetime(prints["trade_date"])
        prints["is_prop"] = prints["is_prop"].fillna(False).astype(bool) | (prints["clientele"] == "PROP")
        prints["house"] = [house_key(c) for c in prints["client"]]
    return {"dsn": dsn, "deal_days": deal_days, "ind": ind, "prints": prints}


# ----------------------------------------------------------------------------------------------- houses
def forward_excess(ind: pd.DataFrame) -> pd.DataFrame:
    """T+20 return from the next open, minus the equal-weight >= 1,000 Cr average (NaN when unfinished)."""
    x = ind[["symbol", "d", "o", "c", "mcap"]].copy()
    g = x.groupby("symbol", sort=False)
    x["o1"] = g["o"].shift(-1)
    x["c20"] = g["c"].shift(-FWD_SESSIONS)
    x["r20"] = (x["c20"] / x["o1"] - 1) * 100
    x.loc[x["r20"].abs() > RET_CAP_PCT, "r20"] = np.nan
    bench = x[x["mcap"] >= FLOOR_CR].groupby("d")["r20"].mean().rename("b20")
    x = x.merge(bench, left_on="d", right_index=True, how="left")
    x["x20"] = x["r20"] - x["b20"]
    return x[["symbol", "d", "x20"]]


def house_record(prints: pd.DataFrame, ind: pd.DataFrame) -> pd.DataFrame:
    """One row per house: finished bets n, avg excess, beat %, class, grade (known at as_of)."""
    cols = ["house", "n", "avg", "beat", "cls", "grade"]
    if prints is None or prints.empty:
        return pd.DataFrame(columns=cols)
    b = prints[(~prints.is_prop) & (prints.side == "BUY")]
    bets = b.groupby(["house", "symbol", "trade_date"]).agg(
        v=("v", "sum"), cls=("clientele", lambda s: s.mode().iat[0])).reset_index()
    bets = bets[bets.v >= BET_MIN_CR]
    if bets.empty:
        return pd.DataFrame(columns=cols)
    fx = forward_excess(ind)
    bets = bets.merge(fx, left_on=["symbol", "trade_date"], right_on=["symbol", "d"], how="left")
    fin = bets[bets.x20.notna()]
    if fin.empty:
        return pd.DataFrame(columns=cols)
    h = fin.groupby("house").agg(n=("x20", "size"), avg=("x20", "mean"), beat=("x20", lambda s: (s > 0).mean() * 100),
                                 cls=("cls", lambda s: s.mode().iat[0])).reset_index()
    h["grade"] = [grade(r.cls, r.n, r.avg, r.beat) for r in h.itertuples()]
    return h[cols]


def grade(cls: str, n: int, avg: float, beat: float) -> str:
    if cls not in ("FII", "DII") or n < GRADE_MIN_BETS:
        return "ungraded"
    if avg > 0 and beat >= 50:
        return "good"
    return "poor" if avg < 0 else "mixed"


# ----------------------------------------------------------------------------------------------- verdicts
def verdict(event: str, strong: bool, r21: float | None, rvol: float | None, buyers: list[dict[str, Any]]) -> tuple[str, str, str]:
    """(class, title, what usually follows) from the evidence study. Ported from the mockup."""
    poor = any(b.get("grade") == "poor" for b in buyers)
    quiet = rvol is not None and rvol < QUIET_RVOL   # unknown RVOL is not called quiet
    if event == "transfer_interse":
        return "ignore", "Transfer between holders", "The same shares changed hands. No new money came in."
    if event == "churn":
        return ("avoid" if quiet else "churn", "Churn" + (" on a quiet day" if quiet else ""),
                "The same desks bought and sold. Churn usually lagged the market by 2.0%."
                + (" On quiet days it lagged by 3.7%." if quiet else ""))
    if event == "placement":
        return ("place", "Placement" + (" on a strong chart" if strong else ""),
                "Institutions took a block from a promoter or a company. "
                + ("This is the best deal type we tested: +2.6% over 20 sessions, and 76% beat the market."
                   if strong else "Placements usually beat the market by 1.9% over 20 sessions."))
    if event == "distribute":
        return ("supply", "Supply at the seller's price",
                "Wait for the price to close above the sellers' price. Absorbed supply beat the market by 1.8%.")
    if r21 is not None and r21 > EXTENDED_R21:
        return "avoid", "Extended: skip", "Buys after a +30% month usually lagged the market by 1.7%."
    if r21 is not None and r21 < FALLING_R21:
        return "avoid", "Falling knife", "Buys into a falling stock usually lagged the market by 2.1%."
    if poor:
        return "avoid", "Poor-record buyer", "This buyer's earlier deals lagged the market."
    if strong:
        return ("watch", "Confirms setup: check day 3",
                "Strong chart and a net buy. Held the deal price for 3 sessions: +5.2% over 20 sessions.")
    return "none", "No edge: weak chart", "Deal buys on a weak chart usually lagged the market by 1.5%."


def next_action(cls: str, level: float | None, strong: bool) -> str:
    lv = "–" if level is None else f"₹{level:,.2f}"
    return {
        "confirm": f"Plan the trade. Put the stop just under {lv}.",
        "watch": f"Watch it. It confirms if it closes above {lv} for 3 sessions.",
        "place": ("Buyable: the chart is strong. " if strong else "Wait for the chart to get strong. ")
                 + f"The deal price {lv} is the line.",
        "absorbed": f"Sellers are done at {lv}. Treat it as support.",
        "supply": f"Wait. It needs a close above {lv} to count as absorbed.",
        "avoid": "Skip it.",
        "churn": "Ignore the deal. Read the chart alone.",
        "ignore": "Ignore the deal.",
        "none": "This deal gives no edge.",
    }[cls]


def _who(pr: pd.DataFrame, grades: dict[str, dict[str, Any]], k: int | None = 3) -> list[dict[str, Any]]:
    if pr is None or pr.empty:
        return []
    g = pr[~pr.is_prop].groupby(["house", "client", "clientele"], as_index=False)["v"].sum().sort_values("v", ascending=False)
    out = []
    for r in (g if k is None else g.head(k)).itertuples():
        rec = grades.get(r.house, {})
        out.append({"name": str(r.client).title()[:40], "house": r.house, "buyer_class": r.clientele,
                    "value_cr": round(float(r.v), 1), "grade": rec.get("grade", "ungraded"),
                    "record_n": int(rec["n"]) if rec.get("n") is not None and not pd.isna(rec.get("n")) else 0})
    return out


def deal_row(r: Any, hist: pd.DataFrame, pr_day: pd.DataFrame, grades: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """One stock-session with its verdict, deal-price status and chips (None below the floor)."""
    d = pd.Timestamp(r.trade_date)
    x = hist[hist.d == d]
    if x.empty:
        return None
    x = x.iloc[0]
    if not (x.mcap or 0) >= FLOOR_CR:
        return None
    buy = _who(pr_day[pr_day.side == "BUY"] if not pr_day.empty else pr_day, grades, None)
    sell = _who(pr_day[pr_day.side == "SELL"] if not pr_day.empty else pr_day, grades, 3)
    e = str(r.event_type)
    strong = bool(x.strong)
    r21 = None if pd.isna(x.r21) else float(x.r21)
    rvol = None if pd.isna(x.rvol) else float(x.rvol)
    cls, title, why = verdict(e, strong, r21, rvol, buy)
    lvl = r.sell_vwap if e == "distribute" else r.buy_vwap
    if lvl is None or pd.isna(lvl):
        lvl = r.vwap
    lvl = None if lvl is None or pd.isna(lvl) else float(lvl)
    after = hist[hist.d > d]
    n_after = int(len(after))
    cnow = float(hist.c.iloc[-1])
    status, chg = None, None
    if lvl and e not in NOISE_EVENTS:
        chg = (cnow / lvl - 1) * 100
        if n_after == 0:
            status = "day 0"
        elif e == "distribute":
            status = "reclaimed" if cnow > lvl else "below seller"
        else:
            below = bool((after.c < lvl).any())
            status = "lost" if cnow < lvl else ("reclaimed" if below else "holding")
        if e != "distribute" and cls == "watch" and n_after >= CONFIRM_DAY:
            if status == "holding":
                cls, title, why = ("confirm", "Confirmed: held the deal price 3 sessions",
                                   "Strong chart, net buy, held 3 sessions: +5.2% over 20 sessions, 60% beat the market (n = 40).")
            elif status == "lost":
                cls, title, why = "avoid", "Failed: lost the deal price", "Net buys that lost the deal price usually lagged the market by 1.1%."
            else:
                title, why = "Back above the deal price: watch", "It dipped below the deal price and is back above. It must hold before it counts."
        if e == "distribute" and n_after >= CONFIRM_DAY and status == "reclaimed":
            cls, title, why = "absorbed", "Absorbed: seller's price reclaimed", "Absorbed supply beat the market by 1.8% over 20 sessions."
    chips = []
    if e == "placement" and strong:
        chips.append("Placement + strong chart")
    if status == "holding" and n_after >= CONFIRM_DAY:
        chips.append("Holding deal price")
    if cls == "absorbed":
        chips.append("Absorbed")
    if (r21 or 0) > EXTENDED_R21:
        chips.append("Extended")
    if e == "churn":
        chips.append("Churn warning")
    if any(b["grade"] == "poor" for b in buy):
        chips.append("Poor-record buyer")
    if any(b["grade"] == "good" for b in buy):
        chips.append("Good-record FII/DII")
    net = float(r.net_value_cr_ex_prop) if not pd.isna(r.net_value_cr_ex_prop) else 0.0
    return {
        "symbol": r.symbol, "name": (x.nm or r.symbol), "deal_date": _iso(d), "sessions_since": n_after,
        "event_type": e, "side": SIDE.get(e), "event_label": EVENT_LABEL.get(e, e),
        "verdict": cls, "verdict_title": title, "why": why, "next_action": next_action(cls, lvl, strong),
        "net_cr": round(net, 1), "bought_cr": round(sum(b["value_cr"] for b in buy), 1),
        "gross_cr": _f(r.gross_ex_prop_cr), "prop_cr": _f(r.prop_value_cr),
        "deal_price": _f(lvl, 2), "close": round(cnow, 2), "vs_deal_pct": _f(chg),
        "status": status, "strong_chart": strong, "rs": _f(x.rs, 0), "from_high_pct": _f(x.a52),
        "month_pct": _f(r21), "rvol": _f(rvol, 2), "mcap_cr": _f(x.mcap, 0),
        "industry": x.industry, "sector": x.sector,
        "buyers": buy[:3], "sellers": sell, "chips": chips,
    }


# ----------------------------------------------------------------------------------------------- build
def build(con: Any, as_of: date) -> dict[str, Any]:
    """Everything the Deals tab and the Telegram digest show, as of `as_of`."""
    inp = load_inputs(con, as_of)
    if "missing" in inp:
        return {"as_of": _iso(as_of), "missing": inp["missing"]}
    dsn, deal_days, ind, prints = inp["dsn"], inp["deal_days"], inp["ind"], inp["prints"]
    as_of_ts = pd.Timestamp(as_of)
    last10, last20 = deal_days[-WATCH_SESSIONS:], deal_days[-HISTORY_SESSIONS:]
    H = house_record(prints, ind)
    grades = H.set_index("house")[["grade", "n", "avg", "beat", "cls"]].to_dict("index") if not H.empty else {}

    by_sym = {s: g for s, g in ind.groupby("symbol", sort=False)}
    win_pr = prints[prints.trade_date >= last10[0]] if not prints.empty else prints
    pr_groups = {k: g for k, g in win_pr.groupby(["symbol", "trade_date"])} if not win_pr.empty else {}
    W = dsn[dsn.trade_date.isin(last10)].sort_values(["trade_date", "gross_ex_prop_cr"], ascending=[False, False])
    empty_pr = win_pr.iloc[0:0] if not win_pr.empty else pd.DataFrame(columns=["side", "is_prop", "house", "client", "clientele", "v"])
    rows: list[dict[str, Any]] = []
    for r in W.itertuples():
        hist = by_sym.get(r.symbol)
        if hist is None:
            continue
        row = deal_row(r, hist, pr_groups.get((r.symbol, pd.Timestamp(r.trade_date)), empty_pr), grades)
        if row:
            rows.append(row)

    # Deal watch: one card per stock, the latest event wins, earlier ones become its history.
    seen: dict[str, dict[str, Any]] = {}
    watch: list[dict[str, Any]] = []
    for x in rows:
        if x["symbol"] in seen:
            seen[x["symbol"]]["earlier"].append({"deal_date": x["deal_date"], "event_type": x["event_type"],
                                                 "side": x["side"], "net_cr": x["net_cr"], "deal_price": x["deal_price"]})
            continue
        x["earlier"] = []
        seen[x["symbol"]] = x
        watch.append(x)

    session = deal_days[-1]
    today = [x for x in rows if x["deal_date"] == _iso(session)]
    n_session = int((dsn.trade_date == session).sum())
    skipped = {"transfer": sum(x["event_type"] == "transfer_interse" for x in today),
               "churn": sum(x["event_type"] == "churn" for x in today),
               "small": max(0, n_session - len(today))}
    now = ind[(ind.d == as_of_ts) & (ind.mcap >= FLOOR_CR)]
    above50 = _f((now.c > now.e50).mean() * 100, 0) if len(now) else None

    # By group (10 deal sessions, transfers and churn out).
    gg: dict[str, dict[str, Any]] = {}
    for x in rows:
        if x["event_type"] in NOISE_EVENTS:
            continue
        key = x["industry"] or "Other"
        g = gg.setdefault(key, {"industry": key, "sector": x["sector"], "_b": set(), "_s": set(), "flow_cr": 0.0, "symbols": set()})
        (g["_s"] if x["event_type"] == "distribute" else g["_b"]).add(x["symbol"])
        g["flow_cr"] += x["net_cr"]
        g["symbols"].add(x["symbol"])
    groups = []
    for g in gg.values():
        groups.append({"industry": g["industry"], "sector": g["sector"], "buying_names": len(g["_b"]),
                       "selling_names": len(g["_s"]), "flow_cr": round(g["flow_cr"], 1), "symbols": sorted(g["symbols"]),
                       "three_plus_buyers": len(g["_b"]) >= 3})
    groups.sort(key=lambda g: (-g["buying_names"], -g["flow_cr"]))

    houses, fund_groups = _houses(win_pr, ind, H)
    history = _history_events(dsn, last20, now)
    gap = _session_gap(ind, last20[0], as_of_ts)
    return {
        "as_of": _iso(as_of), "deal_session": _iso(session), "sessions10": [_iso(d) for d in last10],
        "sessions20": [_iso(d) for d in last20], "rows": rows, "today": today, "watch": watch,
        "groups": groups, "houses": houses, "fund_groups": fund_groups, "history_events": history,
        "skipped": skipped, "above50_pct": above50, "graded_houses": int((H.grade != "ungraded").sum()) if not H.empty else 0,
        "finished_bets": int(H.n.sum()) if not H.empty else 0, "first_deal": _iso(deal_days[0]), "price_gap": gap,
    }


def _session_gap(ind: pd.DataFrame, start: Any, end: Any) -> dict[str, str] | None:
    """Largest calendar gap between consecutive price sessions in the window (> 7 days = missing data)."""
    days = sorted(pd.Timestamp(d) for d in ind.loc[(ind.d >= start) & (ind.d <= end), "d"].unique())
    best = None
    for a, b in zip(days, days[1:]):
        if (b - a).days > 7 and (best is None or (b - a) > (best[1] - best[0])):
            best = (a, b)
    return None if best is None else {"from": _iso(best[0]), "to": _iso(best[1])}


def _houses(win_pr: pd.DataFrame, ind: pd.DataFrame, H: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if win_pr is None or win_pr.empty:
        return [], []
    imap = ind.drop_duplicates("symbol", keep="last").set_index("symbol")["industry"].to_dict()
    pb = win_pr[(~win_pr.is_prop) & (win_pr.side == "BUY")].copy()
    if pb.empty:
        return [], []
    pb["industry"] = pb.symbol.map(imap).fillna("Other")
    rec = H.set_index("house").to_dict("index") if not H.empty else {}
    houses = []
    for h, g in pb.groupby("house"):
        by_ind = g.groupby("industry").agg(v=("v", "sum"), syms=("symbol", lambda s: sorted(set(s)))).sort_values("v", ascending=False)
        tot = float(by_ind.v.sum()) or 1.0
        r = rec.get(h, {})
        n = r.get("n")
        houses.append({
            "house": h, "name": str(g.client.value_counts().index[0]).title()[:40],
            "buyer_class": g.clientele.mode().iat[0], "bought_cr": round(float(g.v.sum()), 1),
            "symbols": sorted(set(g.symbol)), "grade": r.get("grade", "ungraded"),
            "record_n": 0 if n is None or pd.isna(n) else int(n),
            "record_avg_pct": _f(r.get("avg")), "record_beat_pct": _f(r.get("beat"), 0),
            "spread": [{"industry": i, "value_cr": round(float(x.v), 1), "share_pct": round(float(x.v) / tot * 100),
                        "symbols": x.syms} for i, x in by_ind.iterrows()],
        })
    houses.sort(key=lambda x: -x["bought_cr"])
    inst = pb[pb.clientele.isin(["FII", "DII"])]
    fund_groups = []
    for i, g in inst.groupby("industry"):
        fund_groups.append({"industry": i, "houses": int(g.house.nunique()),
                            "fii_cr": round(float(g.loc[g.clientele == "FII", "v"].sum()), 1),
                            "dii_cr": round(float(g.loc[g.clientele == "DII", "v"].sum()), 1),
                            "symbols": sorted(set(g.symbol))})
    fund_groups.sort(key=lambda r: -(r["houses"] * 1000 + r["fii_cr"] + r["dii_cr"]))
    return houses, fund_groups


def _history_events(dsn: pd.DataFrame, last20: list[pd.Timestamp], now: pd.DataFrame) -> list[dict[str, Any]]:
    """Per stock >= floor (trading on as_of): its events over the last 20 deal sessions, with the session index."""
    pos = {pd.Timestamp(d): i for i, d in enumerate(last20)}
    nowi = now.set_index("symbol")
    h = dsn[dsn.trade_date.isin(last20) & dsn.symbol.isin(nowi.index)]
    out = []
    for sym, g in h.groupby("symbol"):
        ev = []
        for r in g.sort_values("trade_date").itertuples():
            ev.append({"i": pos[pd.Timestamp(r.trade_date)], "event_type": r.event_type,
                       "net_cr": round(float(r.net_value_cr_ex_prop or 0), 1) if not pd.isna(r.net_value_cr_ex_prop) else 0.0,
                       "prop_cr": round(float(r.prop_value_cr or 0), 1) if not pd.isna(r.prop_value_cr) else 0.0,
                       "buy_vwap": _f(r.buy_vwap, 2), "sell_vwap": _f(r.sell_vwap, 2)})
        x = nowi.loc[sym]
        out.append({"symbol": sym, "industry": x.industry, "close": round(float(x.c), 2), "events": ev})
    return out


def history_rows(core: dict[str, Any], n: int) -> list[dict[str, Any]]:
    """History view for the last n deal sessions (5 / 10 / 20): pattern, counts, net, prop, avg deal price."""
    total = len(core.get("sessions20") or [])
    lo = max(0, total - n)
    out = []
    for h in core.get("history_events") or []:
        ev = [e for e in h["events"] if e["i"] >= lo]
        if not ev:
            continue
        b = [e for e in ev if e["event_type"] in BUY_EVENTS]
        s = [e for e in ev if e["event_type"] == "distribute"]
        c = [e for e in ev if e["event_type"] == "churn"]
        if len(b) >= 2 and not s:
            pat = "repeat_buy"
        elif len(b) == 1 and not s:
            pat = "single_buy"
        elif s and not b:
            pat = "selling_only"
        elif b and s:
            pat = "mixed"
        elif c:
            pat = "churn_only"
        else:
            pat = "transfers_only"

        def avg(arr: list[dict[str, Any]], k: str) -> float | None:
            v = [e[k] for e in arr if e[k]]
            return sum(v) / len(v) if v else None
        lvl = avg(s, "sell_vwap") if pat == "selling_only" else avg(b, "buy_vwap")
        cells = [None] * (total - lo)
        for e in ev:
            cells[e["i"] - lo] = SIDE.get(e["event_type"])
        out.append({
            "symbol": h["symbol"], "industry": h["industry"], "pattern": pat, "pattern_label": PATTERNS[pat][0],
            "buy_sessions": len(b), "sell_sessions": len(s), "churn_sessions": len(c),
            "net_cr": round(sum(e["net_cr"] for e in ev), 1), "prop_cr": round(sum(e["prop_cr"] for e in ev), 1),
            "avg_deal_price": _f(lvl, 2), "close": h["close"],
            "vs_deal_pct": _f((h["close"] / lvl - 1) * 100) if lvl else None, "cells": cells,
        })
    out.sort(key=lambda x: (PATTERN_ORDER.index(x["pattern"]), -(x["buy_sessions"] + x["sell_sessions"]), -abs(x["net_cr"])))
    return out


def sort_by_verdict(rows: list[dict[str, Any]], key: str = "net") -> list[dict[str, Any]]:
    if key == "age":
        return sorted(rows, key=lambda x: (VERDICT_ORDER.index(x["verdict"]), x["sessions_since"]))
    return sorted(rows, key=lambda x: (VERDICT_ORDER.index(x["verdict"]), -abs(x["net_cr"])))
