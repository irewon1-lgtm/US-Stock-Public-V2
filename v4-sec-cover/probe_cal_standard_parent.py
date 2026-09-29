from __future__ import annotations
import io,json,re,time,zipfile,threading
from pathlib import Path
import requests
from lxml import etree
import pandas as pd

META=json.loads(Path("v4-sec-cover/current_f34_missing_masks.json").read_text())
SNAPS=META["snaps"]; MASKS={int(k):(int(v[0]),int(v[1])) for k,v in META["cik_masks"].items()}
CAND=[c for c,(f3,f4) in sorted(MASKS.items()) if f3][:40]
UA="V4-Full-Rigor CAL-standard-parent probe research@example.com"
S=requests.Session();S.headers.update({"User-Agent":UA,"Accept-Encoding":"gzip, deflate"})
LOCK=threading.Lock();LAST=[0.0];XL="{http://www.w3.org/1999/xlink}"
def wait():
 with LOCK:
  dt=time.monotonic()-LAST[0]
  if dt<0.4:time.sleep(0.4-dt)
  LAST[0]=time.monotonic()
def get(url):
 wait();r=S.get(url,timeout=60)
 if r.status_code==404:return None
 r.raise_for_status();return r
def targets(c):
 m=MASKS[c][0];return [SNAPS[i] for i in range(12) if m&(1<<i)]
def filings(c):
 j=get(f"https://data.sec.gov/submissions/CIK{c:010d}.json").json();a=j["filings"]["recent"];out=[]
 lo=pd.Timestamp(min(targets(c)))-pd.Timedelta(days=900);hi=pd.Timestamp(max(targets(c)))
 for acc,ac,fd,form in zip(a["accessionNumber"],a["acceptanceDateTime"],a["filingDate"],a["form"]):
  if form not in {"10-Q","10-K","10-Q/A","10-K/A"}:continue
  ds=(ac or fd)[:10]
  try:t=pd.Timestamp(ds)
  except:continue
  if lo<=t<=hi:out.append((acc,ac,form))
 return out
rows=[]
for c in CAND:
 for acc,ac,form in filings(c):
  ad=acc.replace("-","");r=get(f"https://www.sec.gov/Archives/edgar/data/{c}/{ad}/{acc}-xbrl.zip")
  if r is None:continue
  try:z=zipfile.ZipFile(io.BytesIO(r.content))
  except:continue
  for n in z.namelist():
   if not n.endswith("_cal.xml"):continue
   try:root=etree.fromstring(z.read(n),parser=etree.XMLParser(recover=True,huge_tree=True))
   except:continue
   for link in root.xpath("//*[local-name()='calculationLink']"):
    role=link.get(XL+"role") or "";loc={}
    for x in link.xpath("./*[local-name()='loc']"):
     h=x.get(XL+"href") or "";k=x.get(XL+"label") or ""
     if k and "#" in h:loc[k]=h.split("#")[-1]
    for x in link.xpath("./*[local-name()='calculationArc']"):
     fr=loc.get(x.get(XL+"from") or "");to=loc.get(x.get(XL+"to") or "");w=x.get("weight") or ""
     if not fr or not to:continue
     key="PaymentsToAcquirePropertyPlantAndEquipment"
     if key in fr or key in to:
      rows.append({"cik":c,"accn":acc,"accepted":ac,"form":form,"role":role,"parent":fr,"child":to,"weight":w})
Path("v4-sec-cal-probe-output").mkdir(exist_ok=True)
pd.DataFrame(rows).to_csv("v4-sec-cal-probe-output/standard_parent_arcs.csv",index=False)
summary={"sample_ciks":len(CAND),"arc_rows":len(rows),"ciks_with_arcs":len(set(r["cik"] for r in rows))}
Path("v4-sec-cal-probe-output/summary.json").write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2));print(pd.DataFrame(rows).head(100).to_string(index=False) if rows else "NO_ARCS")
