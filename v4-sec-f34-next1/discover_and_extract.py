from __future__ import annotations
import csv, io, json, os, re, time, zipfile
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
import requests

ROOT = Path("v4-sec-f34-next1")
OUT = Path("v4-sec-f34-next1-output")
OUT.mkdir(parents=True, exist_ok=True)

UNIVERSE = Path("v3-fast/price_universe_resolved.csv.gz")
FORMS = {"10-Q","10-K","10-Q/A","10-K/A"}
QUARTERS = [f"{y}q{q}" for y in range(2018, 2023) for q in range(1,5)]
SEC_URL = "https://www.sec.gov/files/dera/data/financial-statement-data-sets/{q}.zip"
UA = "V4-Full-Rigor-Research outcome-free SEC PIT tag discovery"

BASE_TAGS = {
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "NetCashProvidedByUsedInOperatingActivities",
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "WeightedAverageNumberOfDilutedSharesOutstanding",
    "WeightedAverageNumberOfSharesOutstandingBasic",
}
KNOWN_ALT_TAGS = {
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    "PaymentsToAcquireProductiveAssets",
    "PaymentsForAdditionsToPropertyPlantAndEquipment",
    # Deprecated historical concept replaced by separate basic/diluted concepts.
    "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
}

def candidate_name(tag: str) -> bool:
    t = str(tag or "")
    lo = t.lower()
    if t in BASE_TAGS or t in KNOWN_ALT_TAGS:
        return True
    if "weightedaverage" in lo and "share" in lo and ("basic" in lo or "dilut" in lo):
        return True
    if "operatingactivities" in lo and ("cash" in lo or "netcash" in lo):
        return True
    if ("payment" in lo or "capitalexpenditure" in lo) and any(k in lo for k in (
        "propertyplantandequipment","productiveasset","capitalasset","equipment"
    )):
        return True
    if "revenue" in lo or "sales" in lo:
        # Discovery only. No revenue tag discovered here is auto-approved.
        bad = ("cost","expense","deferred","unearned","receivable","percentage",
               "remainingperformance","contractliability","perunit","pershare",
               "member","abstract")
        return not any(x in lo for x in bad)
    return False

def read_member(z: zipfile.ZipFile, basename: str):
    name = next(n for n in z.namelist() if Path(n).name.lower() == basename.lower())
    return z.open(name)

u = pd.read_csv(UNIVERSE, usecols=["cik","snapshot_date"], dtype=str, keep_default_na=False)
yrs = pd.to_datetime(u["snapshot_date"], errors="coerce").dt.year
if yrs.ge(2023).any():
    raise RuntimeError("REFUSED: 2023+ formation detected")
ciks = set(pd.to_numeric(u["cik"], errors="coerce").dropna().astype(int))
if not ciks:
    raise RuntimeError("No CIKs")

session = requests.Session()
session.headers.update({
    "User-Agent": UA,
    "Accept-Encoding": "gzip, deflate",
})

catalog_rows = []
usage = Counter()
quarter_summaries = []

