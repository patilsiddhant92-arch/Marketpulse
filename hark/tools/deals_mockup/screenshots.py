"""Phone-size PNG screenshots of the Deals mockup, drawn with Pillow from the data embedded in
hark/mockups/tab-deals.html (no browser needed). Rebuild the mockup first, then:
    python hark/tools/deals_mockup/screenshots.py
Writes hark/mockups/screenshots/deals/*.png."""
import os
ROOT=os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),'../../..'))
OUT=os.path.join(ROOT,'hark/mockups/screenshots/deals')
import json,re
from PIL import Image,ImageDraw,ImageFont
H=open(os.path.join(ROOT,'hark/mockups/tab-deals.html'),encoding='utf-8').read()
D=json.loads(re.search(r'const D=(\{.*?\});\nconst \$',H,re.S).group(1))
S=2.5;W=int(412*S)
FR='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf';FB='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf';FM='/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'
if not os.path.exists(FR):  # Windows fallback (Segoe UI has the rupee sign)
    FR,FB,FM=r'C:\Windows\Fonts\segoeui.ttf',r'C:\Windows\Fonts\segoeuib.ttf',r'C:\Windows\Fonts\consola.ttf'
f=lambda s,b=False,m=False:ImageFont.truetype(FM if m else (FB if b else FR),int(s*S))
BG,PN,P2,LN,TX,MU,DM=(11,13,18),(18,21,29),(23,27,37),(35,40,56),(231,234,240),(138,147,166),(93,101,120)
VC={'confirm':(34,197,94),'watch':(245,158,11),'place':(96,165,250),'absorbed':(45,212,191),'supply':(251,146,60),'churn':(100,116,139),'ignore':(71,85,105),'avoid':(244,63,94),'none':(100,116,139)}
UP,DN=(34,197,94),(239,68,68)
TC={'B':(45,212,191),'P':(96,165,250),'S':(251,146,60),'C':(100,116,139),'T':(148,163,184)}
TAG={'fresh':'B','accumulate':'B','placement':'P','distribute':'S','churn':'C','transfer_interse':'T'}
EV={'fresh':'Net buy (new)','accumulate':'Net buy (repeat)','placement':'Placement','distribute':'Net sell','churn':'Churn','transfer_interse':'Transfer'}
ORDER=['confirm','place','absorbed','watch','supply','none','churn','avoid','ignore']
def f1(v): return '–' if v is None else f"{abs(v):,.1f}".rstrip('0').rstrip('.') if abs(v)<1000 else f"{abs(v):,.0f}"
def sg(v): return '–' if v is None else f"{'+' if v>0 else ''}{v:.1f}%"
class C:
  def __init__(s,h): s.im=Image.new('RGB',(W,int(h*S)),BG);s.d=ImageDraw.Draw(s.im);s.y=0
  def t(s,x,y,txt,sz=12,c=TX,b=False,m=False,anchor='la'): s.d.text((x*S,y*S),txt,font=f(sz,b,m),fill=c,anchor=anchor)
  def r(s,x,y,w,h,c,rad=10,o=None): s.d.rounded_rectangle([x*S,y*S,(x+w)*S,(y+h)*S],radius=rad*S,fill=c,outline=o,width=int(S))
  def dot(s,x,y,c,r=4): s.d.ellipse([(x-r)*S,(y-r)*S,(x+r)*S,(y+r)*S],fill=c)
  def wrap(s,x,y,txt,w,sz=12,c=TX,lh=1.4):
    words=txt.split();line='';fnt=f(sz)
    for wd in words:
      t=(line+' '+wd).strip()
      if s.d.textlength(t,font=fnt)>w*S and line: s.t(x,y,line,sz,c);y+=sz*lh;line=wd
      else: line=t
    if line: s.t(x,y,line,sz,c);y+=sz*lh
    return y
  def save(s,p,h): s.im.crop((0,0,W,int(h*S))).save(p)
