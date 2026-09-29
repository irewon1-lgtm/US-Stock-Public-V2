from __future__ import annotations
import argparse,json,math,re,time
from pathlib import Path
import pandas as pd,requests
from lxml import etree

ROOT=Path(".")
T=json.loads((ROOT/"v4-sec-cover/mcap_primary_html_retry_targets.json").read_text())
OUT=ROOT/"v4-sec-mcap-primary-html-retry-output";OUT.mkdir(exist_ok=True)
FORMS={"10-Q","10-K","10-Q/A","10-K/A","20-F","20-F/A","40-F","40-F/A"}
UA="V4-Full-Rigor exact-shares primary-html retry research@example.com"
S=requests.Session();S.headers.update({"User-Agent":UA,"Accept-Encoding":"gzip, deflate","Accept":"text/html,application/xhtml+xml"})
LOCAL={"EntityCommonStockSharesOutstanding":"DEI_ENTITY_COMMON_SHARES","CommonStockSharesOutstanding":"USGAAP_COMMON_SHARES"}

def get(url,timeout=60,attempts=6):
    last=""
    for i in range(attempts):
        try:
            r=S.get(url,timeout=timeout)
            if r.status_code==404:return None
            if r.status_code in {429,500,502,503,504}:
                raise RuntimeError(f"HTTP_{r.status_code}")
            r.raise_for_status();return r
        except Exception as e:
            last=repr(e)[:300]
            if i<attempts-1:time.sleep(min(25,2.0*(2**i)))
    return "ERROR:"+last

def getj(url):
    r=get(url,45)
    if r is None or isinstance(r,str): raise RuntimeError(str(r))
    return r.json()

def recent_rows(a):
    keys=["accessionNumber","acceptanceDateTime","filingDate","form","primaryDocument"]
    n=max([len(a.get(k) or []) for k in keys]+[0]);out=[]
    for i in range(n):
        def v(k):
            x=a.get(k) or [];return str(x[i] if i<len(x) else "").strip()
        acc=v("accessionNumber"); form=v("form").upper(); ac=v("acceptanceDateTime"); fd=v("filingDate"); pdx=v("primaryDocument")
        if not acc or not pdx or form not in FORMS:continue
        ds=(ac or fd)[:10]
        if not ds or ds<"2017-01-01" or ds>"2022-12-30":continue
        out.append({"accn":acc,"accepted":ac,"filed":fd,"form":form,"primary":pdx})
    return out

