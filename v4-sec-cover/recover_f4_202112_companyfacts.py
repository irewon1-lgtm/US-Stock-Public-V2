from __future__ import annotations
import json, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import pandas as pd, requests

ROOT=Path('.')
T=json.loads((ROOT/'v4-sec-cover/f4_202112_direct_standard_targets.json').read_text())
OUT=ROOT/'v4-sec-f4-202112-companyfacts-output'; OUT.mkdir(exist_ok=True)
FORMS={'10-Q','10-K','10-Q/A','10-K/A'}
TAGS={
 'WeightedAverageNumberOfDilutedSharesOutstanding':'DILUTED',
 'WeightedAverageNumberOfSharesOutstandingBasic':'BASIC',
 'WeightedAverageNumberOfShareOutstandingBasicAndDiluted':'COMBINED',
 'WeightedAverageNumberDilutedSharesOutstandingAdjustment':'ADJ',
}
UA='V4-Full-Rigor F4 companyfacts exact-standard recovery research@example.com'
S=requests.Session(); S.headers.update({'User-Agent':UA,'Accept-Encoding':'gzip, deflate','Accept':'application/json'})
LOCK=threading.Lock(); LAST=[0.0]

def rate_wait():
    with LOCK:
        dt=time.monotonic()-LAST[0]
        if dt<0.14: time.sleep(0.14-dt)
        LAST[0]=time.monotonic()

def get_json(url,attempts=5):
    last=''
    for i in range(attempts):
        try:
            rate_wait(); r=S.get(url,timeout=45)
            if r.status_code in {429,500,502,503,504}: raise RuntimeError(f'HTTP_{r.status_code}')
            r.raise_for_status(); return r.json()
        except Exception as e:
            last=repr(e)
            if i<attempts-1: time.sleep(min(15,1.5*(2**i)))
    raise RuntimeError(last)

def amap(obj):
    a=((obj.get('filings') or {}).get('recent') or {}) if isinstance(obj,dict) else {}
    out={}
    acc=a.get('accessionNumber') or []; ac=a.get('acceptanceDateTime') or []; forms=a.get('form') or []; fd=a.get('filingDate') or []
    for i,x in enumerate(acc):
        out[str(x)]={'accepted':str(ac[i] if i<len(ac) else ''),'form':str(forms[i] if i<len(forms) else ''),'filing':str(fd[i] if i<len(fd) else '')}
    return out

def one(cik):
    audit={'cik':cik,'status':'OK','facts':0,'mapped':0,'error':''}; rows=[]
    try:
        cf=get_json(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json')
        sub=get_json(f'https://data.sec.gov/submissions/CIK{cik:010d}.json')
        m=amap(sub)
        us=((cf.get('facts') or {}).get('us-gaap') or {})
        for tag,role in TAGS.items():
            con=us.get(tag) or {}
            for unit,items in (con.get('units') or {}).items():
                if str(unit).lower() not in {'shares','share'} or not isinstance(items,list): continue
                for r in items:
                    form=str(r.get('form') or '').upper()
                    if form not in FORMS: continue
                    end=str(r.get('end') or '')[:10]; start=str(r.get('start') or '')[:10]; filed=str(r.get('filed') or '')[:10]; accn=str(r.get('accn') or '')
                    if not end or end<'2019-01-01' or end>'2021-12-31': continue
                    if filed and filed>'2021-12-31': continue
                    try: val=float(r.get('val'))
                    except: continue
                    if val<=0: continue
                    try: days=(pd.Timestamp(end)-pd.Timestamp(start)).days+1
                    except: continue
                    q=1 if 60<=days<=125 else 2 if 126<=days<=220 else 3 if 221<=days<=320 else 4 if 321<=days<=410 else None
                    if q is None: continue
                    a=m.get(accn,{})
                    accepted=str(a.get('accepted') or '')
                    if not accepted or accepted[:10]>'2021-12-31': continue
                    rows.append({'cik':cik,'tag':tag,'role':role,'unit':unit,'value':val,'start':start,'end':end,'qtrs':q,'filed':filed,'form':form,'accn':accn,'accepted':accepted})
        audit['facts']=len(rows); audit['mapped']=sum(bool(x['accepted']) for x in rows)
    except Exception as e:
        audit['status']='ERROR'; audit['error']=repr(e)[:500]
    return rows,audit

allrows=[];aud=[]
with ThreadPoolExecutor(max_workers=6) as ex:
    futs={ex.submit(one,int(c)):int(c) for c in T['ciks']}
    for i,f in enumerate(as_completed(futs),1):
        rr,aa=f.result(); allrows.extend(rr); aud.append(aa)
        if i%10==0: print('PROGRESS',i,'/',len(T['ciks']),'facts',len(allrows),flush=True)
d=pd.DataFrame(allrows)
if d.empty:d=pd.DataFrame(columns=['cik','tag','role','unit','value','start','end','qtrs','filed','form','accn','accepted'])
d=d.drop_duplicates(subset=['cik','role','value','start','end','accn'])
d.to_csv(OUT/'standard_share_facts.csv.gz',index=False,compression='gzip')
pd.DataFrame(aud).to_csv(OUT/'audit.csv',index=False)
summary={'schema':'V4_F4_202112_COMPANYFACTS_STANDARD_V1','target_ciks':len(T['ciks']),'fact_rows':len(d),'ciks_with_facts':int(d.cik.nunique()) if len(d) else 0,'role_counts':d.role.value_counts().to_dict() if len(d) else {},'formation_2023_opened':False,'future_outcomes_used':False,'us3700_used':False,'new_corp_action_lookup_calls':0}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary,indent=2),flush=True)
