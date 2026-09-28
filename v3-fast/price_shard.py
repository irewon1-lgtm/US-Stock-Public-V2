from __future__ import annotations
import argparse,time
from urllib.parse import quote
from pathlib import Path
import numpy as np,pandas as pd,requests,exchange_calendars as xcals

START='2019-01-01'; END='2026-02-15'
cal=xcals.get_calendar('XNYS',start='2018-01-01',end='2031-12-31')

def yahoo_symbol(t): return str(t).strip().upper().replace('.','-').replace('/','-')
def _unix_utc(s): return int(pd.Timestamp(s,tz='UTC').timestamp())

def fetch_one(ticker):
    ys=yahoo_symbol(ticker)
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ys,safe='')}"
    params={'period1':_unix_utc(START),'period2':_unix_utc(END),'interval':'1d','events':'div,splits','includeAdjustedClose':'true','includePrePost':'false'}
    last=''
    for attempt in range(4):
        try:
            r=requests.get(url,params=params,timeout=25,headers={'User-Agent':'Mozilla/5.0 V3-Free research'})
            if r.status_code in {429,500,502,503,504}: raise RuntimeError(f'HTTP_{r.status_code}')
            r.raise_for_status(); p=r.json(); chart=p.get('chart') or {}
            if chart.get('error'): raise RuntimeError(str(chart['error']))
            rs=chart.get('result') or []
            if not rs: return pd.DataFrame(),'NO_DATA',''
            q=rs[0]; ts=q.get('timestamp') or []
            if not ts: return pd.DataFrame(),'NO_DATA',''
            inds=q.get('indicators') or {}; qr=(inds.get('quote') or [{}])[0]; ar=(inds.get('adjclose') or [{}])[0]; n=len(ts)
            def arr(name):
                a=list(qr.get(name) or []); return (a+[None]*max(0,n-len(a)))[:n]
            adj=list(ar.get('adjclose') or []); adj=(adj+[None]*max(0,n-len(adj)))[:n]
            d=pd.DataFrame({'date':[pd.to_datetime(int(x),unit='s',utc=True).tz_localize(None).normalize() for x in ts],
                            'open':arr('open'),'high':arr('high'),'low':arr('low'),'close':arr('close'),'adj_close':adj,'volume':arr('volume')})
            for c in ['open','high','low','close','adj_close','volume']: d[c]=pd.to_numeric(d[c],errors='coerce')
            d=d.dropna(subset=['date']).sort_values('date').drop_duplicates('date',keep='last')
            d['adj_factor']=d['adj_close']/d['close']; d.loc[(d['close']<=0)|(d['adj_close']<=0),'adj_factor']=np.nan; d['adj_open']=d['open']*d['adj_factor']
            return d.set_index('date'),'OK',''
        except Exception as e:
            last=repr(e)[:300]
            if attempt<3: time.sleep(min(12,1.5*(2**attempt)))
    return pd.DataFrame(),'ERROR',last

def features_at(d,snapshot):
    s=pd.Timestamp(snapshot).normalize()
    if d.empty or s not in d.index: return {'price_status':'SNAPSHOT_PRICE_MISSING'}
    pos=d.index.get_loc(s)
    if not isinstance(pos,(int,np.integer)): return {'price_status':'DUPLICATE_DATE'}
    raw=float(d.iloc[pos]['close']) if pd.notna(d.iloc[pos]['close']) else np.nan
    if pos<252: return {'price_status':'INSUFFICIENT_252D_HISTORY','raw_close_snapshot':raw}
    cur=d.iloc[pos]; p21=d.iloc[pos-21]['adj_close']; p252=d.iloc[pos-252]['adj_close']; win=d.iloc[pos-251:pos+1]['adj_close']
    if any(pd.isna(x) or x<=0 for x in [cur['adj_close'],p21,p252]) or win.isna().any(): return {'price_status':'ADJUSTED_PRICE_GAP','raw_close_snapshot':raw}
    return {'price_status':'OK','raw_close_snapshot':raw,'adj_close_snapshot':float(cur['adj_close']),
            'F6_mom12_1_raw':float(p21/p252-1.0),'F6_high52_raw':float(cur['adj_close']/win.max()-1.0)}

def execute_entry(d,snapshot):
    s=pd.Timestamp(snapshot).normalize(); sess=cal.sessions_in_range(s,s+pd.Timedelta(days=14)).tz_localize(None)
    fut=[pd.Timestamp(x).normalize() for x in sess if pd.Timestamp(x).normalize()>s]
    if not fut:return None,None
    dt=fut[0]
    if d.empty or dt not in d.index:return None,None
    r=d.loc[dt]
    if pd.isna(r.get('adj_open')) or float(r['adj_open'])<=0:return None,None
    return dt,float(r['adj_open'])

def session_on_or_before(date):
    d=pd.Timestamp(date).normalize(); sess=cal.sessions_in_range(d-pd.Timedelta(days=14),d).tz_localize(None)
    return None if len(sess)==0 else pd.Timestamp(sess[-1]).normalize()
