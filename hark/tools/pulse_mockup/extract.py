"""Build the Tab 1 (Pulse) mockup from the local DuckDB.
Run from the repo root:  python hark/tools/pulse_mockup/extract.py [AS_OF_DATE]
Writes hark/mockups/tab1-pulse.html. Prototype only; the production version is the /api/v2/pulse/* spec in hark/02-tab1-pulse.md.
"""
import duckdb, json, math
import pandas as pd, numpy as np
c=duckdb.connect('Database/marketpulse.duckdb',read_only=True)
import sys as _s
ASOF=_s.argv[1] if len(_s.argv)>1 else '2026-08-13'  # last contiguous session in the committed repo data
b=c.execute(f"""select b.trade_date d, b.stocks, b.advancers adv, b.decliners decl, b.advance_volume_pct upvol,
 b.above_10ema_pct e10,b.above_20ema_pct e20,b.above_50ema_pct e50,b.above_100ema_pct e100,b.above_200ema_pct e200,
 b.new_20d_highs h20, r.new_highs nh, r.new_lows nl, r.stage2_pct st2, r.follow_through_pct ft, r.vix_close vix
 from breadth_daily b left join regime_daily r using(trade_date) where b.trade_date<='{ASOF}' order by 1""").df()
# market turnover/delivery and EW return
m=c.execute(f"""select trade_date d, sum(turnover_cr) tov, sum(delivery_qty*close_price)/1e7 dlv,
 median(case when prev_close>0 then close_price/prev_close-1 end) medret,
 avg(least(greatest(case when prev_close>0 then close_price/prev_close-1 end,-0.2),0.2)) ewret
 from indicators_daily where trade_date<='{ASOF}' group by 1 order by 1""").df()
b=b.merge(m,on='d',how='left')
b['ew']=(1+b['ewret'].fillna(0)).cumprod()*100
b['d']=b['d'].dt.strftime('%Y-%m-%d')
# analogs: similar e50 level & 5d change
b['e50c5']=b['e50']-b['e50'].shift(5)
t=b.iloc[-1]
cand=b.iloc[:-25].copy()
cand['dist']=((cand.e50-t.e50)/10)**2+((cand.e50c5-t.e50c5)/6)**2+((cand.e10-t.e10)/12)**2
cand=cand.dropna(subset=['dist'])
picks=[]
for i,row in cand.sort_values('dist').iterrows():
    if any(abs(i-p)<10 for p in picks): continue
    picks.append(i)
    if len(picks)==8: break
ana=[]
for i in sorted(picks):
    r=b.loc[i]; f10=b.ew.iloc[min(i+10,len(b)-1)]/r.ew-1; f20=b.ew.iloc[min(i+20,len(b)-1)]/r.ew-1
    ana.append(dict(d=r.d,e50=round(r.e50,1),e50c5=round(r.e50c5,1),e10=round(r.e10,1),f10=round(f10*100,1),f20=round(f20*100,1)))
# groups (sector level) last 22 sessions
g=c.execute(f"""select trade_date d, level, group_name n, members, ret_ew_1d r1, ret_ew_5d r5, ret_ew_21d r21, ret_ew_63d r63,
 turnover_cr tov, turnover_share_pct sh, turnover_share_20d_avg sh20, turnover_share_delta shd, delivery_value_cr dlv,
 pct_above_50ema a50, rank, rank_n, rank_chg_5d rc5, rank_chg_20d rc20, rrg_quadrant q, rs_ratio rsr, rs_momentum rsm, deal_net_10s_cr deal
 from group_daily where trade_date<='{ASOF}' and trade_date>= (select min(d) from (select distinct trade_date d from group_daily where trade_date<='{ASOF}' order by d desc limit 63))
 and level in ('Sector','Industry') order by d""").df()
