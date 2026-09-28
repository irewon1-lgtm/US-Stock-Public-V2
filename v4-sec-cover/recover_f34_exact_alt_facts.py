from __future__ import annotations
import csv, json, math, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
import requests

ROOT=Path(".")
TARGETS=ROOT/"v4-sec-cover/next1_missing_f34_target_ciks.json"
EXCLUSIONS=ROOT/"v4-sec-cover/existing_corp_action_exclusions.json"
OUT=ROOT/"v4-sec-f34-exact-alt-output"
OUT.mkdir(parents=True,exist_ok=True)

UA="V4-Full-Rigor-NEXT1 exact-semantic SEC PIT recovery"
FORMS={"10-Q","10-K","10-Q/A","10-K/A"}
TAGS={
    "WeightedAverageNumberOfShareOutstandingBasicAndDiluted":"SHARES_BASIC_DILUTED_COMBINED",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations":"CFO_CONTINUING",
    "CashProvidedByUsedInOperatingActivitiesDiscontinuedOperations":"CFO_DISCONTINUED",
    "RegulatedAndUnregulatedOperatingRevenue":"REVENUE_TOTAL_OPERATING",
    "WeightedAverageNumberDilutedSharesOutstandingAdjustment":"DILUTED_SHARES_ADJUSTMENT",
}
SESSION=requests.Session()
SESSION.headers.update({"User-Agent":UA,"Accept-Encoding":"gzip, deflate","Accept":"application/json"})
RATE_LOCK=threading.Lock(); LAST=[0.0]

def rate_wait():
    with RATE_LOCK:
        dt=time.monotonic()-LAST[0]
        if dt<0.13: time.sleep(0.13-dt)
        LAST[0]=time.monotonic()

def get_json(url, attempts=5):
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
            if i<attempts-1: time.sleep(min(20,1.5*(2**i)))
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
        if not ac: continue
        out[ac]={
            "accepted":str(accepted[i] if i<len(accepted) else "").strip(),
            "sub_form":str(form[i] if i<len(form) else "").strip().upper(),
            "sub_filing_date":str(filing[i] if i<len(filing) else "").strip(),
        }
    return out

def approx_qtrs(start,end):
    try:
        s=datetime.strptime(start[:10],"%Y-%m-%d")
        e=datetime.strptime(end[:10],"%Y-%m-%d")
        days=(e-s).days+1
    except Exception:
        return "", ""
    if 60<=days<=125: q=1
    elif 126<=days<=220: q=2
    elif 221<=days<=320: q=3
    elif 321<=days<=410: q=4
    else: q=""
    return days,q

target_meta=json.loads(TARGETS.read_text(encoding="utf-8"))
policy=json.loads(EXCLUSIONS.read_text(encoding="utf-8"))
if policy.get("new_corp_action_lookup_allowed") is not False:
    raise RuntimeError("Corporate-action lookup policy must remain disabled")
TARGET_CIKS=sorted(set(int(x) for x in target_meta["ciks"]))
EXCLUDED=set(str(x).upper() for x in policy["tickers"])

