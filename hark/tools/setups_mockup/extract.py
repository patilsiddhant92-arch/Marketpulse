"""Build the Tab 2 (Setups) mockup from the local DuckDB.
Run from the repo root:  python hark/tools/setups_mockup/extract.py [AS_OF_DATE]
Writes hark/mockups/tab2-setups.html. Prototype only; the production spec is hark/06-tab2-setups.md.
Reuses the app's own logic: setup_daily (Darvas Squeeze, Darvas 10 EMA, VCP) and App.services.momentum._scan.
"""
import sys, json, math, datetime, os
import duckdb, numpy as np, pandas as pd
sys.path[:0] = ['.', 'Scripts']
from App.services import momentum
from Scripts.darvas_squeeze import calculate_darvas_box
from Scripts.desk_contract import DARVAS

ASOF = sys.argv[1] if len(sys.argv) > 1 else '2026-08-13'
AD = pd.Timestamp(ASOF)
c = duckdb.connect('Database/marketpulse.duckdb', read_only=True)
BARS = 70  # chart bars per stock


def px4(x):
    v = cl(x, 2)
    if v is None: return None
    return round(v, 1) if abs(v) >= 100 else v


def cl(x, nd=2):
    if x is None or x is pd.NA or x is pd.NaT: return None
    if isinstance(x, (bool, np.bool_)): return bool(x)
    if isinstance(x, (np.integer,)): return int(x)
    try:
        f = float(x)
    except Exception:
        return x
    if math.isnan(f) or math.isinf(f): return None
    return round(f, nd)


sessions = [d for (d,) in c.execute(f"select distinct trade_date from indicators_daily where trade_date<='{ASOF}' order by 1").fetchall()]
sessions = [pd.Timestamp(d) for d in sessions]
PREV = sessions[-2]

# ---------------- setups (app queues) ----------------
sd = c.execute(f"select * from setup_daily where trade_date in ('{ASOF}','{PREV.date()}')").df()
sd['trade_date'] = pd.to_datetime(sd.trade_date)
today = sd[sd.trade_date == AD].copy()
prev = sd[sd.trade_date == PREV].copy()
today['f'] = today.features.apply(lambda s: json.loads(s) if isinstance(s, str) else {})
mom = momentum._scan(c, AD.date(), momentum.Params())
mom_prev = {r['symbol'] for r in momentum._scan(c, PREV.date(), momentum.Params())}
momd = {r['symbol']: r for r in mom}

syms = sorted(set(today.symbol) | set(momd))
SQL_SYMS = ",".join("'" + s.replace("'", "''") + "'" for s in syms)
start = sessions[-260]
ind = c.execute(f"""select i.symbol, i.trade_date d, i.open_price o, i.high_price h, i.low_price l, i.close_price cl, i.volume v,
  i.ema_10 e10, i.ema_20 e20, i.ema_50 e50, i.ema_200 e200, i.rsi_14 rsi, i.bullish_rsi_divergence bdiv, i.bearish_rsi_divergence sdiv,
  i.delivery_pct dp, i.avg_delivery_pct_20d dp20, i.turnover_cr tov, i.away_52w_high_pct a52, i.away_10ema_pct a10,
  i.rs_vs_midsml400_21d rs21, i.rs_vs_midsml400_63d rs63, i.rs_percentile rsp, i.range_10d_pct r10, i.atr_pct atr, i.atr_pct_avg_50d atr50,
  i.volume_dryup_pct vdu, i.adr_20_pct adr, i.high_52w h52, i.rvol
  from indicators_daily i where i.symbol in ({SQL_SYMS}) and i.trade_date between '{start.date()}' and '{ASOF}' and i.series='EQ'
  order by symbol, d""").df()
ind['d'] = pd.to_datetime(ind.d)
master = c.execute("select symbol, security_name, sector, industry, market_cap_cr, band, band_remarks from stocks_master").df().drop_duplicates('symbol').set_index('symbol')
ref = c.execute(f"""select symbol, price_band, band_remarks from security_reference_daily where symbol in ({SQL_SYMS})
  and effective_date=(select max(effective_date) from security_reference_daily where effective_date<='{ASOF}')""").df().set_index('symbol')
deals = c.execute(f"""select symbol, trade_date d, side, sum(deal_value_cr) val, max(clientele) who from deals
  where symbol in ({SQL_SYMS}) and trade_date between '{start.date()}' and '{ASOF}' group by 1,2,3""").df()
