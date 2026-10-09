"""Could our screener have caught the big moves? (Research: Before the big moves, case-study mode)
Window: the last 12 months of local data before the Aug-Oct gap (2025-08-13 .. 2026-08-13).
Big mover: mcap >= 1000 Cr today, lowest close in the window -> highest close after it >= +100%.
For every screener preset (same rules as App/services/screener.py) we find the FIRST fresh fire after the move's low
(fresh = true today, false the previous 5 sessions), its entry close, and two outcomes:
  capture_to_peak : entry -> peak close (best case)
  trail20         : buy at the fire close, sell at the first close below the 20 EMA (realistic swing exit)
Usage: python HarkPro/tools/bigmove_study/caught.py [SYM SYM ...]   (no args = all big movers + summary)"""
import os, sys, duckdb, numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
OUT = os.path.dirname(os.path.abspath(__file__))
START, END = "2025-08-13", "2026-08-13"
c = duckdb.connect(os.path.join(ROOT, "Database/marketpulse.duckdb"), read_only=True)
d = c.execute(f"""select i.symbol,i.trade_date,i.close_price,i.high_price,i.ema_10,i.ema_20,i.ema_50,i.ema_100,i.ema_200,i.sma_50,i.sma_150,i.sma_200,
  i.sma_200_rising,i.trend_template_pass,i.rs_percentile,i.away_10ema_pct,i.away_52w_high_pct,i.away_52w_low_pct,i.high_52w,i.delivery_spike,
  i.price_up_delivery_up,i.nr7,i.inside_bar,i.rsi_14_w,i.is_vcp, m.market_cap_cr mcap_now from indicators_daily i join stocks_master m using(symbol)
  where m.market_cap_cr >= 1000 and i.trade_date between date '{START}' - interval 30 day and date '{END}' order by symbol, trade_date""").df()
d["trade_date"] = pd.to_datetime(d.trade_date)
cl = d.close_price
spread = (d[["ema_10", "ema_20", "ema_50"]].max(axis=1) / d[["ema_10", "ema_20", "ema_50"]].min(axis=1) - 1) * 100
stack = (d.ema_10 > d.ema_20) & (d.ema_20 > d.ema_50) & (d.ema_50 > d.ema_100) & (d.ema_100 > d.ema_200)
P = {
 "Minervini 8/8": d.trend_template_pass.fillna(False) & (d.rs_percentile >= 70),
 "Stage 2 leader": (cl > d.ema_200) & (d.away_10ema_pct >= 0) & (d.away_52w_high_pct >= -25) & (d.away_52w_low_pct >= 50) & stack,
 "EMA stack": stack & (d.away_10ema_pct >= 0),
 "EMAs converge": (spread <= 3) & (cl > d.ema_200),
 "Near 52W high": (d.away_52w_high_pct >= -5) & (d.away_52w_low_pct >= 50) & (d.away_10ema_pct >= 0) & (cl > d.ema_200),
 "Fresh 52W high": (d.high_price >= d.high_52w * 0.9999) & (cl > d.ema_200),
 "SMA template": (cl > d.sma_150) & (cl > d.sma_200) & (d.sma_150 > d.sma_200) & (d.sma_50 > d.sma_150) & (cl > d.sma_50)
                 & d.sma_200_rising.fillna(False) & (d.away_52w_high_pct >= -25) & (d.away_52w_low_pct >= 50),
 "Delivery thrust": d.delivery_spike.fillna(False) & d.price_up_delivery_up.fillna(False) & (cl > d.ema_20) & (cl > d.ema_200),
 "NR7 / inside": (d.nr7.fillna(False) | d.inside_bar.fillna(False)) & (d.away_52w_high_pct >= -15) & (d.away_52w_low_pct >= 50),
 "Weekly RSI 60": (d.rsi_14_w >= 60) & (d.away_10ema_pct >= 0) & (cl > d.ema_200),
 "VCP flag": d.is_vcp.fillna(False),
}
for k, v in P.items(): d[k] = v.fillna(False).astype(bool)
g = d.groupby("symbol")
for k in P: d[k + "_fresh"] = d[k] & ~g[k].transform(lambda s: s.shift(1).rolling(5, min_periods=1).max().fillna(0).astype(bool))

def moves():
    w = d[d.trade_date >= START]
    rows = []
    for s, x in w.groupby("symbol"):
        if len(x) < 150: continue
        i_lo = x.close_price.idxmin(); after = x.loc[i_lo:]
        i_pk = after.close_price.idxmax(); gain = after.close_price.max() / x.close_price[i_lo] * 100 - 100
        rows.append((s, x.trade_date[i_lo], x.close_price[i_lo], x.trade_date[i_pk], x.close_price[i_pk], gain))
    return pd.DataFrame(rows, columns=["symbol", "low_date", "low", "peak_date", "peak", "gain"])

def trail20(x, i):
    after = x.loc[i:]; brk = after[after.close_price < after.ema_20]
    ex = brk.iloc[0] if len(brk) else after.iloc[-1]
    return ex.close_price, ex.trade_date

