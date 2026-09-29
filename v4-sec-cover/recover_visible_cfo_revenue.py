from __future__ import annotations
import argparse, io, json, math, re, threading, time, zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import pandas as pd
import requests
from lxml import etree

ROOT=Path(".")
TARGETS=json.loads((ROOT/"v4-sec-cover/current_visible_cfo_revenue_targets.json").read_text())
MASKS=json.loads((ROOT/"v4-sec-cover/current_f34_missing_masks.json").read_text())
SNAPS=list(MASKS["snaps"])
CIK_MASKS={int(k):(int(v[0]),int(v[1])) for k,v in MASKS["cik_masks"].items()}
CAP_CIKS=set(int(x) for x in TARGETS["capex_ciks"])
SHARE_CIKS=set(int(x) for x in TARGETS["share_ciks"])
ALL_CIKS=set(int(x) for x in TARGETS["union_ciks"])
OUT=ROOT/"v4-sec-visible-cfo-revenue-output";OUT.mkdir(parents=True,exist_ok=True)

FORMS={"10-Q","10-K","10-Q/A","10-K/A"}
UA="V4-Full-Rigor visible-row XBRL recovery research@example.com"
H={"User-Agent":UA,"Accept-Encoding":"gzip, deflate","Accept":"application/json"}
SESSION=requests.Session();SESSION.headers.update(H)
RATE_LOCK=threading.Lock();LAST=[0.0]
XL="{http://www.w3.org/1999/xlink}"

def rate_wait():
  with RATE_LOCK:
    dt=time.monotonic()-LAST[0]
    if dt<0.45: time.sleep(0.45-dt)
    LAST[0]=time.monotonic()

def get(url,timeout=75,attempts=4):
  last=""
  for i in range(attempts):
    try:
      rate_wait();r=SESSION.get(url,timeout=timeout)
      if r.status_code==404:return None,"NOT_FOUND",""
      if r.status_code in {429,500,502,503,504}:raise RuntimeError(f"HTTP_{r.status_code}")
      r.raise_for_status();return r,"OK",""
    except Exception as e:
      last=repr(e)[:300]
      if i<attempts-1:time.sleep(min(20,1.5*(2**i)))
  return None,"ERROR",last

def get_json(url):
  r,s,e=get(url,45)
  if s!="OK":raise RuntimeError(f"{s}:{e}")
  return r.json()

def parse_block(a):
  keys=["accessionNumber","acceptanceDateTime","filingDate","form","primaryDocument"]
  n=max([len(a.get(k) or []) for k in keys]+[0]);out=[]
  for i in range(n):
    def v(k):
      z=a.get(k) or [];return str(z[i] if i<len(z) else "").strip()
    acc=v("accessionNumber");form=v("form").upper();accepted=v("acceptanceDateTime");filed=v("filingDate")
    if not acc or form not in FORMS:continue
    ad=(accepted[:10] if accepted else filed[:10])
    if ad and ad>"2022-12-30":continue
    out.append({"accn":acc,"accepted":accepted,"filed":filed,"form":form,"primary":v("primaryDocument")})
  return out

def target_dates(cik):
  f3,f4=CIK_MASKS.get(int(cik),(0,0))
  mask=(f3 if (cik in CFO_CIKS or cik in REV_CIKS) else 0)
  return [SNAPS[i] for i in range(len(SNAPS)) if mask&(1<<i)]

