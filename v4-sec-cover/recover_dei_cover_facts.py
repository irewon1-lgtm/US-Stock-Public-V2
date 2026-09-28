from __future__ import annotations
import csv, json, math, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
import requests

ROOT=Path("v4-sec-cover")
OUT=Path("v4-sec-cover-output")
OUT.mkdir(parents=True,exist_ok=True)
CIKS=json.loads((ROOT/"target_ciks.json").read_text())["ciks"]
UA="V4-Free-Research outcome-free SEC recovery"
FORMS={"10-Q","10-K","10-Q/A","10-K/A","20-F","20-F/A","40-F","40-F/A"}
SESSION=requests.Session()
SESSION.headers.update({"User-Agent":UA,"Accept-Encoding":"gzip, deflate","Accept":"application/json"})
RATE_LOCK=threading.Lock()
LAST=[0.0]

def rate_wait():
    with RATE_LOCK:
        dt=time.monotonic()-LAST[0]
        if dt<0.13:
            time.sleep(0.13-dt)
        LAST[0]=time.monotonic()

def get_json(url, attempts=4):
    last=""
    for i in range(attempts):
        try:
            rate_wait()
            r=SESSION.get(url,timeout=35)
            if r.status_code in {429,500,502,503,504}:
                raise RuntimeError(f"HTTP_{r.status_code}")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last=repr(e)[:300]
            if i<attempts-1:
                time.sleep(min(12,1.5*(2**i)))
    raise RuntimeError(last)

def safe_date(x):
    s=str(x or "")[:10]
    return s if len(s)==10 else ""

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
        if not ac: continue
        out[ac]={
            "accepted":str(accepted[i] if i<len(accepted) else "").strip(),
            "sub_form":str(form[i] if i<len(form) else "").strip().upper(),
            "sub_filing_date":str(filing[i] if i<len(filing) else "").strip(),
        }
    return out

def dei_rows(cf,cik):
    facts=((cf.get("facts") or {}).get("dei") or {})
    concept=facts.get("EntityCommonStockSharesOutstanding") or {}
    units=concept.get("units") or {}
    out=[]
    for unit,rows in units.items():
        if str(unit).lower().strip() not in {"shares","share"} or not isinstance(rows,list):
            continue
        for r in rows:
            try:
                val=float(r.get("val"))
            except Exception:
                continue
            if not math.isfinite(val) or val<=0: continue
            form=str(r.get("form") or "").upper().strip()
            if form and form not in FORMS: continue
            end=safe_date(r.get("end"))
            if not end or end>"2022-12-31": continue
            # Keep enough pre-history to support the first 2020 formation.
            if end<"2017-01-01": continue
            out.append({
                "cik":int(cik),
                "entity_name":str(cf.get("entityName") or ""),
                "tag":"EntityCommonStockSharesOutstanding",
                "unit":str(unit),
                "value":val,
                "end":end,
                "filed":safe_date(r.get("filed")),
                "form":form,
                "fp":str(r.get("fp") or ""),
                "fy":str(r.get("fy") or ""),
                "frame":str(r.get("frame") or ""),
                "accn":str(r.get("accn") or "").strip(),
            })
    # exact duplicate collapse only; selection is done later per formation.
    seen=set(); clean=[]
    for r in sorted(out,key=lambda z:(z["end"],z["filed"],z["accn"],z["value"])):
        k=(r["cik"],r["accn"],r["end"],r["value"],r["form"])
        if k not in seen:
            seen.add(k); clean.append(r)
    return clean

def process_cik(cik):
    cik10=f"{int(cik):010d}"
    audit={"cik":int(cik),"status":"OK","companyfacts_rows":0,"accepted_mapped":0,"accepted_missing":0,"archive_files_fetched":0,"error":""}
    try:
        cf=get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json")
        rows=dei_rows(cf,cik)
        audit["companyfacts_rows"]=len(rows)
        if not rows:
            return [],audit
        needed={r["accn"] for r in rows if r["accn"]}
        sub=get_json(f"https://data.sec.gov/submissions/CIK{cik10}.json")
        amap=parse_acceptance_map(sub)
        missing=needed-set(amap)
        # Fetch only historical submission pages that overlap the candidate filing window.
        files=((sub.get("filings") or {}).get("files") or []) if isinstance(sub,dict) else []
        if missing:
            minfile=min([r["filed"] for r in rows if r["filed"]] or ["2017-01-01"])
            maxfile=max([r["filed"] for r in rows if r["filed"]] or ["2023-01-31"])
            for meta in files:
                if not missing: break
                name=str(meta.get("name") or "").strip()
                frm=str(meta.get("filingFrom") or "")
                to=str(meta.get("filingTo") or "")
                if not name: continue
                if frm and frm>maxfile: continue
                if to and to<minfile: continue
                try:
                    old=get_json("https://data.sec.gov/submissions/"+name)
                    audit["archive_files_fetched"]+=1
                    amap.update(parse_acceptance_map(old))
                    missing=needed-set(amap)
                except Exception:
                    continue
        for r in rows:
            a=amap.get(r["accn"],{})
            r["accepted"]=a.get("accepted","")
            r["sub_form"]=a.get("sub_form","")
            r["sub_filing_date"]=a.get("sub_filing_date","")
            r["acceptance_mapped"]=bool(r["accepted"])
        audit["accepted_mapped"]=sum(bool(r["accepted"]) for r in rows)
        audit["accepted_missing"]=len(rows)-audit["accepted_mapped"]
        return rows,audit
    except Exception as e:
        audit["status"]="ERROR"; audit["error"]=repr(e)[:400]
        return [],audit

allrows=[]; audits=[]
with ThreadPoolExecutor(max_workers=4) as ex:
    futs={ex.submit(process_cik,c):c for c in CIKS}
    for i,f in enumerate(as_completed(futs),1):
        rows,a=f.result(); allrows.extend(rows); audits.append(a)
        if i%25==0:
            print("PROGRESS",i,"/",len(CIKS),"facts",len(allrows),flush=True)

fields=["cik","entity_name","tag","unit","value","end","filed","form","fp","fy","frame","accn","accepted","sub_form","sub_filing_date","acceptance_mapped"]
with (OUT/"dei_cover_share_facts.csv").open("w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(sorted(allrows,key=lambda r:(r["cik"],r["end"],r["accepted"],r["accn"])))
afields=["cik","status","companyfacts_rows","accepted_mapped","accepted_missing","archive_files_fetched","error"]
with (OUT/"sec_cover_fetch_audit.csv").open("w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=afields); w.writeheader(); w.writerows(sorted(audits,key=lambda r:r["cik"]))
summary={
 "schema":"V4_SEC_DEI_COVER_FACT_RECOVERY_V1",
 "purpose":"Outcome-free market-cap eligibility recovery only.",
 "target_ciks":len(CIKS),
 "fact_rows":len(allrows),
 "ciks_with_facts":len({r["cik"] for r in allrows}),
 "accepted_mapped_rows":sum(bool(r["accepted"]) for r in allrows),
 "accepted_missing_rows":sum(not bool(r["accepted"]) for r in allrows),
 "cik_errors":sum(a["status"]!="OK" for a in audits),
 "forms":sorted(FORMS),
 "selection_note":"Only dei:EntityCommonStockSharesOutstanding is extracted. No weighted-average shares and no us-gaap class aggregation. Snapshot selection occurs later with accession acceptance cutoff."
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(json.dumps(summary,indent=2),flush=True)
