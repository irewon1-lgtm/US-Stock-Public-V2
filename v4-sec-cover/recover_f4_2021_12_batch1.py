from __future__ import annotations
import argparse,io,json,math,re,threading,time,zipfile
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import pandas as pd, requests
from lxml import etree

ROOT=Path(".")
META=json.loads((ROOT/"v4-sec-cover/f4_2021_12_batch1.json").read_text())
CICS=sorted(int(x) for x in META["ciks"])
OUT=ROOT/"v4-sec-f4-2021-12-batch1-output";OUT.mkdir(parents=True,exist_ok=True)
FORMS={"10-Q","10-K","10-Q/A","10-K/A"}
TAGS={
 "WeightedAverageNumberOfDilutedSharesOutstanding":"DILUTED",
 "WeightedAverageNumberOfSharesOutstandingBasic":"BASIC",
 "WeightedAverageNumberOfShareOutstandingBasicAndDiluted":"COMBINED",
 "WeightedAverageNumberDilutedSharesOutstandingAdjustment":"DILUTED_ADJUSTMENT",
}
UA="V4-Full-Rigor F4 2021-12 exact-share batch1 research@example.com"
S=requests.Session();S.headers.update({"User-Agent":UA,"Accept-Encoding":"gzip, deflate","Accept":"application/json"})
LOCK=threading.Lock();LAST=[0.0]

def wait_rate():
  with LOCK:
    dt=time.monotonic()-LAST[0]
    if dt<0.45:time.sleep(0.45-dt)
    LAST[0]=time.monotonic()

def get(url,timeout=75,attempts=4):
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
  keys=["accessionNumber","acceptanceDateTime","filingDate","form"]
  n=max([len(a.get(k) or []) for k in keys]+[0]);out=[]
  for i in range(n):
    def v(k):
      z=a.get(k) or [];return str(z[i] if i<len(z) else "").strip()
    acc=v("accessionNumber");ac=v("acceptanceDateTime");fd=v("filingDate");form=v("form").upper()
    if not acc or form not in FORMS:continue
    ds=(ac or fd)[:10]
    if not ds:continue
    try:t=pd.Timestamp(ds)
    except:continue
    if pd.Timestamp("2019-01-01")<=t<=pd.Timestamp("2021-12-31"):
      out.append({"accn":acc,"accepted":ac,"filed":fd,"form":form})
  return out

def filings(cik):
  sub=get_json(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json")
  rows=parse_block(((sub.get("filings") or {}).get("recent") or {}))
  for m in ((sub.get("filings") or {}).get("files") or []):
    name=str(m.get("name") or "").strip()
    if not name:continue
    try:rows.extend(parse_block(get_json("https://data.sec.gov/submissions/"+name)))
    except:pass
  return sorted({x["accn"]:x for x in rows}.values(),key=lambda x:(x["accepted"] or x["filed"],x["accn"]))

def root(data):
  return etree.fromstring(data,parser=etree.XMLParser(recover=True,huge_tree=True))

def contexts(r):
  d={}
  for c in r.xpath("//*[local-name()='context']"):
    cid=c.get("id") or ""
    if not cid:continue
    st=c.xpath(".//*[local-name()='startDate']/text()");en=c.xpath(".//*[local-name()='endDate']/text()")
    dims=c.xpath(".//*[local-name()='explicitMember' or local-name()='typedMember']")
    d[cid]={"start":str(st[0])[:10] if st else "","end":str(en[0])[:10] if en else "","dimensioned":bool(dims)}
  return d

def units(r):
  d={}
  for u in r.xpath("//*[local-name()='unit']"):
    uid=u.get("id") or "";ms=["".join(x.itertext()).strip() for x in u.xpath(".//*[local-name()='measure']")]
    d[uid]="|".join(ms)
  return d

def num(e):
  t=" ".join("".join(e.itertext()).split())
  if not t:return None
  neg=("(" in t and ")" in t);cl=re.sub(r"[^0-9.\-]","",t)
  if cl in {"","-",".","-."}:return None
  try:v=float(cl)
  except:return None
  if neg:v=-abs(v)
  if (e.get("sign") or "")=="-":v=-abs(v)
  try:v*=10**int(e.get("scale") or "0")
  except:pass
  return v if math.isfinite(v) else None

def parse_filing(cik,fil,z):
  rows=[]
  for n in z.namelist():
    if not n.lower().endswith((".htm",".html")):continue
    try:r=root(z.read(n))
    except:continue
    ctx=contexts(r);ums=units(r)
    for e in r.xpath("//*[local-name()='nonFraction']"):
      q=e.get("name") or ""
      if ":" not in q:continue
      pref,tag=q.split(":",1)
      if pref.lower()!="us-gaap" or tag not in TAGS:continue
      cm=ctx.get(e.get("contextRef") or "",{})
      if cm.get("dimensioned") or not cm.get("start") or not cm.get("end"):continue
      unit=ums.get(e.get("unitRef") or "","")
      if "share" not in unit.lower():continue
      v=num(e)
      if v is None or (TAGS[tag]!="DILUTED_ADJUSTMENT" and v<=0) or (TAGS[tag]=="DILUTED_ADJUSTMENT" and v<0):continue
      rows.append({"cik":int(cik),"accn":fil["accn"],"accepted":fil["accepted"],"filed":fil["filed"],"form":fil["form"],"source_file":n,
                   "context_ref":e.get("contextRef") or "","start":cm["start"],"end":cm["end"],"unit":unit,"value":float(v),
                   "decimals":e.get("decimals") or "","scale":e.get("scale") or "","role":TAGS[tag],"tag":tag})
  return rows

def process(cik):
  rows=[];aud={"cik":int(cik),"status":"OK","filings":0,"zip_ok":0,"facts":0,"error":""}
  try:
    fs=filings(cik);aud["filings"]=len(fs)
    for fil in fs:
      ad=fil["accn"].replace("-","");url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{ad}/{fil['accn']}-xbrl.zip"
      r,s,e=get(url)
      if s!="OK":continue
      aud["zip_ok"]+=1
      try:rows+=parse_filing(cik,fil,zipfile.ZipFile(io.BytesIO(r.content)))
      except:continue
    aud["facts"]=len(rows)
  except Exception as e:
    aud["status"]="ERROR";aud["error"]=repr(e)[:500]
  return rows,aud

def main():
  ap=argparse.ArgumentParser();ap.add_argument("--shard",type=int,required=True);ap.add_argument("--nshards",type=int,default=4);a=ap.parse_args()
  ciks=[c for c in CICS if c%a.nshards==a.shard];rows=[];aud=[]
  with ThreadPoolExecutor(max_workers=1) as ex:
    futs={ex.submit(process,c):c for c in ciks}
    for f in as_completed(futs):
      rr,aa=f.result();rows+=rr;aud.append(aa)
  d=pd.DataFrame(rows)
  if d.empty:d=pd.DataFrame(columns=["cik","accn","accepted","filed","form","source_file","context_ref","start","end","unit","value","decimals","scale","role","tag"])
  d.to_csv(OUT/f"f4_exact_{a.shard:02d}.csv.gz",index=False,compression="gzip")
  pd.DataFrame(aud).to_csv(OUT/f"audit_{a.shard:02d}.csv",index=False)
  print(json.dumps({"shard":a.shard,"target_ciks":len(ciks),"fact_rows":len(d),"ciks_with_facts":int(d.cik.nunique()) if len(d) else 0,"role_counts":d.role.value_counts().to_dict() if len(d) else {}},indent=2),flush=True)
if __name__=="__main__":main()
