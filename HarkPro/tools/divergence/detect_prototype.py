import duckdb, pandas as pd, numpy as np, sys
DB='/workspace/projects/a67c59ce-d49a-4e9a-a1a1-69be71f0f93a/work/Marketpulse/Database/marketpulse.duckdb'
K=3; MINGAP=5; MAXGAP=60; PTOL=0.5; RTOL=2.0
def load(c, sym=None):
    q="""select symbol,trade_date d,adj_open_price o,adj_high_price h,adj_low_price l,adj_close_price c,adj_volume v
         from prices_daily where series='EQ' and trade_date<='2026-08-13' """+(f"and symbol='{sym}'" if sym else "")+" order by symbol,trade_date"
    return c.sql(q).df()
def rsi(c,n=14):
    d=c.diff(); up=d.clip(lower=0).ewm(alpha=1/n,adjust=False).mean(); dn=(-d.clip(upper=0)).ewm(alpha=1/n,adjust=False).mean()
    return 100-100/(1+up/dn)
def atr(g,n=14):
    tr=pd.concat([g.h-g.l,(g.h-g.c.shift()).abs(),(g.l-g.c.shift()).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/n,adjust=False).mean()
def classify(dp,dr,side):
    # dp: price diff (new-old)/atr, dr: rsi diff
    pe=abs(dp)<=PTOL; re=abs(dr)<=RTOL
    if side=='bull':
        if dp<-PTOL and dr>RTOL: return 'Strong'
        if pe and dr>RTOL: return 'Medium'
        if dp<-PTOL and re: return 'Weak'
        if dp>PTOL and dr<-RTOL: return 'Hidden'
    else:
        if dp>PTOL and dr<-RTOL: return 'Strong'
        if pe and dr<-RTOL: return 'Medium'
        if dp>PTOL and re: return 'Weak'
        if dp<-PTOL and dr>RTOL: return 'Hidden'
    return None
def detect(g):
    g=g.reset_index(drop=True); g['rsi']=rsi(g.c); g['atr']=atr(g); g['ema50']=g.c.ewm(span=50,adjust=False).mean()
    out=[]
    for side,col,cmp in [('bull','l',np.less_equal),('bear','h',np.greater_equal)]:
        s=g[col].values; piv=[]
        for i in range(K,len(g)-K):
            w=s[i-K:i+K+1]
            if (side=='bull' and s[i]==w.min()) or (side=='bear' and s[i]==w.max()): piv.append(i)
        for a,b in zip(piv,piv[1:]):
            if not MINGAP<=b-a<=MAXGAP: continue
            r1,r2=g.rsi[a],g.rsi[b]
            mid=g.rsi[a:b+1]
            dp=(s[b]-s[a])/g.atr[b]; t=classify(dp,r2-r1,side)
            if not t: continue
            if t!='Hidden':
                if side=='bull' and (min(r1,r2)>=40 or mid.max()>60): continue
                if side=='bear' and (max(r1,r2)<=60 or mid.min()<40): continue
            else:
                trend=g.c[b]>g.ema50[b]
                if side=='bull' and not (trend and r2<50): continue
                if side=='bear' and not ((not trend) and r2>50): continue
            out.append(dict(symbol=g.symbol[0],side=side,type=t,p1=a,p2=b,d1=g.d[a],d2=g.d[b],conf=b+K,
                                  trig=(g.h[a:b+1].max() if side=='bull' else g.l[a:b+1].min())))
    return g,out
if __name__=='__main__':
    c=duckdb.connect(DB,read_only=True)
    big=set(c.sql("select symbol from security_reference_daily where effective_date=(select max(effective_date) from security_reference_daily) and market_cap_cr>=1000").df().symbol)
    df=load(c); res=[]
    for sym,g in df.groupby('symbol'):
        if sym not in big or len(g)<200: continue
        g,out=detect(g)
        for o in out:
            if o['side']!='bull' or o['type']!='Strong' or o['d2']<pd.Timestamp('2025-10-01'): continue
            ci=o['conf']; 
            if ci+30>=len(g): continue
            fut=g.c[ci:ci+30]; tr=np.where(g.c[ci:ci+15].values>o['trig'])[0]
            o['trig_day']=int(tr[0]) if len(tr) else None
            o['ret30']=g.c[ci+29]/g.c[ci]-1; o['r1']=g.rsi[o['p1']]; o['r2']=g.rsi[o['p2']]
            res.append(o)
    r=pd.DataFrame(res); print(len(r)); r=r[r.trig_day.notna()].sort_values('ret30',ascending=False)
    print(r[['symbol','d1','d2','r1','r2','trig_day','ret30']].head(25).to_string())
