import requests, json, time, datetime as dt, pathlib, sys
out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/workspace/work/deals_hist"); out.mkdir(parents=True, exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
s = requests.Session(); s.headers.update({"User-Agent": UA, "Referer": "https://www.nseindia.com/report-detail/display-bulk-and-block-deals", "Accept": "application/json"})
try: s.get("https://www.nseindia.com/", timeout=20)
except Exception: pass
d = dt.date(2024, 4, 1)
while d < dt.date(2026, 10, 9):
    e = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    for kind in ("bulk_deals", "block_deals"):
        f = out / f"{kind}_{d:%Y%m}.csv"
        if f.exists() and f.stat().st_size > 50: continue
        url = f"https://www.nseindia.com/api/historicalOR/bulk-block-short-deals?optionType={kind}&from={d:%d-%m-%Y}&to={e:%d-%m-%Y}&csv=true"
        for a in range(4):
            try:
                r = s.get(url, timeout=60)
                if r.status_code == 200 and "Symbol" in r.text[:200]:
                    f.write_bytes(r.content); print(f.name, r.text.count(chr(10)), flush=True); break
                print(f.name, "status", r.status_code, flush=True)
            except Exception as ex:
                print(f.name, "err", ex, flush=True)
            time.sleep(3); 
            try: s.get("https://www.nseindia.com/", timeout=20)
            except Exception: pass
        time.sleep(1.5)
    d = e + dt.timedelta(days=1)
