from __future__ import annotations
import json,time,threading
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import pandas as pd,requests

ROOT=Path(".")
T=json.loads((ROOT/"v4-sec-cover/v22_mcap_only_targets.json").read_text())
OUT=ROOT/"v4-v22-mcap-sec-output";OUT.mkdir(exist_ok=True)
FORMS={"10-Q","10-K","10-Q/A","10-K/A","20-F","20-F/A","40-F","40-F/A"}
S=requests.Session();S.headers.update({"User-Agent":"V4 V22 mcap-only exact shares research@example.com","Accept-Encoding":"gzip, deflate","Accept":"application/json"})
LOCK=threading.Lock();LAST=[0.0]

def wait():
    with LOCK:
        dt=time.monotonic()-LAST[0]
        if dt<0.14:time.sleep(0.14-dt)
        LAST[0]=time.monotonic()

def gj(url,attempts=5):
    last=""
    for i in range(attempts):
        try:
            wait();r=S.get(url,timeout=45)
            if r.status_code in {429,500,502,503,504}:raise RuntimeError(f"HTTP_{r.status_code}")
            r.raise_for_status();return r.json()
        except Exception as e:
            last=repr(e)[:300]
            if i<attempts-1:time.sleep(min(15,1.5*(2**i)))
    raise RuntimeError(last)

def block_map(a):
    out={};acc=a.get("accessionNumber") or [];ac=a.get("acceptanceDateTime") or [];fm=a.get("form") or [];fd=a.get("filingDate") or []
    for i,x in enumerate(acc):
        out[str(x)]={"accepted":str(ac[i] if i<len(ac) else ""),"sub_form":str(fm[i] if i<len(fm) else ""),"sub_filing_date":str(fd[i] if i<len(fd) else "")}
    return out

def acceptance_map(sub):
    out=block_map(((sub.get("filings") or {}).get("recent") or {}))
    for meta in ((sub.get("filings") or {}).get("files") or []):
        frm=str(meta.get("filingFrom") or "");to=str(meta.get("filingTo") or "");name=str(meta.get("name") or "")
        if not name:continue
        if frm and frm>"2022-12-30":continue
        if to and to<"2017-01-01":continue
        try:out.update(block_map(gj("https://data.sec.gov/submissions/"+name)))
        except Exception:pass
    return out

def one(cik):
    audit={"cik":cik,"status":"OK","facts":0,"error":""};rows=[]
    try:
        cf=gj(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
        sub=gj(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        amap=acceptance_map(sub)
        specs=[("dei","EntityCommonStockSharesOutstanding","DEI_ENTITY_COMMON_SHARES"),
               ("us-gaap","CommonStockSharesOutstanding","USGAAP_COMMON_SHARES")]
        facts=cf.get("facts") or {}
        for ns,tag,role in specs:
            con=((facts.get(ns) or {}).get(tag) or {})
            for unit,items in (con.get("units") or {}).items():
                if str(unit).lower().strip() not in {"shares","share"} or not isinstance(items,list):continue
                for r in items:
                    form=str(r.get("form") or "").upper().strip()
                    if form not in FORMS:continue
                    end=str(r.get("end") or "")[:10];filed=str(r.get("filed") or "")[:10];accn=str(r.get("accn") or "")
                    if not end or end<"2017-01-01" or end>"2022-12-30":continue
                    if filed and filed>"2022-12-30":continue
                    try:val=float(r.get("val"))
                    except:continue
                    if val<=0:continue
                    a=amap.get(accn,{})
                    accepted=str(a.get("accepted") or "")
                    if not accepted or accepted[:10]>"2022-12-30":continue
                    rows.append({"cik":cik,"entity_name":str(cf.get("entityName") or ""),"namespace":ns,"tag":tag,"role":role,
                                 "unit":unit,"value":val,"end":end,"filed":filed,"form":form,"fp":str(r.get("fp") or ""),
                                 "fy":str(r.get("fy") or ""),"frame":str(r.get("frame") or ""),"accn":accn,"accepted":accepted})
        audit["facts"]=len(rows)
    except Exception as e:
        audit["status"]="ERROR";audit["error"]=repr(e)[:500]
    return rows,audit

rows=[];aud=[]
with ThreadPoolExecutor(max_workers=6) as ex:
    futs=[ex.submit(one,int(c)) for c in T["ciks"]]
    for i,f in enumerate(as_completed(futs),1):
        rr,aa=f.result();rows.extend(rr);aud.append(aa)
        if i%10==0:print("PROGRESS",i,"/",len(T["ciks"]),"facts",len(rows),flush=True)
d=pd.DataFrame(rows)
if d.empty:d=pd.DataFrame(columns=["cik","entity_name","namespace","tag","role","unit","value","end","filed","form","fp","fy","frame","accn","accepted"])
d=d.drop_duplicates(["cik","namespace","tag","value","end","accn"])
d.to_csv(OUT/"exact_share_facts.csv.gz",index=False,compression="gzip")
pd.DataFrame(aud).to_csv(OUT/"audit.csv",index=False)
summary={"schema":"V4_V22_MCAP_ONLY_SEC_EXACT_SHARES_V1","target_ciks":len(T["ciks"]),"fact_rows":len(d),
         "ciks_with_facts":int(d.cik.nunique()) if len(d) else 0,"fetch_errors":sum(x["status"]!="OK" for x in aud),
         "formation_2023_opened":False,"future_outcomes_used":False,"us3700_used":False,"new_corp_action_lookup_calls":0}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(json.dumps(summary,indent=2),flush=True)
