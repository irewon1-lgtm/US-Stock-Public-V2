from __future__ import annotations
import json,time,threading
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import pandas as pd,requests

ROOT=Path(".")
T=json.loads((ROOT/"v4-sec-cover/mcap_companyfacts_retry_targets.json").read_text())
OUT=ROOT/"v4-sec-mcap-companyfacts-retry-output";OUT.mkdir(exist_ok=True)
TAGS={"EntityCommonStockSharesOutstanding":"DEI_ENTITY_COMMON_SHARES","CommonStockSharesOutstanding":"USGAAP_COMMON_SHARES"}
FORMS={"10-Q","10-K","10-Q/A","10-K/A","20-F","20-F/A","40-F","40-F/A"}
UA="V4-Full-Rigor mcap companyfacts retry research@example.com"
S=requests.Session();S.headers.update({"User-Agent":UA,"Accept-Encoding":"gzip, deflate","Accept":"application/json"})
LOCK=threading.Lock();LAST=[0.0]
def wait():
    with LOCK:
        dt=time.monotonic()-LAST[0]
        if dt<0.16: time.sleep(0.16-dt)
        LAST[0]=time.monotonic()
def getj(url):
    last=""
    for i in range(5):
        try:
            wait();r=S.get(url,timeout=45)
            if r.status_code in {429,500,502,503,504}:raise RuntimeError(f"HTTP_{r.status_code}")
            r.raise_for_status();return r.json()
        except Exception as e:
            last=repr(e)
            if i<4:time.sleep(min(15,1.5*(2**i)))
    raise RuntimeError(last)
def amap(sub):
    a=((sub.get("filings") or {}).get("recent") or {})
    out={}
    acc=a.get("accessionNumber") or [];ac=a.get("acceptanceDateTime") or [];fm=a.get("form") or [];fd=a.get("filingDate") or []
    for i,x in enumerate(acc):
        out[str(x)]={"accepted":str(ac[i] if i<len(ac) else ""),"sub_form":str(fm[i] if i<len(fm) else ""),"sub_filing_date":str(fd[i] if i<len(fd) else "")}
    return out
def one(cik):
    rows=[];audit={"cik":cik,"status":"OK","rows":0,"error":""}
    try:
        cf=getj(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
        sub=getj(f"https://data.sec.gov/submissions/CIK{cik:010d}.json");mp=amap(sub)
        facts=cf.get("facts") or {}
        for ns in ["dei","us-gaap"]:
            d=facts.get(ns) or {}
            for tag,role in TAGS.items():
                con=d.get(tag)
                if not con:continue
                for unit,items in (con.get("units") or {}).items():
                    if str(unit).lower() not in {"share","shares"} or not isinstance(items,list):continue
                    for r in items:
                        form=str(r.get("form") or "").upper()
                        if form not in FORMS:continue
                        end=str(r.get("end") or "")[:10];filed=str(r.get("filed") or "")[:10];accn=str(r.get("accn") or "")
                        if not end or end<"2017-01-01" or end>"2022-12-30":continue
                        if filed and filed>"2022-12-30":continue
                        try:val=float(r.get("val"))
                        except:continue
                        if val<=0:continue
                        a=mp.get(accn,{})
                        accepted=str(a.get("accepted") or "")
                        if not accepted or accepted[:10]>"2022-12-30":continue
                        rows.append({"cik":cik,"namespace":ns,"tag":tag,"role":role,"unit":unit,"value":val,"end":end,"filed":filed,"form":form,"fp":str(r.get("fp") or ""),"fy":str(r.get("fy") or ""),"frame":str(r.get("frame") or ""),"accn":accn,"accepted":accepted})
        audit["rows"]=len(rows)
    except Exception as e:
        audit["status"]="ERROR";audit["error"]=repr(e)[:500]
    return rows,audit
allr=[];auds=[]
with ThreadPoolExecutor(max_workers=5) as ex:
    futs={ex.submit(one,int(c)):int(c) for c in T["ciks"]}
    for i,f in enumerate(as_completed(futs),1):
        rr,aa=f.result();allr.extend(rr);auds.append(aa)
        if i%10==0:print("PROGRESS",i,"/",len(T["ciks"]),"rows",len(allr),flush=True)
d=pd.DataFrame(allr)
if d.empty:d=pd.DataFrame(columns=["cik","namespace","tag","role","unit","value","end","filed","form","fp","fy","frame","accn","accepted"])
d=d.drop_duplicates(subset=["cik","namespace","tag","value","end","accn"])
d.to_csv(OUT/"standard_share_facts.csv.gz",index=False,compression="gzip")
pd.DataFrame(auds).to_csv(OUT/"audit.csv",index=False)
summary={"schema":"V4_MCAP_COMPANYFACTS_RETRY_V1","target_ciks":len(T["ciks"]),"fact_rows":len(d),"ciks_with_facts":int(d.cik.nunique()) if len(d) else 0,"errors":sum(x["status"]!="OK" for x in auds),"formation_2023_opened":False,"future_outcomes_used":False,"us3700_used":False,"new_corp_action_lookup_calls":0}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))