deals['d'] = pd.to_datetime(deals.d)

# ---------------- group state (Industry, all stocks) ----------------
gd = c.execute(f"""select trade_date d, group_name n, members, ret_ew_5d r5, ret_ew_21d r21, ret_ew_63d r63,
  pct_above_50ema a50, turnover_share_pct sh, turnover_share_5d_avg sh5, turnover_share_20d_avg sh20, ew_index ew, ew_index_ema50 ew50
  from group_daily where level='Industry' and floor='all' and trade_date<='{ASOF}' order by d""").df()
gd['d'] = pd.to_datetime(gd.d)
# group RS = group's equal-weight return minus the median industry's (excess_midsml_* is mostly empty locally)
gd['x21'] = gd.r21 - gd.groupby('d').r21.transform('median')
gd['x63'] = gd.r63 - gd.groupby('d').r63.transform('median')


def gstate(r):
    if pd.isna(r.x21) or pd.isna(r.a50): return ('Neutral', 'Not enough history.')
    if r.sh20 and r.sh5 and r.sh5 < 0.85 * r.sh20 and (r.r5 or 0) < 0:
        return ('Caution', f'Money leaving: turnover share {r.sh5:.2f}% vs {r.sh20:.2f}% 20D avg, group {r.r5:+.1f}% in 5D.')
    if r.x21 > 0 and r.a50 >= 60 and r.ew > r.ew50:
        return ('Favour', f'Trending: {r.a50:.0f}% of stocks above 50 EMA, {r.x21:+.1f} pts vs median industry in 21D.')
    if (r.x63 or 0) < 0 and r.a50 < 40:
        return ('Caution', f'Weak: {r.a50:.0f}% above 50 EMA, {r.x63:+.1f} pts vs median industry in 63D.')
    return ('Neutral', f'{r.a50:.0f}% above 50 EMA, {r.x21:+.1f} pts vs median industry in 21D.')


st = gd.apply(gstate, axis=1)
gd['state'] = [s[0] for s in st]
gd['why'] = [s[1] for s in st]
gd['rank'] = gd.groupby('d').x63.rank(ascending=False)
gtoday = gd[gd.d == AD].set_index('n')
_gw = gd[gd.d >= sessions[-45]]
gsh = {1: _gw.pivot(index='d', columns='n', values='sh'), 5: _gw.pivot(index='d', columns='n', values='sh5'), 20: _gw.pivot(index='d', columns='n', values='sh20')}

def gshare_chg(n, k):
    t = gsh[k]
    if n not in t.columns: return None
    s = t[n].dropna()
    if len(s) <= k: return None
    a, b = s.iloc[-1], s.iloc[-1 - k]
    return cl((a / b - 1) * 100, 1) if b else None

gr5 = gd[gd.d == sessions[-6]].set_index('n')['rank']

# ---------------- base rates: new setups by queue x group state, fwd 20D ----------------
hist = c.execute(f"""select s.queue, s.symbol, s.trade_date d, s.close_price c0, m.industry n
  from setup_daily s join stocks_master m using(symbol) where s.status='new' and s.trade_date<='{sessions[-21].date()}'""").df()
hist['d'] = pd.to_datetime(hist.d)
px = c.execute(f"select symbol, trade_date d, close_price c from indicators_daily where series='EQ' and trade_date<='{ASOF}'").df()
px['d'] = pd.to_datetime(px.d)
sidx = {d: i for i, d in enumerate(sessions)}
px['i'] = px.d.map(sidx)
pxi = px.set_index(['symbol', 'i']).c
hist['i'] = hist.d.map(sidx)
hist['c20'] = [pxi.get((s, i + 20)) for s, i in zip(hist.symbol, hist.i)]
hist['f20'] = hist.c20 / hist.c0 - 1
hist = hist.merge(gd[['d', 'n', 'state']], on=['d', 'n'], how='left').dropna(subset=['f20'])
base = {}
for (q, s), g in hist.groupby(['queue', 'state']):
    base[f'{q}|{s}'] = dict(n=int(len(g)), win=cl((g.f20 > 0).mean() * 100, 0), med=cl(g.f20.median() * 100, 1))
for q, g in hist.groupby('queue'):
    base[f'{q}|All'] = dict(n=int(len(g)), win=cl((g.f20 > 0).mean() * 100, 0), med=cl(g.f20.median() * 100, 1))

