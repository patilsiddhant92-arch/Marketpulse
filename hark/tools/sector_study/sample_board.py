import duckdb, pandas as pd, numpy as np, sys
sys.path.insert(0,__import__('os').path.abspath(__import__('os').path.join(__import__('os').path.dirname(__file__),'../../..')))
from Scripts.derived.group_daily import add_health_columns
c=duckdb.connect(sys.path[0]+'/Database/marketpulse.duckdb',read_only=True)
LV=sys.argv[1] if len(sys.argv)>1 else 'Industry'
g=c.execute(f"""select trade_date d, group_name gname, members, ret_ew_1d, ret_ew_21d, ret_ew_63d, pct_above_50ema b50, pct_above_200ema b200,
 pct_trend_template tt, pct_new_highs_52w nh, turnover_share_delta flow, turnover_share_5d_chg_5d flowchg, deliv_acc_10d_pct dacc, top1_turnover_share_pct top1
 from group_daily where level='Broad Industry' and floor='1000cr' and trade_date<='2026-08-13' order by gname,d""").df()
g['d']=pd.to_datetime(g['d'])
dates=sorted(g.d.unique()); di={d:i for i,d in enumerate(dates)}
g['i']=g.d.map(di)
# synthetic benchmark: mean of group ew 1d returns (eligible) per day
mk=g[g.members>=3].groupby('d').ret_ew_1d.mean()/100
bench=np.exp(np.log1p(mk.fillna(0)).cumsum())
g=g.sort_values(['gname','d']).reset_index(drop=True)
gb=g.groupby('gname')
idx=np.exp(np.log1p((g.ret_ew_1d/100).fillna(0).clip(lower=-.99)).groupby(g.gname).cumsum())
rs=idx/g.d.map(bench)
g['_rs']=rs
fast=g.groupby('gname')['_rs'].transform(lambda s:s.ewm(span=10,adjust=False,min_periods=10).mean())
slow=g.groupby('gname')['_rs'].transform(lambda s:s.ewm(span=50,adjust=False,min_periods=50).mean())
g['rs_ratio_self']=100*fast/slow
g['rs_momentum_self']=100*g.rs_ratio_self/g.groupby('gname').rs_ratio_self.shift(10)
add_health_columns(g,'gname',['d'],members='members',ret1='ret_ew_1d',ret21='ret_ew_21d',b50='b50',b200='b200')
# forward 21d return from cumulative index
g['idx']=idx.values
for h in (10,21):
    g[f'fwd{h}']=(g.groupby('gname').idx.shift(-h)/g.idx-1)*100
g['score']=(g.ret_ew_21d+g.ret_ew_63d)/2
g['health_chg10']=g.health-g.groupby('gname').health.shift(10)
e=g[(g.members>=3)&(g.d>=pd.Timestamp('2024-10-01'))].copy()
# exclude forward windows crossing gap: last valid date index such that i+21 <= index of 2026-08-13
e=e[e.i+21<=di[pd.Timestamp('2026-08-13')]]
D=pd.Timestamp('2026-08-13')
g['tt10']=g.tt-g.groupby('gname').tt.shift(10)
g['nh5']=g.groupby('gname').nh.transform(lambda s:s.rolling(5,min_periods=1).sum())  # pct sum proxy
g['x21']=g.ret_ew_21d-g.groupby('d').ret_ew_21d.transform('median')
el=g[g.members>=5]
g['hrank']=el.groupby('d').health.rank(ascending=False)
g['hr5']=g.groupby('gname').hrank.shift(5)-g.hrank; g['hr21']=g.groupby('gname').hrank.shift(21)-g.hrank
g['ttpct']=g.groupby('gname').tt.transform(lambda s:s.rank(pct=True))*100
t=g[(g.d==D)&(g.members>=5)].sort_values('tt',ascending=False)
# new highs count over last 5 sessions from stock data
s=c.execute("""select m.broad_industry gname, i.symbol, i.rs_percentile rs, i.trade_date d, (i.high_price>lag(i.high_52w) over (partition by i.symbol order by i.trade_date))::int nh
 from indicators_daily i join stocks_master m using(symbol) where m.market_cap_cr>=1000 and i.trade_date between '2026-07-20' and '2026-08-13'""").df()
s['d']=pd.to_datetime(s.d)
last5=sorted(s.d.unique())[-5:]
nhc=s[s.d.isin(last5)].groupby('gname').apply(lambda x:x[x.nh==1].symbol.nunique())
ld=s[s.d==D].sort_values('rs',ascending=False).groupby('gname').symbol.apply(lambda x:' '.join(x[:3]))
t['nhw']=t.gname.map(nhc).fillna(0).astype(int); t['lead']=t.gname.map(ld)
def st(r):
    if r.b50>=60 and r.x21>0: return 'Favour'
    if r.b50<40 and r.ret_ew_63d<g[g.d==D].ret_ew_63d.median(): return 'Caution'
    return 'Neutral'
t['state']=t.apply(st,axis=1)
cols=['gname','state','members','tt','tt10','ttpct','nhw','x21','rs_momentum','b50','dacc','health','hr5','hr21','lead']
print(t[cols].round(1).to_string(index=False))
