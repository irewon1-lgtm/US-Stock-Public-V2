from __future__ import annotations
import argparse, json, math, re, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import pandas as pd
import requests
from lxml import etree

ROOT=Path(".")
MASKS=json.loads((ROOT/"v4-sec-cover/current_f34_missing_masks.json").read_text())
VIS=json.loads((ROOT/"v4-sec-cover/current_visible_row_targets.json").read_text())
SNAPS=list(MASKS["snaps"])
CIK_MASKS={int(k):(int(v[0]),int(v[1])) for k,v in MASKS["cik_masks"].items()}
ALREADY_RAW=set(int(x) for x in VIS["union_ciks"])
ALL_CIKS=set(CIK_MASKS)-ALREADY_RAW
OUT=ROOT/"v4-sec-raw-exact-output"; OUT.mkdir(parents=True,exist_ok=True)

FORMS={"10-Q","10-K","10-Q/A","10-K/A"}
TAGS={
 "RevenueFromContractWithCustomerExcludingAssessedTax":"REVENUE",
 "RevenueFromContractWithCustomerIncludingAssessedTax":"REVENUE",
 "Revenues":"REVENUE",
 "SalesRevenueNet":"REVENUE",
 "RegulatedAndUnregulatedOperatingRevenue":"REVENUE",
 "NetCashProvidedByUsedInOperatingActivities":"CFO",
 "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations":"CFO_CONTINUING",
 "CashProvidedByUsedInOperatingActivitiesDiscontinuedOperations":"CFO_DISCONTINUED",
 "PaymentsToAcquirePropertyPlantAndEquipment":"CAPEX",
 "PaymentsForAdditionsToPropertyPlantAndEquipment":"CAPEX",
 "WeightedAverageNumberOfDilutedSharesOutstanding":"DILUTED",
 "WeightedAverageNumberOfSharesOutstandingBasic":"BASIC",
 "WeightedAverageNumberOfShareOutstandingBasicAndDiluted":"COMBINED",
 "WeightedAverageNumberDilutedSharesOutstandingAdjustment":"DILUTED_ADJUSTMENT",
}
UA="V4-Full-Rigor raw-exact iXBRL research@example.com"
S=requests.Session();S.headers.update({"User-Agent":UA,"Accept-Encoding":"gzip, deflate","Accept":"text/html,application/json"})
LOCK=threading.Lock();LAST=[0.0]

def wait_rate():
  with LOCK:
    dt=time.monotonic()-LAST[0]
    if dt<0.45: time.sleep(0.45-dt)
    LAST[0]=time.monotonic()

def get(url,timeout=60,attempts=4):
  last=""
  for i in range(attempts):
    try:
      wait_rate();r=S.get(url,timeout=timeout)
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
    acc=v("accessionNumber");form=v("form").upper();accepted=v("acceptanceDateTime");filed=v("filingDate");primary=v("primaryDocument")
    if not acc or not primary or form not in FORMS:continue
    ad=(accepted[:10] if accepted else filed[:10])
    if ad and ad>"2022-12-30":continue
    out.append({"accn":acc,"accepted":accepted,"filed":filed,"form":form,"primary":primary})
  return out

def target_dates(cik):
  f3,f4=CIK_MASKS[int(cik)];mask=f3|f4
  return [SNAPS[i] for i in range(len(SNAPS)) if mask&(1<<i)]