def study(sym, mv):
    x = d[d.symbol == sym].set_index(d.index[d.symbol == sym])
    m = mv.iloc[0]; win = x[(x.trade_date >= m.low_date) & (x.trade_date <= m.peak_date)]
    out = []
    for k in P:
        f = win[win[k + "_fresh"]]
        if f.empty: out.append((sym, k, None, None, None, None, None, None, 0)); continue
        i = f.index[0]; e = x.close_price[i]; xp, xd = trail20(x, i)
        out.append((sym, k, x.trade_date[i].date(), round(e, 1), round((e / m.low - 1) * 100), round((m.peak / e - 1) * 100),
                    round((xp / e - 1) * 100, 1), xd.date(), len(f)))
    return pd.DataFrame(out, columns=["symbol", "preset", "first_fire", "entry", "entry_vs_low_%", "to_peak_%", "trail20_%", "trail20_exit", "fresh_fires"])

M = moves()
syms = sys.argv[1:]
if syms:
    for s in syms:
        mv = M[M.symbol == s]; m = mv.iloc[0]
        print(f"\n== {s}: low {m.low:.0f} on {m.low_date.date()} -> peak {m.peak:.0f} on {m.peak_date.date()} (+{m.gain:.0f}%)")
        print(study(s, mv).sort_values("first_fire", na_position="last").to_string(index=False))
else:
    big = M[M.gain >= 100].sort_values("gain", ascending=False)
    big.to_csv(os.path.join(OUT, "big_movers.csv"), index=False)
    R = pd.concat([study(s, big[big.symbol == s]) for s in big.symbol])
    R.to_csv(os.path.join(OUT, "caught_by_preset.csv"), index=False)
    n = len(big); f = R.dropna(subset=["first_fire"])
    f = f.merge(big[["symbol", "gain"]], on="symbol"); f["share_of_move_left"] = (1 + f["to_peak_%"] / 100) / (1 + f.gain / 100)
    S = f.groupby("preset").agg(caught=("symbol", "nunique"), entry_vs_low=("entry_vs_low_%", "median"),
          to_peak=("to_peak_%", "median"), trail20=("trail20_%", "median"), fires=("fresh_fires", "median")).round(1)
    S["caught_%"] = (S.caught / n * 100).round()
    print(f"{n} big movers (>= +100% low->peak, mcap >= 1000 Cr) in {START}..{END}")
    print(S.sort_values("trail20", ascending=False).to_string())
    print(big.head(25).round(0).to_string(index=False))

# ---- Re-entry ladder: enter on the first fresh fire of any ENTRY preset, exit on a close below the 20 EMA, repeat.
ENTRY = ["Delivery thrust", "EMAs converge", "VCP flag", "Fresh 52W high", "Near 52W high"]
def ladder(sym, mv, end=None):
    x = d[d.symbol == sym]; m = mv.iloc[0]
    x = x[x.trade_date >= m.low_date]
    any_fire = x[[k + "_fresh" for k in ENTRY]].any(axis=1)
    legs, i, n = [], 0, len(x)
    while i < n:
        j = next((k for k in range(i, n) if any_fire.iat[k] and x.close_price.iat[k] > x.ema_20.iat[k]), None)
        if j is None: break
        why = [k for k in ENTRY if x[k + "_fresh"].iat[j]][0]
        e = next((k for k in range(j + 1, n) if x.close_price.iat[k] < x.ema_20.iat[k]), n - 1)
        legs.append((x.trade_date.iat[j].date(), why, round(x.close_price.iat[j], 1), x.trade_date.iat[e].date(),
                     round(x.close_price.iat[e], 1), round((x.close_price.iat[e] / x.close_price.iat[j] - 1) * 100, 1)))
        i = e + 1
    L = pd.DataFrame(legs, columns=["entry_date", "signal", "entry", "exit_date", "exit", "pnl_%"])
    comp = (np.prod(1 + L["pnl_%"] / 100) - 1) * 100 if len(L) else 0
    return L, comp

if syms:
    for s in syms:
        L, comp = ladder(s, M[M.symbol == s])
        print(f"\n-- {s} re-entry ladder (exit: close < 20 EMA): {len(L)} trades, compounded {comp:.0f}%")
        print(L.to_string(index=False))
else:
    big = M[M.gain >= 100]
    res = [(s, *ladder(s, big[big.symbol == s])[::-1][:1], len(ladder(s, big[big.symbol == s])[0])) for s in big.symbol]
    Q = pd.DataFrame(res, columns=["symbol", "ladder_%", "trades"]).merge(big[["symbol", "gain"]], on="symbol")
    Q.to_csv(os.path.join(OUT, "ladder.csv"), index=False)
    print("\nLadder across big movers: median compounded", round(Q["ladder_%"].median()), "% vs median move", round(Q.gain.median()), "%; median trades", Q.trades.median())
