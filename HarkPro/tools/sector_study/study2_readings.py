import duckdb, pandas as pd, numpy as np, sys, warnings; warnings.filterwarnings('ignore')
import os; ROOT=os.path.abspath(os.path.join(os.path.dirname(__file__),'../../..'))
c=duckdb.connect(ROOT+'/Database/marketpulse.duckdb',read_only=True)
p=c.execute("""select i.symbol, i.trade_date d, i.close_price c, i.prev_close pc, i.turnover_cr t, i.delivery_qty*i.close_price/1e7 dv,
 i.delivery_pct dp, i.avg_delivery_pct_20d adp, i.high_52w h52, i.high_price hi, i.trend_template_pass tt,
 m.sector, m.broad_industry, m.industry from indicators_daily i join stocks_master m using(symbol)
 where m.market_cap_cr>=1000 and i.trade_date<='2026-08-13' order by symbol,d""").df()
p['d']=pd.to_datetime(p.d)
g=p.groupby('symbol')
prev=g.c.shift(1).fillna(p.pc); r=p.c/prev-1
bad=(r<=-.35)|(r>=1); p['r']=r.where(~bad)
p['adv']=np.sign(p.r)
p['near']=(p.c>=0.9*p.h52).astype(float).where(p.h52.notna())
ph=g.h52.shift(1); p['nh']=(p.hi>ph).astype(float).where(ph.notna())
p['upt']=p.t*(p.r>0); p['upd']=p.dv*(p.r>0)
p['dpx']=(p.dp-p.adp)
p['tt']=p.tt.astype(float)
dates=sorted(p.d.unique()); di={d:i for i,d in enumerate(dates)}
END=di[pd.Timestamp('2026-08-13')]
res={}
for LV in ['sector','broad_industry','industry']:
    a=p.groupby([LV,'d']).agg(n=('symbol','size'),r=('r','mean'),adv=('adv','mean'),near=('near','mean'),nh=('nh','mean'),
        t=('t','sum'),upt=('upt','sum'),dv=('dv','sum'),upd=('upd','sum'),dpx=('dpx','mean'),tt=('tt','mean')).reset_index().rename(columns={LV:'gname'})
    a=a.sort_values(['gname','d']).reset_index(drop=True); G=a.groupby('gname')
    a['idx']=np.exp(np.log1p(a.r.fillna(0)).groupby(a.gname).cumsum())
    a['fwd']=(G.idx.shift(-21)/a.idx-1)*100
    tot=a.groupby('d').t.transform('sum'); a['sh']=a.t/tot
    roll=lambda col,w,how='mean': G[col].transform(lambda s:getattr(s.rolling(w,min_periods=max(1,w//2)),how)())
    F={}
    a['t63']=roll('t',63); a['dv63']=roll('dv',63); a['sh63']=roll('sh',63)
    for N in (1,5,10,20):
        F[f'A/D {N}d']=roll('adv',N)
        F[f'Turnover x {N}d']=roll('t',N)/a.t63
        F[f'T/O share x {N}d']=roll('sh',N)/a.sh63
        F[f'Up-turnover share {N}d']=roll('upt',N,'sum')/roll('t',N,'sum')
        F[f'Delivery value x {N}d']=roll('dv',N)/a.dv63
        F[f'Up-delivery share {N}d']=roll('upd',N,'sum')/roll('dv',N,'sum')
        F[f'Delivery % vs own avg {N}d']=roll('dpx',N)
        F[f'New 52W highs {N}d']=roll('nh',N,'sum')
        F[f'Return {N}d']=(a.idx/G.idx.shift(N)-1)
        F[f'Near 52W hi chg {N}d']=a.near-G.near.shift(N)
    F['Near 52W high (within 10%)']=a.near
    F['Trend template %']=a.tt
    for k,v in F.items(): a[k]=v
    e=a[(a.n>=3)&(a.d>=pd.Timestamp('2024-10-01'))&(a.d.map(di)+21<=END)].copy()
    e['x']=e.fwd-e.groupby('d').fwd.transform('median')
    rows=[]
    for f in F:
        s=e.dropna(subset=[f,'x']); s=s[np.isfinite(s[f])]
        ic=s.groupby('d').apply(lambda z:z[f].rank().corr(z.x.rank()) if len(z)>8 else np.nan).dropna()
        q=s.groupby('d')[f].transform(lambda z:pd.qcut(z.rank(method='first'),5,labels=False))
        rows.append((f,ic.mean(),ic.mean()/ic.std()*np.sqrt(len(ic)/21),(s.x[q==4]>0).mean()*100,(s.x[q==0]>0).mean()*100,s.x[q==4].median()-s.x[q==0].median()))
    res[LV]=pd.DataFrame(rows,columns=['reading','IC','t','top%','bot%','spread']).set_index('reading')
    a.to_pickle(f'a_{LV}.pkl')
out=pd.concat(res,axis=1).round(3)
pd.set_option('display.width',250)
print(out.to_string())
out.to_csv('study2.csv')