def filings(cik):
  tg=target_dates(cik)
  earliest=pd.Timestamp(min(tg))-pd.Timedelta(days=900);latest=pd.Timestamp(max(tg))
  sub=get_json(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json")
  rows=parse_block(((sub.get("filings") or {}).get("recent") or {}))
  for m in ((sub.get("filings") or {}).get("files") or []):
    frm=str(m.get("filingFrom") or "");to=str(m.get("filingTo") or "")
    if frm:
      try:
        if pd.Timestamp(frm)>latest:continue
      except:pass
    if to:
      try:
        if pd.Timestamp(to)<earliest:continue
      except:pass
    name=str(m.get("name") or "").strip()
    if not name:continue
    try:rows.extend(parse_block(get_json("https://data.sec.gov/submissions/"+name)))
    except Exception:pass
  ded={x["accn"]:x for x in rows};out=[]
  for x in ded.values():
    ds=(x["accepted"] or x["filed"])[:10]
    try:t=pd.Timestamp(ds)
    except:continue
    if earliest<=t<=latest:out.append(x)
  return sorted(out,key=lambda x:(x["accepted"] or x["filed"],x["accn"]))

def parse_root(data):
  return etree.fromstring(data,parser=etree.HTMLParser(recover=True,huge_tree=True))

def contexts(root):
  d={}
  for c in root.xpath("//*[local-name()='context']"):
    cid=c.get("id") or ""
    if not cid:continue
    st=c.xpath(".//*[local-name()='startDate']/text()");en=c.xpath(".//*[local-name()='endDate']/text()");ins=c.xpath(".//*[local-name()='instant']/text()")
    dims=c.xpath(".//*[local-name()='explicitMember' or local-name()='typedMember']")
    d[cid]={"start":str(st[0])[:10] if st else "","end":str(en[0])[:10] if en else (str(ins[0])[:10] if ins else ""),"instant":bool(ins),"dimensioned":bool(dims)}
  return d

def units(root):
  d={}
  for u in root.xpath("//*[local-name()='unit']"):
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

def parse_filing(cik,fil,content):
  root=parse_root(content);ctx=contexts(root);ums=units(root);rows=[]
  for e in root.xpath("//*[local-name()='nonFraction']"):
    q=e.get("name") or ""
    if ":" not in q:continue
    pref,tag=q.split(":",1)
    if pref.lower()!="us-gaap" or tag not in TAGS:continue
    cm=ctx.get(e.get("contextRef") or "",{})
    if cm.get("dimensioned"):continue
    v=num(e)
    if v is None:continue
    role=TAGS[tag]
    # duration concepts only; share weighted-average and flows all need start/end.
    if not cm.get("start") or not cm.get("end"):continue
    rows.append({"cik":int(cik),"accn":fil["accn"],"accepted":fil["accepted"],"filed":fil["filed"],"form":fil["form"],
                 "tag":tag,"role":role,"start":cm["start"],"end":cm["end"],"unit":ums.get(e.get("unitRef") or "",""),
                 "value":float(v),"context_ref":e.get("contextRef") or "","decimals":e.get("decimals") or "","scale":e.get("scale") or ""})
  return rows

def process(cik):
  aud={"cik":int(cik),"status":"OK","filings":0,"html_ok":0,"html_missing":0,"fact_rows":0,"error":""};rows=[]
  try:
    fs=filings(cik);aud["filings"]=len(fs)
    for fil in fs:
      ad=fil["accn"].replace("-","");url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{ad}/{fil['primary']}"
      r,s,e=get(url,75)
      if s=="NOT_FOUND":aud["html_missing"]+=1;continue
      if s!="OK":continue
      aud["html_ok"]+=1
      try:rows.extend(parse_filing(cik,fil,r.content))
      except Exception:continue
    aud["fact_rows"]=len(rows)
  except Exception as e:
    aud["status"]="ERROR";aud["error"]=repr(e)[:500]
  return rows,aud

def main():
  ap=argparse.ArgumentParser();ap.add_argument("--shard",type=int,required=True);ap.add_argument("--nshards",type=int,default=4);a=ap.parse_args()
  ciks=sorted(c for c in ALL_CIKS if c%a.nshards==a.shard)
  rows=[];aud=[]
  with ThreadPoolExecutor(max_workers=1) as ex:
    futs={ex.submit(process,c):c for c in ciks}
    for i,f in enumerate(as_completed(futs),1):
      rr,aa=f.result();rows+=rr;aud.append(aa)
      if i%20==0:print("PROGRESS",i,"/",len(ciks),"facts",len(rows),flush=True)
  d=pd.DataFrame(rows)
  if d.empty:d=pd.DataFrame(columns=["cik","accn","accepted","filed","form","tag","role","start","end","unit","value","context_ref","decimals","scale"])
  d.to_csv(OUT/f"raw_exact_{a.shard:02d}.csv.gz",index=False,compression="gzip")
  pd.DataFrame(aud).sort_values("cik").to_csv(OUT/f"audit_{a.shard:02d}.csv",index=False)
  summary={"schema":"V4_SEC_RAW_EXACT_CURRENT_MISSING_V1","shard":a.shard,"nshards":a.nshards,"target_ciks":len(ciks),
           "already_precision_queried_ciks_excluded":len(ALREADY_RAW),"fact_rows":len(d),
           "role_counts":d["role"].value_counts().to_dict() if len(d) else {},
           "ciks_with_facts":int(d["cik"].nunique()) if len(d) else 0,
           "formation_2023_opened":False,"future_outcomes_used":False,"us3700_used":False,"new_corp_action_lookup_calls":0}
  (OUT/f"summary_{a.shard:02d}.json").write_text(json.dumps(summary,indent=2),encoding="utf-8");print(json.dumps(summary,indent=2),flush=True)
if __name__=="__main__":main()
