"""Fund tracking test: does a house's out-of-sample record persist, by client class and with chart context?"""
import runpy, pathlib, io, contextlib, numpy as np, pandas as pd
here = pathlib.Path(__file__).parent
with contextlib.redirect_stdout(io.StringIO()):
    S = runpy.run_path(str(here / "study.py"))
p, ind, row, LAST = S["p"], S["ind"], S["row"], S["LAST_DEAL"]
ctx = ind[["symbol", "trade_date", "close_price", "ema_200", "rs", "a52"]]
p = p.merge(ctx, on=["symbol", "trade_date"], how="left")
p["strong"] = (p.close_price > p.ema_200) & (p.rs >= 70) & (p.a52 >= -15)
rec = []
for h, g in p.groupby("house"):
    g = g.reset_index(drop=True)
    for i, r in g.iterrows():
        prior = g[(g.si + 21 <= r.si) & g.x20.notna()]
        ps = prior[prior.strong]
        rec.append((r.trade_date, r.clientele, r.strong, r.x20, len(prior), prior.x20.mean() if len(prior) else np.nan,
                    len(ps), ps.x20.mean() if len(ps) else np.nan))
hr = pd.DataFrame(rec, columns=["d", "cls", "strong", "x20", "n", "px", "ns", "psx"])
hr = hr[hr.d <= LAST].assign(x5=np.nan)
R = []
for cls in ["FII", "DII", "CORPORATE", "OTHER"]:
    s = hr[(hr.cls == cls)]
    R.append(row(f"{cls}: all buys", s))
    R.append(row(f"{cls}: house prior avg > 0 (>=5 bets)", s[(s.n >= 5) & (s.px > 0)]))
    R.append(row(f"{cls}: house prior avg < 0 (>=5 bets)", s[(s.n >= 5) & (s.px < 0)]))
R.append(row("any: good-record house buying a STRONG chart", hr[(hr.n >= 5) & (hr.px > 0) & hr.strong]))
R.append(row("any: poor-record house buying a STRONG chart", hr[(hr.n >= 5) & (hr.px < 0) & hr.strong]))
R.append(row("any: house good on its prior strong-chart bets (>=3), buying strong", hr[(hr.ns >= 3) & (hr.psx > 0) & hr.strong]))
R.append(row("any: buys on a strong chart, no record filter", hr[hr.strong]))
v = hr[(hr.n >= 5)].dropna(subset=["px", "x20"])
print(f"rank corr prior record vs next bet (n={len(v)}): {v.px.rank().corr(v.x20.rank()):.3f}")
pd.set_option("display.width", 200)
print(pd.DataFrame(R).drop(columns=["x5"]).to_string(index=False))