def target_session_from_entry(entry,years): return None if entry is None else session_on_or_before(pd.Timestamp(entry).normalize()+pd.DateOffset(years=years))
def last_observed_to(d,start,end):
    if start is None or end is None or d.empty:return None,np.nan
    z=d[(d.index>=pd.Timestamp(start).normalize())&(d.index<=pd.Timestamp(end).normalize())]
    z=z[pd.to_numeric(z['adj_close'],errors='coerce').gt(0)]
    if z.empty:return None,np.nan
    dt=z.index[-1]; return pd.Timestamp(dt).normalize(),float(z.iloc[-1]['adj_close'])
def known_delisting(base,target3):
    x=str(base.get('target_only_delisting_date','') or '').strip()
    if not x or target3 is None:return None
    dt=pd.to_datetime(x,errors='coerce')
    if pd.isna(dt):return None
    dt=dt.normalize(); return dt if dt<=pd.Timestamp(target3).normalize() else None

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input',required=True); ap.add_argument('--shard',type=int,required=True); ap.add_argument('--nshards',type=int,default=4); ap.add_argument('--outdir',required=True)
    a=ap.parse_args(); outdir=Path(a.outdir); outdir.mkdir(parents=True,exist_ok=True)
    u=pd.read_csv(a.input,dtype=str,keep_default_na=False); u['_row_id']=np.arange(len(u))
    if pd.to_datetime(u['snapshot_date'],errors='coerce').dt.year.ge(2023).any(): raise RuntimeError('REFUSED 2023+ formation snapshot')
    reuse=u.copy(); reuse['cik_norm']=pd.to_numeric(reuse['cik'],errors='coerce')
    amb=set(reuse.groupby('ticker_at_snapshot')['cik_norm'].nunique(dropna=True).loc[lambda x:x>1].index)
    tickers=sorted(u['ticker_at_snapshot'].str.upper().str.strip().unique())
    tickers=[t for i,t in enumerate(tickers) if i%a.nshards==a.shard]
    rows=[]; audit=[]
    for i,t in enumerate(tickers,1):
        ug=u[u['ticker_at_snapshot'].str.upper().str.strip().eq(t)]
        if t in amb:
            for _,r in ug.iterrows(): rows.append(r.to_dict()|{'snapshot_session':r['snapshot_date'],'price_status':'TICKER_REUSE_MULTIPLE_CIK','target_status':'UNRESOLVED'})
            audit.append({'ticker':t,'status':'AMBIGUOUS_TICKER_REUSE','rows':0}); continue
        d,status,err=fetch_one(t); audit.append({'ticker':t,'status':status,'rows':0 if d.empty else len(d),'error':err})
        if d.empty:
            for _,r in ug.iterrows(): rows.append(r.to_dict()|{'snapshot_session':r['snapshot_date'],'price_status':'PRICE_FILE_MISSING','target_status':'UNRESOLVED'})
        else:
            for _,r in ug.iterrows():
                b=r.to_dict(); snap=str(r['snapshot_date']); feat=features_at(d,snap); entry_date,entry_adj_open=execute_entry(d,snap)
                out=b|{'snapshot_session':snap}|feat
                if entry_date is None:
                    out|={'entry_date':'','entry_adj_open':np.nan,'target_status':'NO_EXECUTABLE_ENTRY','target_resolution_class':'UNRESOLVED_OTHER'}; rows.append(out); continue
                target3=target_session_from_entry(entry_date,3); target5=target_session_from_entry(entry_date,5)
                out|={'entry_date':entry_date.date().isoformat(),'entry_adj_open':entry_adj_open,'target_3y_session':'' if target3 is None else target3.date().isoformat(),'target_5y_session':'' if target5 is None else target5.date().isoformat()}
                kd=known_delisting(b,target3); tr=None if target3 is None or target3 not in d.index else d.loc[target3]
                if kd is None and tr is not None and pd.notna(tr.get('adj_close')) and tr['adj_close']>0:
                    mult=float(tr['adj_close'])/entry_adj_open
                    out|={'target_status':'PRICE_RESOLVED','target_resolution_class':'RESOLVED','exit_adj_close_3y':float(tr['adj_close']),'multiple_3y':mult,'return_3y':mult-1.0,'hit_2x_3y':int(mult>=2),'hit_3x_3y':int(mult>=3),'hit_5x_3y':int(mult>=5),'hit_10x_3y':int(mult>=10)}
                else:
                    last_end=kd if kd is not None else target3; ldt,lpx=last_observed_to(d,entry_date,last_end); lmult=lpx/entry_adj_open if pd.notna(lpx) and entry_adj_open>0 else np.nan
                    out|={'target_status':'TARGET_PRICE_UNRESOLVED','target_resolution_class':'DELISTING_UNRESOLVED' if kd is not None else 'UNRESOLVED_OTHER','known_delisting_date':'' if kd is None else kd.date().isoformat(),'last_observed_date_to_target':'' if ldt is None else ldt.date().isoformat(),'last_observed_adj_close_to_target':lpx,'last_observed_multiple_3y':lmult,'return_3y':np.nan,'multiple_3y':np.nan}
                rows.append(out)
        if i%100==0: print(f'shard {a.shard}: {i}/{len(tickers)}',flush=True)
        time.sleep(0.02)
    pd.DataFrame(rows).to_csv(outdir/f'rows_{a.shard}.csv.gz',index=False,compression='gzip')
    pd.DataFrame(audit).to_csv(outdir/f'audit_{a.shard}.csv',index=False)

if __name__=='__main__': main()