def collect_companyfacts(cik):
    cik10=f"{int(cik):010d}"
    audit={"cik":int(cik),"status":"OK","raw_candidate_facts":0,"accepted_mapped":0,"accepted_missing":0,"archive_files_fetched":0,"error":""}
    try:
        cf=get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json")
        us=((cf.get("facts") or {}).get("us-gaap") or {})
        rows=[]
        for tag,role in TAGS.items():
            concept=us.get(tag) or {}
            units=concept.get("units") or {}
            for unit,items in units.items():
                if str(unit).lower().strip() not in {"usd","shares","share"} or not isinstance(items,list):
                    continue
                for r in items:
                    form=str(r.get("form") or "").upper().strip()
                    filed=str(r.get("filed") or "")[:10]
                    start=str(r.get("start") or "")[:10]
                    end=str(r.get("end") or "")[:10]
                    accn=str(r.get("accn") or "").strip()
                    if form not in FORMS: continue
                    if not filed or filed>"2022-12-31": continue
                    if not end or end>"2022-12-31" or end<"2017-01-01": continue
                    try: val=float(r.get("val"))
                    except Exception: continue
                    if not math.isfinite(val): continue
                    days,q=approx_qtrs(start,end)
                    rows.append({
                        "cik":int(cik),"entity_name":str(cf.get("entityName") or ""),
                        "tag":tag,"role":role,"unit":str(unit),"value":val,
                        "start":start,"end":end,"duration_days":days,"qtrs_approx":q,
                        "filed":filed,"form":form,"fp":str(r.get("fp") or ""),
                        "fy":str(r.get("fy") or ""),"frame":str(r.get("frame") or ""),
                        "accn":accn,
                    })
        audit["raw_candidate_facts"]=len(rows)
        if not rows: return [],audit
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
            r["accepted_mapped"]=bool(r["accepted"])
        audit["accepted_mapped"]=sum(bool(r["accepted"]) for r in rows)
        audit["accepted_missing"]=len(rows)-audit["accepted_mapped"]
        return rows,audit
    except Exception as e:
        audit["status"]="ERROR"; audit["error"]=repr(e)[:400]
        return [],audit

allrows=[];audits=[]
with ThreadPoolExecutor(max_workers=6) as ex:
    futs={ex.submit(collect_companyfacts,c):c for c in TARGET_CIKS}
    for i,f in enumerate(as_completed(futs),1):
        rows,a=f.result();allrows.extend(rows);audits.append(a)
        if i%100==0:
            print("PROGRESS",i,"/",len(TARGET_CIKS),"facts",len(allrows),flush=True)

fields=["cik","entity_name","tag","role","unit","value","start","end","duration_days","qtrs_approx","filed","form","fp","fy","frame","accn","accepted","sub_form","sub_filing_date","accepted_mapped"]
with (OUT/"exact_alt_facts.csv").open("w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(sorted(allrows,key=lambda r:(r["cik"],r["role"],r["end"],r["accepted"],r["accn"])))
afields=["cik","status","raw_candidate_facts","accepted_mapped","accepted_missing","archive_files_fetched","error"]
with (OUT/"fetch_audit.csv").open("w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=afields);w.writeheader();w.writerows(sorted(audits,key=lambda r:r["cik"]))

by_role={}
for role in TAGS.values():
    rr=[r for r in allrows if r["role"]==role]
    by_role[role]={"rows":len(rr),"ciks":len({r["cik"] for r in rr}),"accepted_mapped":sum(bool(r["accepted"]) for r in rr)}
summary={
    "schema":"V4_NEXT1_SEC_EXACT_ALT_FACTS_V1",
    "target_ciks":len(TARGET_CIKS),
    "existing_corp_action_excluded_tickers":sorted(EXCLUDED),
    "new_corp_action_lookup_calls":0,
    "formation_2023_opened":False,
    "future_outcomes_used":False,
    "us3700_used":False,
    "source":"SEC data.sec.gov companyfacts + submissions accepted timestamps",
    "approved_exact_or_exactly_composable_roles":{
        "SHARES_BASIC_DILUTED_COMBINED":"single reported weighted-average value explicitly used for both basic and diluted EPS",
        "BASIC_PLUS_DILUTED_ADJUSTMENT":"basic weighted-average shares plus the reported dilutive potential-share adjustment reconstructs diluted weighted-average shares",
        "CFO_CONTINUING_PLUS_CFO_DISCONTINUED":"sum only when both components align to same duration/end; reconstructs total operating cash flow",
        "REVENUE_TOTAL_OPERATING":"RegulatedAndUnregulatedOperatingRevenue definition states total operating revenues"
    },
    "rejected_for_final_mapping":[
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations alone",
        "PaymentsToAcquireProductiveAssets",
        "component revenue tags without proven exhaustive aggregation"
    ],
    "by_role":by_role,
    "fetch_errors":sum(a["status"]!="OK" for a in audits),
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(json.dumps(summary,indent=2),flush=True)
