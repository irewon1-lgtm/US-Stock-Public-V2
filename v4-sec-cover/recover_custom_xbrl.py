from __future__ import annotations
import argparse, io, json, math, re, threading, time, zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import pandas as pd
import requests
from lxml import etree

ROOT=Path(".")
OUT=ROOT/"v4-sec-custom-xbrl-output"
OUT.mkdir(parents=True,exist_ok=True)
TARGET_FILES=[
 ROOT/"v4-sec-cover/next1_missing_f34_target_ciks.json",
 ROOT/"v4-sec-cover/next1_strict_supplemental_target_ciks.json",
 ROOT/"v4-sec-cover/next1_after_sec_cover_new_confirmed_target_ciks.json",
]
FORMS={"10-Q","10-K","10-Q/A","10-K/A"}
MIN_FILED="2017-01-01"
MAX_ACCEPT_DATE="2022-12-30"
UA="V4-Full-Rigor custom-XBRL recovery research@example.com"
H={"User-Agent":UA,"Accept-Encoding":"gzip, deflate","Accept":"application/json"}
SESSION=requests.Session(); SESSION.headers.update(H)
RATE_LOCK=threading.Lock(); LAST=[0.0]

XLINK="{http://www.w3.org/1999/xlink}"
LINK_NS="http://www.xbrl.org/2003/linkbase"

def rate_wait():
    with RATE_LOCK:
        dt=time.monotonic()-LAST[0]
        if dt<0.16:
            time.sleep(0.16-dt)
        LAST[0]=time.monotonic()

def get(url,timeout=60,attempts=4):
    last=""
    for i in range(attempts):
        try:
            rate_wait()
            r=SESSION.get(url,timeout=timeout)
            if r.status_code==404:
                return None,"NOT_FOUND",""
            if r.status_code in {429,500,502,503,504}:
                raise RuntimeError(f"HTTP_{r.status_code}")
            r.raise_for_status()
            return r,"OK",""
        except Exception as e:
            last=repr(e)[:300]
            if i<attempts-1:
                time.sleep(min(20,1.5*(2**i)))
    return None,"ERROR",last

def get_json(url):
    r,s,e=get(url,timeout=45)
    if s!="OK": raise RuntimeError(f"{s}:{e}")
    return r.json()

def parse_filings_block(a):
    keys=["accessionNumber","acceptanceDateTime","filingDate","form","primaryDocument"]
    n=max([len(a.get(k) or []) for k in keys]+[0])
    out=[]
    for i in range(n):
        def v(k):
            arr=a.get(k) or []
            return str(arr[i] if i<len(arr) else "").strip()
        acc=v("accessionNumber"); form=v("form").upper()
        if not acc or form not in FORMS: continue
        accepted=v("acceptanceDateTime"); filed=v("filingDate"); primary=v("primaryDocument")
        adate=(accepted[:10] if accepted else filed[:10])
        if filed and filed<MIN_FILED: continue
        if adate and adate>MAX_ACCEPT_DATE: continue
        out.append({"accn":acc,"accepted":accepted,"filed":filed,"form":form,"primary":primary})
    return out

def filings_for_cik(cik):
    cik10=f"{int(cik):010d}"
    sub=get_json(f"https://data.sec.gov/submissions/CIK{cik10}.json")
    rows=parse_filings_block(((sub.get("filings") or {}).get("recent") or {}))
    files=((sub.get("filings") or {}).get("files") or [])
    for meta in files:
        frm=str(meta.get("filingFrom") or "")
        to=str(meta.get("filingTo") or "")
        if frm and frm>MAX_ACCEPT_DATE: continue
        if to and to<MIN_FILED: continue
        name=str(meta.get("name") or "").strip()
        if not name: continue
        try:
            old=get_json("https://data.sec.gov/submissions/"+name)
            rows.extend(parse_filings_block(old if isinstance(old,dict) else {}))
        except Exception:
            continue
    ded={}
    for x in rows:
        ded[x["accn"]]=x
    return sorted(ded.values(),key=lambda x:(x.get("accepted") or x.get("filed") or "",x["accn"]))

def xml_root(data):
    return etree.fromstring(data,parser=etree.XMLParser(recover=True,huge_tree=True))