def filings(cik):
    sub=getj(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    out=recent_rows(((sub.get("filings") or {}).get("recent") or {}))
    for meta in ((sub.get("filings") or {}).get("files") or []):
        name=str(meta.get("name") or "").strip()
        if not name:continue
        frm=str(meta.get("filingFrom") or "");to=str(meta.get("filingTo") or "")
        if frm and frm>"2022-12-30":continue
        if to and to<"2017-01-01":continue
        try:out.extend(recent_rows(getj("https://data.sec.gov/submissions/"+name)))
        except:pass
    d={x["accn"]:x for x in out}
    return sorted(d.values(),key=lambda x:(x.get("accepted") or x.get("filed") or "",x["accn"]))

def ctxmap(root):
    out={}
    for c in root.xpath("//*[local-name()='context']"):
        cid=c.get("id") or ""
        if not cid:continue
        inst=c.xpath(".//*[local-name()='instant']/text()")
        dims=c.xpath(".//*[local-name()='explicitMember' or local-name()='typedMember']")
        out[cid]={"end":str(inst[0])[:10] if inst else "","dimensioned":bool(dims)}
    return out

def units(root):
    out={}
    for u in root.xpath("//*[local-name()='unit']"):
        uid=u.get("id") or ""
        ms=["".join(x.itertext()).strip() for x in u.xpath(".//*[local-name()='measure']")]
        out[uid]="|".join(ms)
    return out

def num(el):
    txt=" ".join("".join(el.itertext()).split())
    clean=re.sub(r"[^0-9.\-]","",txt)
    if clean in {"","-",".","-."}:return None
    try:v=float(clean)
    except:return None
    if "(" in txt and ")" in txt:v=-abs(v)
    if (el.get("sign") or "").strip()=="-":v=-abs(v)
    try:sc=int(el.get("scale") or "0")
    except:sc=0
    v*=10**sc
    return v if math.isfinite(v) else None

def extract(root,cik,f,url):
    cm=ctxmap(root);um=units(root);rows=[]
    for el in root.xpath("//*[local-name()='nonFraction']"):
        qn=el.get("name") or ""
        if ":" not in qn:continue
        pref,local=qn.split(":",1)
        if local not in LOCAL:continue
        if local=="EntityCommonStockSharesOutstanding" and pref.lower()!="dei":continue
        if local=="CommonStockSharesOutstanding" and pref.lower()!="us-gaap":continue
        c=cm.get(el.get("contextRef") or "",{})
        if c.get("dimensioned"):continue
        end=c.get("end","")
        if not end or end>"2022-12-30":continue
        unit=um.get(el.get("unitRef") or "","")
        if "share" not in unit.lower():continue
        v=num(el)
        if v is None or v<=0:continue
        rows.append({"cik":cik,"accn":f["accn"],"accepted":f["accepted"],"filed":f["filed"],"form":f["form"],"primary":f["primary"],"url":url,
                     "tag":local,"role":LOCAL[local],"value":v,"end":end,"unit":unit,"context_ref":el.get("contextRef") or ""})
    return rows

def one(cik):
    rows=[];aud={"cik":cik,"filings":0,"html_ok":0,"facts":0,"errors":0}
    fs=filings(cik);aud["filings"]=len(fs)
    for f in fs:
        ad=f["accn"].replace("-","")
        url=f"https://www.sec.gov/Archives/edgar/data/{cik}/{ad}/{f['primary']}"
        r=get(url,70)
        if r is None or isinstance(r,str):
            aud["errors"]+=1;continue
        aud["html_ok"]+=1
        try:root=etree.fromstring(r.content,parser=etree.XMLParser(recover=True,huge_tree=True))
        except:continue
        rows.extend(extract(root,cik,f,url))
        time.sleep(.15)
    aud["facts"]=len(rows)
    return rows,aud

ap=argparse.ArgumentParser();ap.add_argument("--shard",type=int,required=True);ap.add_argument("--nshards",type=int,default=2);a=ap.parse_args()
ciks=[int(x) for x in T["ciks"] if int(x)%a.nshards==a.shard]
rows=[];auds=[]
for i,cik in enumerate(ciks,1):
    try:rr,aa=one(cik)
    except Exception as e:rr=[];aa={"cik":cik,"filings":0,"html_ok":0,"facts":0,"errors":1,"fatal":repr(e)[:500]}
    rows.extend(rr);auds.append(aa);print("CIK",cik,"facts",len(rr),i,"/",len(ciks),flush=True)
d=pd.DataFrame(rows)
if d.empty:d=pd.DataFrame(columns=["cik","accn","accepted","filed","form","primary","url","tag","role","value","end","unit","context_ref"])
d=d.drop_duplicates(subset=["cik","accn","tag","value","end","context_ref"])
d.to_csv(OUT/f"facts_{a.shard}.csv.gz",index=False,compression="gzip")
pd.DataFrame(auds).to_csv(OUT/f"audit_{a.shard}.csv",index=False)
summary={"schema":"V4_MCAP_PRIMARY_HTML_RETRY_SHARD_V1","shard":a.shard,"target_ciks":len(ciks),"fact_rows":len(d),"ciks_with_facts":int(d.cik.nunique()) if len(d) else 0,"formation_2023_opened":False,"future_outcomes_used":False,"us3700_used":False,"new_corp_action_lookup_calls":0}
(OUT/f"summary_{a.shard}.json").write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))
