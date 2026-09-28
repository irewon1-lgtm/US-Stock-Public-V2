from __future__ import annotations
import csv, io, json, re, time, zipfile
from pathlib import Path
import pandas as pd
import requests

ROOT=Path(".")
UNIVERSE=ROOT/"v3-fast/price_universe_resolved.csv.gz"
OUT=ROOT/"v4-sec-f34-next1-output"
OUT.mkdir(parents=True,exist_ok=True)
UA="V4-Full-Rigor-NEXT1 outcome-free SEC FSD tag discovery"
KNOWN_DELISTED_NO_RECOVERY={"ABMD","STMP","AAWW"}
FORMS={"10-Q","10-K","10-Q/A","10-K/A"}
QUARTERS=[f"{y}q{q}" for y in range(2018,2023) for q in range(1,5)]

u=pd.read_csv(UNIVERSE,dtype=str,keep_default_na=False,compression="gzip",low_memory=False)
if "snapshot_date" in u.columns:
    yy=pd.to_datetime(u["snapshot_date"],errors="coerce").dt.year
    if yy.ge(2023).any():
        raise RuntimeError("REFUSED: 2023+ formation present")
u["ticker_norm"]=u["ticker_at_snapshot"].astype(str).str.upper().str.strip()
u["cik_num"]=pd.to_numeric(u["cik"],errors="coerce").astype("Int64")
u=u[~u.ticker_norm.isin(KNOWN_DELISTED_NO_RECOVERY)]
TARGET_CIKS=set(u.cik_num.dropna().astype(int))

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

def get_zip(q):
    urls=[
      f"https://www.sec.gov/files/dera/data/financial-statement-data-sets/{q}.zip",
      f"https://dcm.sec.gov/files/dera/data/financial-statement-data-sets/{q}.zip",
    ]
    last=""
    for url in urls:
        try:
            r=requests.get(url,headers={"User-Agent":UA,"Accept-Encoding":"gzip, deflate"},timeout=120)
            if r.ok:
                return zipfile.ZipFile(io.BytesIO(r.content))
            last=f"{url} HTTP {r.status_code}"
        except Exception as e:
            last=repr(e)
    raise RuntimeError(last)

facts=[]
defs=[]
audits=[]
for q in QUARTERS:
    t0=time.time()
    with get_zip(q) as z:
        names={Path(n).name.lower():n for n in z.namelist()}
        sub=pd.read_csv(z.open(names["sub.txt"]),sep="\t",dtype=str,keep_default_na=False,na_filter=False,
                        usecols=lambda c:c.lower() in {"adsh","cik","form","accepted","filed"},low_memory=False)
        sub.columns=[c.lower() for c in sub.columns]
        sub["cik_num"]=pd.to_numeric(sub.cik,errors="coerce").astype("Int64")
        sub["form"]=sub.form.str.upper().str.strip()
        sub=sub[sub.cik_num.isin(TARGET_CIKS)&sub.form.isin(FORMS)].copy()
        meta=sub[["adsh","cik_num","form","accepted","filed"]].drop_duplicates("adsh",keep="last")
        aset=set(meta.adsh)
        parts=[]
        for ch in pd.read_csv(z.open(names["num.txt"]),sep="\t",dtype=str,keep_default_na=False,na_filter=False,
                              usecols=lambda c:c.lower() in {"adsh","tag","version","ddate","qtrs","uom","coreg","segments","value"},
                              chunksize=450000,quoting=csv.QUOTE_NONE,on_bad_lines="skip"):
            ch.columns=[c.lower() for c in ch.columns]
            x=ch[ch.adsh.isin(aset)].copy()
            if x.empty: continue
            x=x[x.tag.map(candidate_tag)]
            if x.empty: continue
            x=x[x.coreg.astype(str).str.strip().eq("") & x.segments.astype(str).str.strip().eq("")]
            if x.empty: continue
            # Standard taxonomy only. Filer extension version equals accession number.
            x=x[x.version.astype(str).str.strip().ne(x.adsh.astype(str).str.strip())]
            if not x.empty: parts.append(x)
        if parts:
            x=pd.concat(parts,ignore_index=True).merge(meta,on="adsh",how="left",validate="many_to_one")
            x["source_quarter"]=q
            facts.append(x)
        if "tag.txt" in names:
            tg=pd.read_csv(z.open(names["tag.txt"]),sep="\t",dtype=str,keep_default_na=False,na_filter=False,
                           quoting=csv.QUOTE_NONE,on_bad_lines="skip",low_memory=False)
            tg.columns=[c.lower() for c in tg.columns]
            if "tag" in tg.columns:
                tg=tg[tg.tag.map(candidate_tag)].copy()
                if "version" in tg.columns and "custom" in tg.columns:
                    tg=tg[tg["custom"].astype(str).str.strip().isin({"0","false","False",""})]
                tg["source_quarter"]=q
                defs.append(tg)
        audits.append({"source_quarter":q,"sub_rows":len(sub),"candidate_fact_rows":0 if not parts else len(x),
                       "elapsed_sec":round(time.time()-t0,2)})
    print(q,audits[-1],flush=True)

allf=pd.concat(facts,ignore_index=True) if facts else pd.DataFrame()
if not allf.empty:
    allf["cik_num"]=pd.to_numeric(allf.cik_num,errors="coerce").astype("Int64")
    allf["qtrs_num"]=pd.to_numeric(allf.qtrs,errors="coerce")
    allf.to_csv(OUT/"candidate_facts_2018q1_2022q4.csv.gz",index=False,compression="gzip")
    s=(allf.groupby(["tag","version","uom"],dropna=False)
       .agg(fact_rows=("adsh","size"),unique_ciks=("cik_num","nunique"),
            qtrs_min=("qtrs_num","min"),qtrs_max=("qtrs_num","max"),
            first_accepted=("accepted","min"),last_accepted=("accepted","max"))
       .reset_index().sort_values(["unique_ciks","fact_rows"],ascending=False))
else:
    s=pd.DataFrame()
s.to_csv(OUT/"candidate_tag_summary.csv",index=False)

alld=pd.concat(defs,ignore_index=True) if defs else pd.DataFrame()
if not alld.empty:
    keep=[c for c in ["tag","version","datatype","abstract","crdr","tlabel","doc","source_quarter"] if c in alld.columns]
    alld=alld[keep].drop_duplicates()
alld.to_csv(OUT/"candidate_tag_definitions.csv",index=False)

pd.DataFrame(audits).to_csv(OUT/"download_extract_audit.csv",index=False)
summary={
 "schema":"V4_NEXT1_SEC_FSD_CANDIDATE_TAG_DISCOVERY_V1",
 "period":"2018Q1-2022Q4_ONLY",
 "formation_2023_opened":False,
 "future_outcomes_used":False,
 "us3700_used":False,
 "known_delisted_no_recovery":sorted(KNOWN_DELISTED_NO_RECOVERY),
 "target_ciks":len(TARGET_CIKS),
 "candidate_fact_rows":int(len(allf)),
 "candidate_tags":int(allf.tag.nunique()) if not allf.empty else 0,
 "note":"Discovery only. No candidate tag becomes an accepted F3/F4 mapping until semantic review and PIT/alignment recomputation."
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(json.dumps(summary,indent=2),flush=True)
