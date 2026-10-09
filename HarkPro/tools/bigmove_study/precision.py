"""Precision check for caught.py: a preset that 'caught' 90% of big movers may just fire on everything.
For every fresh fire (Aug 2025 - Feb 2026, so 120 sessions of future exist) on every >= 1000 Cr stock:
hit = the stock closes >= +50% above the fire close at some point in the next 120 sessions.
Compared with the base rate on all stock-days. Also: hits when the fire comes with RS >= 80 and delivery spike."""
import os, sys, numpy as np, pandas as pd
sys.argv = [sys.argv[0], "__none__"]
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H)
src = open(os.path.join(H, "caught.py")).read().split("M = moves()")[0]
exec(src)
g = d.groupby("symbol").close_price
d["fmax"] = g.transform(lambda s: s[::-1].rolling(120, min_periods=60).max()[::-1].shift(-1))
d["hit"] = d.fmax / d.close_price >= 1.5
z = d[(d.trade_date >= "2025-08-13") & (d.trade_date <= "2026-02-13") & d.fmax.notna()]
rows = [("All stock-days", len(z), z.hit.mean() * 100)]
for k in P:
    f = z[z[k + "_fresh"]]; rows.append((k, len(f), f.hit.mean() * 100))
    f2 = f[(f.rs_percentile >= 80)]; rows.append((k + " + RS>=80", len(f2), f2.hit.mean() * 100))
R = pd.DataFrame(rows, columns=["signal", "fires", "hit_50pct_in_120d_%"]).round(1)
print(R.to_string(index=False)); R.to_csv(os.path.join(H, "precision.csv"), index=False)