# ---------------- scan count history ----------------
cnt = c.execute(f"""select trade_date d, queue, count(*) n from setup_daily where trade_date<='{ASOF}' group by 1,2 order by 1""").df()
cnt['d'] = pd.to_datetime(cnt.d).dt.strftime('%Y-%m-%d')
counts = {q: g[['d', 'n']].values.tolist() for q, g in cnt.groupby('queue')}

# ---------------- per-stock rows ----------------
QMAP = {'darvas_squeeze': 'SQZ', 'darvas_10ema': '10E', 'vcp': 'VCP'}
rows, charts = [], {}
by_sym = {s: g.reset_index(drop=True) for s, g in ind.groupby('symbol')}
tq = {s: g for s, g in today.groupby('symbol')}
for s in syms:
    g = by_sym.get(s)
    if g is None or g.d.iloc[-1] != AD or len(g) < 30: continue
    L = g.iloc[-1]
    tags, trig, stop, status, age, extra = [], None, None, 'active', None, {}
    for _, r in (tq[s].iterrows() if s in tq else []):
        t = QMAP[r.queue]
        f = r.f
        if t == '10E':
            flav = f.get('flavor')
            case = 'Catch-up' if flav == 'Catch-up' else 'Retrace'
            tier = 1 if L.l >= L.e10 else 2
            t = f'10E {case} T{tier}'
        if t == 'SQZ': extra['sqz'] = cl(f.get('squeeze_pct'), 1)
        if t == 'VCP': extra['vcp'] = f.get('footprint')
        tags.append(t)
        trig = trig or cl(r.trigger_price); stop = stop or cl(r.stop_price)
        status = r.status if status == 'active' else status
        age = max(age or 0, int(r.setup_age_sessions or 0))
    if s in momd:
        tags.append('MOM ' + momd[s]['bucket'].replace('_', '–'))
        if s not in mom_prev and not trig: status = 'new'
    if not tags: continue
    m = master.loc[s] if s in master.index else None
    n = m.industry if m is not None else None
    gt = gtoday.loc[n] if (n is not None and n in gtoday.index) else None
    # delivery streak
    dd = g[['dp', 'dp20']].dropna()
    streak = 0
    for a, b in zip(dd.dp[::-1], dd.dp20[::-1]):
        if a > b: streak += 1
        else: break
    t63 = g.tov.tail(63).mean()
    risk = cl((trig - stop) / trig * 100, 1) if trig and stop else None
    room = None
    if trig and L.h52:
        room = 'Blue sky' if trig >= L.h52 * 0.995 else cl((L.h52 / trig - 1) * 100, 1)
    # stock character: box breakouts in last 126 sessions
    top, bot = calculate_darvas_box(g.h.values, g.l.values, boxp=5)
    held = failed = 0
    cvals = g.cl.values
    for i in range(max(1, len(g) - 126), len(g) - 5):
        if np.isfinite(top[i - 1]) and cvals[i] > top[i - 1] >= cvals[i - 1]:
            if np.nanmax(cvals[i + 1:i + 11]) >= cvals[i] * 1.05: held += 1
            elif np.nanmin(cvals[i + 1:i + 6]) < top[i - 1]: failed += 1
    # weekly
    w = g.set_index('d').cl.resample('W-FRI').last().dropna()
    wk_above = bool(len(w) >= 10 and w.iloc[-1] > w.tail(10).mean())
    wk_tight = bool(len(w) >= 3 and (w.tail(3).max() / w.tail(3).min() - 1) * 100 <= 2.0)
    chips = []
    rr = ref.loc[s] if s in ref.index else None
    br = str(rr.band_remarks) if rr is not None and rr.band_remarks is not None else ''
    if 'GSM' in br or 'ASM' in br: chips.append(['risk', br.strip()])
    try:
        if rr is not None and float(rr.price_band) == 10: chips.append(['band', '10% band'])
    except Exception:
        pass
    dl = deals[(deals.symbol == s) & (deals.d >= sessions[-10])]
    if len(dl):
        net = dl.apply(lambda x: x.val if str(x.side).upper().startswith('B') else -x.val, axis=1).sum()
        chips.append(['deal', f'Deal {net:+.0f} Cr'])
    if L.a52 is not None and L.a52 >= -0.5: chips.append(['hi', '52W high'])
    gr = gtoday.loc[n] if gt is not None else None
    rows.append(dict(
        s=s, name=m.security_name if m is not None else s, sec=m.sector if m is not None else None, ind=n,
        mcap=cl(m.market_cap_cr, 0) if m is not None else None, tags=tags, status=status, age=age,
        close=cl(L.cl), chg=cl((L.cl / g.cl.iloc[-2] - 1) * 100, 2), trig=trig, stop=stop, risk=risk,
        riskadr=cl(risk / L.adr, 2) if risk and L.adr else None, adr=cl(L.adr, 1),
        a52=cl(L.a52, 1), a10=cl(L.a10, 1), a50=cl((L.cl / L.e50 - 1) * 100, 1) if L.e50 else None,
        rs21=cl(L.rs21, 1), rs63=cl(L.rs63, 1), rsp=cl(L.rsp, 0),
        rsp5=cl(L.rsp - g.rsp.iloc[-6], 0) if len(g) > 6 and pd.notna(g.rsp.iloc[-6]) else None,
        r10=cl(L.r10, 1), atrx=cl(L.atr / L.atr50, 2) if L.atr50 else None, vdu=cl(L.vdu, 0), **extra,
        dp=cl(L.dp, 0), dp20=cl(L.dp20, 0), dstreak=streak, dp5=[cl(x, 0) for x in g.dp.tail(5)],
        t1=cl(L.tov / t63, 2) if t63 else None, t5=cl(g.tov.tail(5).mean() / t63, 2) if t63 else None,
        t21=cl(g.tov.tail(21).mean() / t63, 2) if t63 else None, tov=cl(L.tov, 1),
        gstate=gt.state if gt is not None else 'Neutral', gwhy=gt.why if gt is not None else 'Group not mapped.',
        gsh1=gshare_chg(n, 1), gsh5=gshare_chg(n, 5), gsh21=gshare_chg(n, 20),
        grank=cl(gt['rank'], 0) if gt is not None else None, granks=len(gtoday),
        grankd=cl(gr5.get(n) - gt['rank'], 0) if gt is not None and n in gr5.index else None,
        room=room, held=held, failed=failed, wk_above=wk_above, wk_tight=wk_tight, chips=chips,
        results=None,  # security_events is empty locally: results-date highlight needs ingestion
    ))
    h = g.tail(BARS)
    ts = top[-BARS:]; bs = bot[-BARS:]
    dset = set(deals[deals.symbol == s].d)
    charts[s] = dict(
        d=[x.strftime('%m-%d') for x in h.d], o=[px4(x) for x in h.o], h=[px4(x) for x in h.h], l=[px4(x) for x in h.l], c=[px4(x) for x in h.cl],
        v=[int(x) if pd.notna(x) else 0 for x in h.v], e10=[px4(x) for x in h.e10], e20=[px4(x) for x in h.e20],
        top=[px4(x) for x in ts], bot=[px4(x) for x in bs], rsi=[cl(x, 0) for x in h.rsi],
        bd=[i for i, x in enumerate(h.bdiv) if pd.notna(x) and bool(x)], sd=[i for i, x in enumerate(h.sdiv) if pd.notna(x) and bool(x)],
        deal=[i for i, x in enumerate(h.d) if x in dset])

