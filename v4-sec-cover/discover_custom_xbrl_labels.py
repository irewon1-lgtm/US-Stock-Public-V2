from __future__ import annotations
import argparse, io, json, re, time, zipfile
from pathlib import Path
import requests
import xml.etree.ElementTree as ET
import pandas as pd

ROOT=Path(".")
OUT=ROOT/"v4-sec-custom-xbrl-output"; OUT.mkdir(parents=True,exist_ok=True)
TARGET_FILES=[
 ROOT/"v4-sec-cover/next1_missing_f34_target_ciks.json",
 ROOT/"v4-sec-cover/next1_strict_supplemental_target_ciks.json",
 ROOT/"v4-sec-cover/next1_after_sec_cover_new_confirmed_target_ciks.json",
]
FORMS={"10-Q","10-K","10-Q/A","10-K/A"}
UA="V4-Full-Rigor custom-XBRL discovery research@example.com"
H={"User-Agent":UA,"Accept-Encoding":"gzip, deflate","Accept":"application/json"}
S=requests.Session();S.headers.update(H)
LAST=[0.0]
MIN_DELAY=0.55

XLINK="{http://www.w3.org/1999/xlink}"
LINK="{http://www.xbrl.org/2003/linkbase}"
XSD="{http://www.w3.org/2001/XMLSchema}"

BROAD=[
 ("CAPEX",re.compile(r"capital expenditure|property.*plant.*equipment|property.*equipment|purchases?.*equipment|additions?.*equipment|acquir.*equipment|flight equipment",re.I)),
 ("SHARES",re.compile(r"weighted average.*share|share.*weighted average|diluted.*share|basic.*share",re.I)),
 ("CFO",re.compile(r"net cash.*operating activit|cash.*provided.*operating activit|cash.*used.*operating activit",re.I)),
 ("REVENUE",re.compile(r"\b(total )?(operating )?revenues?\b|\bnet sales\b|\btotal sales\b",re.I)),
]

def wait():
    dt=time.monotonic()-LAST[0]
    if dt<MIN_DELAY: time.sleep(MIN_DELAY-dt)
    LAST[0]=time.monotonic()

def get(url, timeout=60):
    last=""
    for a in range(4):
        try:
            wait(); r=S.get(url,timeout=timeout)
            if r.status_code in {429,500,502,503,504}:
                raise RuntimeError(f"HTTP_{r.status_code}")
            return r
        except Exception as e:
            last=repr(e)
            if a<3: time.sleep(min(15,2**a))
    raise RuntimeError(last)

def all_targets():
    z=set()
    for p in TARGET_FILES:
        if not p.exists(): continue
        j=json.loads(p.read_text())
        z.update(int(x) for x in j.get("ciks",[]))
    return sorted(z)

def filing_candidates(sub):
    r=(sub.get("filings") or {}).get("recent") or {}
    keys=["accessionNumber","form","filingDate","acceptanceDateTime","primaryDocument"]
    arr={k:list(r.get(k) or []) for k in keys}
    n=max([len(v) for v in arr.values()]+[0]); out=[]
    for i in range(n):
        x={k:(arr[k][i] if i<len(arr[k]) else "") for k in keys}
        form=str(x["form"]).upper().strip(); fd=str(x["filingDate"])[:10]
        if form not in FORMS or not fd or fd>"2022-12-31": continue
        if not x["accessionNumber"]: continue
        out.append(x)
    # latest filing; prefer non-amended if same period vicinity
    out.sort(key=lambda x:(x["filingDate"],x["acceptanceDateTime"],x["accessionNumber"]),reverse=True)
    return out

def role_defs(xsd_text):
    out={}
    try: root=ET.fromstring(xsd_text)
    except Exception:return out
    for e in root.iter():
        if e.tag.endswith("roleType"):
            uri=e.attrib.get("roleURI","")
            definition=""
            for c in e:
                if c.tag.endswith("definition") and (c.text or "").strip():
                    definition=(c.text or "").strip();break
            if uri: out[uri]=definition
    return out

def parse_labels(text):
    loc={}; lab={}; arcs=[]
    try: root=ET.fromstring(text)
    except Exception:return {}
    for e in root.iter():
        tag=e.tag
        if tag.endswith("loc"):
            labid=e.attrib.get(XLINK+"label",""); href=e.attrib.get(XLINK+"href","")
            if labid and href: loc[labid]=href
        elif tag.endswith("label"):
            lid=e.attrib.get(XLINK+"label",""); role=e.attrib.get(XLINK+"role","")
            if lid: lab[lid]=(role," ".join("".join(e.itertext()).split()))
        elif tag.endswith("labelArc"):
            arcs.append((e.attrib.get(XLINK+"from",""),e.attrib.get(XLINK+"to","")))
    out={}
    for fr,to in arcs:
        href=loc.get(fr); item=lab.get(to)
        if not href or not item: continue
        concept=href.split("#")[-1]
        out.setdefault(concept,[]).append(item)
    return out

