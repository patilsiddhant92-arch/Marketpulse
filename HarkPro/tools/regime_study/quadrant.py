"""Two-axis regime test on choppy_daily.csv (run choppy.py first).
Index axis: Range if Choppiness(14) is in the top 40% of its history or efficiency ratio(20) in the bottom 40%, else Trend.
Breakout axis: Failing if trailing 10-session follow-through is below its median, else Paying.
Checks what the NEXT 10 sessions of breakouts did (follow-through %) in each quadrant, plus EW market fwd 20."""
import os, pandas as pd
H = os.path.dirname(os.path.abspath(__file__))
o = pd.read_csv(os.path.join(H, "choppy_daily.csv"), index_col=0, parse_dates=True).dropna(subset=["chop", "ft"])
rk = lambda s: s.expanding(60).apply(lambda x: (x[:-1] < x[-1]).mean(), raw=True)  # point-in-time percentile
o["chop_p"], o["er_p"], o["ft_p"] = rk(o.chop), rk(o.er), rk(o.ft)
o = o.dropna(subset=["chop_p"])
o["index"] = (((o.chop_p > 0.6) | (o.er_p < 0.4))).map({True: "Range", False: "Trend"})
o["brk"] = (o.ft_p < 0.5).map({True: "Failing", False: "Paying"})
raw = pd.read_csv(os.path.join(H, "choppy_daily.csv"), index_col=0, parse_dates=True)
ftn, bon = raw.ft * raw.bo_n / 100, raw.bo_n
nx = lambda s: s[::-1].rolling(10).sum()[::-1].shift(-1)
o["next_ft"] = (nx(ftn) / nx(bon) * 100).reindex(o.index)
o["f20"] = ((raw.idx.shift(-20) / raw.idx - 1) * 100).reindex(o.index)
t = o.groupby(["index", "brk"]).agg(days=("f20", "size"), next10_breakout_ft=("next_ft", "mean"), ew_fwd20=("f20", "mean")).round(1)
print(t.to_string()); print("\nbase next10 FT", round(o.next_ft.mean(), 1))
print("\nlatest:", o.iloc[-1][["chop", "er", "ft", "index", "brk"]].to_dict())
o[["index", "brk"]].to_csv(os.path.join(H, "quadrant_daily.csv"))
