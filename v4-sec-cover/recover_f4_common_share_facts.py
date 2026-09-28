from __future__ import annotations
import csv, json, math, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import pandas as pd
import requests

ROOT=Path(".")
CAND=ROOT/"v4-sec-f34-next1-output/candidate_tag_by_cik.csv.gz"
OUT=ROOT/"v4-sec-f34-next1-output"
OUT.mkdir(parents=True,exist_ok=True)
TAG="WeightedAverageNumberOfShareOutstandingBasicAndDiluted"
FORMS={"10-Q","10-K","10-Q/A","10-K/A"}
EXCLUDED={"AAWW","ABMD","STMP"}
UA="V4-Full-Rigor-NEXT1 SEC PIT common-share recovery"
SESSION=requests.Session()
SESSION.headers.update({"User-Agent":UA,"Accept-Encoding":"gzip, deflate","Accept":"application/json"})
LOCK=threading.Lock(); LAST=[0.0]

def rate_wait():
    with LOCK:
        dt=time.monotonic()-LAST[0]
        if dt<0.13:
            time.sleep(0.13-dt)
        LAST[0]=time.monotonic()

def get_json(url,attempts=5):
    last=""
    for i in range(attempts):
        try:
            rate_wait()
            r=SESSION.get(url,timeout=45)
            if r.status_code in {429,500,502,503,504}:
                raise RuntimeError(f"HTTP_{r.status_code}")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last=repr(e)[:400]
            if i<attempts-1:
                time.sleep(min(15,1.5*(2**i)))
    raise RuntimeError(last)

def parse_acceptance_map(obj):
    if not isinstance(obj,dict): return {}
    if isinstance(obj.get("filings"),dict) and isinstance(obj["filings"].get("recent"),dict):
        a=obj["filings"]["recent"]
    else:
        a=obj
    acc=list(a.get("accessionNumber") or [])
    accepted=list(a.get("acceptanceDateTime") or [])
    form=list(a.get("form") or [])
    filing=list(a.get("filingDate") or [])
    n=max(len(acc),len(accepted),len(form),len(filing),0)
    out={}
    for i in range(n):
        ac=str(acc[i] if i<len(acc) else "").strip()
        if ac:
            out[ac]={
              "accepted":str(accepted[i] if i<len(accepted) else "").strip(),
              "sub_form":str(form[i] if i<len(form) else "").strip().upper(),
              "sub_filing_date":str(filing[i] if i<len(filing) else "").strip(),
            }
    return out

def qtrs_from_dates(start,end):
    try:
        d=(pd.Timestamp(end)-pd.Timestamp(start)).days
    except Exception:
        return None
    if 60<=d<=125: return 1
    if 150<=d<=220: return 2
    if 240<=d<=310: return 3
    if 330<=d<=400: return 4
    return None

cand=pd.read_csv(CAND,compression="gzip",low_memory=False)
cand["cik"]=pd.to_numeric(cand["cik"],errors="coerce").astype("Int64")
targets=sorted(set(cand.loc[cand["tag"].eq(TAG),"cik"].dropna().astype(int)))
print(json.dumps({"tag":TAG,"candidate_ciks":len(targets),"new_corp_action_lookup_calls":0}),flush=True)