for qi, q in enumerate(QUARTERS, 1):
    print("DOWNLOAD", q, qi, "/", len(QUARTERS), flush=True)
    r = session.get(SEC_URL.format(q=q), timeout=180, stream=True)
    r.raise_for_status()
    buf = io.BytesIO()
    for ch in r.iter_content(chunk_size=1024*1024):
        if ch:
            buf.write(ch)
    buf.seek(0)

    with zipfile.ZipFile(buf) as z:
        sub = pd.read_csv(
            read_member(z, "sub.txt"), sep="\t", dtype=str,
            keep_default_na=False, na_filter=False,
            usecols=lambda c: c.lower() in {"adsh","cik","name","sic","countryba","form","filed","accepted","period","fy","fp"},
            low_memory=False,
        )
        sub.columns = [c.lower() for c in sub.columns]
        sub["cik_num"] = pd.to_numeric(sub["cik"], errors="coerce").astype("Int64")
        sub["form"] = sub["form"].str.upper().str.strip()
        sub = sub[sub["cik_num"].isin(ciks) & sub["form"].isin(FORMS)].copy()
        meta = sub[["adsh","cik_num","name","sic","countryba","form","filed","accepted","period","fy","fp"]].drop_duplicates("adsh", keep="last")
        aset = set(meta["adsh"])

        tag = pd.read_csv(
            read_member(z, "tag.txt"), sep="\t", dtype=str,
            keep_default_na=False, na_filter=False, low_memory=False,
        )
        tag.columns = [c.lower() for c in tag.columns]
        for c in ["tag","version","custom","abstract","datatype","iord","crdr","tlabel","doc"]:
            if c not in tag.columns:
                tag[c] = ""
        tag = tag[tag["tag"].map(candidate_name)].copy()
        # standard taxonomy only; custom extension tags are discovery-noise here
        if "custom" in tag.columns:
            tag = tag[~tag["custom"].astype(str).str.strip().isin({"1","true","TRUE"})]
        candidates = set(tag["tag"])
        if not candidates:
            quarter_summaries.append({"source_quarter":q,"candidate_tags":0,"facts":0,"submissions":len(meta)})
            continue

        parts = []
        for ch in pd.read_csv(
            read_member(z, "num.txt"), sep="\t", dtype=str,
            keep_default_na=False, na_filter=False,
            usecols=lambda c: c.lower() in {"adsh","tag","version","ddate","qtrs","uom","coreg","segments","value"},
            chunksize=400000, quoting=csv.QUOTE_NONE, on_bad_lines="skip",
        ):
            ch.columns = [c.lower() for c in ch.columns]
            x = ch[ch["adsh"].isin(aset) & ch["tag"].isin(candidates)].copy()
            if x.empty:
                continue
            x = x[x["coreg"].astype(str).str.strip().eq("") & x["segments"].astype(str).str.strip().eq("")]
            # standard taxonomy facts only; in FSD custom tags normally have version==adsh
            x = x[x["version"].astype(str).str.strip().ne(x["adsh"].astype(str).str.strip())]
            if x.empty:
                continue
            parts.append(x)

        if parts:
            facts = pd.concat(parts, ignore_index=True).merge(meta, on="adsh", how="left", validate="many_to_one")
            facts["source_quarter"] = q
            facts.to_csv(OUT/f"{q}_candidate_facts.csv.gz", index=False, compression="gzip")
            for t, n in facts["tag"].value_counts().items():
                usage[(q, str(t))] += int(n)
            nf = len(facts)
        else:
            facts = pd.DataFrame()
            pd.DataFrame(columns=["adsh","tag","version","ddate","qtrs","uom","coreg","segments","value","cik_num","accepted","source_quarter"]).to_csv(
                OUT/f"{q}_candidate_facts.csv.gz", index=False, compression="gzip"
            )
            nf = 0

        for row in tag.to_dict("records"):
            catalog_rows.append({
                "source_quarter": q,
                "tag": row.get("tag",""),
                "version": row.get("version",""),
                "datatype": row.get("datatype",""),
                "iord": row.get("iord",""),
                "crdr": row.get("crdr",""),
                "tlabel": row.get("tlabel",""),
                "doc": row.get("doc",""),
                "is_baseline": int(row.get("tag","") in BASE_TAGS),
                "is_known_alt": int(row.get("tag","") in KNOWN_ALT_TAGS),
                "fact_rows_for_target_ciks": int(usage.get((q,row.get("tag","")),0)),
            })
        quarter_summaries.append({"source_quarter":q,"candidate_tags":len(candidates),"facts":nf,"submissions":len(meta)})
        print("DONE", q, "subs", len(meta), "tags", len(candidates), "facts", nf, flush=True)

    del buf
    time.sleep(0.2)

catalog = pd.DataFrame(catalog_rows)
if not catalog.empty:
    # Preserve taxonomy-version metadata but also provide cross-quarter usage summary.
    catalog.to_csv(OUT/"candidate_tag_catalog_by_quarter.csv", index=False)
    agg = catalog.groupby("tag", as_index=False).agg(
        first_quarter=("source_quarter","min"),
        last_quarter=("source_quarter","max"),
        taxonomy_versions=("version", lambda s: "|".join(sorted(set(x for x in s if x)))),
        datatype=("datatype","first"),
        iord=("iord","first"),
        crdr=("crdr","first"),
        tlabel=("tlabel","first"),
        doc=("doc","first"),
        is_baseline=("is_baseline","max"),
        is_known_alt=("is_known_alt","max"),
        fact_rows_for_target_ciks=("fact_rows_for_target_ciks","sum"),
    ).sort_values(["fact_rows_for_target_ciks","tag"], ascending=[False,True])
    agg.to_csv(OUT/"candidate_tag_catalog.csv", index=False)

summary = {
    "schema":"V4_SEC_F34_NEXT1_DISCOVERY_V1",
    "purpose":"Outcome-free SEC PIT F3/F4 missing-role alternative-tag discovery only.",
    "quarters":QUARTERS,
    "target_ciks":len(ciks),
    "formation_2023_accessed":False,
    "future_outcomes_used":False,
    "delisted_or_mna_lookup_performed":False,
    "auto_approval_note":"Discovered revenue/cash-flow/capex/share tags are NOT auto-approved. Semantic approval is a separate step using taxonomy definitions before recomputation.",
    "known_alt_tags":sorted(KNOWN_ALT_TAGS),
    "quarter_summaries":quarter_summaries,
}
(OUT/"summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2), flush=True)