g['d']=g['d'].dt.strftime('%Y-%m-%d')
def clean(x):
    if x is pd.NA or x is pd.NaT or x is None: return None
    if isinstance(x,(bool,np.bool_)): return bool(x)
    if isinstance(x,float) and (math.isnan(x) or math.isinf(x)): return None
    if isinstance(x,(np.floating,)): 
        x=float(x); return None if math.isnan(x) else round(x,3)
    if isinstance(x,(np.integer,)): return int(x)
    if isinstance(x,float): return round(x,3)
    return x
groups={}
for (lvl,n),gg in g.groupby(['level','n']):
    last=gg.iloc[-1]
    if last.d!=ASOF: continue
    hist=gg[['d','sh','r1']].tail(63)
    groups.setdefault(lvl,[]).append({**{k:clean(last[k]) for k in ['n','members','r1','r5','r21','r63','tov','sh','sh20','shd','dlv','a50','rank','rank_n','rc5','rc20','q','rsr','rsm','deal']},
       'shh':[clean(v) for v in hist.sh], 'r1h':[clean(v) for v in hist.r1]})
# movers >=1000cr
s=c.execute(f"""select i.symbol s, sm.security_name nm, sm.sector sec, sm.industry ind, sm.market_cap_cr mc, i.close_price px,
 (i.close_price/i.prev_close-1)*100 ch, i.turnover_cr tov, i.delivery_qty*i.close_price/1e7 dlv, i.delivery_pct dp, i.avg_delivery_pct_20d dp20,
 i.rvol, i.rs_percentile rs, i.adr_20_pct adr, i.away_10ema_pct x10, i.is_fresh_52w_high h52, sm.ipo_age_days ipo, i.band_remarks band,
 i.return_5d_pct r5, i.return_1m_pct r21
 from indicators_daily i join stocks_master sm using(symbol) where i.trade_date='{ASOF}' and i.series='EQ' and sm.market_cap_cr>=1000""").df()
dl=c.execute(f"select distinct symbol from deals where trade_date between date '{ASOF}' - interval 3 day and '{ASOF}'").df().symbol.tolist()
s['deal']=s.s.isin(dl)
stocks=[{k:clean(v) for k,v in r.items()} for r in s.to_dict('records')]
for x in stocks: x['deal']=bool(x['deal']); x['h52']=bool(x['h52']) if x['h52'] is not None else False
series={col:[clean(v) for v in b[col]] for col in b.columns}
import sys; sys.path[:0]=['.','App']
from thematic_engine import CANONICAL_44_INDICES as C44
ix=c.execute(f"select trade_date d,index_name n,close_price px,return_1d_pct r1,return_5d_pct r5,return_20d_pct r21,return_63d_pct r63,distance_ema_50_pct d50,distance_ema_20_pct d20,trend_state tr,new_52w_high h52 from index_daily where trade_date<='{ASOF}' order by d").df()
indices=[]
for n,gg in ix.groupby('n'):
    if n not in C44 or gg.iloc[-1].d.strftime('%Y-%m-%d')!=ASOF: continue
    last=gg.iloc[-1]
    indices.append({'n':n,'cat':C44[n]['category'],**{k:clean(last[k]) for k in ['px','r1','r5','r21','r63','d50','d20','tr','h52']},'pxh':[clean(v) for v in gg.px.tail(30)]})
out=dict(indices=indices,asof=ASOF,series=series,analogs=ana,groups=groups,stocks=stocks,universe_all=int(t.stocks),universe_1000=len(stocks))
import os
HERE=os.path.dirname(os.path.abspath(__file__))
tpl=open(os.path.join(HERE,'template.html'),encoding='utf-8').read()
open(os.path.join(HERE,'..','..','mockups','tab1-pulse.html'),'w',encoding='utf-8').write(tpl.replace('__DATA__',json.dumps(out)))
print(len(b), ana, len(groups.get('Sector',[])), len(groups.get('Industry',[])), len(stocks))
print(b.tail(6)[['d','e10','e20','e50','e200','adv','decl','nh','nl','tov','ew']].to_string())
