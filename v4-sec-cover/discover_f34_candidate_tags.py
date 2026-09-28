from __future__ import annotations
import json, re, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

ROOT=Path(".")
UNIVERSE=ROOT/"v3-fast/price_universe_resolved.csv.gz"
TARGETS=ROOT/"v4-sec-cover/next1_missing_f34_target_ciks.json"
EXCLUSIONS=ROOT/"v4-sec-cover/existing_corp_action_exclusions.json"
OUT=ROOT/"v4-sec-f34-next1-output"
OUT.mkdir(parents=True,exist_ok=True)

UA="V4-Full-Rigor-NEXT1 outcome-free SEC candidate discovery"
FORMS={"10-Q","10-K","10-Q/A","10-K/A"}
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

def candidate_tag(tag:str)->bool:
    t=str(tag or "")
    if not t:
        return False
    lo=t.lower()
    # Discovery only. Semantic approval remains separate.
    if "revenue" in lo or "salesrevenue" in lo or "operatingrevenue" in lo:
        bad=("cost","expense","deferred","unearned","receivable","percentage",
             "remainingperformance","contractliability","perunit","pershare",
             "member","abstract")
        return not any(x in lo for x in bad)
    if "operatingactivities" in lo and ("cash" in lo or "netcash" in lo):
        return True
    if ("payment" in lo or "capitalexpenditure" in lo) and any(k in lo for k in (
        "propertyplantandequipment","productiveasset","capitalasset","equipment"
    )):
        return True
    if "weightedaverage" in lo and ("share" in lo or "stock" in lo) and ("basic" in lo or "dilut" in lo or "outstanding" in lo):
        return True
    return False

u=pd.read_csv(UNIVERSE,dtype=str,keep_default_na=False,compression="gzip",low_memory=False)
years=pd.to_datetime(u["snapshot_date"],errors="coerce").dt.year
if years.ge(2023).any():
    raise RuntimeError("REFUSED: 2023+ formation present")
u["ticker_norm"]=u["ticker_at_snapshot"].astype(str).str.upper().str.strip()
u["cik_num"]=pd.to_numeric(u["cik"],errors="coerce").astype("Int64")

policy=json.loads(EXCLUSIONS.read_text(encoding="utf-8"))
excluded_tickers=set(str(x).upper().strip() for x in policy["tickers"])
if policy.get("new_corp_action_lookup_allowed") is not False:
    raise RuntimeError("Corporate-action policy must forbid new lookup")

# Existing-only exclusion: no API/search is used to expand this set.
u_calc=u[~u["ticker_norm"].isin(excluded_tickers)].copy()
ticker_by_cik=(u_calc.dropna(subset=["cik_num"]).groupby("cik_num")["ticker_norm"]
               .agg(lambda s:"|".join(sorted(set(x for x in s if x)))))

target_meta=json.loads(TARGETS.read_text(encoding="utf-8"))
target_ciks=set(int(x) for x in target_meta["ciks"])
available_ciks=set(u_calc["cik_num"].dropna().astype(int))
TARGET_CIKS=sorted(target_ciks & available_ciks)

def scan_cik(cik:int):
    cik10=f"{cik:010d}"
    audit={"cik":cik,"status":"OK","candidate_tags":0,"candidate_fact_rows":0,"error":""}
    tags=[]
    try:
        cf=get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json")
        us=((cf.get("facts") or {}).get("us-gaap") or {})
        for tag,concept in us.items():
            if not candidate_tag(tag):
                continue
            units=concept.get("units") or {}
            kept=0
            unit_names=[]
            duration_rows=0
            for unit,rows in units.items():
                if str(unit).lower().strip() not in {"usd","shares","share"} or not isinstance(rows,list):
                    continue
                unit_names.append(str(unit))
                for r in rows:
                    form=str(r.get("form") or "").upper().strip()
                    filed=str(r.get("filed") or "")[:10]
                    end=str(r.get("end") or "")[:10]
                    start=str(r.get("start") or "")[:10]
                    if form not in FORMS:
                        continue
                    # Discovery is strictly pre-2023 and outcome-free.
                    if not filed or filed>"2022-12-31":
                        continue
                    if end and (end>"2022-12-31" or end<"2017-01-01"):
                        continue
                    kept+=1
                    if start and end:
                        duration_rows+=1
            if kept:
                tags.append({
                    "cik":cik,
                    "ticker":ticker_by_cik.get(cik,""),
                    "tag":tag,
                    "label":str(concept.get("label") or ""),
                    "description":str(concept.get("description") or ""),
                    "fact_rows_pre2023":kept,
                    "duration_rows_pre2023":duration_rows,
                    "units":"|".join(sorted(set(unit_names))),
                })
        audit["candidate_tags"]=len(tags)
        audit["candidate_fact_rows"]=sum(x["fact_rows_pre2023"] for x in tags)
        return tags,audit
    except Exception as e:
        audit["status"]="ERROR"
        audit["error"]=repr(e)[:400]
        return [],audit

alltags=[]
audits=[]
with ThreadPoolExecutor(max_workers=6) as ex:
    futs={ex.submit(scan_cik,c):c for c in TARGET_CIKS}
    for i,f in enumerate(as_completed(futs),1):
        rows,a=f.result()
        alltags.extend(rows)
        audits.append(a)
        if i%100==0:
            print("PROGRESS",i,"/",len(TARGET_CIKS),"tag_rows",len(alltags),flush=True)

d=pd.DataFrame(alltags)
if d.empty:
    d=pd.DataFrame(columns=["cik","ticker","tag","label","description","fact_rows_pre2023","duration_rows_pre2023","units"])
d.to_csv(OUT/"candidate_tag_by_cik.csv.gz",index=False,compression="gzip")

if len(d):
    s=(d.groupby(["tag","label","description","units"],dropna=False)
       .agg(unique_ciks=("cik","nunique"),
            fact_rows_pre2023=("fact_rows_pre2023","sum"),
            duration_rows_pre2023=("duration_rows_pre2023","sum"))
       .reset_index()
       .sort_values(["unique_ciks","fact_rows_pre2023"],ascending=False))
else:
    s=pd.DataFrame(columns=["tag","label","description","units","unique_ciks","fact_rows_pre2023","duration_rows_pre2023"])
s.to_csv(OUT/"candidate_tag_summary.csv",index=False)
pd.DataFrame(audits).sort_values("cik").to_csv(OUT/"companyfacts_fetch_audit.csv",index=False)

summary={
    "schema":"V4_NEXT1_SEC_COMPANYFACTS_CANDIDATE_TAG_DISCOVERY_V3",
    "source":"SEC data.sec.gov companyfacts; only facts filed/end <= 2022-12-31 retained",
    "formation_2023_opened":False,
    "future_outcomes_used":False,
    "us3700_used":False,
    "corporate_action_policy":"existing-confirmed-only; no new lookup",
    "existing_corp_action_excluded_tickers":sorted(excluded_tickers),
    "new_corp_action_lookup_calls":0,
    "target_ciks":len(TARGET_CIKS),
    "fetch_errors":sum(a["status"]!="OK" for a in audits),
    "candidate_cik_tag_rows":int(len(d)),
    "candidate_tags":int(d["tag"].nunique()) if len(d) else 0,
    "note":"Discovery only. No candidate tag becomes an accepted F3/F4 mapping until semantic review and accepted-time/alignment recomputation."
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(json.dumps(summary,indent=2),flush=True)