def filings_for_cik(cik):
  tg=target_dates(cik)
  if not tg:return []
  earliest=pd.Timestamp(min(tg))-pd.Timedelta(days=900);latest=pd.Timestamp(max(tg))
  sub=get_json(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json")
  rows=parse_block(((sub.get("filings") or {}).get("recent") or {}))
  for meta in ((sub.get("filings") or {}).get("files") or []):
    frm=str(meta.get("filingFrom") or "");to=str(meta.get("filingTo") or "")
    if frm and pd.Timestamp(frm)>latest:continue
    if to and pd.Timestamp(to)<earliest:continue
    name=str(meta.get("name") or "").strip()
    if not name:continue
    try:rows.extend(parse_block(get_json("https://data.sec.gov/submissions/"+name)))
    except Exception:pass
  ded={x["accn"]:x for x in rows};out=[]
  for x in ded.values():
    ds=(x["accepted"] or x["filed"])[:10]
    try:t=pd.Timestamp(ds)
    except Exception:continue
    if earliest<=t<=latest:out.append(x)
  return sorted(out,key=lambda x:(x["accepted"] or x["filed"],x["accn"]))

def root(data):
  return etree.fromstring(data,parser=etree.XMLParser(recover=True,huge_tree=True))

def role_defs(z):
  d={}
  for n in z.namelist():
    if not n.lower().endswith(".xsd"):continue
    try:r=root(z.read(n))
    except Exception:continue
    for e in r.xpath("//*[local-name()='roleType']"):
      u=e.get("roleURI") or "";tx=e.xpath("./*[local-name()='definition']/text()")
      if u:d[u]=" ".join(map(str,tx)).strip()
  return d

def presentation(z,rdefs):
  d={}
  for n in z.namelist():
    if not n.lower().endswith("_pre.xml"):continue
    try:r=root(z.read(n))
    except Exception:continue
    for link in r.xpath("//*[local-name()='presentationLink']"):
      uri=link.get(XL+"role") or "";rd=rdefs.get(uri,uri);loc={}
      for e in link.xpath("./*[local-name()='loc']"):
        h=e.get(XL+"href") or "";k=e.get(XL+"label") or ""
        if k and "#" in h:loc[k]=h.split("#")[-1]
      for c in loc.values():d.setdefault(c,set()).add(rd)
  return d

def contexts(r):
  d={}
  for c in r.xpath("//*[local-name()='context']"):
    cid=c.get("id") or ""
    if not cid:continue
    st=c.xpath(".//*[local-name()='startDate']/text()");en=c.xpath(".//*[local-name()='endDate']/text()");ins=c.xpath(".//*[local-name()='instant']/text()")
    dims=c.xpath(".//*[local-name()='explicitMember' or local-name()='typedMember']")
    d[cid]={"start":str(st[0])[:10] if st else "","end":str(en[0])[:10] if en else (str(ins[0])[:10] if ins else ""),"instant":bool(ins),"dimensioned":bool(dims)}
  return d

def units(r):
  d={}
  for u in r.xpath("//*[local-name()='unit']"):
    uid=u.get("id") or "";ms=["".join(x.itertext()).strip() for x in u.xpath(".//*[local-name()='measure']")]
    d[uid]="|".join(ms)
  return d

def num(el):
  t=" ".join("".join(el.itertext()).split())
  if not t:return None
  neg=("(" in t and ")" in t);cl=re.sub(r"[^0-9.\-]","",t)
  if cl in {"","-",".","-."}:return None
  try:v=float(cl)
  except:return None
  if neg:v=-abs(v)
  if (el.get("sign") or "")=="-":v=-abs(v)
  try:v*=10**int(el.get("scale") or "0")
  except:pass
  return v if math.isfinite(v) else None

def norm(s):
  s=re.sub(r"\s+"," ",str(s or "")).strip()
  s=re.sub(r"^[•·\-–—]+\s*","",s)
  return s.strip(" :;")

def row_label(el):
  tr=el.xpath("ancestor::*[local-name()='tr'][1]")
  if not tr:return ""
  cells=tr[0].xpath("./*[local-name()='td' or local-name()='th']")
  for c in cells:
    txt=norm(" ".join(c.itertext()))
    # remove pure-number table cells; first alphabetic cell is the visible line label
    if re.search(r"[A-Za-z]",txt) and len(txt)<=300:
      return txt
  return ""

def classify_visible(lbl,roles,need_cfo,need_rev):
  l=norm(lbl).lower()
  role=" | ".join(sorted(roles)).lower()
  if need_cfo and "statement" in role and "cash flow" in role and "disclosure" not in role:
    exact_cfo={
      "net cash provided by operating activities",
      "net cash used in operating activities",
      "net cash provided by (used in) operating activities",
      "net cash provided by (used for) operating activities",
      "net cash provided by operating activities:",
      "net cash used in operating activities:",
      "cash flows from operating activities",
    }
    if l in exact_cfo:return "CFO_VISIBLE_EXACT",True
    if "operating activities" in l:return "CFO_VISIBLE_NEAR",False
  if need_rev:
    okrole=("statement" in role and re.search(r"income|operations|earnings",role) is not None and "cash flow" not in role and "disclosure" not in role)
    if okrole and l in {"revenue","revenues","total revenue","total revenues","net revenue","net revenues","sales","net sales","sales, net","sales net","operating revenue","operating revenues","total operating revenue","total operating revenues"}:
      return "REVENUE_VISIBLE_EXACT",True
    if okrole and ("revenue" in l or "sales" in l):return "REVENUE_VISIBLE_NEAR",False
  return "",False

def parse_cal(z,rdefs):
  arcs=[]
  for n in z.namelist():
    if not n.lower().endswith("_cal.xml"):continue
    try:r=root(z.read(n))
    except Exception:continue
    for link in r.xpath("//*[local-name()='calculationLink']"):
      uri=link.get(XL+"role") or "";rd=rdefs.get(uri,uri);loc={}
      for e in link.xpath("./*[local-name()='loc']"):
        h=e.get(XL+"href") or "";k=e.get(XL+"label") or ""
        if k and "#" in h:loc[k]=h.split("#")[-1]
      for e in link.xpath("./*[local-name()='calculationArc']"):
        fr=loc.get(e.get(XL+"from") or "");to=loc.get(e.get(XL+"to") or "")
        if fr and to:
          try:w=float(e.get("weight") or "1")
          except:w=1.0
          arcs.append((rd,fr,to,w))
  return arcs

def parse_filing(cik,fil,z):
  rdefs=role_defs(z);pres=presentation(z,rdefs);allfacts=[];candidates=[]
  for n in z.namelist():
    if not n.lower().endswith((".htm",".html")):continue
    try:r=root(z.read(n))
    except Exception:continue
    ctx=contexts(r);ums=units(r)
    for e in r.xpath("//*[local-name()='nonFraction']"):
      q=e.get("name") or ""
      if ":" not in q:continue
      pref,loc=q.split(":",1);concept=pref+"_"+loc;cref=e.get("contextRef") or "";cm=ctx.get(cref,{})
      if cm.get("dimensioned"):continue
      v=num(e)
      if v is None:continue
      u=ums.get(e.get("unitRef") or "","")
      rec={"cik":int(cik),"accn":fil["accn"],"accepted":fil["accepted"],"filed":fil["filed"],"form":fil["form"],"source_file":n,
           "concept":concept,"qname":q,"context_ref":cref,"start":cm.get("start",""),"end":cm.get("end",""),"instant":bool(cm.get("instant")),
           "unit":u,"value":float(v),"decimals":e.get("decimals") or "","scale":e.get("scale") or ""}
      allfacts.append(rec)
      lbl=row_label(e)
      if lbl:
        cls,accept=classify_visible(lbl,pres.get(concept,set()),cik in CFO_CIKS,cik in REV_CIKS)
        if cls:
          qrec=dict(rec);qrec.update({"visible_label":lbl,"presentation_roles":" || ".join(sorted(pres.get(concept,set())))[:2500],"semantic_class":cls,"auto_accept":accept})
          candidates.append(qrec)
  arcs=parse_cal(z,rdefs)
  cand_concepts=set(x["concept"] for x in candidates)
  related=set(cand_concepts)
  kept_arcs=[]
  for rd,fr,to,w in arcs:
    if fr in cand_concepts or to in cand_concepts:
      related.update([fr,to]);kept_arcs.append({"cik":int(cik),"accn":fil["accn"],"accepted":fil["accepted"],"cal_role":rd,"from_concept":fr,"to_concept":to,"weight":w})
  relfacts=[x for x in allfacts if x["concept"] in related]
  return candidates,kept_arcs,relfacts

def process(cik):
  aud={"cik":int(cik),"status":"OK","filings":0,"zip_ok":0,"zip_missing":0,"candidate_rows":0,"exact_rows":0,"cal_arcs":0,"related_facts":0,"error":""}
  cand=[];arcs=[];rel=[]
  try:
    fs=filings_for_cik(cik);aud["filings"]=len(fs)
    for fil in fs:
      ad=fil["accn"].replace("-","");url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{ad}/{fil['accn']}-xbrl.zip"
      r,s,e=get(url)
      if s=="NOT_FOUND":aud["zip_missing"]+=1;continue
      if s!="OK":continue
      aud["zip_ok"]+=1
      try:
        z=zipfile.ZipFile(io.BytesIO(r.content));c,a,rf=parse_filing(cik,fil,z);cand+=c;arcs+=a;rel+=rf
      except Exception:continue
    aud["candidate_rows"]=len(cand);aud["exact_rows"]=sum(bool(x["auto_accept"]) for x in cand);aud["cal_arcs"]=len(arcs);aud["related_facts"]=len(rel)
  except Exception as e:
    aud["status"]="ERROR";aud["error"]=repr(e)[:500]
  return cand,arcs,rel,aud

def main():
  ap=argparse.ArgumentParser();ap.add_argument("--shard",type=int,required=True);ap.add_argument("--nshards",type=int,default=4);a=ap.parse_args()
  ciks=sorted(c for c in ALL_CIKS if c%a.nshards==a.shard)
  C=[];A=[];R=[];U=[]
  with ThreadPoolExecutor(max_workers=1) as ex:
    futs={ex.submit(process,c):c for c in ciks}
    for i,f in enumerate(as_completed(futs),1):
      c,ar,rf,u=f.result();C+=c;A+=ar;R+=rf;U.append(u)
      if i%10==0:print("PROGRESS",i,"/",len(ciks),"cand",len(C),"arcs",len(A),flush=True)
  cd=pd.DataFrame(C);ad=pd.DataFrame(A);rd=pd.DataFrame(R);ud=pd.DataFrame(U)
  cd.to_csv(OUT/f"visible_candidates_{a.shard:02d}.csv.gz",index=False,compression="gzip")
  ad.to_csv(OUT/f"cal_arcs_{a.shard:02d}.csv.gz",index=False,compression="gzip")
  rd.to_csv(OUT/f"cal_related_facts_{a.shard:02d}.csv.gz",index=False,compression="gzip")
  ud.to_csv(OUT/f"audit_{a.shard:02d}.csv",index=False)
  summary={"schema":"V4_SEC_VISIBLE_CFO_REVENUE_SHARD_V1","shard":a.shard,"target_ciks":len(ciks),"candidate_rows":len(cd),"exact_rows":int(cd.auto_accept.astype(str).str.lower().isin(["true","1"]).sum()) if len(cd) else 0,
           "semantic_counts":cd.semantic_class.value_counts().to_dict() if len(cd) else {},"cal_arcs":len(ad),"related_facts":len(rd),"formation_2023_opened":False,"future_outcomes_used":False,"us3700_used":False,"new_corp_action_lookup_calls":0}
  (OUT/f"summary_{a.shard:02d}.json").write_text(json.dumps(summary,indent=2),encoding="utf-8");print(json.dumps(summary,indent=2),flush=True)
if __name__=="__main__":main()
