"""Deals redesign mockup extractor (hark Deals round 2).

Usage (repo root):  python hark/tools/deals_mockup/extract.py [AS_OF]
Writes hark/mockups/tab-deals.html from template.html + Database/marketpulse.duckdb (+ the round-1 house record,
built from the 2.5-year NSE history by hark/tools/deals_study/study.py).

AS_OF defaults to 2026-08-13, the last session before the local price gap, so day-3 states can be shown.
Verdicts follow hark/08-tab-deals.md (evidence: T+20 excess vs the equal-weight >= 1000 Cr market):
  strong chart = close > 200 EMA, RS >= 70, within 15% of the 52W high.
  net buy: prior 21D > +30% -> Extended; < -10% -> Falling knife; strong -> Confirms setup (day 3 check);
           weak -> No edge.   placement -> Placement (+strong = best).  distribute -> Supply at seller price.
  churn -> Churn warning (quiet day RVOL < 3 = avoid).  transfer -> ignore.
Deal watch: last 10 deal sessions; level = buy VWAP (buys/placements) or sell VWAP (distribution);
  holding = never closed below the level since; lost = last close below; reclaimed = closed below, now above.
House grade (FII/DII only, >= 5 finished bets known at AS_OF): good if avg excess > 0 and beat% >= 50,
  poor if avg excess < 0, else mixed.
"""
from __future__ import annotations
import contextlib, io, json, os, runpy, sys, warnings
import duckdb, numpy as np, pandas as pd
warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, "../../.."))
AS_OF = pd.Timestamp(sys.argv[1] if len(sys.argv) > 1 else "2026-08-13")
con = duckdb.connect(os.path.join(ROOT, "Database/marketpulse.duckdb"), read_only=True)

ind = con.execute("""select i.symbol, i.trade_date d, i.open_price o, i.high_price h, i.low_price l, i.close_price c,
  i.ema_50 e50, i.ema_200 e200, i.rs_percentile rs, i.away_52w_high_pct a52, i.return_1m_pct r21, i.rvol,
  i.delivery_qty, i.avg_delivery_qty_20d, m.security_name nm, m.market_cap_cr mcap, m.sector, m.industry
  from indicators_daily i join stocks_master m using(symbol) where i.trade_date <= ? and i.trade_date >= ?""",
  [AS_OF.date(), (AS_OF - pd.Timedelta(days=200)).date()]).df()
ind["d"] = pd.to_datetime(ind.d); ind = ind.sort_values(["symbol", "d"])
sess = sorted(ind.d.unique()); si = {d: i for i, d in enumerate(sess)}
big = ind[ind.mcap >= 1000]
now = big[big.d == AS_OF].set_index("symbol")
ind["strong"] = (ind.c > ind.e200) & (ind.rs >= 70) & (ind.a52 >= -15)

dsn = con.execute("select * from deal_session_net where trade_date <= ?", [AS_OF.date()]).df()
dsn["trade_date"] = pd.to_datetime(dsn.trade_date)
deal_days = sorted(dsn.trade_date.unique())
last10 = deal_days[-10:]
prints = con.execute("""select trade_date, symbol, client_name, side, price, deal_value_cr v, clientele, clientele_sub, is_prop
  from deals where trade_date between ? and ?""", [pd.Timestamp(last10[0]).date(), AS_OF.date()]).df()
prints["trade_date"] = pd.to_datetime(prints.trade_date)

# ---- houses: out-of-sample record from the 2.5-year study (only bets finished by AS_OF)
with contextlib.redirect_stdout(io.StringIO()):
    S = runpy.run_path(os.path.join(ROOT, "hark/tools/deals_study/study.py"))
P = S["p"]; spos = {d: i for i, d in enumerate(sorted(S["ind"].trade_date.unique()))}
cut = spos.get(AS_OF, max(spos.values()))
fin = P[(P.si + 21 <= cut) & P.x20.notna()]
def house_key(s):
    return pd.Series(s).str.upper().str.replace(r"\b(PVT|PRIVATE|LTD|LIMITED|FPI|ODI|-)\b", "", regex=True).str.split().str[:3].str.join(" ")
H = fin.groupby("house").agg(n=("x20", "size"), avg=("x20", "mean"), beat=("x20", lambda s: (s > 0).mean() * 100),
                             cls=("clientele", lambda s: s.mode().iat[0]), last=("trade_date", "max")).reset_index()
def grade(r):
    if r.cls not in ("FII", "DII") or r.n < 5: return "ungraded"
    if r.avg > 0 and r.beat >= 50: return "good"
    return "poor" if r.avg < 0 else "mixed"
H["grade"] = H.apply(grade, axis=1)
GR = H.set_index("house")[["grade", "n", "avg", "beat", "cls"]].to_dict("index")