def parse_pre_roles(text):
    out={}
    try: root=ET.fromstring(text)
    except Exception:return out
    for pl in root.iter():
        if not pl.tag.endswith("presentationLink"): continue
        role=pl.attrib.get(XLINK+"role","")
        loc={}
        for e in pl:
            if e.tag.endswith("loc"):
                labid=e.attrib.get(XLINK+"label","");href=e.attrib.get(XLINK+"href","")
                if labid and href:loc[labid]=href.split("#")[-1]
        for concept in loc.values():
            out.setdefault(concept,set()).add(role)
    return out

def classify(text):
    cats=[]
    for cat,rx in BROAD:
        if rx.search(text): cats.append(cat)
    return cats

def custom_concept(concept):
    lo=concept.lower()
    return not (lo.startswith("us-gaap_") or lo.startswith("dei_") or lo.startswith("srt_"))

def process(cik):
    audit={"cik":cik,"status":"OK","filing":"","zip_status":"","candidate_rows":0,"error":""}
    try:
        r=get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json",45)
        if r.status_code!=200: raise RuntimeError(f"SUB_HTTP_{r.status_code}")
        fs=filing_candidates(r.json())
        if not fs:
            audit["status"]="NO_FILING";return [],audit
        f=fs[0]; acc=str(f["accessionNumber"]);audit["filing"]=acc
        ad=acc.replace("-","")
        url=f"https://www.sec.gov/Archives/edgar/data/{cik}/{ad}/{acc}-xbrl.zip"
        zres=get(url,90);audit["zip_status"]=str(zres.status_code)
        if zres.status_code!=200:
            audit["status"]="NO_XBRL_ZIP";return [],audit
        z=zipfile.ZipFile(io.BytesIO(zres.content))
        names=z.namelist()
        xsd=next((n for n in names if n.lower().endswith(".xsd")),None)
        labf=next((n for n in names if n.lower().endswith("_lab.xml")),None)
        pref=next((n for n in names if n.lower().endswith("_pre.xml")),None)
        if not labf:
            audit["status"]="NO_LABEL_LINKBASE";return [],audit
        labels=parse_labels(z.read(labf).decode("utf-8","ignore"))
        pre=parse_pre_roles(z.read(pref).decode("utf-8","ignore")) if pref else {}
        rdefs=role_defs(z.read(xsd).decode("utf-8","ignore")) if xsd else {}
        rows=[]
        for concept, labs in labels.items():
            if not custom_concept(concept): continue
            label_texts=sorted(set(t for role,t in labs if t))
            joined=" | ".join(label_texts+[concept.replace("_"," ")])
            cats=classify(joined)
            if not cats: continue
            roles=sorted(pre.get(concept,set()))
            defs=sorted(set(rdefs.get(u,"") for u in roles if rdefs.get(u,"")))
            rows.append({
              "cik":cik,"accession":acc,"form":f["form"],"filing_date":f["filingDate"],
              "accepted":f["acceptanceDateTime"],"primary_document":f["primaryDocument"],
              "concept":concept,"categories":"|".join(cats),
              "labels":" || ".join(label_texts),
              "presentation_roles":" || ".join(roles),
              "role_definitions":" || ".join(defs),
              "xbrl_zip_bytes":len(zres.content),
            })
        audit["candidate_rows"]=len(rows)
        return rows,audit
    except Exception as e:
        audit["status"]="ERROR";audit["error"]=repr(e)[:500]
        return [],audit

ap=argparse.ArgumentParser();ap.add_argument("--shard",type=int,required=True);ap.add_argument("--nshards",type=int,required=True);args=ap.parse_args()
targets=all_targets(); mine=[c for i,c in enumerate(targets) if i%args.nshards==args.shard]
rows=[];aud=[]
for i,c in enumerate(mine,1):
    rr,aa=process(c);rows.extend(rr);aud.append(aa)
    if i%25==0: print("PROGRESS",args.shard,i,"/",len(mine),"candidates",len(rows),flush=True)
pd.DataFrame(rows).to_csv(OUT/f"candidates_{args.shard:02d}.csv.gz",index=False,compression="gzip")
pd.DataFrame(aud).to_csv(OUT/f"audit_{args.shard:02d}.csv",index=False)
meta={"schema":"V4_SEC_CUSTOM_XBRL_DISCOVERY_SHARD_V1","shard":args.shard,"nshards":args.nshards,"targets_total":len(targets),"targets_shard":len(mine),"candidate_rows":len(rows),"formation_2023_opened":False,"future_outcomes_used":False,"us3700_used":False,"new_corp_action_lookup_calls":0}
(OUT/f"meta_{args.shard:02d}.json").write_text(json.dumps(meta,indent=2))
print(json.dumps(meta),flush=True)
