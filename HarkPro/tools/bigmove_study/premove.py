"""What separates a lift that becomes a big move from one that fizzles?  (Research View 3, round 1)
Event   : a stock >= 1000 Cr closes >= 20% above its 120-session low for the first time in 60 sessions ("early lift").
          Events from 2024-11-01 to 2026-02-13 (120 sessions of future must exist before the Aug-Oct data gap).
Outcome : RUNNER  = closes >= +50% above the event close within the next 120 sessions
          FIZZLE  = never gets +15% above the event close in that time
Traits  : measured at the event close, grouped as daily structure, weekly, monthly, accumulation (weeks/months),
          improvement (change over 1-3 months), base/volatility.
Output  : per trait, runner rate in its top vs bottom quintile and the lift vs the base rate; then a simple
          trait-count score trained on events before 2025-07-01 and TESTED on later events (out of sample).
Usage   : python HarkPro/tools/bigmove_study/premove.py"""
import os, duckdb, numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")); OUT = os.path.dirname(os.path.abspath(__file__))
c = duckdb.connect(os.path.join(ROOT, "Database/marketpulse.duckdb"), read_only=True)
cols = """symbol, trade_date, close_price cl, high_price hi, low_price lo, volume vol, delivery_pct dp, avg_delivery_pct_20d dp20,
 ema_10, ema_20, ema_50, ema_200, ema_200_rising, wema_10, wema_20, wma_30, wema_200, rsi_14, rsi_14_w, rsi_14_m, mema_10, mema_200,
 rs_percentile rs, rs_rank_t30, trend_template_pass_n ttn, away_52w_high_pct a52h, away_52w_low_pct a52l, atr_pct, atr_pct_avg_50d,
 range_50d_pct, range_20d_pct, rvol, avg_traded_value_cr_20d adv"""
d = c.execute(f"select {cols} from indicators_daily i join stocks_master m using(symbol) where m.market_cap_cr >= 1000 and i.trade_date <= '2026-08-13' order by symbol, trade_date").df()
d["trade_date"] = pd.to_datetime(d.trade_date)
g = d.groupby("symbol", sort=False)
roll = lambda col, n, f="mean", mp=None: g[col].transform(lambda s: getattr(s.rolling(n, min_periods=mp or n), f)())
# ---- event + outcome
d["low120"] = roll("cl", 120, "min", 60)
d["lift"] = d.cl >= 1.2 * d.low120
d["lift_prev"] = g["lift"].transform(lambda s: s.shift(1).rolling(60, min_periods=1).max()).fillna(1).astype(bool)
d["event"] = d.lift & ~d.lift_prev
d["fmax"] = g.cl.transform(lambda s: s[::-1].rolling(120, min_periods=100).max()[::-1].shift(-1))
# ---- traits
d["ret"] = g.cl.pct_change()
d["upvol"] = np.where(d.ret > 0, d.vol, 0); d["dnvol"] = np.where(d.ret < 0, d.vol, 0)
T = {}
# daily structure
T["D: % above 20 EMA"] = (d.cl / d.ema_20 - 1) * 100
T["D: % above 50 EMA"] = (d.cl / d.ema_50 - 1) * 100
T["D: % above 200 EMA"] = (d.cl / d.ema_200 - 1) * 100
T["D: 50 EMA above 200 EMA %"] = (d.ema_50 / d.ema_200 - 1) * 100
T["D: RSI 14"] = d.rsi_14
T["D: % from 52W high"] = d.a52h
T["D: % above 52W low"] = d.a52l
# weekly
T["W: % above 10W EMA"] = (d.cl / d.wema_10 - 1) * 100
T["W: % above 30W MA"] = (d.cl / d.wma_30 - 1) * 100
T["W: 10W above 30W %"] = (d.wema_10 / d.wma_30 - 1) * 100
T["W: weekly RSI"] = d.rsi_14_w
lo5 = roll("lo", 5, "min")
hl = sum((g[lo5.name if False else "lo"].transform(lambda s: s.rolling(5).min().shift(5 * k)) >
          g["lo"].transform(lambda s: s.rolling(5).min().shift(5 * (k + 1)))).astype(int) for k in range(8))
