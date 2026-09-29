from __future__ import annotations
import io,json,math,time,threading,zipfile
from pathlib import Path
import pandas as pd, requests
from lxml import etree

ROOT=Path('.')
TARGET=json.loads((ROOT/'v4-sec-cover/f4_202112_direct_standard_targets.json').read_text())
OUT=ROOT/'v4-sec-f4-202112-direct-output'; OUT.mkdir(exist_ok=True)
CUTOFF=pd.Timestamp('2021-12-31T23:59:59Z')
START=pd.Timestamp('2019-01-01T00:00:00Z')
FORMS={'10-Q','10-K','10-Q/A','10-K/A'}
QMAP={
 'us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding':'DILUTED',
 'us-gaap:WeightedAverageNumberOfSharesOutstandingBasic':'BASIC',
 'us-gaap:WeightedAverageNumberOfShareOutstandingBasicAndDiluted':'COMBINED',
 'us-gaap:WeightedAverageNumberDilutedSharesOutstandingAdjustment':'ADJ',
}
UA='V4-Full-Rigor F4 exact-standard inline recovery research@example.com'
S=requests.Session();S.headers.update({'User-Agent':UA,'Accept-Encoding':'gzip, deflate'})
LOCK=threading.Lock();LAST=[0.0]

def wait():
    with LOCK:
        dt=time.monotonic()-LAST[0]
        if dt<0.35: time.sleep(0.35-dt)
        LAST[0]=time.monotonic()

def get(url,timeout=60):
    last=''
    for i in range(4):
        try:
            wait(); r=S.get(url,timeout=timeout)
            if r.status_code==404:return None
            if r.status_code in {429,500,502,503,504}:raise RuntimeError(f'HTTP_{r.status_code}')
            r.raise_for_status();return r
        except Exception as e:
            last=repr(e)
            if i<3:time.sleep(min(15,1.5*(2**i)))
    raise RuntimeError(last)

def parse_recent(cik):
    r=get(f'https://data.sec.gov/submissions/CIK{cik:010d}.json',45)
    if r is None:return []
    j=r.json(); a=(j.get('filings') or {}).get('recent') or {}
    out=[]
    keys=['accessionNumber','acceptanceDateTime','filingDate','form','primaryDocument']
    n=max([len(a.get(k) or []) for k in keys]+[0])
    for i in range(n):
        def v(k):
            z=a.get(k) or [];return str(z[i] if i<len(z) else '').strip()
        form=v('form').upper();acc=v('accessionNumber');accepted=v('acceptanceDateTime');filed=v('filingDate')
        if form not in FORMS or not acc:continue
        ds=accepted or filed
        try:t=pd.Timestamp(ds)
        except:continue
        if t.tzinfo is None:t=t.tz_localize('UTC')
        else:t=t.tz_convert('UTC')
        if START<=t<=CUTOFF:out.append({'accn':acc,'accepted':accepted,'filed':filed,'form':form})
    return out

def ctx_map(root):
    out={}
    for c in root.xpath("//*[local-name()='context']"):
        cid=c.get('id') or ''
        if not cid:continue
        starts=c.xpath(".//*[local-name()='startDate']/text()")
        ends=c.xpath(".//*[local-name()='endDate']/text()")
        inst=c.xpath(".//*[local-name()='instant']/text()")
        dims=c.xpath(".//*[local-name()='explicitMember' or local-name()='typedMember']")
        out[cid]={'start':str(starts[0])[:10] if starts else '', 'end':str(ends[0])[:10] if ends else (str(inst[0])[:10] if inst else ''), 'dimensioned':bool(dims), 'instant':bool(inst)}
    return out

def unit_map(root):
    out={}
    for u in root.xpath("//*[local-name()='unit']"):
        uid=u.get('id') or ''
        ms=[''.join(x.itertext()).strip() for x in u.xpath(".//*[local-name()='measure']")]
        out[uid]='|'.join(ms)
    return out