def parse_roles(z):
    roles={}
    for name in z.namelist():
        if not name.lower().endswith(".xsd"): continue
        try: root=xml_root(z.read(name))
        except Exception: continue
        for el in root.xpath("//*[local-name()='roleType']"):
            uri=el.get("roleURI") or ""
            defs=el.xpath("./*[local-name()='definition']/text()")
            if uri: roles[uri]=" ".join(str(x) for x in defs).strip()
    return roles

def parse_labels(z):
    labels={}
    for name in z.namelist():
        if not name.lower().endswith("_lab.xml"): continue
        try: root=xml_root(z.read(name))
        except Exception: continue
        for link in root.xpath("//*[local-name()='labelLink']"):
            loc={}
            lab={}
            for x in link.xpath("./*[local-name()='loc']"):
                key=x.get(XLINK+"label") or ""
                href=x.get(XLINK+"href") or ""
                if key and "#" in href: loc[key]=href.split("#")[-1]
            for x in link.xpath("./*[local-name()='label']"):
                key=x.get(XLINK+"label") or ""
                txt=" ".join("".join(x.itertext()).split())
                role=x.get(XLINK+"role") or ""
                if key and txt: lab[key]=(txt,role)
            for x in link.xpath("./*[local-name()='labelArc']"):
                fr=x.get(XLINK+"from") or ""; to=x.get(XLINK+"to") or ""
                concept=loc.get(fr); payload=lab.get(to)
                if concept and payload:
                    labels.setdefault(concept,[]).append(payload)
    return labels

def parse_presentation(z,role_defs):
    out={}
    for name in z.namelist():
        if not name.lower().endswith("_pre.xml"): continue
        try: root=xml_root(z.read(name))
        except Exception: continue
        for link in root.xpath("//*[local-name()='presentationLink']"):
            uri=link.get(XLINK+"role") or ""
            rdef=role_defs.get(uri,"")
            for x in link.xpath("./*[local-name()='loc']"):
                href=x.get(XLINK+"href") or ""
                if "#" not in href: continue
                concept=href.split("#")[-1]
                out.setdefault(concept,set()).add(rdef or uri)
    return out

def norm_label(s):
    s=re.sub(r"\([^)]*(shares|dollars|millions|thousands|000s)[^)]*\)"," ",s,flags=re.I)
    s=re.sub(r"\s+"," ",s).strip(" :-–—")
    return s

def classify(concept,label,roles):
    l=norm_label(label).lower()
    role=" | ".join(sorted(roles)).lower()
    cash_role=("cash flow" in role or "cashflow" in role)
    income_role=any(k in role for k in ["income statement","statements of income","statement of income","operations","earnings"])
    eps_role=("earnings per share" in role or "eps" in role)
    reject_cap=any(k in l for k in ["net of","proceeds","return","sale of","software","intangible","productive asset","lease","acquisition of business","business acquisition","reimbursement"])
    cap_exact=(
        (re.fullmatch(r"capital expenditures?",l) is not None)
        or (re.search(r"\b(purchases?|payments?|additions?|acquisitions?)\b.*\b(property(,? plant)?(,? and)? equipment|property and equipment|plant and equipment|fixed assets?)\b",l) is not None)
        or (re.search(r"\b(property(,? plant)?(,? and)? equipment|property and equipment|plant and equipment|fixed assets?)\b.*\b(purchases?|payments?|additions?|acquisitions?)\b",l) is not None)
    ) and not reject_cap and cash_role
    cap_near=(("capital expenditure" in l or ("property" in l and "equipment" in l and any(k in l for k in ["purchase","payment","addition","acquisition"]))) and not cap_exact)

    diluted_exact=("weighted average" in l and "diluted" in l and "share" in l and ("outstanding" in l or "common shares" in l)
                   and not any(k in l for k in ["pro forma","adjustment","anti-dilutive","antidilutive"]))
    combined_exact=("weighted average" in l and "basic" in l and "diluted" in l and "share" in l
                    and not any(k in l for k in ["pro forma","adjustment","anti-dilutive","antidilutive"]))
    cfo_exact=(cash_role and any(p in l for p in [
        "net cash provided by operating activities",
        "net cash used in operating activities",
        "net cash provided by (used in) operating activities",
        "net cash provided by (used for) operating activities",
        "cash flows from operating activities",
    ]) and not any(k in l for k in ["continuing operations","discontinued operations","adjustment","reconcile"]))
    revenue_exact=(income_role and l in {"revenues","revenue","total revenues","net revenues","net sales","sales, net","sales net","operating revenues","total operating revenues"})
    if cap_exact:return "CAPEX_CUSTOM_EXACT",True
    if diluted_exact:return "DILUTED_SHARES_CUSTOM_EXACT",True
    if combined_exact:return "BASIC_DILUTED_CUSTOM_EXACT",True
    if cfo_exact:return "CFO_CUSTOM_EXACT",True
    if revenue_exact:return "REVENUE_CUSTOM_EXACT",True
    if cap_near:return "CAPEX_CUSTOM_NEAR",False
    if "weighted average" in l and "share" in l:return "SHARES_CUSTOM_NEAR",False
    if cash_role and "operating activities" in l:return "CFO_CUSTOM_NEAR",False
    if income_role and ("revenue" in l or "sales" in l):return "REVENUE_CUSTOM_NEAR",False
    return "",False

