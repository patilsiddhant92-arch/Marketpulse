"""Sector Intel mockup extractor (hark design round 2/3).

Usage (repo root):  python hark/tools/sector_mockup/extract.py [AS_OF]
Writes hark/mockups/tab-sector-intel.html from template.html + Database/marketpulse.duckdb.

Readings per group (stocks >= 1000 Cr, current taxonomy; groups >= 3 members):
  near   = % of members with close within 10% of their 52W high
  nh_N   = distinct members making a new 52W high (high > prior 52W high) within the last N sessions
  ad_N   = mean over N sessions of (advancers - decliners) / members, %
  upd_N  = delivered value on up days / all delivered value over N sessions, %
  tox_N  = group turnover N-session avg / 63-session avg
  shd_N  = turnover share N-session avg minus 63-session avg, points
  rx_N   = group equal-weight return over N sessions minus the median group's, points
  score  = mean of within-level percentile ranks of near, nh_N, ad_N, upd_N (0-100)
  pct_*  = today's value vs the group's own history (all sessions available)
State (Tab 2 definition): Favour = >= 60% above 50 EMA, 21D return beats the median group and EW index above its
50 EMA; Caution = turnover share 5D < 85% of 20D while 21D return < 0, or < 40% above 50 EMA and 63D lagging; else Neutral.
Mood (Pulse definition): mean expanding percentile of % > 10/50/200 EMA, up-turnover %, net new highs, TT pass %.
Reliability: realised rank-IC of the score vs forward 21-session return, averaged over the 63 sessions that ended
21 sessions ago (only data known at as_of).
"""
from __future__ import annotations

import json
import os
import sys
import warnings

import duckdb
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "../../.."))
AS_OF = pd.Timestamp(sys.argv[1] if len(sys.argv) > 1 else "2026-08-13")
LEVELS = {"sector": "Sector", "broad_industry": "Broad Industry", "industry": "Industry"}
WINDOWS = {"1D": 1, "1W": 5, "2W": 10, "1M": 21}
CHART_N = 160

con = duckdb.connect(os.path.join(ROOT, "Database/marketpulse.duckdb"), read_only=True)
p = con.execute("""
  SELECT i.symbol, i.trade_date d, i.open_price o, i.high_price hi, i.low_price lo, i.close_price c, i.prev_close pc,
         i.turnover_cr t, i.delivery_qty*i.close_price/1e7 dv, i.high_52w h52, i.ema_50 e50, i.rs_percentile rs,
         m.security_name nm, m.market_cap_cr mcap, m.sector, m.broad_industry, m.industry
  FROM indicators_daily i JOIN stocks_master m USING(symbol)
  WHERE m.market_cap_cr >= 1000 AND i.trade_date <= ? ORDER BY symbol, d""", [AS_OF.date()]).df()
p["d"] = pd.to_datetime(p.d)
g = p.groupby("symbol")
prev = g.c.shift(1).fillna(p.pc)
r = p.c / prev - 1
bad = (r <= -0.35) | (r >= 1.0)
p["r"] = r.where(~bad)
for k in ("o", "hi", "lo"):
    p["r" + k] = (p[k] / prev - 1).where(~bad)
p["adv"] = np.sign(p.r)
p["near"] = (p.c >= 0.9 * p.h52).astype(float).where(p.h52.notna())
ph = g.h52.shift(1)
p["nh"] = (p.hi > ph).astype(float).where(ph.notna())
p["upd"] = p.dv * (p.r > 0)
p["a50"] = (p.c > p.e50).astype(float).where(p.e50.notna())
for _wk, _N in {"1D": 1, "1W": 5, "2W": 10, "1M": 21}.items():  # distinct members with a new 52W high in the window
    p["nhw_" + _wk] = g.nh.transform(lambda s, n=_N: s.rolling(n, min_periods=1).max())
dates = sorted(p.d.unique())
if AS_OF not in set(dates):
    AS_OF = dates[-1]
di = {d: i for i, d in enumerate(dates)}

