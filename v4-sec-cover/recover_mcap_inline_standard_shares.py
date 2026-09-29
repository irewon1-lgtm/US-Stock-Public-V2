from __future__ import annotations
import argparse, io, json, math, re, threading, time, zipfile
from pathlib import Path
import pandas as pd
import requests
from lxml import etree

ROOT=Path(".")
TARGET=json.loads((ROOT/"v4-sec-cover/mcap_inline_standard_shares_targets.json").read_text())
OUT=ROOT/"v4-sec-mcap-inline-shares-output"; OUT.mkdir(exist_ok=True)
FORMS={"10-Q","10-K","10-Q/A","10-K/A","20-F","20-F/A","40-F","40-F/A"}
START=pd.Timestamp("2017-01-01T00:00:00Z")
END=pd.Timestamp("2022-12-30T23:59:59Z")
LOCAL_NAMES={"EntityCommonStockSharesOutstanding":"DEI_ENTITY_COMMON_SHARES","CommonStockSharesOutstanding":"USGAAP_COMMON_SHARES"}
UA="V4-Full-Rigor direct-inline market-cap shares research@example.com"
S=requests.Session(); S.headers.update({"User-Agent":UA,"Accept-Encoding":"gzip, deflate","Accept":"application/json"})
LOCK=threading.Lock(); LAST=[0.0]

def rate_wait():
    with LOCK:
        dt=time.monotonic()-LAST[0]
        if dt<0.32: time.sleep(0.32-dt)
        LAST[0]=time.monotonic()

def get(url,timeout=60,attempts=4):
    last=""
    for i in range(attempts):
        try:
            rate_wait(); r=S.get(url,timeout=timeout)
            if r.status_code==404: return None
            if r.status_code in {429,500,502,503,504}: raise RuntimeError(f"HTTP_{r.status_code}")
            r.raise_for_status(); return r
        except Exception as e:
            last=repr(e)[:400]
            if i<attempts-1: time.sleep(min(15,1.5*(2**i)))
    raise RuntimeError(last)

def get_json(url,timeout=45):
    r=get(url,timeout)
    if r is None: raise RuntimeError("NOT_FOUND "+url)
    return r.json()

def rows_from_block(a):
    keys=["accessionNumber","acceptanceDateTime","filingDate","form","primaryDocument"]
    n=max([len(a.get(k) or []) for k in keys]+[0])
    out=[]
    for i in range(n):
        def v(k):
            x=a.get(k) or []
            return str(x[i] if i<len(x) else "").strip()
        acc=v("accessionNumber"); form=v("form").upper(); accepted=v("acceptanceDateTime"); filed=v("filingDate")
        if not acc or form not in FORMS: continue
        ds=accepted or filed
        try: t=pd.Timestamp(ds)
        except: continue
        if t.tzinfo is None: t=t.tz_localize("UTC")
        else: t=t.tz_convert("UTC")
        if START<=t<=END:
            out.append({"accn":acc,"accepted":accepted,"filed":filed,"form":form,"primary":v("primaryDocument")})
    return out

def filings(cik):
    cik10=f"{int(cik):010d}"
    sub=get_json(f"https://data.sec.gov/submissions/CIK{cik10}.json")
    out=rows_from_block(((sub.get("filings") or {}).get("recent") or {}))
    for meta in ((sub.get("filings") or {}).get("files") or []):
        name=str(meta.get("name") or "").strip()
        if not name: continue
        frm=str(meta.get("filingFrom") or ""); to=str(meta.get("filingTo") or "")
        if frm and frm>"2022-12-30": continue
        if to and to<"2017-01-01": continue
        try:
            old=get_json("https://data.sec.gov/submissions/"+name)
            out.extend(rows_from_block(old if isinstance(old,dict) else {}))
        except Exception:
            continue
    d={}
    for x in out: d[x["accn"]]=x
    return sorted(d.values(),key=lambda x:(x.get("accepted") or x.get("filed") or "",x["accn"]))

def parse_num(text,scale=0,sign=""):
    t=" ".join(str(text or "").split())
    if not t or t in {"-","—","–","N/A","n/a"}: return None
    neg=("(" in t and ")" in t)
    clean=re.sub(r"[^0-9.\-]","",t)
    if clean in {"","-",".","-."}: return None
    try: v=float(clean)
    except: return None
    if neg: v=-abs(v)
    if str(sign).strip()=="-": v=-abs(v)
    try: sc=int(scale or 0)
    except: sc=0
    v*=10**sc
    return v if math.isfinite(v) else None

def context_map(root):
    out={}
    for c in root.xpath("//*[local-name()='context']"):
        cid=c.get("id") or ""
        if not cid: continue
        inst=c.xpath(".//*[local-name()='instant']/text()")
        dims=c.xpath(".//*[local-name()='explicitMember' or local-name()='typedMember']")
        out[cid]={"end":str(inst[0])[:10] if inst else "","instant":bool(inst),"dimensioned":bool(dims)}
    return out

def unit_map(root):
    out={}
    for u in root.xpath("//*[local-name()='unit']"):
        uid=u.get("id") or ""
        ms=["".join(x.itertext()).strip() for x in u.xpath(".//*[local-name()='measure']")]
        out[uid]="|".join(ms)
    return out

def exact_namespace_ok(uri,local):
    uri=str(uri or "")
    if local=="EntityCommonStockSharesOutstanding":
        return "xbrl.sec.gov/dei" in uri
    if local=="CommonStockSharesOutstanding":
        return "fasb.org/us-gaap" in uri
    return False

