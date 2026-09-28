from __future__ import annotations
import csv, json, math, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import pandas as pd
import requests

ROOT=Path(".")
UNIVERSE=ROOT/"v3-fast/price_universe_resolved.csv.gz"
TARGETS=ROOT/"v4-sec-cover/next1_missing_f34_target_ciks.json"
EXCLUSIONS=ROOT/"v4-sec-cover/existing_corp_action_exclusions.json"
OUT=ROOT/"v4-sec-f34-approved-alt-output"
OUT.mkdir(parents=True,exist_ok=True)

UA="V4-Full-Rigor-NEXT1 approved SEC alt facts"
FORMS={"10-Q","10-K","10-Q/A","10-K/A"}
# Only semantically defensible total-role alternatives are allowed.
APPROVED={
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations":("CFO",2,"CONTINUING_OPS_CFO"),
    "PaymentsToAcquireProductiveAssets":("CAPEX",2,"PRODUCTIVE_ASSETS"),
    "PaymentsForAdditionsToPropertyPlantAndEquipment":("CAPEX",3,"PP&E_ADDITIONS"),
    "PaymentsToAcquireOilAndGasPropertyAndEquipment":("CAPEX",4,"OIL_GAS_PROPERTY_EQUIPMENT"),
    "WeightedAverageNumberOfShareOutstandingBasicAndDiluted":("DILUTED_SHARES",2,"BASIC_AND_DILUTED_COMBINED"),
    "RegulatedAndUnregulatedOperatingRevenue":("REVENUE",5,"TOTAL_REGULATED_AND_UNREGULATED_OPERATING_REVENUE"),
    "HealthCareOrganizationRevenue":("REVENUE",6,"TOTAL_HEALTHCARE_ORG_REVENUE"),
    "HealthCareOrganizationRevenueNetOfPatientServiceRevenueProvisions":("REVENUE",7,"TOTAL_HEALTHCARE_ORG_REVENUE_NET_PROVISIONS"),
}
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
                time.sleep(min(20,1.5*(2**i)))
    raise RuntimeError(last)

def safe_date(x):
    s=str(x or "")[:10]
    return s if len(s)==10 else ""

def parse_acceptance_map(obj):
    if not isinstance(obj,dict):
        return {}
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
        if not ac:
            continue
        out[ac]={
            "accepted":str(accepted[i] if i<len(accepted) else "").strip(),
            "sub_form":str(form[i] if i<len(form) else "").strip().upper(),
            "sub_filing_date":str(filing[i] if i<len(filing) else "").strip(),
        }
    return out

u=pd.read_csv(UNIVERSE,dtype=str,keep_default_na=False,compression="gzip",low_memory=False)
years=pd.to_datetime(u["snapshot_date"],errors="coerce").dt.year
if years.ge(2023).any():
    raise RuntimeError("REFUSED: 2023+ formation present")
u["ticker_norm"]=u["ticker_at_snapshot"].astype(str).str.upper().str.strip()
u["cik_num"]=pd.to_numeric(u["cik"],errors="coerce").astype("Int64")
policy=json.loads(EXCLUSIONS.read_text(encoding="utf-8"))
excluded=set(str(x).upper().strip() for x in policy["tickers"])
if policy.get("new_corp_action_lookup_allowed") is not False:
    raise RuntimeError("Corporate-action policy must forbid new lookup")
u=u[~u["ticker_norm"].isin(excluded)].copy()
available=set(u["cik_num"].dropna().astype(int))
target_meta=json.loads(TARGETS.read_text(encoding="utf-8"))
TARGET_CIKS=sorted(set(int(x) for x in target_meta["ciks"]) & available)

def collect_rows(cf,cik):
    us=((cf.get("facts") or {}).get("us-gaap") or {})
    out=[]
    for tag,(role,priority,semantic_basis) in APPROVED.items():
        concept=us.get(tag) or {}
        units=concept.get("units") or {}
        for unit,rows in units.items():
            unit_norm=str(unit).lower().strip()
            want={"shares","share"} if role=="DILUTED_SHARES" else {"usd"}
            if unit_norm not in want or not isinstance(rows,list):
                continue
            for r in rows:
                try:
                    val=float(r.get("val"))
                except Exception:
                    continue
                if not math.isfinite(val):
                    continue
                if role=="DILUTED_SHARES" and val<=0:
                    continue
                form=str(r.get("form") or "").upper().strip()
                filed=safe_date(r.get("filed"))
                end=safe_date(r.get("end"))
                start=safe_date(r.get("start"))
                if form not in FORMS:
                    continue
                if not filed or filed>"2022-12-31":
                    continue
                if end and (end>"2022-12-31" or end<"2017-01-01"):
                    continue
                accn=str(r.get("accn") or "").strip()
                if not accn:
                    continue
                # qtrs is reconstructed later from start/end if companyfacts has no qtrs field.
                out.append({
                    "cik":int(cik),
                    "entity_name":str(cf.get("entityName") or ""),
                    "tag":tag,
                    "fact_role":role,
                    "tag_priority":priority,
                    "semantic_basis":semantic_basis,
                    "unit":str(unit),
                    "value":val,
                    "start":start,
                    "end":end,
                    "filed":filed,
                    "form":form,
                    "fp":str(r.get("fp") or ""),
                    "fy":str(r.get("fy") or ""),
                    "frame":str(r.get("frame") or ""),
                    "accn":accn,
                })
    # exact duplicate collapse
    seen=set(); clean=[]
    for r in sorted(out,key=lambda z:(z["tag"],z["end"],z["filed"],z["accn"],z["value"])):
        k=(r["cik"],r["tag"],r["accn"],r["start"],r["end"],r["value"],r["form"])
        if k not in seen:
            seen.add(k); clean.append(r)
    return clean