# ---------------- market EW index + mood ----------------
mk = p.groupby("d").agg(r=("r", "mean"))
mk["idx"] = np.exp(np.log1p(mk.r.fillna(0)).cumsum())
mall = con.execute("""SELECT trade_date d, avg((close_price>ema_10)::int) a10, avg((close_price>ema_50)::int) a50,
  avg((close_price>ema_200)::int) a200,
  sum(CASE WHEN close_price>prev_close THEN turnover_cr ELSE 0 END)/nullif(sum(turnover_cr),0) upv,
  (sum((close_price>=high_52w*0.999)::int)-sum((close_price<=low_52w*1.001)::int))*1.0/count(*) nnh,
  avg(trend_template_pass::int) s2 FROM indicators_daily WHERE trade_date<=? GROUP BY 1 ORDER BY 1""", [AS_OF.date()]).df()
mall["d"] = pd.to_datetime(mall.d)
MC = ["a10", "a50", "a200", "upv", "nnh", "s2"]
for k in MC:
    mall[k + "_p"] = mall[k].expanding(60).apply(lambda s: (s <= s.iloc[-1]).mean() * 100, raw=False)
mall["mood"] = mall[[k + "_p" for k in MC]].mean(axis=1)
mall["a10chg"] = (mall.a10 - mall.a10.shift(10)) * 100
mrow = mall.iloc[-1]
mood = float(mrow.mood)
label = "Strong" if mood >= 70 else "Healthy" if mood >= 55 else "Mixed" if mood >= 45 else "Weak" if mood >= 30 else "Very weak"
direction = "cooling fast" if mrow.a10chg < -10 else "improving fast" if mrow.a10chg > 10 else "steady"

# ---------------- group frames ----------------
OUT: dict = {"as_of": str(AS_OF.date()), "levels": {}, "charts": {}, "members": {}, "windows": list(WINDOWS)}
rel_out = {}
leaders_now = p[p.d == AS_OF]