def context_map(root):
    out={}
    for c in root.xpath("//*[local-name()='context']"):
        cid=c.get("id") or ""
        if not cid: continue
        starts=c.xpath(".//*[local-name()='startDate']/text()")
        ends=c.xpath(".//*[local-name()='endDate']/text()")
        inst=c.xpath(".//*[local-name()='instant']/text()")
        dims=c.xpath(".//*[local-name()='explicitMember' or local-name()='typedMember']")
        out[cid]={
            "start":str(starts[0])[:10] if starts else "",
            "end":str(ends[0])[:10] if ends else (str(inst[0])[:10] if inst else ""),
            "instant":bool(inst),
            "dimensioned":bool(dims),
        }
    return out

def unit_map(root):
    out={}
    for u in root.xpath("//*[local-name()='unit']"):
        uid=u.get("id") or ""
        ms=["".join(x.itertext()).strip() for x in u.xpath(".//*[local-name()='measure']")]
        out[uid]="|".join(ms)
    return out

def parse_num(text,el):
    t=" ".join(text.split())
    if not t or t in {"-","—","–","N/A","n/a"}: return None
    neg=("(" in t and ")" in t)
    clean=re.sub(r"[^0-9.\-]","",t)
    if clean in {"","-",".","-."}: return None
    try:v=float(clean)
    except Exception:return None
    if neg:v=-abs(v)
    if (el.get("sign") or "").strip()=="-":v=-abs(v)
    try:scale=int(el.get("scale") or "0")
    except Exception:scale=0
    v*=10**scale
    return v if math.isfinite(v) else None

def facts_from_inline(z,labels,pres,cik,fil):
    rows=[]
    for name in z.namelist():
        if not name.lower().endswith((".htm",".html")): continue
        try:
            root=xml_root(z.read(name))
        except Exception:
            continue
        ctx=context_map(root); units=unit_map(root)
        for el in root.xpath("//*[local-name()='nonFraction']"):
            qn=el.get("name") or ""
            if ":" not in qn: continue
            prefix,local=qn.split(":",1)
            if prefix.lower() in {"us-gaap","dei","srt","country","exch","ecd","invest","currency"}: continue
            candidates=[k for k in labels if k.endswith("_"+local) or k==local]
            if not candidates:
                candidates=[local]
            concept=candidates[0]
            labs=labels.get(concept,[])
            if not labs: continue
            roles=pres.get(concept,set())
            chosen=[]
            for lab,labrole in labs:
                cls,accept=classify(concept,lab,roles)
                if cls: chosen.append((accept,cls,lab,labrole))
            if not chosen: continue
            chosen.sort(reverse=True)
            accept,cls,lab,labrole=chosen[0]
            cref=el.get("contextRef") or ""
            cm=ctx.get(cref,{})
            if cm.get("dimensioned"): continue
            val=parse_num("".join(el.itertext()),el)
            if val is None: continue
            unit=units.get(el.get("unitRef") or "","")
            rows.append({
                "cik":int(cik),"accn":fil["accn"],"accepted":fil["accepted"],"filed":fil["filed"],"form":fil["form"],
                "source_file":name,"concept":concept,"qname":qn,"label":lab,"label_role":labrole,
                "presentation_roles":" || ".join(sorted(roles))[:2000],
                "semantic_class":cls,"auto_accept":bool(accept),
                "context_ref":cref,"start":cm.get("start",""),"end":cm.get("end",""),"instant":bool(cm.get("instant")),
                "unit":unit,"value":float(val),"decimals":el.get("decimals") or "","scale":el.get("scale") or "",
            })
    return rows

