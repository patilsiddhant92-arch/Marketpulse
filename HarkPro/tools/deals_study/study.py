"""Deals round 1 evidence study.
Input: NSE historical bulk/block deal CSVs (api/historicalOR/bulk-block-short-deals ... &csv=true) in DEALS_DIR,
plus prices/indicators from Database/marketpulse.duckdb. Builds deal_session_net with the app's own builder,
then measures forward excess returns (entry next open, exit close T+5/T+20; excess vs the equal-weight
average of all >= 1000 Cr stocks over the same sessions) for each reading.
"""
import glob, sys, pathlib, duckdb, numpy as np, pandas as pd
ROOT = pathlib.Path(__file__).resolve().parents[3]; sys.path.insert(0, str(ROOT))
from Scripts.derived.deal_session_net import build_deal_session_net, normalise_deals
DEALS_DIR = sys.argv[1] if len(sys.argv) > 1 else "/workspace/work/deals_hist"
LAST_DEAL = pd.Timestamp("2026-07-14")   # T+20 must finish before the local data gap (13 Aug 2026)
FLOOR = 1000.0

def load_deals():
    fr = []
    for f in sorted(glob.glob(f"{DEALS_DIR}/*_deals_*.csv")):
        d = pd.read_csv(f, dtype=str, encoding="utf-8-sig")
        d.columns = [c.strip() for c in d.columns]
        if d.empty: continue
        d = d.rename(columns={"Date": "trade_date", "Symbol": "symbol", "Client Name": "client_name", "Buy / Sell": "side",
                              "Quantity Traded": "quantity", "Trade Price / Wght. Avg. Price": "price"})
        d["deal_type"] = "Block" if "block" in f else "Bulk"
        fr.append(d[["trade_date", "symbol", "client_name", "side", "quantity", "price", "deal_type"]])
    d = pd.concat(fr, ignore_index=True)
    d["trade_date"] = pd.to_datetime(d["trade_date"].str.strip(), format="%d-%b-%Y", errors="coerce")
    for c in ("quantity", "price"):
        d[c] = pd.to_numeric(d[c].str.replace(",", "").str.strip(), errors="coerce")
    for c in ("symbol", "client_name", "side"):
        d[c] = d[c].str.strip()
    return d.dropna(subset=["trade_date"])

con = duckdb.connect(str(ROOT / "Database/marketpulse.duckdb"), read_only=True)
raw = load_deals()
print("raw prints", len(raw), raw.trade_date.min().date(), raw.trade_date.max().date())
ind = con.execute("""select i.symbol, i.trade_date, i.open_price, i.close_price, i.volume, i.turnover_cr,
    i.avg_traded_value_cr_20d adv, i.ema_200, i.rs_percentile rs, i.away_52w_high_pct a52, m.market_cap_cr mc_now, m.industry, m.sector
    from indicators_daily i join stocks_master m using(symbol)""").df()
ind["trade_date"] = pd.to_datetime(ind["trade_date"])
ind = ind.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
last_close = ind.groupby("symbol").close_price.transform("last")
ind["mcap"] = ind.mc_now * ind.close_price / last_close          # price-scaled current share count (approximation)
g = ind.groupby("symbol")
ind["o1"] = g.open_price.shift(-1)
for h in (5, 20):
    ind[f"c{h}"] = g.close_price.shift(-h)
    ind[f"r{h}"] = (ind[f"c{h}"] / ind.o1 - 1) * 100
    ind.loc[ind[f"r{h}"].abs() > 60, f"r{h}"] = np.nan             # unadjusted corporate actions
u = ind[ind.mcap >= FLOOR]
bench = u.groupby("trade_date")[["r5", "r20"]].mean().add_prefix("b")
ind = ind.merge(bench, left_on="trade_date", right_index=True, how="left")
for h in (5, 20):
    ind[f"x{h}"] = ind[f"r{h}"] - ind[f"br{h}"]

prices = ind[["symbol", "trade_date", "close_price", "volume", "turnover_cr"]].rename(columns={})
dsn = build_deal_session_net(raw, prices, ind[["symbol", "trade_date", "close_price", "volume", "turnover_cr"]])
dsn["trade_date"] = pd.to_datetime(dsn["trade_date"])
print("symbol-sessions", len(dsn), dsn.event_type.value_counts().to_dict())
ev = dsn.merge(ind[["symbol", "trade_date", "mcap", "adv", "close_price", "ema_200", "rs", "a52", "industry", "sector", "x5", "x20", "r20"]],
               on=["symbol", "trade_date"], how="left", suffixes=("", "_i"))
ev = ev[(ev.trade_date <= LAST_DEAL) & (ev.mcap >= FLOOR)]
base = ind[(ind.mcap >= FLOOR) & ind.trade_date.isin(ev.trade_date.unique()) & (ind.trade_date <= LAST_DEAL)]

def row(name, s):
    s20 = s.x20.dropna(); s5 = s.x5.dropna(); n = len(s20)
    t = s20.mean() / (s20.std(ddof=1) / np.sqrt(n)) if n > 2 else np.nan
    return {"reading": name, "n": n, "x5": round(s5.mean(), 2), "x20": round(s20.mean(), 2), "x20_med": round(s20.median(), 2),
            "beat%": round((s20 > 0).mean() * 100, 1) if n else np.nan, "t": round(t, 1)}
R = [row("baseline: all >=1000Cr stocks, same dates", base)]
for et in ["accumulate", "fresh", "distribute", "transfer_interse", "placement", "churn"]:
    R.append(row(f"event: {et}", ev[ev.event_type == et]))