def roll(G, col, w, how="mean"):
    return G[col].transform(lambda s: getattr(s.rolling(w, min_periods=max(1, w // 2)), how)())


for lv, lvname in LEVELS.items():
    a = p.groupby([lv, "d"]).agg(n=("symbol", "size"), r=("r", "mean"), ro=("ro", "mean"), rhi=("rhi", "mean"),
                                 rlo=("rlo", "mean"), adv=("adv", "mean"), near=("near", "mean"), nh=("nh", "sum"),
                                 t=("t", "sum"), dv=("dv", "sum"), upd=("upd", "sum"), a50=("a50", "mean"),
                                 **{"nhw_" + k: ("nhw_" + k, "sum") for k in WINDOWS}).reset_index()
    a = a.rename(columns={lv: "gname"}).sort_values(["gname", "d"]).reset_index(drop=True)
    G = a.groupby("gname")
    a["idx"] = np.exp(np.log1p(a.r.fillna(0)).groupby(a.gname).cumsum()) * 100
    a["pidx"] = G.idx.shift(1)
    a["e50"] = G.idx.transform(lambda s: s.ewm(span=50, adjust=False).mean())
    a["sh"] = a.t / a.groupby("d").t.transform("sum") * 100
    a["t63"], a["dv63"], a["sh63"] = roll(G, "t", 63), roll(G, "dv", 63), roll(G, "sh", 63)
    a["sh5"], a["sh20"] = roll(G, "sh", 5), roll(G, "sh", 20)
    elig = a.n >= 3
    for wk, N in WINDOWS.items():
        a[f"nh_{wk}"] = a["nhw_" + wk]
        a[f"ad_{wk}"] = roll(G, "adv", N) * 100
        a[f"upd_{wk}"] = roll(G, "upd", N, "sum") / roll(G, "dv", N, "sum") * 100
        a[f"tox_{wk}"] = roll(G, "t", N) / a.t63
        a[f"shd_{wk}"] = roll(G, "sh", N) - a.sh63
        ret = (a.idx / G.idx.shift(N) - 1) * 100
        a[f"ret_{wk}"] = ret
        a[f"rx_{wk}"] = ret - ret.where(elig).groupby(a.d).transform("median")
        a[f"nearchg_{wk}"] = (a.near - G.near.shift(N)) * 100
        parts = [a["near"], a[f"nh_{wk}"] / a.n, a[f"ad_{wk}"], a[f"upd_{wk}"]]
        a[f"score_{wk}"] = sum(x.where(elig).groupby(a.d).rank(pct=True) for x in parts) / 4 * 100
    a["near"] *= 100
    a["a50"] *= 100
    for col in ["near", "ad_2W", "upd_2W", "score_2W"]:
        a["pct_" + col] = G[col].transform(lambda s: s.expanding(40).apply(lambda z: (z <= z.iloc[-1]).mean() * 100, raw=False))
    a["ret_63"] = (a.idx / G.idx.shift(63) - 1) * 100
    med21 = a.ret_1M.where(elig).groupby(a.d).transform("median")
    med63 = a.ret_63.where(elig).groupby(a.d).transform("median")
    fav = (a.a50 >= 60) & (a.ret_1M > med21) & (a.idx > a.e50)
    cau = ((a.sh5 < 0.85 * a.sh20) & (a.ret_1M < 0)) | ((a.a50 < 40) & (a.ret_63 < med63))
    a["state"] = np.where(fav, "Favour", np.where(cau, "Caution", "Neutral"))

    def why(z):
        if z.state == "Favour":
            return f"{z.a50:.0f}% of members above the 50 EMA; 1M return beats the median group by {z.rx_1M:+.1f} pts; index above its 50 EMA"
        if z.state == "Caution":
            if z.a50 < 40:
                return f"Only {z.a50:.0f}% of members above the 50 EMA and 3M return below the median group"
            return f"Turnover share fell to {z.sh5 / z.sh20 * 100:.0f}% of its 20D average while the group fell {z.ret_1M:.1f}% in 1M"
        return f"{z.a50:.0f}% above the 50 EMA; 1M vs median group {z.rx_1M:+.1f} pts"

    # reliability (Broad Industry and others): realised IC known at as_of
    a["fwd"] = (G.idx.shift(-21) / a.idx - 1) * 100
    e = a[elig & a.fwd.notna()]
    e = e.assign(x=e.fwd - e.groupby("d").fwd.transform("median"))
    ic = e.groupby("d").apply(lambda z: z.score_2W.rank().corr(z.x.rank()) if len(z) > 8 else np.nan).dropna()
    last = ic[ic.index >= dates[max(0, di[AS_OF] - 21 - 62)]]
    tq = e[e.d.isin(last.index)]
    q = tq.groupby("d").score_2W.transform(lambda z: pd.qcut(z.rank(method="first"), 5, labels=False))
    rel_out[lv] = {"ic": round(float(last.mean()), 3), "top": round(float((tq.x[q == 4] > 0).mean() * 100)),
                   "bot": round(float((tq.x[q == 0] > 0).mean() * 100)), "days": int(len(last)),
                   "from": str(last.index.min().date()), "to": str(last.index.max().date())}

    now = a[(a.d == AS_OF)].copy()
    lead = leaders_now.sort_values("rs", ascending=False).groupby(lv).symbol.apply(lambda s: list(s[:3]))
    rows = []
    for _, z in now.iterrows():
        gid = f"{lv}:{z.gname}"
        row = {"id": gid, "g": z.gname, "n": int(z.n), "state": z.state, "why": why(z), "a50": round(z.a50, 1),
               "near": round(z.near, 1), "lead": lead.get(z.gname, []),
               "pct": {k: (None if pd.isna(z["pct_" + k]) else round(z["pct_" + k])) for k in ["near", "ad_2W", "upd_2W", "score_2W"]}}
        for wk in WINDOWS:
            for k in ["nh", "ad", "upd", "tox", "shd", "rx", "ret", "nearchg", "score"]:
                v = z[f"{k}_{wk}"]
                row[f"{k}_{wk}"] = None if pd.isna(v) or not np.isfinite(v) else round(float(v), 2 if k in ("tox", "shd") else 1)
        rows.append(row)
        # chart: last CHART_N sessions, EW OHLC
        h = a[a.gname == z.gname].tail(CHART_N)
        o = (h.pidx * (1 + h.ro)).round(2)
        hi_ = (h.pidx * (1 + h.rhi)).round(2)
        lo_ = (h.pidx * (1 + h.rlo)).round(2)
        cl = h.idx.round(2)
        hi_ = np.maximum.reduce([hi_.fillna(cl), o.fillna(cl), cl])
        lo_ = np.minimum.reduce([lo_.fillna(cl), o.fillna(cl), cl])
        full = a[a.gname == z.gname]
        ema = lambda s: full.idx.ewm(span=s, adjust=False).mean().tail(CHART_N).round(2).tolist()
        rsl = (full.idx / full.d.map(mk.idx)).tail(CHART_N)
        rsl = (rsl / rsl.iloc[0] * 100).round(2)
        OUT["charts"][gid] = {"d": [str(x.date()) for x in h.d], "o": o.fillna(cl).tolist(), "h": list(map(float, hi_)),
                              "l": list(map(float, lo_)), "c": cl.tolist(), "e10": ema(10), "e20": ema(20), "e50": ema(50),
                              "rs": rsl.tolist(), "near": h.near.round(1).tolist()}
        if lv == "industry" or lv == "broad_industry" or lv == "sector":
            m = leaders_now[leaders_now[lv] == z.gname]
            OUT["members"].setdefault(gid, [
                {"s": x.symbol, "nm": (x.nm or "")[:28], "mcap": round(x.mcap), "c": round(x.c, 2),
                 "chg": None if pd.isna(x.r) else round(x.r * 100, 1),
                 "fh": None if pd.isna(x.h52) or not x.h52 else round((x.c / x.h52 - 1) * 100, 1),
                 "rs": None if pd.isna(x.rs) else round(x.rs), "a50": bool(x.a50 == 1)}
                for x in m.sort_values("rs", ascending=False).itertuples()])
    rows.sort(key=lambda r: -(r["score_2W"] or -1))
    OUT["levels"][lv] = {"name": lvname, "rows": rows}

# member 1M returns
ret1m = p[p.d.isin([AS_OF, dates[di[AS_OF] - 21]])].pivot(index="symbol", columns="d", values="c")
if ret1m.shape[1] == 2:
    r1m = (ret1m.iloc[:, 1] / ret1m.iloc[:, 0] - 1) * 100
    for lst in OUT["members"].values():
        for x in lst:
            v = r1m.get(x["s"])
            x["r1m"] = None if v is None or pd.isna(v) else round(float(v), 1)

# ---------------- indices (index_daily only) ----------------
sys.path.insert(0, ROOT)
try:
    from App.thematic_engine import CANONICAL_44_INDICES as C44
except Exception:
    C44 = {}
ix = con.execute("SELECT index_name, trade_date d, close_price c FROM index_daily WHERE trade_date<=? ORDER BY 1,2", [AS_OF.date()]).df()
irows = []
for name, meta in C44.items():
    s = ix[ix.index_name.str.upper() == meta.get("clean_name", name).upper()]
    if s.empty:
        s = ix[ix.index_name == name]
    if s.empty:
        continue
    cc = s.c.reset_index(drop=True)
    rr = lambda n: None if len(cc) <= n else round((cc.iloc[-1] / cc.iloc[-1 - n] - 1) * 100, 1)
    e20 = cc.ewm(span=20, adjust=False).mean().iloc[-1]
    irows.append({"g": name, "cat": meta.get("category", ""), "c": round(float(cc.iloc[-1]), 1), "r1d": rr(1), "r1w": rr(5),
                  "r2w": rr(10), "r1m": rr(21), "a20": bool(cc.iloc[-1] > e20), "n": int(len(cc))})
OUT["indices"] = irows
OUT["mood"] = {"score": round(mood), "label": label, "dir": direction, "a10chg": round(float(mrow.a10chg), 1),
               "spark": mall.mood.tail(120).round(1).tolist()}
OUT["reliability"] = rel_out
# evidence table (local study, Oct 2024 - Jul 2026), Broad Industry score IC by breadth direction
OUT["evidence"] = {"dir": {"cooling fast": [0.061, 55, 46], "steady": [0.156, 59, 43], "improving fast": [0.170, 63, 41]},
                   "lag": {"working": 0.164, "not": 0.042}}

tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
html = tpl.replace("/*DATA*/null", json.dumps(OUT, separators=(",", ":"), allow_nan=True).replace("NaN", "null").replace("-Infinity", "null").replace("Infinity", "null"))
dst = os.path.join(ROOT, "hark/mockups/tab-sector-intel.html")
open(dst, "w", encoding="utf-8").write(html)
print("as_of", AS_OF.date(), {k: len(v["rows"]) for k, v in OUT["levels"].items()}, "indices", len(irows),
      "mood", OUT["mood"], "rel", rel_out, "bytes", len(html))