# peers: same industry, >= 1000 Cr, top RS
peer_df = c.execute(f"""select i.symbol s, m.industry n, i.rs_percentile rsp, i.away_52w_high_pct a52, i.away_10ema_pct a10
  from indicators_daily i join stocks_master m using(symbol) where i.trade_date='{ASOF}' and m.market_cap_cr>=1000 and i.series='EQ'""").df()
inrow = {r['s']: r['tags'] for r in rows}
peers = {}
for n, g in peer_df.groupby('n'):
    g = g.sort_values('rsp', ascending=False).head(6)
    peers[n] = [dict(s=r.s, rsp=cl(r.rsp, 0), a52=cl(r.a52, 1), a10=cl(r.a10, 1), tags=inrow.get(r.s, [])) for r in g.itertuples()]

# ---------------- near-miss (Squeeze) and why dropped ----------------
pool = c.execute(f"""select i.symbol from indicators_daily i join stocks_master m using(symbol)
  where i.trade_date='{ASOF}' and i.series='EQ' and m.market_cap_cr>=1000 and (i.ema_200 is null or i.close_price>i.ema_200)
  and i.turnover_cr>=3""").df().symbol.tolist()
P = ",".join("'" + s.replace("'", "''") + "'" for s in pool)
pi = c.execute(f"""select symbol, trade_date d, high_price h, low_price l, close_price cl, ema_10 e10, ema_20 e20, rvol
  from indicators_daily where symbol in ({P}) and series='EQ' and trade_date between '{sessions[-80].date()}' and '{ASOF}' order by 1,2""").df()