T["W: higher weekly lows (of 8)"] = hl
T["W: 30W MA rising (13w slope %)"] = g.wma_30.transform(lambda s: (s / s.shift(65) - 1) * 100)
# monthly
T["M: % above 10M EMA"] = (d.cl / d.mema_10 - 1) * 100
T["M: monthly RSI"] = d.rsi_14_m
T["M: 6M return %"] = g.cl.transform(lambda s: (s / s.shift(126) - 1) * 100)
T["M: 12M return %"] = g.cl.transform(lambda s: (s / s.shift(250) - 1) * 100)
# accumulation over weeks / months
T["A: up/down volume 50d"] = roll("upvol", 50, "sum") / roll("dnvol", 50, "sum")
T["A: up/down volume 13w"] = roll("upvol", 65, "sum") / roll("dnvol", 65, "sum")
T["A: delivery % vs 6M avg"] = d.dp20 - roll("dp", 126, "mean", 60)
wk_ret = g.cl.transform(lambda s: s / s.shift(5) - 1); wk_vol = roll("vol", 5, "sum")
wk_vol_avg = g[wk_vol.name if False else "vol"].transform(lambda s: s.rolling(5).sum().rolling(50).mean())
acc = ((wk_ret > 0) & (wk_vol > wk_vol_avg)).astype(float); dist = ((wk_ret < 0) & (wk_vol > wk_vol_avg)).astype(float)
d["acc"], d["dist"] = acc, dist
T["A: accumulation minus distribution weeks (13w)"] = sum(g["acc"].shift(5 * k) - g["dist"].shift(5 * k) for k in range(13))
T["A: traded value 20d vs 6M"] = d.adv / g.adv.transform(lambda s: s.rolling(126, min_periods=60).mean())
# improvement
T["I: RS percentile now"] = d.rs
T["I: RS change 1M"] = d.rs - g.rs.shift(21)
T["I: RS change 3M"] = d.rs - g.rs.shift(63)
T["I: trend-template checks (of 8)"] = d.ttn
T["I: template checks gained 1M"] = d.ttn - g.ttn.shift(21)
T["I: 200 EMA slope 1M %"] = g.ema_200.transform(lambda s: (s / s.shift(21) - 1) * 100)
# base / volatility
T["B: 50d range %"] = d.range_50d_pct
T["B: ATR% vs its 50d avg"] = d.atr_pct / d.atr_pct_avg_50d
T["B: days to lift from low"] = np.nan  # filled below
for k, v in T.items(): d[k] = v
# days from 120d low to event
d["i"] = g.cumcount()
d["lowpos"] = g.cl.transform(lambda s: s.rolling(120, min_periods=60).apply(lambda x: len(x) - 1 - np.argmin(x), raw=True))
d["B: days to lift from low"] = d.lowpos
E = d[d.event & (d.trade_date >= "2024-11-01") & (d.trade_date <= "2026-02-13") & d.fmax.notna()].copy()
E["runner"] = E.fmax >= 1.5 * E.cl; E["fizzle"] = E.fmax < 1.15 * E.cl
E = E[E.runner | E.fizzle]
base = E.runner.mean() * 100
rows = []
for k in T:
    x = E[[k, "runner"]].dropna()
    if len(x) < 200: continue
    q = pd.qcut(x[k].rank(method="first"), 5, labels=False)
    r = x.groupby(q).runner.mean() * 100
    rows.append((k, len(x), round(r.iloc[0], 1), round(r.iloc[2], 1), round(r.iloc[4], 1), round(x.loc[x.runner, k].median(), 2),
                 round(x.loc[~x.runner, k].median(), 2), round(max(r.iloc[4], r.iloc[0]) / base, 2), "high" if r.iloc[4] >= r.iloc[0] else "low"))
R = pd.DataFrame(rows, columns=["trait", "n", "Q1_low_%", "Q3_%", "Q5_high_%", "runner_median", "fizzle_median", "best_lift", "better_when"])
R = R.sort_values("best_lift", ascending=False)
pd.set_option("display.width", 250)
print(f"Events: {len(E)}  runners {E.runner.sum()}  fizzles {E.fizzle.sum()}  base runner rate {base:.1f}%")
print(R.to_string(index=False)); R.to_csv(os.path.join(OUT, "premove_traits.csv"), index=False)
# ---- out-of-sample trait-count score
train, test = E[E.trade_date < "2025-07-01"], E[E.trade_date >= "2025-07-01"]
top = []
for k in T:
    x = train[[k, "runner"]].dropna()
    if len(x) < 150: continue
    hi_cut, lo_cut = x[k].quantile(0.6), x[k].quantile(0.4)
    up, dn = x[x[k] >= hi_cut].runner.mean(), x[x[k] <= lo_cut].runner.mean()
    side, cut, rate = ("high", hi_cut, up) if up >= dn else ("low", lo_cut, dn)
    top.append((k, side, cut, rate / x.runner.mean()))
top = sorted(top, key=lambda t: -t[3])[:10]
def score(df): return sum(((df[k] >= cut) if side == "high" else (df[k] <= cut)).astype(int) for k, side, cut, _ in top)
test = test.assign(score=score(test)); train = train.assign(score=score(train))
print("\nTop 10 traits picked on TRAIN (Nov 2024-Jun 2025):")
for k, side, cut, l in top: print(f"  {k:45s} {side:4s} cut {cut:8.2f}  train lift {l:.2f}")
print(f"\nTEST (Jul 2025-Feb 2026), base runner rate {test.runner.mean()*100:.1f}%  (n={len(test)})")
b = pd.cut(test.score, [-1, 3, 5, 7, 10], labels=["0-3", "4-5", "6-7", "8-10"])
print(test.groupby(b, observed=True).agg(events=("runner", "size"), runner_rate=("runner", "mean")).assign(runner_rate=lambda x: (x.runner_rate * 100).round(1)).to_string())
E[["symbol", "trade_date", "cl", "runner"] + list(T)].to_csv(os.path.join(OUT, "premove_events.csv"), index=False)
pd.DataFrame(top, columns=["trait", "side", "cut", "train_lift"]).to_csv(os.path.join(OUT, "premove_score_traits.csv"), index=False)
