from __future__ import annotations
import json, math, re, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import pandas as pd
import requests

ROOT=Path(".")
UNIVERSE=ROOT/"v3-fast/price_universe_resolved.csv.gz"
OUT=ROOT/"v4-sec-f34-next1-output"
OUT.mkdir(parents=True,exist_ok=True)
UA="V4-Full-Rigor-NEXT1 outcome-free SEC candidate discovery"
KNOWN_DELISTED_NO_RECOVERY={"ABMD","STMP","AAWW"}
FORMS={"10-Q","10-K","10-Q/A","10-K/A"}
SESSION=requests.Session()
SESSION.headers.update({"User-Agent":UA,"Accept-Encoding":"gzip, deflate","Accept":"application/json"})
RATE_LOCK=threading.Lock()
LAST=[0.0]

def rate_wait():
    with RATE_LOCK:
        dt=time.monotonic()-LAST[0]
        if dt<0.115:
            time.sleep(0.115-dt)
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
    if not t: return False
    if re.search(r"(Revenue|SalesRevenue|OperatingRevenue)",t,re.I): return True
    if t.startswith("NetCashProvidedByUsedInOperatingActivities"): return True
    if "Payments" in t and any(k in t for k in [
        "PropertyPlantAndEquipment","ProductiveAssets","CapitalExpenditure",
        "CapitalExpenditures","AdditionsToPropertyPlantAndEquipment"
    ]): return True
    if "WeightedAverage" in t and ("Share" in t or "Stock" in t) and any(k in t for k in [
        "Outstanding","Basic","Diluted"
    ]): return True
    return False

u=pd.read_csv(UNIVERSE,dtype=str,keep_default_na=False,compression="gzip",low_memory=False)
if "snapshot_date" in u.columns:
    yy=pd.to_datetime(u["snapshot_date"],errors="coerce").dt.year
    if yy.ge(2023).any():
        raise RuntimeError("REFUSED: 2023+ formation present")
u["ticker_norm"]=u["ticker_at_snapshot"].astype(str).str.upper().str.strip()
u["cik_num"]=pd.to_numeric(u["cik"],errors="coerce").astype("Int64")
u=u[~u.ticker_norm.isin(KNOWN_DELISTED_NO_RECOVERY)]
ticker_by_cik=(u.dropna(subset=["cik_num"]).groupby("cik_num")["ticker_norm"]
               .agg(lambda s:"|".join(sorted(set(x for x in s if x)))))
TARGET_META=json.loads((ROOT/"v4-sec-cover/next1_missing_f34_target_ciks.json").read_text())\nTARGET_CIKS=sorted(int(x) for x in TARGET_META["ciks"] if int(x) in set(u.cik_num.dropna().astype(int)))

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
            qtrs_like=0
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
                    # Deliberately ignore post-2022 filings/facts. No 2023 formation data is opened/used.
                    if not filed or filed>"2022-12-31":
                        continue
                    if end and end>"2022-12-31":
                        continue
                    if end and end<"2017-01-01":
                        continue
                    kept+=1
                    if start and end:
                        qtrs_like+=1
            if kept:
                tags.append({
                    "cik":cik,
                    "ticker":ticker_by_cik.get(cik,""),
                    "tag":tag,
                    "label":str(concept.get("label") or ""),
                    "description":str(concept.get("description") or ""),
                    "fact_rows_pre2023":kept,
                    "duration_rows_pre2023":qtrs_like,
                    "units":"|".join(sorted(set(unit_names))),
                })
        audit["candidate_tags"]=len(tags)
        audit["candidate_fact_rows"]=sum(x["fact_rows_pre2023"] for x in tags)
        return tags,audit
    except Exception as e:
        audit["status"]="ERROR"; audit["error"]=repr(e)[:400]
        return [],audit

alltags=[]; audits=[]
with ThreadPoolExecutor(max_workers=6) as ex:
    futs={ex.submit(scan_cik,c):c for c in TARGET_CIKS}
    for i,f in enumerate(as_completed(futs),1):
        rows,a=f.result()
        alltags.extend(rows); audits.append(a)
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
 "schema":"V4_NEXT1_SEC_COMPANYFACTS_CANDIDATE_TAG_DISCOVERY_V2",
 "source":"SEC data.sec.gov companyfacts; only facts filed/end <= 2022-12-31 retained",
 "formation_2023_opened":False,
 "future_outcomes_used":False,
 "us3700_used":False,
 "known_delisted_no_recovery":sorted(KNOWN_DELISTED_NO_RECOVERY),
 "target_ciks":len(TARGET_CIKS),
 "fetch_errors":sum(a["status"]!="OK" for a in audits),
 "candidate_cik_tag_rows":int(len(d)),
 "candidate_tags":int(d.tag.nunique()) if len(d) else 0,
 "note":"Discovery only. No candidate tag becomes an accepted F3/F4 mapping until semantic review and accepted-time/alignment recomputation."
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(json.dumps(summary,indent=2),flush=True)
