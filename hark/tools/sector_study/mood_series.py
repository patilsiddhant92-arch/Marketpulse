import duckdb,pandas as pd,numpy as np,warnings;warnings.filterwarnings('ignore')
import os; ROOT=os.path.abspath(os.path.join(os.path.dirname(__file__),'../../..'))
c=duckdb.connect(ROOT+'/Database/marketpulse.duckdb',read_only=True)
m=c.execute("""select trade_date d, avg((close_price>ema_10)::int) a10, avg((close_price>ema_50)::int) a50, avg((close_price>ema_200)::int) a200,
 sum(case when close_price>prev_close then turnover_cr else 0 end)/nullif(sum(turnover_cr),0) upv,
 (sum((close_price>=high_52w*0.999)::int)-sum((close_price<=low_52w*1.001)::int))*1.0/count(*) nnh,
 avg(trend_template_pass::int) s2 from indicators_daily where trade_date<='2026-08-13' group by 1 order by 1""").df()
m['d']=pd.to_datetime(m.d)
cols=['a10','a50','a200','upv','nnh','s2']
# expanding percentile (point in time), min 60 sessions
for k in cols:
    m[k+'_p']=m[k].expanding(60).apply(lambda s:(s<=s.iloc[-1]).mean()*100,raw=False)
m['mood']=m[[k+'_p' for k in cols]].mean(axis=1)
m['a10chg']=(m.a10-m.a10.shift(10))*100
m.to_pickle('mood.pkl')
print(m[['d','mood']].dropna().iloc[::40].to_string(index=False))