def process_cik(cik):
    audit={"cik":int(cik),"status":"OK","filings_considered":0,"xbrl_zip_ok":0,"xbrl_zip_missing":0,"candidate_rows":0,"accepted_exact_rows":0,"error":""}
    out=[]
    try:
        fs=filings_for_cik(cik); audit["filings_considered"]=len(fs)
        for fil in fs:
            ad=fil["accn"].replace("-","")
            url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{ad}/{fil['accn']}-xbrl.zip"
            r,s,e=get(url,timeout=75)
            if s=="NOT_FOUND":
                audit["xbrl_zip_missing"]+=1; continue
            if s!="OK":
                continue
            audit["xbrl_zip_ok"]+=1
            try:
                z=zipfile.ZipFile(io.BytesIO(r.content))
                roles=parse_roles(z); labels=parse_labels(z); pres=parse_presentation(z,roles)
                out.extend(facts_from_inline(z,labels,pres,cik,fil))
            except Exception:
                continue
        audit["candidate_rows"]=len(out)
        audit["accepted_exact_rows"]=sum(bool(x["auto_accept"]) for x in out)
    except Exception as e:
        audit["status"]="ERROR"; audit["error"]=repr(e)[:500]
    return out,audit

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--shard",type=int,required=True); ap.add_argument("--nshards",type=int,default=8)
    a=ap.parse_args()
    ciks=set()
    for p in TARGET_FILES:
        if p.exists():
            j=json.loads(p.read_text()); ciks.update(int(x) for x in j.get("ciks",[]))
    ciks=sorted(c for c in ciks if c%a.nshards==a.shard)
    print(json.dumps({"shard":a.shard,"nshards":a.nshards,"target_ciks":len(ciks)}),flush=True)
    rows=[]; audits=[]
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs={ex.submit(process_cik,c):c for c in ciks}
        for i,f in enumerate(as_completed(futs),1):
            rr,aa=f.result(); rows.extend(rr); audits.append(aa)
            if i%10==0: print("PROGRESS",i,"/",len(ciks),"candidate_rows",len(rows),flush=True)
    d=pd.DataFrame(rows)
    if d.empty:
        d=pd.DataFrame(columns=["cik","accn","accepted","filed","form","source_file","concept","qname","label","label_role","presentation_roles","semantic_class","auto_accept","context_ref","start","end","instant","unit","value","decimals","scale"])
    d.to_csv(OUT/f"custom_xbrl_facts_{a.shard:02d}.csv.gz",index=False,compression="gzip")
    pd.DataFrame(audits).sort_values("cik").to_csv(OUT/f"custom_xbrl_audit_{a.shard:02d}.csv",index=False)
    summary={
        "schema":"V4_SEC_CUSTOM_XBRL_RECOVERY_SHARD_V1","shard":a.shard,"nshards":a.nshards,
        "target_ciks":len(ciks),"candidate_rows":int(len(d)),
        "auto_accept_rows":int(d["auto_accept"].astype(str).str.lower().isin(["true","1"]).sum()) if len(d) else 0,
        "semantic_counts":d["semantic_class"].value_counts().to_dict() if len(d) else {},
        "formation_2023_opened":False,"future_outcomes_used":False,"us3700_used":False,
        "new_corp_action_lookup_calls":0,
        "policy":"Only exact custom concepts are auto-accepted. Near matches are audit-only."
    }
    (OUT/f"summary_{a.shard:02d}.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print(json.dumps(summary,indent=2),flush=True)

if __name__=="__main__": main()