buy = ev[ev.event_type.isin(["accumulate", "fresh"])].copy()
buy["vs_adv"] = buy.net_value_cr_ex_prop / buy.adv
for lo, hi in [(0, .25), (.25, 1), (1, 3), (3, 1e9)]:
    R.append(row(f"net buy size {lo}-{hi if hi<1e9 else '+'}x ADV", buy[(buy.vs_adv >= lo) & (buy.vs_adv < hi)]))
for c in ["fii", "dii", "corporate", "other", "hni"]:
    col = f"net_value_cr_{c}"
    if col in ev: R.append(row(f"net buyer class: {c.upper()} > 0", ev[(ev[col] > 0) & ev.event_type.isin(["accumulate", "fresh"])]))
R.append(row("net buy, >=2 buying houses", buy[buy.buying_houses >= 2]))
R.append(row("net buy, 1 buying house", buy[buy.buying_houses < 2]))
R.append(row("net buy, repeat (>=2 net-buy sessions in 10)", buy[buy.net_buy_sessions_10 >= 2]))
R.append(row("net buy at premium to close (vwap > close)", buy[buy.buy_vwap_vs_close_pct < 0]))
R.append(row("net buy at discount to close", buy[buy.buy_vwap_vs_close_pct >= 0]))
ctx = (buy.close_price > buy.ema_200) & (buy.rs >= 70) & (buy.a52 >= -15)
R.append(row("net buy + strong chart (>200EMA, RS>=70, within 15% of high)", buy[ctx]))
R.append(row("net buy + weak chart", buy[~ctx & buy.rs.notna()]))
R.append(row("block deal present, net buy", buy[buy.deal_types.str.contains("Block", na=False)]))
R.append(row("bulk only, net buy", buy[~buy.deal_types.str.contains("Block", na=False)]))
strong = base[(base.close_price > base.ema_200) & (base.rs >= 70) & (base.a52 >= -15)]
R.append(row("baseline: strong chart, no condition on deals", strong))
dist = ev[ev.event_type == "distribute"]
R.append(row("distribute + strong chart", dist[(dist.close_price > dist.ema_200) & (dist.rs >= 70) & (dist.a52 >= -15)]))
out = pd.DataFrame(R)

# House track record, out of sample: a house's prior bets (T+20 finished before this bet's date) decide its grade.
p = normalise_deals(raw)
p = p[(p.side == "BUY") & (p.clientele != "PROP") & (p.value_cr >= 5)]
p = p.merge(ind[["symbol", "trade_date", "mcap", "x20"]], on=["symbol", "trade_date"], how="left")
p = p[p.mcap >= FLOOR].sort_values("trade_date")
p["house"] = p.client.str.replace(r"\b(PVT|PRIVATE|LTD|LIMITED|FPI|ODI|-)\b", "", regex=True).str.split().str[:3].str.join(" ")
sess = sorted(ind.trade_date.unique()); pos = {d: i for i, d in enumerate(sess)}
p["si"] = p.trade_date.map(pos)
rec = []
for h, gdf in p.groupby("house"):
    gdf = gdf.reset_index(drop=True)
    for i, r in gdf.iterrows():
        prior = gdf[(gdf.si + 21 <= r.si) & gdf.x20.notna()]
        rec.append((r.trade_date, r.x20, len(prior), prior.x20.mean() if len(prior) else np.nan, (prior.x20 > 0).mean() if len(prior) else np.nan))
hr = pd.DataFrame(rec, columns=["d", "x20", "n_prior", "prior_x20", "prior_beat"])
hr = hr[hr.d <= LAST_DEAL]
H = [row("house buy >= 5Cr, any house", hr.rename(columns={}).assign(x5=np.nan))]
for lab, m in [("house with <5 prior finished bets", hr.n_prior < 5),
               ("house >=5 prior bets, prior avg excess > +3%", (hr.n_prior >= 5) & (hr.prior_x20 > 3)),
               ("house >=5 prior bets, prior avg excess 0..3%", (hr.n_prior >= 5) & hr.prior_x20.between(0, 3)),
               ("house >=5 prior bets, prior avg excess < 0", (hr.n_prior >= 5) & (hr.prior_x20 < 0))]:
    H.append(row(lab, hr[m].assign(x5=np.nan)))
out = pd.concat([out, pd.DataFrame(H)], ignore_index=True)

# Group level (parked item): net-buy deal count per industry over the last 10 sessions vs the industry's next 20 sessions.
fl = ev[ev.event_type.isin(["accumulate", "fresh"])].groupby(["industry", "trade_date"]).size().rename("nb").reset_index()
ig = u.groupby(["industry", "trade_date"]).x20.mean().rename("gx20").reset_index() if "x20" in u else None
u2 = ind[ind.mcap >= FLOOR].groupby(["industry", "trade_date"]).x20.mean().rename("gx20").reset_index()
u2 = u2.merge(fl, on=["industry", "trade_date"], how="left").fillna({"nb": 0}).sort_values(["industry", "trade_date"])
u2["nb10"] = u2.groupby("industry").nb.transform(lambda s: s.rolling(10, min_periods=10).sum())
u2 = u2[(u2.trade_date <= LAST_DEAL) & (u2.trade_date >= raw.trade_date.min() + pd.Timedelta(days=15))]
G = []
for lab, m in [("industry with 0 net-buy deal stocks in 10 sessions", u2.nb10 == 0), ("1-2", u2.nb10.between(1, 2)), ("3+", u2.nb10 >= 3)]:
    s = u2[m].rename(columns={"gx20": "x20"}).assign(x5=np.nan)
    G.append(row("group: " + lab, s))
out = pd.concat([out, pd.DataFrame(G)], ignore_index=True)
pd.set_option("display.width", 200); pd.set_option("display.max_colwidth", 70)
print(out.to_string(index=False))
out.to_csv(ROOT / "HarkPro/tools/deals_study/results.csv", index=False)
