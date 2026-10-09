"""Builds hark/mockups/stock-heatmap.html: TradingView-style stock heatmap from the local DB."""
import json, sys, duckdb, pandas as pd, pathlib
D = sys.argv[1] if len(sys.argv) > 1 else "2026-08-13"
root = pathlib.Path(__file__).resolve().parents[3]
c = duckdb.connect(str(root / "Database/marketpulse.duckdb"), read_only=True)
q = f"""
with b as (select symbol, trade_date, close_price c, turnover_cr t,
  lag(close_price,1) over w c1, lag(close_price,5) over w c5, lag(close_price,21) over w c21,
  avg(turnover_cr) over (partition by symbol order by trade_date rows 19 preceding) t20
  from indicators_daily where trade_date between date '{D}' - 60 and '{D}' window w as (partition by symbol order by trade_date))
select b.symbol s, m.sector, m.broad_industry bi, m.industry ind, round(m.market_cap_cr) mc, c,
  round(100*(c/c1-1),2) r1, round(100*(c/c5-1),2) r5, round(100*(c/c21-1),2) r21, round(t,2) t, round(t20,2) t20
from b join stocks_master m using(symbol) where trade_date='{D}' and t>0 and m.sector is not null"""
df = c.execute(q).df()
for col in ("r1", "r5", "r21"):  # unadjusted split/bonus guard
    df.loc[(df[col] <= -35) | (df[col] >= 100), col] = None
rows = df.where(pd.notna(df), None).values.tolist()
data = {"date": D, "cols": list(df.columns), "rows": rows}
tpl = (pathlib.Path(__file__).parent / "template.html").read_text()
out = root / "hark/mockups/stock-heatmap.html"
out.write_text(tpl.replace("/*DATA*/null", json.dumps(data, separators=(",", ":"))))
print(out, len(rows))
