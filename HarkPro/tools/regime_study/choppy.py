"""Choppy-market study (Research round 2 prep). Builds an equal-weight market of stocks >= 1000 Cr and three readings:
  price   : Choppiness Index (14) in the top 30% of its history, or Kaufman efficiency ratio (20) in the bottom 30%
  breadth : % of stocks above their 50 EMA crossed 50% >= 2 times in 20 sessions (whipsaw)
  outcome : breakout follow-through in the bottom 35% of its history; follow-through = share of 50-day-high breakouts on >= 1.5x volume still above the breakout close 5 sessions later
Choppy when 2 of 3 agree. Usage: python HarkPro/tools/regime_study/choppy.py"""
import os, duckdb, numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
c = duckdb.connect(os.path.join(ROOT, "Database/marketpulse.duckdb"), read_only=True)
d = c.execute("""select i.symbol, i.trade_date d, i.open_price o, i.high_price h, i.low_price l, i.close_price cl, i.ema_50 e50, i.rvol
  from indicators_daily i join stocks_master m using(symbol) where m.market_cap_cr >= 1000 order by 1,2""").df()
d["d"] = pd.to_datetime(d.d); d = d.sort_values(["symbol", "d"])
g = d.groupby("symbol")
d["pc"] = g.cl.shift(1)
d = d[d.pc > 0]
for k in ("h", "l", "cl"): d["r" + k] = (d[k] / d.pc - 1).clip(-0.25, 0.25)
d["hi50"] = g.cl.transform(lambda s: s.shift(1).rolling(50, min_periods=40).max())
d["c5"] = g.cl.shift(-5)
d["bo"] = (d.cl > d.hi50) & (d.rvol >= 1.5)
m = d.groupby("d").agg(rh=("rh", "mean"), rl=("rl", "mean"), rc=("rcl", "mean"), above50=("e50", lambda s: np.nan),
                       n=("symbol", "size")).drop(columns="above50")
m["above50"] = d.assign(a=d.cl > d.e50).groupby("d").a.mean() * 100
bo = d[d.bo & d.c5.notna()]
m["bo_n"] = bo.groupby("d").size(); m["bo_ft"] = bo.assign(ok=bo.c5 > bo.cl).groupby("d").ok.sum()
m = m.fillna({"bo_n": 0, "bo_ft": 0})
# gap guard: drop the 13 Aug -> 8 Oct jump
m = m[m.index <= "2026-08-13"]
m["idx"] = (1 + m.rc).cumprod() * 100
m["hi"] = m.idx.shift(1) * (1 + m.rh); m["lo"] = m.idx.shift(1) * (1 + m.rl)
tr = pd.concat([m.hi - m.lo, (m.hi - m.idx.shift(1)).abs(), (m.lo - m.idx.shift(1)).abs()], axis=1).max(axis=1)
n = 14
m["chop"] = 100 * np.log10(tr.rolling(n).sum() / (m.hi.rolling(n).max() - m.lo.rolling(n).min())) / np.log10(n)
m["er"] = (m.idx - m.idx.shift(20)).abs() / m.idx.diff().abs().rolling(20).sum()
x = (m.above50 > 50).astype(int); m["cross"] = x.diff().abs().rolling(20).sum()
m["ft"] = m.bo_ft.rolling(10).sum() / m.bo_n.rolling(10).sum() * 100
m["e50"] = m.idx.ewm(span=50, adjust=False).mean()
m["dd"] = (m.idx / m.idx.cummax() - 1) * 100
pct = lambda s: s.rank(pct=True)  # vs its own history (5-year archive: use expanding rank to stay point-in-time)
price = (pct(m.chop) > 0.7) | (pct(m.er) < 0.3)
breadth = m.cross >= 2
outcome = pct(m.ft) < 0.35
m["votes"] = price.astype(int) + breadth.astype(int) + outcome.astype(int)
def lab(r):
    if pd.isna(r.chop) or pd.isna(r.ft): return ""
    if r.dd < -20: return "Bear"
    if r.idx < r.e50 and r.dd < -8: return "Correction"
    if r.votes >= 2: return "Choppy"
    if r.idx > r.e50 and r.above50 > 55: return "Trending up"
    return "Mixed"
m["regime"] = m.apply(lab, axis=1)
out = m[["idx", "dd", "chop", "er", "above50", "cross", "ft", "bo_n", "votes", "regime"]].round(2)
out.to_csv(os.path.join(os.path.dirname(__file__), "choppy_daily.csv"))
# episodes
r = out.regime[out.regime != ""]; ep = (r != r.shift()).cumsum()
E = r.groupby(ep).agg(regime="first", start=lambda s: s.index[0].date(), end=lambda s: s.index[-1].date(), sessions="size")
E["ew_move_%"] = [round((out.idx.loc[str(s)] if False else out.idx[out.index.date == e].iat[0]) / out.idx[out.index.date == s].iat[0] * 100 - 100, 1) for s, e in zip(E.start, E.end)]
E = E[E.sessions >= 8]
print(E.to_string(index=False))
print("\nForward 20-session EW return by regime (all days):")
out["f20"] = (out.idx.shift(-20) / out.idx - 1) * 100
print(out[out.regime != ""].groupby("regime").agg(days=("f20", "size"), fwd20=("f20", "mean"), ft=("ft", "mean")).round(1).to_string())