prints["house"] = house_key(prints.client_name).values
def who(sym, d, side, k=3):
    g = prints[(prints.symbol == sym) & (prints.trade_date == d) & (prints.side == side) & ~prints.is_prop]
    g = g.groupby(["house", "client_name", "clientele"], as_index=False).v.sum().sort_values("v", ascending=False)
    return [{"n": r.client_name.title()[:34], "h": r.house, "cls": r.clientele, "v": round(r.v, 1),
             "g": GR.get(r.house, {}).get("grade", "ungraded")} for r in g.head(k).itertuples()]

def verdict(e, x, rvol, bn):
    strong = bool(x.get("strong")); r21 = x.get("r21")
    inst = any(b["cls"] in ("FII", "DII") for b in bn); poor = any(b["g"] == "poor" for b in bn)
    if e == "transfer_interse": return ("ignore", "Transfer between holders", "Same shares changing hands; no new money.")
    if e == "churn":
        return ("avoid" if (rvol or 0) < 3 else "churn", "Churn" + (" on a quiet day" if (rvol or 0) < 3 else ""),
                "Same desks buying and selling. Usually lags the market (−2.0%" + (", −3.7% on quiet days)." if (rvol or 0) < 3 else ")."))
    if e == "placement":
        return ("place", "Placement" + (" on a strong chart" if strong else ""),
                "Institutions took a block from a promoter or corporate. " + ("Best deal type we tested: +2.6%, 76% beat the market." if strong else "Usually +1.9% over 20 sessions."))
    if e == "distribute":
        return ("supply", "Supply at the seller's price", "Wait for the price to reclaim the seller's level; absorbed supply averaged +1.8%.")
    if r21 is not None and r21 > 30: return ("avoid", "Extended: skip", "Buying after a +30% month usually lagged (−1.7%).")
    if r21 is not None and r21 < -10: return ("avoid", "Falling knife", "Buying into a falling stock usually lagged (−2.1%).")
    if poor: return ("avoid", "Poor-record buyer", "This buyer's earlier deals lagged the market.")
    if strong: return ("watch", "Confirms setup: check day 3", "Strong chart + net buy. If price holds the deal level for 3 sessions: +5.2% historically.")
    return ("none", "No edge: weak chart", "A deal buy on a weak chart usually lagged (−1.5%).")

def row_for(r):
    sym, d = r.symbol, r.trade_date
    hist = ind[ind.symbol == sym]
    x = hist[hist.d == d]
    if x.empty: return None
    x = x.iloc[0].to_dict()
    if (x.get("mcap") or 0) < 1000: return None
    bn, sl = who(sym, d, "BUY", 50), who(sym, d, "SELL")
    e = r.event_type
    cls, title, why = verdict(e, x, x.get("rvol"), bn)
    lvl = r.sell_vwap if e == "distribute" else r.buy_vwap
    if pd.isna(lvl): lvl = r.vwap
    after = hist[hist.d > d]
    n_after = len(after)
    cnow = hist.c.iloc[-1]
    status, chg = None, None
    if pd.notna(lvl) and e not in ("churn", "transfer_interse"):
        chg = (cnow / lvl - 1) * 100
        if n_after == 0: status = "day 0"
        elif e == "distribute":
            status = "reclaimed" if cnow > lvl else "below seller"
        else:
            below = (after.c < lvl).any()
            status = "lost" if cnow < lvl else ("reclaimed" if below else "holding")
        if e != "distribute" and cls == "watch" and n_after >= 3:
            if status == "holding": cls, title, why = "confirm", "Confirmed: held the deal price 3 sessions", "Strong chart + net buy + held 3 days: +5.2%, 60% beat the market (n=40)."
            elif status == "lost": cls, title, why = "avoid", "Failed: lost the deal price", "Net buys that lost the deal price usually lagged (−1.1%)."
            else: title, why = "Back above the deal price: watch", "Dipped below the deal price, now back above. Needs to hold before it counts."
        if e == "distribute" and n_after >= 3 and status == "reclaimed":
            cls, title, why = "absorbed", "Absorbed: seller's price reclaimed", "Absorbed supply averaged +1.8% over 20 sessions."
    chips = []
    if e == "placement" and x.get("strong"): chips.append("Placement + strong chart")
    if status == "holding" and n_after >= 3: chips.append("Holding deal price")
    if cls == "absorbed": chips.append("Absorbed")
    if (x.get("r21") or 0) > 30: chips.append("Extended")
    if e == "churn": chips.append("Churn warning")
    if any(b["g"] == "poor" for b in bn): chips.append("Poor-record buyer")
    if any(b["g"] == "good" for b in bn): chips.append("Good-record FII/DII")
    spark = hist[hist.d >= d - pd.Timedelta(days=45)]
    return {"sym": sym, "nm": (x.get("nm") or sym)[:30], "d": str(d.date()), "ago": n_after, "ev": e, "cls": cls, "title": title, "why": why,
            "net": round(float(r.net_value_cr_ex_prop or 0), 1), "bv": round(sum(b["v"] for b in bn), 1), "gross": round(float(r.gross_ex_prop_cr or 0), 1),
            "lvl": None if pd.isna(lvl) else round(float(lvl), 2), "c": round(float(cnow), 2), "chg": None if chg is None else round(chg, 1),
            "status": status, "strong": bool(x.get("strong")), "rs": None if pd.isna(x.get("rs")) else round(x["rs"]),
            "a52": None if pd.isna(x.get("a52")) else round(x["a52"], 1), "r21": None if pd.isna(x.get("r21")) else round(x["r21"], 1),
            "mcap": round(float(x["mcap"])), "ind": x.get("industry"), "sec": x.get("sector"), "buy": bn[:3], "sell": sl, "chips": chips,
            "px": [[str(t.d.date()), round(t.o, 2), round(t.h, 2), round(t.l, 2), round(t.c, 2)] for t in spark.itertuples()]}