def process(cik):
    cik10=f"{cik:010d}"
    audit={"cik":cik,"status":"OK","candidate_rows":0,"accepted_mapped":0,"accepted_missing":0,"archive_files_fetched":0,"error":""}
    try:
        cf=get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json")
        concept=(((cf.get("facts") or {}).get("us-gaap") or {}).get(TAG) or {})
        rows=[]
        for unit,arr in (concept.get("units") or {}).items():
            if str(unit).lower().strip() not in {"shares","share"} or not isinstance(arr,list):
                continue
            for r in arr:
                form=str(r.get("form") or "").upper().strip()
                filed=str(r.get("filed") or "")[:10]
                start=str(r.get("start") or "")[:10]
                end=str(r.get("end") or "")[:10]
                if form not in FORMS or not filed or filed>"2022-12-31" or not end or end>"2022-12-31" or end<"2017-01-01":
                    continue
                qtrs=qtrs_from_dates(start,end)
                if qtrs is None:
                    continue
                try:
                    val=float(r.get("val"))
                except Exception:
                    continue
                if not math.isfinite(val) or val<=0:
                    continue
                rows.append({
                  "cik":cik,"tag":TAG,"unit":str(unit),"value":val,"start":start,"end":end,"qtrs":qtrs,
                  "filed":filed,"form":form,"fp":str(r.get("fp") or ""),"fy":str(r.get("fy") or ""),
                  "frame":str(r.get("frame") or ""),"accn":str(r.get("accn") or "").strip()
                })
        audit["candidate_rows"]=len(rows)
        if not rows:
            return [],audit
        needed={r["accn"] for r in rows if r["accn"]}
        sub=get_json(f"https://data.sec.gov/submissions/CIK{cik10}.json")
        amap=parse_acceptance_map(sub)
        missing=needed-set(amap)
        files=((sub.get("filings") or {}).get("files") or []) if isinstance(sub,dict) else []
        if missing:
            minfile=min([r["filed"] for r in rows if r["filed"]] or ["2017-01-01"])
            maxfile=max([r["filed"] for r in rows if r["filed"]] or ["2022-12-31"])
            for meta in files:
                if not missing: break
                name=str(meta.get("name") or "").strip()
                frm=str(meta.get("filingFrom") or "")
                to=str(meta.get("filingTo") or "")
                if not name or (frm and frm>maxfile) or (to and to<minfile):
                    continue
                try:
                    old=get_json("https://data.sec.gov/submissions/"+name)
                    audit["archive_files_fetched"]+=1
                    amap.update(parse_acceptance_map(old))
                    missing=needed-set(amap)
                except Exception:
                    pass
        for r in rows:
            a=amap.get(r["accn"],{})
            r["accepted"]=a.get("accepted","")
            r["sub_form"]=a.get("sub_form","")
            r["sub_filing_date"]=a.get("sub_filing_date","")
            r["acceptance_mapped"]=bool(r["accepted"])
        audit["accepted_mapped"]=sum(bool(r["accepted"]) for r in rows)
        audit["accepted_missing"]=len(rows)-audit["accepted_mapped"]
        seen=set(); clean=[]
        for r in sorted(rows,key=lambda z:(z["end"],z["qtrs"],z["accepted"],z["accn"],z["value"])):
            k=(r["cik"],r["accn"],r["start"],r["end"],r["qtrs"],r["value"],r["form"])
            if k not in seen:
                seen.add(k);clean.append(r)
        return clean,audit
    except Exception as e:
        audit["status"]="ERROR"
        audit["error"]=repr(e)[:400]
        return [],audit

allrows=[];audits=[]
with ThreadPoolExecutor(max_workers=4) as ex:
    futs=[ex.submit(process,c) for c in targets]
    for i,f in enumerate(as_completed(futs),1):
        rows,a=f.result()
        allrows.extend(rows);audits.append(a)
        if i%50==0:
            print("PROGRESS",i,"/",len(targets),"facts",len(allrows),flush=True)

fields=["cik","tag","unit","value","start","end","qtrs","filed","form","fp","fy","frame","accn","accepted","sub_form","sub_filing_date","acceptance_mapped"]
with (OUT/"f4_common_basic_diluted_pit_facts.csv").open("w",newline="",encoding="utf-8") as fh:
    w=csv.DictWriter(fh,fieldnames=fields)
    w.writeheader()
    w.writerows(sorted(allrows,key=lambda r:(r["cik"],r["end"],r["qtrs"],r["accepted"],r["accn"])))
pd.DataFrame(audits).sort_values("cik").to_csv(OUT/"f4_common_basic_diluted_fetch_audit.csv",index=False)
summary={
 "schema":"V4_NEXT1_F4_COMMON_BASIC_DILUTED_PIT_V1",
 "tag":TAG,
 "semantic_basis":"SEC Company Facts definition says the average shares used in calculating both basic and diluted EPS; accepted as exact common basic=diluted share series.",
 "candidate_ciks":len(targets),
 "fact_rows":len(allrows),
 "ciks_with_facts":len({r["cik"] for r in allrows}),
 "accepted_mapped_rows":sum(bool(r["accepted"]) for r in allrows),
 "accepted_missing_rows":sum(not bool(r["accepted"]) for r in allrows),
 "fetch_errors":sum(a["status"]!="OK" for a in audits),
 "formation_2023_opened":False,
 "future_outcomes_used":False,
 "us3700_used":False,
 "corporate_action_policy":"existing-confirmed-only; no new lookup",
 "existing_corp_action_excluded_tickers":sorted(EXCLUDED),
 "new_corp_action_lookup_calls":0
}
(OUT/"f4_common_basic_diluted_summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(json.dumps(summary,indent=2),flush=True)
