"""Deals round 2 study: does price action AROUND the deal add an edge? Reuses study.py's frames (runpy).
Confirmation tests enter at the close k sessions after the deal and measure 20 sessions from there vs the market."""
import runpy, pathlib, numpy as np, pandas as pd, sys, io, contextlib
here = pathlib.Path(__file__).parent
with contextlib.redirect_stdout(io.StringIO()):
    S = runpy.run_path(str(here / "study.py"))
ind, ev, row, FLOOR, LAST = S["ind"], S["ev"], S["row"], S["FLOOR"], S["LAST_DEAL"]
con = S["con"]
extra = con.execute("select symbol, trade_date, prev_close, close_location_pct clp, delivery_pct dp, avg_delivery_pct_20d adp, "
                    "return_1m_pct r1m, rvol from indicators_daily").df()
extra["trade_date"] = pd.to_datetime(extra.trade_date)
ind = ind.merge(extra, on=["symbol", "trade_date"], how="left")
g = ind.groupby("symbol")
for k in (1, 3, 5):
    ind[f"ck{k}"] = g.close_price.shift(-k)
    ind[f"cc{k}"] = (g.close_price.shift(-(k + 20)) / ind[f"ck{k}"] - 1) * 100
    ind.loc[ind[f"cc{k}"].abs() > 60, f"cc{k}"] = np.nan
    b = ind[ind.mcap >= FLOOR].groupby("trade_date")[f"cc{k}"].mean().rename(f"bcc{k}")
    ind = ind.merge(b, left_on="trade_date", right_index=True, how="left")
    ind[f"y{k}"] = ind[f"cc{k}"] - ind[f"bcc{k}"]
cols = ["symbol", "trade_date", "ck1", "ck3", "ck5", "y1", "y3", "y5", "prev_close", "clp", "dp", "adp", "r1m", "rvol"]
e = ev.merge(ind[cols], on=["symbol", "trade_date"], how="left")
e = e[e.trade_date <= LAST - pd.Timedelta(days=10)]
e["ref"] = e.buy_vwap.where(e.buy_vwap > 0, e.vwap)
e["sref"] = e.sell_vwap.where(e.sell_vwap > 0, e.vwap)
e["day_chg"] = (e.close_price / e.prev_close - 1) * 100
strong = (e.close_price > e.ema_200) & (e.rs >= 70) & (e.a52 >= -15)
def r(name, s, col="x20"):
    s = s.copy(); s["x20"] = s[col]; s["x5"] = np.nan; return row(name, s)
buy = e[e.event_type.isin(["accumulate", "fresh"])]
pl = e[e.event_type == "placement"]
di = e[e.event_type == "distribute"]
R = []
R.append(r("A net buy: base (enter next open)", buy))
for k in (1, 3, 5):
    R.append(r(f"A net buy, close T+{k} ABOVE buy price (enter T+{k} close)", buy[buy[f"ck{k}"] > buy.ref], f"y{k}"))
    R.append(r(f"A net buy, close T+{k} BELOW buy price (enter T+{k} close)", buy[buy[f"ck{k}"] <= buy.ref], f"y{k}"))
sb = buy[strong.reindex(buy.index, fill_value=False)]
R.append(r("A net buy + strong chart, T+3 above buy price", sb[sb.ck3 > sb.ref], "y3"))
R.append(r("A net buy + strong chart, T+3 below buy price", sb[sb.ck3 <= sb.ref], "y3"))
R.append(r("A placement, T+3 above deal price", pl[pl.ck3 > pl.ref], "y3"))
R.append(r("A placement, T+3 below deal price", pl[pl.ck3 <= pl.ref], "y3"))
R.append(r("A distribute, T+3 above sell price (supply absorbed)", di[di.ck3 > di.sref], "y3"))
R.append(r("A distribute, T+3 below sell price", di[di.ck3 <= di.sref], "y3"))
for lab, m in [("< -10%", buy.r1m < -10), ("-10..+10%", buy.r1m.between(-10, 10)), ("+10..+30%", buy.r1m.between(10, 30)), ("> +30%", buy.r1m > 30)]:
    R.append(r(f"B net buy, prior 1M return {lab}", buy[m]))
R.append(r("C net buy, deal-day close in top third of range", buy[buy.clp >= 67]))
R.append(r("C net buy, deal-day close in bottom third", buy[buy.clp <= 33]))
R.append(r("C net buy, deal-day up >3%", buy[buy.day_chg > 3]))
R.append(r("C net buy, deal-day down", buy[buy.day_chg < 0]))
R.append(r("C net buy, delivery% >= 1.5x its 20D avg", buy[buy.dp >= 1.5 * buy.adp]))
R.append(r("C net buy, delivery% below its 20D avg", buy[buy.dp < buy.adp]))
pd_ = (pl.ref / pl.close_price - 1) * 100
R.append(r("E placement at >=3% discount to close", pl[pd_ <= -3]))
R.append(r("E placement within 3% of close", pl[pd_ > -3]))
R.append(r("E placement + strong chart", pl[strong.reindex(pl.index, fill_value=False)]))
ch = e[e.event_type == "churn"]
R.append(r("F churn, stock RVOL >= 3 (hype day)", ch[ch.rvol >= 3]))
R.append(r("F churn, RVOL < 3", ch[ch.rvol < 3]))
out = pd.DataFrame(R)
pd.set_option("display.width", 200); pd.set_option("display.max_colwidth", 70)
print(out.drop(columns=["x5"]).to_string(index=False))
out.to_csv(here / "results2.csv", index=False)
