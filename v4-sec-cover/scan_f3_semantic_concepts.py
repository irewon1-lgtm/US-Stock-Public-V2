from __future__ import annotations
import json, re, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import requests

ROOT=Path(".")
BASE=json.loads((ROOT/"v4-sec-cover/next1_missing_f34_target_ciks.json").read_text())["ciks"]
SUPP=json.loads((ROOT/"v4-sec-cover/next1_strict_supplemental_target_ciks.json").read_text())["ciks"]
POL=json.loads((ROOT/"v4-sec-cover/existing_corp_action_exclusions.json").read_text())
if POL.get("new_corp_action_lookup_allowed") is not False:
    raise RuntimeError("corp action lookup must stay disabled")
CIKS=sorted(set(int(x) for x in BASE)|set(int(x) for x in SUPP))
OUT=ROOT/"v4-sec-f3-semantic-scan-output"; OUT.mkdir(exist_ok=True)

H={"User-Agent":"V4-Full-Rigor NEXT1 semantic concept scan","Accept":"application/json","Accept-Encoding":"gzip, deflate"}
lock=threading.Lock(); last=[0.0]

def rate_wait():
    with lock:
        dt=time.monotonic()-last[0]
        if dt<0.13: time.sleep(0.13-dt)
        last[0]=time.monotonic()

def get(c):
    err=""
    for i in range(5):
        try:
            rate_wait()
            r=requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{c:010d}.json",headers=H,timeout=45)
            if r.status_code in {429,500,502,503,504}: raise RuntimeError(f"HTTP_{r.status_code}")
            r.raise_for_status(); return r.json()
        except Exception as e:
            err=repr(e)[:300]
            if i<4: time.sleep(min(15,1.5*(2**i)))
    raise RuntimeError(err)

def pre2023_count(concept):
    n=0; dur=0; units=set()
    for unit,rows in (concept.get("units") or {}).items():
        if not isinstance(rows,list): continue
        for r in rows:
            form=str(r.get("form") or "").upper().strip()
            filed=str(r.get("filed") or "")[:10]
            end=str(r.get("end") or "")[:10]
            start=str(r.get("start") or "")[:10]
            if form not in {"10-Q","10-K","10-Q/A","10-K/A"}: continue
            if not filed or filed>"2022-12-31": continue
            if end and (end>"2022-12-31" or end<"2017-01-01"): continue
            n+=1; units.add(str(unit))
            if start and end: dur+=1
    return n,dur,"|".join(sorted(units))

def classify(tag,label,desc):
    txt=" ".join([str(tag or ""),str(label or ""),str(desc or "")]).lower()
    compact=re.sub(r"[^a-z0-9]+","",txt)
    # Discovery bucket, not automatic approval.
    capex_signal=(
        "capital expenditure" in txt or "capital expenditures" in txt or
        "property, plant and equipment" in txt or "property plant and equipment" in txt or
        "propertyplantandequipment" in compact or "capitalexpenditure" in compact
    )
    cash_signal=any(x in txt for x in ["cash outflow","cash payment","cash paid","payments to acquire","payments for"])
    capex_bad=any(x in txt for x in [
        "not yet paid","accrued","noncash","proceeds from","sale of","disposal",
        "productive assets","intangible","software","business acquisition",
        "acquire businesses","acquisition of business","leasehold"
    ])
    cfo_signal=("operating activities" in txt and any(x in txt for x in ["cash inflow","cash outflow","net cash","cash provided","cash used"]))
    revenue_signal=("revenue" in txt and any(x in txt for x in ["total revenue","total amount of operating revenues","aggregate revenue"]))
    share_signal=("weighted average" in txt and ("share" in txt or "stock" in txt) and ("diluted" in txt or "basic" in txt) and "exercise price" not in txt and "grant date" not in txt)
    roles=[]
    if capex_signal and cash_signal and not capex_bad: roles.append("CAPEX_EXACT_CANDIDATE")
    elif capex_signal: roles.append("CAPEX_REVIEW")
    if cfo_signal: roles.append("CFO_REVIEW")
    if revenue_signal: roles.append("REVENUE_REVIEW")
    if share_signal: roles.append("SHARES_REVIEW")
    return roles

def scan(c):
    p=get(c); out=[]
    for ns,concepts in (p.get("facts") or {}).items():
        for tag,concept in (concepts or {}).items():
            label=str(concept.get("label") or ""); desc=str(concept.get("description") or "")
            roles=classify(tag,label,desc)
            if not roles: continue
            n,dur,units=pre2023_count(concept)
            if not n: continue
            out.append({"cik":c,"namespace":ns,"tag":tag,"label":label,"description":desc,"roles":"|".join(roles),"fact_rows_pre2023":n,"duration_rows_pre2023":dur,"units":units})
    return out

rows=[]; errs=[]
with ThreadPoolExecutor(max_workers=5) as ex:
    fs={ex.submit(scan,c):c for c in CIKS}
    for i,f in enumerate(as_completed(fs),1):
        c=fs[f]
        try: rows.extend(f.result())
        except Exception as e: errs.append({"cik":c,"error":repr(e)[:400]})
        if i%100==0: print("PROGRESS",i,"/",len(CIKS),"rows",len(rows),flush=True)

# Aggregate exact-capex discovery separately for easy audit.
from collections import defaultdict
agg={}
for r in rows:
    k=(r["namespace"],r["tag"],r["label"],r["description"],r["roles"],r["units"])
    x=agg.setdefault(k,{"unique_ciks":set(),"fact_rows_pre2023":0,"duration_rows_pre2023":0})
    x["unique_ciks"].add(r["cik"]); x["fact_rows_pre2023"]+=r["fact_rows_pre2023"]; x["duration_rows_pre2023"]+=r["duration_rows_pre2023"]
summary_rows=[]
for k,x in agg.items():
    ns,tag,label,desc,roles,units=k
    summary_rows.append({"namespace":ns,"tag":tag,"label":label,"description":desc,"roles":roles,"units":units,"unique_ciks":len(x["unique_ciks"]),"fact_rows_pre2023":x["fact_rows_pre2023"],"duration_rows_pre2023":x["duration_rows_pre2023"]})
summary_rows=sorted(summary_rows,key=lambda x:(-x["unique_ciks"],-x["fact_rows_pre2023"],x["namespace"],x["tag"]))
payload={
 "schema":"V4_NEXT1_F3_SEMANTIC_CONCEPT_SCAN_V1",
 "target_ciks":len(CIKS),
 "fetch_errors":len(errs),
 "new_corp_action_lookup_calls":0,
 "formation_2023_opened":False,
 "future_outcomes_used":False,
 "us3700_used":False,
 "candidate_summary":summary_rows,
 "errors":errs,
 "note":"Discovery only. CAPEX_EXACT_CANDIDATE still requires manual semantic approval before any fact is used."
}
(OUT/"summary.json").write_text(json.dumps(payload,indent=2),encoding="utf-8")
(OUT/"by_cik.json").write_text(json.dumps(rows,indent=2),encoding="utf-8")
print(json.dumps({"target_ciks":len(CIKS),"fetch_errors":len(errs),"candidate_concepts":len(summary_rows),"exact_capex_candidates":sum("CAPEX_EXACT_CANDIDATE" in x["roles"] for x in summary_rows)},indent=2),flush=True)