def header(c,active):
  c.t(14,14,'Deals',20,b=True);c.t(80,20,'as of '+D['asof'],10.5,MU)
  x=14;c.r(10,46,392,30,PN,9,LN)
  for k in ['Today','Watch','History','Houses','Groups','Telegram']:
    w=c.d.textlength(k,font=f(11))/S+12
    if k==active: c.r(x-2,49,w,24,P2,7,LN)
    c.t(x+4,55,k,11,TX if k==active else MU);x+=w+1
  return 90
def tvb(c,y,n):
  k=f'Copy {n} to TradingView';w=c.d.textlength(k,font=f(10.5))/S+18;c.r(402-w,y-3,w,22,P2,7,LN);c.t(402-w/2,y+1,k,10.5,TX,anchor='ma')
def verdict(c,x,y,o,sz=11.5,maxw=None):
  c.dot(x+4,y+sz*0.55,VC[o['cls']]);t=o['title']
  if maxw:
    while c.d.textlength(t,font=f(sz,True))/S>maxw and len(t)>4: t=t[:-2]
    if t!=o['title']: t=t.rstrip()+'…'
  c.t(x+13,y,t,sz,b=True)

def chips(c,x,y,o):
  col={'Placement':((19,40,74),(147,197,253)),'Holding':((18,54,31),(134,239,172)),'Good':((18,54,31),(134,239,172)),'Absorbed':((15,58,54),(94,234,212)),'Extended':((58,42,16),(252,211,77)),'Churn':((59,21,32),(253,164,175)),'Poor':((59,21,32),(253,164,175))}
  for ch in o['chips']:
    bg,fg=next((v for k,v in col.items() if ch.startswith(k)),((35,42,59),(201,210,230)))
    w=c.d.textlength(ch,font=f(9.5))/S+10;c.r(x,y,w,16,bg,4);c.t(x+5,y+2.5,ch,9.5,fg);x+=w+4
# ---------- 1 Today
def today():
  c=C(2200);y=header(c,'Today')
  T=sorted(D['today'],key=lambda o:(ORDER.index(o['cls']),-abs(o['net'])))
  NZ=['churn','ignore','none'];cnt=lambda k:sum(o['cls']==k for o in T)
  boxes=[(cnt('watch')+cnt('confirm'),'Confirms setup',VC['confirm']),(cnt('place'),'Placements',VC['place']),(cnt('supply'),'Supply',VC['supply']),(cnt('avoid'),'Avoid',VC['avoid']),(cnt('churn')+cnt('ignore')+cnt('none'),'Noise',MU)]
  bw=(392-16)/5
  for i,(n,l,col) in enumerate(boxes):
    x=10+i*(bw+4);c.r(x,y,bw,54,PN,10,LN);c.t(x+8,y+6,str(n),20,col,True);c.t(x+8,y+35,l,9,MU)
  y+=66;top=y
  c.t(22,y+12,'Every deal stock today',13,b=True);c.t(22,y+30,f"Sorted by what matters · {D['mkt']['above50']}% of stocks above 50 EMA",10,MU);y+=52
  for o in [o for o in T if o['cls'] not in NZ]:
    v=o['bv'] if (o['ev']=='placement' or abs(o['net'])<0.5) else o['net']
    c.t(22,y,o['sym'],12.5,b=True);c.t(398,y,('+' if v>=0 else '−')+'₹'+f1(v)+' Cr',12,UP if v>=0 else DN,anchor='ra')
    verdict(c,22,y+19,o,11)
    b=o['buy'][0]['n'][:26]+' · '+o['buy'][0]['cls'] if o['buy'] else '–'
    c.t(22,y+38,f"{EV[o['ev']]} @ ₹{f1(o['lvl'])}  ·  {b}",10,MU)
    yy=y+56
    if o['chips']: chips(c,22,yy,o);yy+=22
    c.d.line([(22*S,(yy+2)*S),(398*S,(yy+2)*S)],fill=(26,31,44),width=2);y=yy+10
  n=sum(o['cls'] in NZ for o in T);c.r(22,y,240,26,P2,8,LN);c.t(32,y+6,f'Show {n} noise rows (churn, no edge)',10.5,MU);y+=38
  c.d.rounded_rectangle([10*S,top*S,402*S,y*S],radius=12*S,outline=LN,width=int(S))
  c.save(os.path.join(OUT,'deals_shot1_today.png'),y+12)