def process_cik(cik):
    cik10=f"{int(cik):010d}"
    audit={"cik":int(cik),"status":"OK","fact_rows":0,"accepted_mapped":0,"accepted_missing":0,"archive_files_fetched":0,"error":""}
    try:
        cf=get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json")
        rows=collect_rows(cf,cik)
        audit["fact_rows"]=len(rows)
        if not rows:
            return [],audit
        needed={r["accn"] for r in rows}
        sub=get_json(f"https://data.sec.gov/submissions/CIK{cik10}.json")
        amap=parse_acceptance_map(sub)
        missing=needed-set(amap)
        files=((sub.get("filings") or {}).get("files") or []) if isinstance(sub,dict) else []
        if missing:
            minfile=min([r["filed"] for r in rows if r["filed"]] or ["2017-01-01"])
            maxfile=max([r["filed"] for r in rows if r["filed"]] or ["2022-12-31"])
            for meta in files:
                if not missing:
                    break
                name=str(meta.get("name") or "").strip()
                frm=str(meta.get("filingFrom") or "")
                to=str(meta.get("filingTo") or "")
                if not name:
                    continue
                if frm and frm>maxfile:
                    continue
                if to and to<minfile:
                    continue
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
        audit["status"]="ERROR"
        audit["error"]=repr(e)[:400]
        return [],audit

allrows=[]; audits=[]
with ThreadPoolExecutor(max_workers=4) as ex:
    futs={ex.submit(process_cik,c):c for c in TARGET_CIKS}
    for i,f in enumerate(as_completed(futs),1):
        rows,a=f.result()
        allrows.extend(rows); audits.append(a)
        if i%100==0:
            print("PROGRESS",i,"/",len(TARGET_CIKS),"facts",len(allrows),flush=True)

fields=["cik","entity_name","tag","fact_role","tag_priority","semantic_basis","unit","value","start","end","filed","form","fp","fy","frame","accn","accepted","sub_form","sub_filing_date","acceptance_mapped"]
with (OUT/"approved_alt_facts.csv").open("w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(sorted(allrows,key=lambda r:(r["cik"],r["tag"],r["end"],r["accepted"],r["accn"])))
afields=["cik","status","fact_rows","accepted_mapped","accepted_missing","archive_files_fetched","error"]
with (OUT/"fetch_audit.csv").open("w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=afields); w.writeheader(); w.writerows(sorted(audits,key=lambda r:r["cik"]))

by_tag={}
for tag in APPROVED:
    rr=[r for r in allrows if r["tag"]==tag]
    by_tag[tag]={
        "rows":len(rr),
        "ciks":len({r["cik"] for r in rr}),
        "accepted_mapped":sum(bool(r["accepted"]) for r in rr),
        "role":APPROVED[tag][0],
        "priority":APPROVED[tag][1],
        "semantic_basis":APPROVED[tag][2],
    }
summary={
    "schema":"V4_NEXT1_SEC_APPROVED_ALT_FACTS_V1",
    "formation_2023_opened":False,
    "future_outcomes_used":False,
    "us3700_used":False,
    "corporate_action_policy":"existing-confirmed-only; no new lookup",
    "existing_corp_action_excluded_tickers":sorted(excluded),
    "new_corp_action_lookup_calls":0,
    "target_ciks":len(TARGET_CIKS),
    "fact_rows":len(allrows),
    "accepted_mapped_rows":sum(bool(r["accepted"]) for r in allrows),
    "accepted_missing_rows":sum(not bool(r["accepted"]) for r in allrows),
    "cik_errors":sum(a["status"]!="OK" for a in audits),
    "approved_tags":by_tag,
    "note":"Only semantically approved total-role alternatives. PIT selection must still enforce accepted<=formation and aligned-quarter reconstruction."
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(json.dumps(summary,indent=2),flush=True)
