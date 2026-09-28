from __future__ import annotations
import argparse,json,math,time
from urllib.parse import quote
from pathlib import Path
import numpy as np,pandas as pd,requests

START='2019-01-01'; END='2026-10-01'
def unix_utc(s): return int(pd.Timestamp(s,tz='UTC').timestamp())
def ys(t): return str(t).strip().upper().replace('.','-').replace('/','-')

def fetch_splits(ticker):
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ys(ticker),safe='')}"
    params={'period1':unix_utc(START),'period2':unix_utc(END),'interval':'1d','events':'splits','includeAdjustedClose':'false','includePrePost':'false'}
    last=''
    for a in range(4):
        try:
            r=requests.get(url,params=params,timeout=12,headers={'User-Agent':'Mozilla/5.0 V4 split reconstruction'})
            if r.status_code==404: return [],'NO_DATA','HTTP_404'
            if r.status_code in {429,500,502,503,504}: raise RuntimeError(f'HTTP_{r.status_code}')
            if r.status_code==400:
                try: desc=str(((r.json().get('chart') or {}).get('error') or {}).get('description',''))
                except: desc=''
                if 'Data' in desc or 'delisted' in desc.lower(): return [],'NO_DATA',desc[:250]
            r.raise_for_status()
            q=((r.json().get('chart') or {}).get('result') or [None])[0]
            if not q: return [],'NO_DATA','NO_RESULT'
            ev=((q.get('events') or {}).get('splits') or {})
            out=[]
            for x in ev.values() if isinstance(ev,dict) else []:
                try:
                    dt=pd.to_datetime(int(x.get('date')),unit='s',utc=True).tz_localize(None).normalize()
                    num=float(x.get('numerator')); den=float(x.get('denominator'))
                    if num>0 and den>0 and math.isfinite(num) and math.isfinite(den): out.append((dt,num/den))
                except: pass
            return sorted(out,key=lambda z:z[0]),'OK',''
        except Exception as e:
            last=repr(e)[:300]
            if a<3: time.sleep(min(8,1.5*(2**a)))
    return [],'ERROR',last

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--shard',type=int,required=True); ap.add_argument('--nshards',type=int,default=16); a=ap.parse_args()
    out=Path('v4-yahoo-splits-output'); out.mkdir(parents=True,exist_ok=True)
    u=pd.read_csv('v3-fast/price_universe_resolved.csv.gz',dtype=str,keep_default_na=False,compression='gzip'); u['_row_id']=np.arange(len(u))
    if len(u)!=42014 or pd.to_datetime(u.snapshot_date,errors='coerce').dt.year.ge(2023).any(): raise RuntimeError('REFUSED input/2023+')
    tmp=u.copy(); tmp['_cik']=pd.to_numeric(tmp.cik,errors='coerce')
    amb=set(tmp.groupby(tmp.ticker_at_snapshot.astype(str).str.upper().str.strip())['_cik'].nunique(dropna=True).loc[lambda x:x>1].index)
    tickers=sorted(u.ticker_at_snapshot.astype(str).str.upper().str.strip().unique()); tickers=[t for i,t in enumerate(tickers) if i%a.nshards==a.shard]
    rows=[]; audit=[]
    for i,t in enumerate(tickers,1):
        g=u[u.ticker_at_snapshot.astype(str).str.upper().str.strip().eq(t)]
        if t in amb:
            for _,r in g.iterrows(): rows.append({'_row_id':int(r['_row_id']),'yahoo_split_status':'TICKER_REUSE_MULTIPLE_CIK','yahoo_future_split_ratio':np.nan})
            audit.append({'ticker':t,'status':'AMBIGUOUS_TICKER_REUSE','split_count':0}); continue
        sp,st,err=fetch_splits(t)
        for _,r in g.iterrows():
            if st!='OK':
                rows.append({'_row_id':int(r['_row_id']),'yahoo_split_status':st,'yahoo_future_split_ratio':np.nan})
            else:
                s=pd.Timestamp(r.snapshot_date).normalize(); m=1.0
                for dt,rat in sp:
                    if dt>s: m*=rat
                rows.append({'_row_id':int(r['_row_id']),'yahoo_split_status':'OK','yahoo_future_split_ratio':m})
        audit.append({'ticker':t,'status':st,'split_count':len(sp),'error':err})
        if i%50==0: print(a.shard,i,len(tickers),flush=True)
        time.sleep(.015)
    pd.DataFrame(rows).to_csv(out/f'rows_{a.shard}.csv.gz',index=False,compression='gzip')
    pd.DataFrame(audit).to_csv(out/f'audit_{a.shard}.csv',index=False)
if __name__=='__main__': main()