def extract_from_root(root,cik,fil,source_file,is_inline):
    ctx=context_map(root); units=unit_map(root); rows=[]
    if is_inline:
        els=root.xpath("//*[local-name()='nonFraction']")
        for el in els:
            qn=el.get("name") or ""
            if ":" not in qn: continue
            local=qn.split(":",1)[1]
            if local not in LOCAL_NAMES: continue
            # exact prefix/namespace discipline
            pref=qn.split(":",1)[0].lower()
            if local=="EntityCommonStockSharesOutstanding" and pref!="dei": continue
            if local=="CommonStockSharesOutstanding" and pref!="us-gaap": continue
            cm=ctx.get(el.get("contextRef") or "",{})
            if not cm.get("instant") or cm.get("dimensioned"): continue
            end=cm.get("end","")
            if not end or end>"2022-12-30": continue
            unit=units.get(el.get("unitRef") or "","")
            if "share" not in unit.lower(): continue
            val=parse_num("".join(el.itertext()),el.get("scale"),el.get("sign"))
            if val is None or val<=0: continue
            rows.append({"cik":cik,"accn":fil["accn"],"accepted":fil["accepted"],"filed":fil["filed"],"form":fil["form"],
                         "source_file":source_file,"tag":local,"role":LOCAL_NAMES[local],"unit":unit,"value":val,"end":end,
                         "context_ref":el.get("contextRef") or "","source_kind":"INLINE_NONFRACTION"})
    else:
        for el in root.iter():
            try: q=etree.QName(el)
            except: continue
            local=q.localname
            if local not in LOCAL_NAMES or not exact_namespace_ok(q.namespace,local): continue
            cm=ctx.get(el.get("contextRef") or "",{})
            if not cm.get("instant") or cm.get("dimensioned"): continue
            end=cm.get("end","")
            if not end or end>"2022-12-30": continue
            unit=units.get(el.get("unitRef") or "","")
            if "share" not in unit.lower(): continue
            val=parse_num("".join(el.itertext()),0,"")
            if val is None or val<=0: continue
            rows.append({"cik":cik,"accn":fil["accn"],"accepted":fil["accepted"],"filed":fil["filed"],"form":fil["form"],
                         "source_file":source_file,"tag":local,"role":LOCAL_NAMES[local],"unit":unit,"value":val,"end":end,
                         "context_ref":el.get("contextRef") or "","source_kind":"INSTANCE_XML"})
    return rows

def one(cik):
    aud={"cik":cik,"status":"OK","filings":0,"zip_ok":0,"fact_rows":0,"error":""}; rows=[]
    try:
        fs=filings(cik); aud["filings"]=len(fs)
        for fil in fs:
            acc=fil["accn"]; ad=acc.replace("-","")
            r=get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{ad}/{acc}-xbrl.zip",75)
            if r is None: continue
            aud["zip_ok"]+=1
            try: z=zipfile.ZipFile(io.BytesIO(r.content))
            except: continue
            for name in z.namelist():
                low=name.lower()
                if low.endswith((".htm",".html")):
                    try: root=etree.fromstring(z.read(name),parser=etree.XMLParser(recover=True,huge_tree=True))
                    except: continue
                    rows.extend(extract_from_root(root,cik,fil,name,True))
                elif low.endswith(".xml") and not any(low.endswith(s) for s in ["_cal.xml","_def.xml","_lab.xml","_pre.xml"]):
                    try: root=etree.fromstring(z.read(name),parser=etree.XMLParser(recover=True,huge_tree=True))
                    except: continue
                    rows.extend(extract_from_root(root,cik,fil,name,False))
        aud["fact_rows"]=len(rows)
    except Exception as e:
        aud["status"]="ERROR"; aud["error"]=repr(e)[:500]
    return rows,aud

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--shard",type=int,required=True); ap.add_argument("--nshards",type=int,default=4)
    a=ap.parse_args()
    ciks=[int(c) for c in TARGET["ciks"] if int(c)%a.nshards==a.shard]
    rows=[]; audits=[]
    for i,cik in enumerate(ciks,1):
        rr,aa=one(cik); rows.extend(rr); audits.append(aa)
        if i%10==0: print("PROGRESS",a.shard,i,"/",len(ciks),"facts",len(rows),flush=True)
    d=pd.DataFrame(rows)
    if d.empty:
        d=pd.DataFrame(columns=["cik","accn","accepted","filed","form","source_file","tag","role","unit","value","end","context_ref","source_kind"])
    d=d.drop_duplicates(subset=["cik","accn","tag","value","end","context_ref","source_kind"])
    d.to_csv(OUT/f"inline_standard_shares_{a.shard:02d}.csv.gz",index=False,compression="gzip")
    pd.DataFrame(audits).to_csv(OUT/f"audit_{a.shard:02d}.csv",index=False)
    summary={"schema":"V4_MCAP_INLINE_STANDARD_SHARES_SHARD_V1","shard":a.shard,"target_ciks":len(ciks),
             "fact_rows":int(len(d)),"ciks_with_facts":int(d.cik.nunique()) if len(d) else 0,
             "fetch_errors":sum(x["status"]!="OK" for x in audits),"formation_2023_opened":False,
             "future_outcomes_used":False,"us3700_used":False,"new_corp_action_lookup_calls":0}
    (OUT/f"summary_{a.shard:02d}.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print(json.dumps(summary,indent=2),flush=True)
if __name__=="__main__": main()
