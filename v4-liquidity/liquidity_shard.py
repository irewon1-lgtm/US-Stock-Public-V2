from __future__ import annotations
import argparse,time
from urllib.parse import quote
from pathlib import Path
import numpy as np,pandas as pd,requests

START='2019-09-01'; END='2023-01-05'

def yahoo_symbol(t): return str(t).strip().upper().replace('.','-').replace('/','-')
def unix_utc(s): return int(pd.Timestamp(s,tz='UTC').timestamp())

def fetch_one(ticker):
    ys=yahoo_symbol(ticker); url=f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ys,safe='')}"
    params={'period1':unix_utc(START),'period2':unix_utc(END),'interval':'1d','events':'div,splits','includeAdjustedClose':'false','includePrePost':'false'}
    last=''
    for attempt in range(4):
        try:
            r=requests.get(url,params=params,timeout=12,headers={'User-Agent':'Mozilla/5.0 V4 feasibility research'})
            if r.status_code==404: return pd.DataFrame(),'NO_DATA','HTTP_404_PERMANENT'
            if r.status_code in {429,500,502,503,504}: raise RuntimeError(f'HTTP_{r.status_code}')
            if r.status_code==400:
                try: desc=str(((r.json().get('chart') or {}).get('error') or {}).get('description',''))
                except Exception: desc=''
                if 'Data' in desc or 'delisted' in desc.lower(): return pd.DataFrame(),'NO_DATA',desc[:250]
            r.raise_for_status(); q=((r.json().get('chart') or {}).get('result') or [None])[0]
            if not q or not q.get('timestamp'): return pd.DataFrame(),'NO_DATA',''
            ts=q['timestamp']; qr=((q.get('indicators') or {}).get('quote') or [{}])[0]; n=len(ts)
            def arr(name):
                a=list(qr.get(name) or []); return (a+[None]*max(0,n-len(a)))[:n]
            d=pd.DataFrame({'date':[pd.to_datetime(int(x),unit='s',utc=True).tz_localize(None).normalize() for x in ts], 'close':arr('close'),'volume':arr('volume')})
            d['close']=pd.to_numeric(d.close,errors='coerce'); d['volume']=pd.to_numeric(d.volume,errors='coerce')
            d=d.dropna(subset=['date']).sort_values('date').drop_duplicates('date',keep='last').set_index('date')
            return d,'OK',''
        except Exception as e:
            last=repr(e)[:250]
            if attempt<3: time.sleep(min(8,1.25*(2**attempt)))
    return pd.DataFrame(),'ERROR',last

def features(d,snapshot):
    s=pd.Timestamp(snapshot).normalize()
    if d.empty or s not in d.index: return {'liquidity_status':'SNAPSHOT_PRICE_MISSING'}
    loc=d.index.get_loc(s)
    if not isinstance(loc,(int,np.integer)): return {'liquidity_status':'DUPLICATE_DATE'}
    raw=d.iloc[loc]['close']; out={'raw_close_v4':raw}
    hist=d.iloc[max(0,loc-59):loc+1].copy()
    if len(hist)<60: return out|{'liquidity_status':'INSUFFICIENT_60_SESSIONS','sessions_available':len(hist)}
    ok=hist['close'].gt(0)&hist['volume'].ge(0)&hist['close'].notna()&hist['volume'].notna()
    if not ok.all(): return out|{'liquidity_status':'PRICE_VOLUME_GAP','sessions_available':len(hist),'valid_sessions':int(ok.sum())}
    dv=hist['close']*hist['volume']
    return out|{'liquidity_status':'OK','sessions_available':60,'valid_sessions':60,'median_dollar_volume_60d':float(dv.median()),'median_raw_close_60d':float(hist.close.median())}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input',required=True); ap.add_argument('--shard',type=int,required=True); ap.add_argument('--nshards',type=int,default=8); ap.add_argument('--outdir',required=True)
    a=ap.parse_args(); out=Path(a.outdir); out.mkdir(parents=True,exist_ok=True)
    u=pd.read_csv(a.input,dtype=str,keep_default_na=False); u['_row_id']=np.arange(len(u))
    years=pd.to_datetime(u['snapshot_date'],errors='coerce').dt.year
    if years.ge(2023).any(): raise RuntimeError('REFUSED 2023+ formation snapshot')
    reuse=u.copy(); reuse['cik_norm']=pd.to_numeric(reuse['cik'],errors='coerce')
    amb=set(reuse.groupby('ticker_at_snapshot')['cik_norm'].nunique(dropna=True).loc[lambda x:x>1].index)
    tickers=sorted(u.ticker_at_snapshot.str.upper().str.strip().unique()); tickers=[t for i,t in enumerate(tickers) if i%a.nshards==a.shard]
    rows=[]; audit=[]
    for i,t in enumerate(tickers,1):
        g=u[u.ticker_at_snapshot.str.upper().str.strip().eq(t)]
        if t in amb:
            for _,r in g.iterrows(): rows.append({'_row_id':r['_row_id'],'snapshot_date':r['snapshot_date'],'ticker_at_snapshot':t,'liquidity_status':'TICKER_REUSE_MULTIPLE_CIK'})
            audit.append({'ticker':t,'status':'AMBIGUOUS_TICKER_REUSE','rows':0}); continue
        d,status,err=fetch_one(t); audit.append({'ticker':t,'status':status,'rows':0 if d.empty else len(d),'error':err})
        for _,r in g.iterrows(): rows.append({'_row_id':r['_row_id'],'snapshot_date':r['snapshot_date'],'ticker_at_snapshot':t}|features(d,r['snapshot_date']))
        if i%100==0: print(a.shard,i,len(tickers),flush=True)
        time.sleep(.015)
    pd.DataFrame(rows).to_csv(out/f'rows_{a.shard}.csv.gz',index=False,compression='gzip')
    pd.DataFrame(audit).to_csv(out/f'audit_{a.shard}.csv',index=False)
if __name__=='__main__': main()