W = dsn[dsn.trade_date.isin(last10)].sort_values(["trade_date", "gross_ex_prop_cr"], ascending=[False, False])
rows = [x for x in (row_for(r) for r in W.itertuples()) if x]
# one card per stock in Deal watch: latest event wins, earlier ones listed as history
seen, watch = {}, []
for x in rows:
    if x["sym"] in seen: seen[x["sym"]]["hist"].append({"d": x["d"], "ev": x["ev"], "net": x["net"], "lvl": x["lvl"]}); continue
    x["hist"] = []; seen[x["sym"]] = x; watch.append(x)
# every deal-day marker for the chart: all events for the stock within its spark window
marks = {}
for x in rows:
    marks.setdefault(x["sym"], []).append({"d": x["d"], "ev": x["ev"], "lvl": x["lvl"], "net": x["net"]})

# ---- groups: deals over the last 10 sessions by industry (ex transfers and churn)
gg = {}
for x in rows:
    if x["ev"] in ("churn", "transfer_interse"): continue
    g = gg.setdefault(x["ind"] or "Other", {"ind": x["ind"] or "Other", "sec": x["sec"], "b": 0, "s": 0, "flow": 0.0, "syms": []})
    g.setdefault("bs", set()); g.setdefault("ss", set())
    (g["ss"] if x["ev"] == "distribute" else g["bs"]).add(x["sym"])
    g["flow"] += x["net"]; g["syms"].append(x["sym"])
for g in gg.values(): g["b"], g["s"] = len(g.pop("bs")), len(g.pop("ss"))
groups = sorted(gg.values(), key=lambda g: (-g["b"], -g["flow"]))
for g in groups: g["flow"] = round(g["flow"], 1); g["syms"] = sorted(set(g["syms"]))

# ---- houses table: houses active in the window + their record
act = prints[(~prints.is_prop) & (prints.side == "BUY")].groupby("house").agg(v=("v", "sum"), syms=("symbol", lambda s: sorted(set(s))[:6]), cls=("clientele", lambda s: s.mode().iat[0])).reset_index()
act = act.merge(H[["house", "n", "avg", "beat", "grade"]], on="house", how="left").sort_values("v", ascending=False).head(40)
houses = [{"h": r.house.title(), "cls": r.cls, "v": round(r.v, 1), "syms": r.syms, "n": 0 if pd.isna(r.n) else int(r.n),
           "avg": None if pd.isna(r.avg) else round(r.avg, 1), "beat": None if pd.isna(r.beat) else round(r.beat),
           "grade": r.grade if isinstance(r.grade, str) else ("ungraded")} for r in act.itertuples()]
cls_ev = [{"c": "FII", "n": 947, "x": 1.2, "b": 53}, {"c": "DII", "n": 825, "x": 0.9, "b": 46},
          {"c": "Corporate", "n": 1373, "x": -2.6, "b": 38}, {"c": "Trading firms / HNI", "n": 2374, "x": -2.7, "b": 41}]

today = [x for x in rows if x["d"] == str(AS_OF.date())]
skipped = {"transfer": sum(x["ev"] == "transfer_interse" for x in today), "churn": sum(x["ev"] == "churn" for x in today),
           "small": int(((dsn.trade_date == AS_OF)).sum() - len(today))}
br = big[big.d == AS_OF]
mkt = {"above50": round(float((br.c > br.e50).mean() * 100)), "adv": round(float(0))}
data = {"asof": str(AS_OF.date()), "sessions": [str(pd.Timestamp(d).date()) for d in last10], "today": today, "watch": watch,
        "marks": marks, "groups": groups, "houses": houses, "clsev": cls_ev, "skipped": skipped, "mkt": mkt}
tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
out = os.path.join(ROOT, "hark/mockups/tab-deals.html")
open(out, "w", encoding="utf-8").write(tpl.replace("/*DATA*/null", json.dumps(data, default=str)))
print("wrote", out, "today", len(today), "watch", len(watch), "groups", len(groups), "houses", len(houses), skipped)
