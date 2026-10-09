"""Follow-up on premove.py: (1) are runners clustered in one regime (the Mar-2025 bottom)? (2) two families:
   turnaround lifts (below the 200 EMA at the event) vs trend lifts (above it) - which traits matter inside each?"""
import os, numpy as np, pandas as pd
H = os.path.dirname(os.path.abspath(__file__))
E = pd.read_csv(os.path.join(H, "premove_events.csv"), parse_dates=["trade_date"])
m = E.groupby(E.trade_date.dt.to_period("Q")).agg(events=("runner", "size"), runner_pct=("runner", "mean"))
m["runner_pct"] = (m.runner_pct * 100).round(1); print(m.to_string())
traits = [c for c in E.columns if c[:3] in ("D: ", "W: ", "M: ", "A: ", "I: ", "B: ")]
for name, sub in (("TURNAROUND (below 200 EMA)", E[E["D: % above 200 EMA"] < 0]), ("TREND (above 200 EMA)", E[E["D: % above 200 EMA"] >= 0])):
    base = sub.runner.mean() * 100; rows = []
    for k in traits:
        x = sub[[k, "runner"]].dropna()
        if len(x) < 100: continue
        q = pd.qcut(x[k].rank(method="first"), 3, labels=False); r = x.groupby(q).runner.mean() * 100
        rows.append((k, len(x), round(r.iloc[0], 1), round(r.iloc[2], 1), round(max(r.iloc[0], r.iloc[2]) / base, 2), "high" if r.iloc[2] >= r.iloc[0] else "low"))
    R = pd.DataFrame(rows, columns=["trait", "n", "low_third_%", "high_third_%", "lift", "better_when"]).sort_values("lift", ascending=False)
    print(f"\n{name}: n={len(sub)} base runner {base:.1f}%"); print(R.head(12).to_string(index=False))
    R.to_csv(os.path.join(H, "premove_" + name.split()[0].lower() + ".csv"), index=False)
