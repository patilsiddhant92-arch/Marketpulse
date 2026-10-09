import duckdb, pandas as pd, numpy as np, sys
sys.path.insert(0,__import__('os').path.abspath(__import__('os').path.join(__import__('os').path.dirname(__file__),'../../..')))
from Scripts.derived.group_daily import add_health_columns
c=duckdb.connect(sys.path[0]+'/Database/marketpulse.duckdb',read_only=True)
LV=sys.argv[1] if len(sys.argv)>1 else 'Industry'
g=c.execute(f"""select trade_date d, group_name gname, members, ret_ew_1d, ret_ew_21d, ret_ew_63d, pct_above_50ema b50, pct_above_200ema b200,
 pct_trend_template tt, pct_new_highs_52w nh, turnover_share_delta flow, turnover_share_5d_chg_5d flowchg, deliv_acc_10d_pct dacc, top1_turnover_share_pct top1
 from group_daily where level='{LV}' and floor='1000cr' and trade_date<='2026-08-13' order by gname,d""").df()
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
for h in (10,21):
    e[f'xf{h}']=e[f'fwd{h}']-e.groupby('d')[f'fwd{h}'].transform('median')
feats=['health','score','ret_ew_21d','ret_ew_63d','b50','tt','nh','flow','flowchg','dacc','rs_ratio','rs_momentum','health_chg10']
out=[]
for f in feats:
    s=e.dropna(subset=[f,'xf21'])
    ic=s.groupby('d').apply(lambda x:x[f].rank().corr(x.xf21.rank()) if len(x)>10 else np.nan).dropna()
    s=s.assign(q=s.groupby('d')[f].transform(lambda x:pd.qcut(x.rank(method='first'),5,labels=False)))
    top=s[s.q==4].xf21; bot=s[s.q==0].xf21
    out.append((f,round(ic.mean(),3),round(ic.mean()/ic.std()*np.sqrt(len(ic)/21),2),round(top.mean(),2),round(bot.mean(),2),round((top>0).mean()*100),round((bot>0).mean()*100),len(ic)))
print(LV,'dates',e.d.nunique(),'groups/day',round(e.groupby('d').size().mean()))
print(pd.DataFrame(out,columns=['feat','IC21','t~(nonoverlap)','Q5 xs21','Q1 xs21','Q5 %>med','Q1 %>med','n_days']).to_string(index=False))
print(e.groupby('rrg_quadrant').xf21.agg(['mean','median','count',lambda x:(x>0).mean()]).round(2))
print(e.groupby('abs_trend').xf21.agg(['mean','median','count',lambda x:(x>0).mean()]).round(2))
# health zones
e['zone']=pd.cut(e.health,[-1,45,65,101],labels=['Weak','Mixed','Healthy'])
print(e.groupby('zone').xf21.agg(['mean','median','count',lambda x:(x>0).mean()]).round(2))
# persistence of top-10 health rank
e['top10']=e.health_rank<=10
print('top10 health xs21', e[e.top10].xf21.mean().round(2), (e[e.top10].xf21>0).mean().round(2))
e.to_pickle(f"e_{LV}.pkl")