# ---------- 2 Deal watch
def watch():
  c=C(2600);y=header(c,'Watch')
  Wl=sorted([o for o in D['watch'] if o['ev'] not in ('churn','transfer_interse')],key=lambda o:(ORDER.index(o['cls']),o['ago']))
  c.t(14,y,'Deal watch · last 10 deal sessions',13,b=True);y=c.wrap(14,y+20,'The deal price is a level. Day 3 decides: holding it upgrades the verdict, losing it downgrades.',380,10.5,MU)+6
  x=14
  for k in ['All','Best','Holding','Lost','Reclaimed']:
    w=c.d.textlength(k,font=f(11))/S+16;c.r(x,y,w,24,P2 if k=='All' else PN,7,LN);c.t(x+8,y+5,k,11,TX if k=='All' else MU);x+=w+5
  y+=36
  stc={'holding':((18,54,31),(134,239,172)),'lost':((59,21,32),(253,164,175)),'below':((59,21,32),(253,164,175)),'reclaimed':((15,58,54),(94,234,212)),'day':((35,42,59),(201,210,230))}
  for o in Wl[:16]:
    c.r(10,y,392,74,PN,10,LN)
    c.t(22,y+9,o['sym'],12.5,b=True);c.t(22+c.d.textlength(o['sym'],font=f(12.5,True))/S+6,y+11,o['d'][5:],10,DM)
    st=o['status'] or '–';bg,fg=stc.get(st.split(' ')[0],((35,42,59),MU));w=c.d.textlength(st,font=f(10,True))/S+10
    c.r(392-w,y+8,w,17,bg,4);c.t(392-w+5,y+10,st,10,fg,True)
    verdict(c,22,y+29,o,11,300)
    c.t(22,y+50,f"Deal ₹{f1(o['lvl'])} → now ₹{f1(o['c'])}  ·  day {o['ago']}",10.5,MU)
    c.t(392,y+50,sg(o['chg']),11.5,UP if (o['chg'] or 0)>=0 else DN,True,anchor='ra');y+=80
  c.save(os.path.join(OUT,'deals_shot2_watch.png'),y+6)