def parse_num(el):
    t=' '.join(''.join(el.itertext()).split())
    if not t or t in {'-','—','–','N/A','n/a'}:return None
    neg=('(' in t and ')' in t)
    import re
    clean=re.sub(r'[^0-9.\-]','',t)
    if clean in {'','-','.','-.'}:return None
    try:v=float(clean)
    except:return None
    if neg:v=-abs(v)
    if (el.get('sign') or '').strip()=='-':v=-abs(v)
    try:scale=int(el.get('scale') or '0')
    except:scale=0
    v*=10**scale
    return v if math.isfinite(v) else None

def collect(cik):
    audit={'cik':cik,'filings':0,'zip_ok':0,'facts':0,'error':''}
    rows=[]
    try:
        fs=parse_recent(cik);audit['filings']=len(fs)
        for f in fs:
            acc=f['accn'];ad=acc.replace('-','')
            r=get(f'https://www.sec.gov/Archives/edgar/data/{cik}/{ad}/{acc}-xbrl.zip',75)
            if r is None:continue
            audit['zip_ok']+=1
            try:z=zipfile.ZipFile(io.BytesIO(r.content))
            except:continue
            for name in z.namelist():
                if not name.lower().endswith(('.htm','.html')):continue
                try:root=etree.fromstring(z.read(name),parser=etree.XMLParser(recover=True,huge_tree=True))
                except:continue
                ctx=ctx_map(root);units=unit_map(root)
                for el in root.xpath("//*[local-name()='nonFraction']"):
                    qn=el.get('name') or ''
                    role=QMAP.get(qn)
                    if not role:continue
                    cm=ctx.get(el.get('contextRef') or '',{})
                    if cm.get('dimensioned') or cm.get('instant'):continue
                    val=parse_num(el)
                    if val is None or val<=0:continue
                    unit=units.get(el.get('unitRef') or '','').lower()
                    if 'shares' not in unit:continue
                    start=cm.get('start','');end=cm.get('end','')
                    try:days=(pd.Timestamp(end)-pd.Timestamp(start)).days+1
                    except:continue
                    q=1 if 60<=days<=125 else 2 if 126<=days<=220 else 3 if 221<=days<=320 else 4 if 321<=days<=410 else None
                    if q is None:continue
                    rows.append({'cik':cik,'accn':acc,'accepted':f['accepted'],'filed':f['filed'],'form':f['form'],'source_file':name,'qname':qn,'role':role,'start':start,'end':end,'qtrs':q,'value':val,'unit':unit})
        audit['facts']=len(rows)
    except Exception as e:audit['error']=repr(e)[:500]
    return rows,audit

allrows=[];aud=[]
for i,cik in enumerate(TARGET['ciks'],1):
    rr,aa=collect(int(cik));allrows.extend(rr);aud.append(aa)
    print('CIK',cik,'facts',len(rr),'progress',i,'/',len(TARGET['ciks']),flush=True)

d=pd.DataFrame(allrows)
if d.empty:d=pd.DataFrame(columns=['cik','accn','accepted','filed','form','source_file','qname','role','start','end','qtrs','value','unit'])
d=d.drop_duplicates(subset=['cik','accepted','role','start','end','value'])
d.to_csv(OUT/'direct_standard_share_facts.csv.gz',index=False,compression='gzip')
pd.DataFrame(aud).to_csv(OUT/'audit.csv',index=False)
summary={'schema':'V4_F4_202112_DIRECT_STANDARD_FACTS_V1','target_ciks':len(TARGET['ciks']),'fact_rows':int(len(d)),'ciks_with_facts':int(d.cik.nunique()) if len(d) else 0,'role_counts':d.role.value_counts().to_dict() if len(d) else {},'formation_2023_opened':False,'future_outcomes_used':False,'us3700_used':False,'new_corp_action_lookup_calls':0}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary,indent=2),flush=True)
