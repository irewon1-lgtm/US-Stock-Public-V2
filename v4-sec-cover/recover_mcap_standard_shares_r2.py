from __future__ import annotations
import json, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import pandas as pd, requests

ROOT=Path(".")
TARGET=json.loads((ROOT/"v4-sec-cover/mcap_standard_shares_targets_r2.json").read_text())
OUT=ROOT/"v4-sec-mcap-standard-shares-r2-output"; OUT.mkdir(exist_ok=True)
FORMS={"10-Q","10-K","10-Q/A","10-K/A","20-F","20-F/A","40-F","40-F/A"}
TAG="CommonStockSharesOutstanding"
UA="V4-Full-Rigor market-cap standard shares research@example.com"
S=requests.Session();S.headers.update({"User-Agent":UA,"Accept-Encoding":"gzip, deflate","Accept":"application/json"})
LOCK=threading.Lock();LAST=[0.0]

def rate_wait():
    with LOCK:
        dt=time.monotonic()-LAST[0]
        if dt<0.14: time.sleep(0.14-dt)
        LAST[0]=time.monotonic()

def get_json(url,attempts=5):
    last=""
    for i in range(attempts):
        try:
            rate_wait(); r=S.get(url,timeout=45)
            if r.status_code in {429,500,502,503,504}: raise RuntimeError(f"HTTP_{r.status_code}")
            r.raise_for_status(); return r.json()
        except Exception as e:
            last=repr(e)[:400]
            if i<attempts-1: time.sleep(min(15,1.5*(2**i)))
    raise RuntimeError(last)

def parse_acceptance(obj):
    a=((obj.get("filings") or {}).get("recent") or {}) if isinstance(obj,dict) else {}
    acc=a.get("accessionNumber") or []; ac=a.get("acceptanceDateTime") or []; fm=a.get("form") or []; fd=a.get("filingDate") or []
    out={}
    for i,x in enumerate(acc):
        out[str(x)]={"accepted":str(ac[i] if i<len(ac) else ""),"sub_form":str(fm[i] if i<len(fm) else ""),"sub_filing_date":str(fd[i] if i<len(fd) else "")}
    return out

def one(cik):
    audit={"cik":cik,"status":"OK","fact_rows":0,"accepted_mapped":0,"error":""}; rows=[]
    try:
        cf=get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
        sub=get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        amap=parse_acceptance(sub)
        concept=(((cf.get("facts") or {}).get("us-gaap") or {}).get(TAG) or {})
        for unit,items in (concept.get("units") or {}).items():
            if str(unit).lower().strip() not in {"shares","share"} or not isinstance(items,list): continue
            for r in items:
                form=str(r.get("form") or "").upper().strip()
                if form not in FORMS: continue
                filed=str(r.get("filed") or "")[:10]; end=str(r.get("end") or "")[:10]; accn=str(r.get("accn") or "").strip()
                if not end or end<"2017-01-01" or end>"2022-12-30": continue
                if filed and filed>"2022-12-30": continue
                try: val=float(r.get("val"))
                except: continue
                if val<=0: continue
                a=amap.get(accn,{})
                accepted=str(a.get("accepted") or "")
                if not accepted or accepted[:10]>"2022-12-30": continue
                rows.append({"cik":cik,"entity_name":str(cf.get("entityName") or ""),"tag":TAG,"unit":unit,"value":val,"end":end,"filed":filed,"form":form,"fp":str(r.get("fp") or ""),"fy":str(r.get("fy") or ""),"frame":str(r.get("frame") or ""),"accn":accn,"accepted":accepted,"sub_form":a.get("sub_form",""),"sub_filing_date":a.get("sub_filing_date","")})
        audit["fact_rows"]=len(rows);audit["accepted_mapped"]=len(rows)
    except Exception as e:
        audit["status"]="ERROR";audit["error"]=repr(e)[:400]
    return rows,audit

allrows=[];aud=[]
with ThreadPoolExecutor(max_workers=6) as ex:
    futs={ex.submit(one,int(c)):int(c) for c in TARGET["ciks"]}
    for i,f in enumerate(as_completed(futs),1):
        rr,aa=f.result();allrows.extend(rr);aud.append(aa)
        if i%10==0: print("PROGRESS",i,"/",len(TARGET["ciks"]),"facts",len(allrows),flush=True)
d=pd.DataFrame(allrows)
if d.empty:d=pd.DataFrame(columns=["cik","entity_name","tag","unit","value","end","filed","form","fp","fy","frame","accn","accepted","sub_form","sub_filing_date"])
d=d.drop_duplicates(subset=["cik","value","end","accn"])
d.to_csv(OUT/"common_stock_shares_outstanding_facts.csv.gz",index=False,compression="gzip")
pd.DataFrame(aud).to_csv(OUT/"audit.csv",index=False)
summary={"schema":"V4_MCAP_STANDARD_SHARES_RECOVERY_R2_V1","target_ciks":len(TARGET["ciks"]),"fact_rows":int(len(d)),"ciks_with_facts":int(d.cik.nunique()) if len(d) else 0,"fetch_errors":sum(x["status"]!="OK" for x in aud),"formation_2023_opened":False,"future_outcomes_used":False,"us3700_used":False,"new_corp_action_lookup_calls":0}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(json.dumps(summary,indent=2),flush=True)