# ---------- 3 stock drawer with deal candles
def drawer(sym):
  o=next(x for x in D['watch'] if x['sym']==sym)
  c=C(1500);y=14
  c.t(14,y,o['sym'],18,b=True);c.t(14+c.d.textlength(o['sym'],font=f(18,True))/S+8,y+6,o['nm'],10.5,MU);y+=32
  verdict(c,14,y,o,12.5);y=c.wrap(14,y+22,o['why'],384,11,(201,210,230))+6
  px=o['px'];marks=D['marks'].get(sym,[]);cw,ch=384,230;x0,y0=14,y
  c.r(10,y-4,392,ch+30,PN,10,LN)
  lv=[m['lvl'] for m in marks if m['lvl']]
  lo=min([p[3] for p in px]+lv)*0.99;hi=max([p[2] for p in px]+lv)*1.01
  bw=(cw-46)/len(px);Y=lambda v:y0+10+(ch-30)*(1-(v-lo)/(hi-lo))
  for i,p in enumerate(px):
    X=x0+6+i*bw+bw/2;up=p[4]>=p[1];col=UP if up else DN
    m=next((k for k in marks if k['d']==p[0]),None);tg=TAG[m['ev']] if m else None
    col=TC[tg] if tg else col
    c.d.line([(X*S,Y(p[2])*S),(X*S,Y(p[3])*S)],fill=col,width=int(S*0.8))
    a,b=sorted([Y(p[1]),Y(p[4])]);b=max(b,a+0.6)
    c.d.rectangle([(X-bw*0.33)*S,a*S,(X+bw*0.33)*S,b*S],fill=col)
    if tg: c.t(X,(Y(p[3])+4) if tg=='S' else (Y(p[2])-15),tg,10,TC[tg],True,anchor='ma')
  used=[]
  for m in sorted(marks,key=lambda k:k['d'],reverse=True)[:3]:
    tg=TAG[m['ev']]
    if not m['lvl'] or tg in 'CT': continue
    i=next((j for j,p in enumerate(px) if p[0]==m['d']),None)
    if i is None: continue
    yy=Y(m['lvl']);xs=x0+6+i*bw
    while xs<x0+cw-42: c.d.line([(xs*S,yy*S),(min(xs+4,x0+cw-42)*S,yy*S)],fill=TC[tg],width=int(S*1.1));xs+=7
    if all(abs(yy-u)>12 for u in used): c.t(x0+cw-40,yy-6,f1(m['lvl']),9.5,TC[tg]);used.append(yy)
  c.t(x0+4,y0+ch-12,px[0][0],9,MU);c.t(x0+cw-50,y0+ch-12,px[-1][0],9,MU,anchor='ra')
  y=y0+ch+34
  lx=14
  for k,l in [('B','net buy'),('P','placement'),('S','net sell'),('C','churn'),('T','transfer')]:
    c.t(lx,y,k,10.5,TC[k],True);c.t(lx+11,y,l,10,MU);lx+=c.d.textlength(l,font=f(10))/S+24
  y+=16;c.t(14,y,'dashed line = deal price',10,DM);y+=22
  kv=[('Deal price','₹'+f1(o['lvl'])),('Now','₹'+f1(o['c'])+' '+sg(o['chg'])),('Status',o['status'] if str(o['status']).startswith('day') else f"{o['status']} · day {o['ago']}"),('Chart',('Strong' if o['strong'] else 'Weak')+f" · RS {o['rs']}"),('From 52W high',sg(o['a52'])),('Last month',sg(o['r21']))]
  for i,(k,v) in enumerate(kv):
    xx=14+(i%3)*130;yy=y+(i//3)*38;c.t(xx,yy,k,9.5,MU);c.t(xx,yy+14,v,11.5)
  y+=84
  for title,lst in [('Bought',o['buy']),('Sold',o['sell'])]:
    c.t(14,y,title,10.5,MU);y+=18
    for b in lst or [{'n':'none (ex prop desks)','cls':'','v':None,'g':''}]:
      c.t(14,y,b['n'][:30],11);xx=14+c.d.textlength(b['n'][:30],font=f(11))/S+6;c.t(xx,y+1,b['cls'],9.5,DM)
      if b['cls'] in ('FII','DII'):
        gc={'good':((18,54,31),(134,239,172)),'poor':((59,21,32),(253,164,175)),'mixed':((58,42,16),(252,211,77))}.get(b['g'],((35,42,59),MU))
        xx+=c.d.textlength(b['cls'],font=f(9.5))/S+6;w=c.d.textlength(b['g'],font=f(9,True))/S+8;c.r(xx,y,w,15,gc[0],4);c.t(xx+4,y+2,b['g'],9,gc[1],True)
      if b['v'] is not None: c.t(398,y,'₹'+f1(b['v'])+' Cr',11,anchor='ra')
      y+=22
    y+=6
  fol={'confirm':f"Plan it: stop just under {f1(o['lvl'])}.",'absorbed':f"Sellers are done at {f1(o['lvl'])}; treat it as support.",'place':f"Deal price {f1(o['lvl'])} is the line."}.get(o['cls'],'Watch the deal price.')
  c.r(10,y,392,36,P2,8);c.d.rectangle([10*S,y*S,13*S,(y+36)*S],fill=(124,156,255));c.t(22,y+10,fol,11.5);y+=46
  c.save(os.path.join(OUT,f'deals_shot3_{sym}.png'),y)
# ---------- 4 telegram
def tg():
  T,Wl=D['today'],D['watch']
  def cr(v): return '₹'+f1(v)+' Cr'
  conf=[o for o in T if o['cls']=='watch'];pl=[o for o in T if o['cls']=='place'];cf=[o for o in Wl if o['cls']=='confirm'];ab=[o for o in Wl if o['cls']=='absorbed'][:4]
  d3=[o for o in Wl if o['ago']==3 and o['status'] and o['ev']!='distribute' and o['cls'] not in ('churn','ignore')][:5]
  av=[o['sym'] for o in T if o['cls']=='avoid'][:6]
  L=[('h',f"Deals · 13 Aug · {D['mkt']['above50']}% above 50 EMA")]
  if conf: L+= [('s','CONFIRMS A SETUP (watch day 3)',VC['confirm'])]+[('l',f"{o['sym']}  {cr(o['bv'] if abs(o['net'])<0.5 else o['net'])} · hold ₹{f1(o['lvl'])}") for o in conf]
  if pl: L+= [('s','PLACEMENT',VC['place'])]+[('l',f"{o['sym']}  {cr(o['gross'])} @ ₹{f1(o['lvl'])}") for o in pl]
  if cf: L+= [('s','CONFIRMED (held 3 days)',VC['confirm'])]+[('l',f"{o['sym']}  {sg(o['chg'])} over ₹{f1(o['lvl'])}") for o in cf]
  if ab: L+= [('s','ABSORBED (seller price reclaimed)',VC['absorbed'])]+[('l',f"{o['sym']}  sold @ ₹{f1(o['lvl'])}, now ₹{f1(o['c'])}") for o in ab]
  if d3: L+= [('s','DAY 3',VC['watch'])]+[('l',f"{o['sym']} {o['status']} {sg(o['chg'])}") for o in d3]
  if av: L+= [('s','AVOID',VC['avoid']),('l',', '.join(av))]
  sk=D['skipped'];L+=[('m',f"Skipped: {sk['transfer']} transfers, {sk['churn']} churn, {sk['small']} under ₹1,000 Cr")]
  c=C(1400);c.r(0,0,412,56,(23,33,48),0);c.t(16,12,'MarketPulse Bot',14,b=True);c.t(16,32,'bot',10,MU)
  y=72;top=y;c.y=y+12
  rows=[]
  yy=top+12
  for k,*v in L:
    if k=='s': yy+=8
    yy+=22 if k!='h' else 26
  c.r(14,top,380,yy-top+40,(24,37,51),14)
  y=top+12
  for k,*v in L:
    if k=='h': c.t(26,y,v[0],12,b=True);y+=26
    elif k=='s': y+=8;c.dot(30,y+7,v[1]);c.t(40,y,v[0],10.5,v[1],True);y+=22
    elif k=='l': c.t(40,y,v[0],10.5,TX,m=True);y+=22
    else: c.t(26,y,v[0],10,MU);y+=22
  c.t(26,y+4,'TV: NSE:SEAMECLTD,NSE:APOLLOPIPE,NSE:URBANCO,…',9.5,(124,156,255),m=True);c.t(386,y+20,'21:05',9,MU,anchor='ra')
  c.save(os.path.join(OUT,'deals_shot4_telegram.png'),y+60)

def history(N=10):
  PAT={'rbuy':('Repeated buying',VC['confirm'],'Buying in 2+ sessions, no selling. Alone it showed no edge: use the chart and deal price.'),
   'buy':('Single buy',VC['absorbed'],'One net-buy session.'),
   'sell':('Selling only',VC['supply'],"Overhang until price closes above the sellers' price."),
   'mixed':('Buying and selling',VC['watch'],'Read the latest session and the deal price.'),
   'prop':('Prop desk / churn only',VC['churn'],'Lagged the market: −2.0%, −3.7% on quiet days.'),
   'xfer':('Transfers only',VC['ignore'],'Shares changing hands; no new money.')}
  n20=len(D['sessions20']);lo=n20-N;R=[]
  for h in D['hist20']:
    ev=[e for e in h['ev'] if e[0]>=lo]
    if not ev: continue
    b=[e for e in ev if e[1] in('fresh','accumulate','placement')];sl=[e for e in ev if e[1]=='distribute'];ch=[e for e in ev if e[1]=='churn']
    pat='rbuy' if len(b)>=2 and not sl else 'buy' if len(b)==1 and not sl else 'sell' if sl and not b else 'mixed' if b and sl else 'prop' if ch else 'xfer'
    vals=[e[5] if pat=='sell' else e[4] for e in (sl if pat=='sell' else b) if (e[5] if pat=='sell' else e[4])]
    lvl=sum(vals)/len(vals) if vals else None
    R.append(dict(sym=h['sym'],ev=ev,pat=pat,nb=len(b),ns=len(sl),net=sum(e[2] for e in ev),prop=sum(e[3] for e in ev),lvl=lvl,vs=(h['c']/lvl-1)*100 if lvl else None))
  c=C(4000);y=header(c,'History')
  syms=[];[syms.append(r['sym']) for r in R if r['sym'] not in syms];tvb(c,y,len(syms))
  c.t(14,y+24,f'Deal history · last {N} deal sessions',13,b=True);y+=24;y=c.wrap(14,y+20,'Every deal stock, incl. churn, prop desks and transfers. One square per session, oldest first.',380,10.5,MU)+6
  x=14
  for n in (5,10,20):
    k=f'{n} sessions';w=c.d.textlength(k,font=f(11))/S+16;c.r(x,y,w,24,P2 if n==N else PN,7,LN);c.t(x+8,y+5,k,11,TX if n==N else MU);x+=w+5
  y+=36
  for k,(lab,col,note) in PAT.items():
    L=sorted([r for r in R if r['pat']==k],key=lambda r:(-(r['nb']+r['ns']),-abs(r['net'])))
    if not L: continue
    c.dot(18,y+8,col,5);c.t(28,y,f'{lab}  ',13,col,True);c.t(28+c.d.textlength(lab+'  ',font=f(13,True))/S,y+2,f'{len(L)} stocks',11,MU);y=c.wrap(14,y+20,note,380,10,DM)+4
    for r in L[:4]:
      c.r(10,y,392,62,PN,10,LN);c.t(22,y+9,r['sym'],12.5,b=True)
      sx=180;cw=(392-170-6)/N
      for i in range(lo,n20):
        e=next((z for z in r['ev'] if z[0]==i),None);tg=TAG[e[1]] if e else None
        c.r(sx,y+9,cw-2,16,TC[tg] if tg else (29,35,49),3)
        if tg and cw>11: c.t(sx+(cw-2)/2,y+11,tg,9,(11,13,18),True,anchor='ma')
        sx+=cw
      parts=[f"Buy {r['nb']}",f"Sell {r['ns']}",('Net ' + ('0' if abs(r['net'])<0.05 else ('+' if r['net']>0 else '−')+'₹'+f1(r['net'])+' Cr'))]
      if r['prop']: parts.append(f"Prop ₹{f1(r['prop'])} Cr")
      c.t(22,y+38,'  ·  '.join(parts),10.5,MU)
      if r['vs'] is not None: c.t(392,y+38,f"vs deal {sg(r['vs'])}",10.5,UP if r['vs']>=0 else DN,True,anchor='ra')
      y+=68
    if len(L)>4: c.t(22,y,f'+ {len(L)-4} more',10.5,DM);y+=20
    y+=10
  c.save(os.path.join(OUT,'deals_shot5_history.png'),y)

def houses():
  c=C(3000);y=header(c,'Houses')
  k='Copy every list (sections)';w=c.d.textlength(k,font=f(10.5))/S+18;c.r(14,y-3,w,22,P2,7,LN);c.t(14+w/2,y+1,k,10.5,TX,anchor='ma');y+=32
  fg=D['fundgrp'];tvb(c,y,len({s for g in fg for s in g['syms']}));y+=26
  c.t(14,y,'Where FII/DII money went · by group',13,b=True);y=c.wrap(14,y+20,'Non-prop FII and DII buys, last 10 deal sessions. Many houses in one group = broad interest, not one desk.',380,10.5,MU)+8
  mx=max(g['fii']+g['dii'] for g in fg)
  for g in fg[:7]:
    c.r(10,y,392,58,PN,10,LN);nm=g['ind']
    while c.d.textlength(nm,font=f(12,True))/S>250: nm=nm[:-2]
    c.t(22,y+8,nm+('…' if nm!=g['ind'] else ''),12,b=True);c.t(392,y+8,f"{g['houses']} houses",11,MU,anchor='ra')
    bw=170;fw=bw*g['fii']/mx;dw=bw*g['dii']/mx
    if fw>0: c.r(22,y+30,max(fw,3),8,(96,165,250),3)
    if dw>0: c.r(22+fw+(2 if fw else 0),y+30,max(dw,3),8,(167,139,250),3)
    c.t(22+fw+dw+8,y+27,f"₹{f1(g['fii']+g['dii'])} Cr",10.5,MU)
    c.t(392,y+28,', '.join(g['syms']),10.5,TX,anchor='ra');y+=64
  c.dot(22,y+6,(96,165,250));c.t(30,y,'FII',10.5,MU);c.dot(62,y+6,(167,139,250));c.t(70,y,'DII',10.5,MU);y+=30
  hs=[h for h in D['houses'] if h['cls'] in ('FII','DII')][:7]
  tvb(c,y,len({s for h in hs for g in h['grp'] for s in g[2]}));y+=26
  c.t(14,y,'Each fund · spread across groups',13,b=True);y=c.wrap(14,y+20,'Share of the fund\'s buying in each industry this window.',380,10.5,MU)+8
  pal=[(45,212,191),(96,165,250),(167,139,250),(251,146,60),(148,163,184)]
  for h in hs:
    tot=sum(g[1] for g in h['grp']) or 1;nl=len(h['grp'][:4])
    c.r(10,y,392,46+nl*18,PN,10,LN);c.t(22,y+8,h['h'],12,b=True);c.t(392,y+8,f"{h['cls']} · ₹{f1(h['v'])} Cr · {len(h['grp'])} group{'s' if len(h['grp'])>1 else ''}",10.5,MU,anchor='ra')
    x=22
    for i,g in enumerate(h['grp']):
      w=368*g[1]/tot;c.r(x,y+28,max(w-2,2),7,pal[min(i,4)],3);x+=w
    yy=y+42
    for i,g in enumerate(h['grp'][:4]):
      c.dot(26,yy+6,pal[min(i,4)],3.5);nm=g[0]
      while c.d.textlength(nm,font=f(10.5))/S>185: nm=nm[:-2]
      c.t(34,yy,nm+('…' if nm!=g[0] else ''),10.5,MU);c.t(262,yy,f"{round(g[1]/tot*100)}%",10.5,TX,anchor='ra');sy=', '.join(g[2])
      while c.d.textlength(sy,font=f(10.5))/S>118: sy=sy[:-2]
      c.t(392,yy,sy+('…' if sy!=', '.join(g[2]) else ''),10.5,TX,anchor='ra');yy+=18
    y+=52+nl*18
  c.save(os.path.join(OUT,'deals_shot6_houses.png'),y+8)
today();watch();drawer('DIAMONDYD');tg();history();houses();drawer('APOLLOPIPE')
print('ok')