sq_today = set(today[today.queue == 'darvas_squeeze'].symbol)
near = []
for s, g in pi.groupby('symbol'):
    if s in sq_today or len(g) < 30 or pd.Timestamp(g.d.iloc[-1]) != AD: continue
    top, _ = calculate_darvas_box(g.h.values, g.l.values, boxp=5)
    L = g.iloc[-1]; t = top[-1]
    if not (np.isfinite(t) and t > L.e10 and L.e10 * 0.998 <= L.cl <= t * 1.002): continue
    sq = (t - L.e10) / t * 100; rng = (L.h - L.l) / L.cl * 100; dt = (t - L.cl) / t * 100
    fails = []
    if sq > DARVAS['max_squeeze_pct']: fails.append(f'Squeeze {sq:.1f}% (needs ≤ 5%)')
    if dt > DARVAS['max_squeeze_pct']: fails.append(f'{dt:.1f}% below box top (needs ≤ 5%)')
    if rng > DARVAS['max_range_pct']: fails.append(f'Day range {rng:.1f}% (needs ≤ 4%)')
    if pd.notna(L.rvol) and L.rvol > DARVAS['max_rvol']: fails.append(f'RVOL {L.rvol:.2f} (needs ≤ 1.0)')
    if L.e10 <= g.e10.iloc[-2]: fails.append('10 EMA not rising')
    if pd.notna(L.e20) and L.e10 < L.e20 * DARVAS['ema_trend_tol']: fails.append('10 EMA below 20 EMA')
    if len(fails) == 1:
        m = master.loc[s] if s in master.index else None
        near.append(dict(s=s, ind=m.industry if m is not None else None, why=fails[0], sq=cl(sq, 1), close=cl(L.cl), top=cl(t)))
near.sort(key=lambda r: r['sq'])

dropped = []
qnames = {'darvas_squeeze': 'Darvas Squeeze', 'darvas_10ema': 'Darvas 10 EMA', 'vcp': 'VCP'}
last = c.execute(f"select symbol, close_price cl, low_price l, ema_10 e10 from indicators_daily where trade_date='{ASOF}' and series='EQ'").df().drop_duplicates('symbol').set_index('symbol')
for q in qnames:
    gone = set(prev[prev.queue == q].symbol) - set(today[today.queue == q].symbol)
    pf = prev[prev.queue == q].set_index('symbol')
    for s in sorted(gone):
        L = last.loc[s] if s in last.index else None
        p = pf.loc[s]
        if L is None: why = 'No bar today'
        elif s not in set(pool): why = 'Left the pool (turnover, market cap or below 200 EMA)'
        elif p.trigger_price and L.cl > p.trigger_price: why = f'Broke out: closed {L.cl:.1f} above trigger {p.trigger_price:.1f}'
        elif L.cl < L.e10: why = f'Closed below 10 EMA ({(L.cl / L.e10 - 1) * 100:+.1f}%)'
        elif p.stop_price and L.l < p.stop_price: why = 'Hit the stop'
        else: why = 'A rule no longer holds (volume or range)'
        dropped.append(dict(q=qnames[q], s=s, why=why))
for s in sorted(mom_prev - set(momd)):
    dropped.append(dict(q='Momentum', s=s, why='Failed a current-day momentum rule'))

data = dict(asof=ASOF, prev=str(PREV.date()), rows=rows, charts=charts, peers=peers, base=base, counts=counts,
            near=near[:40], dropped=dropped, mom_n=len(momd), nfavour=int((gtoday.state == 'Favour').sum()),
            ncaution=int((gtoday.state == 'Caution').sum()), ngroups=len(gtoday))
here = os.path.dirname(__file__)
tpl = open(os.path.join(here, 'template.html')).read()
out = tpl.replace('/*DATA*/null', json.dumps(data, separators=(',', ':'), default=str))
open('hark/mockups/tab2-setups.html', 'w').write(out)
print('rows', len(rows), 'near', len(near), 'dropped', len(dropped), 'bytes', len(out))
