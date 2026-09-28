import json,requests,time
from pathlib import Path
CIKS=[1158449,1674862,1018963,14707,811156,723612,215466,794619,109563,866787]
H={"User-Agent":"V4-Full-Rigor namespace probe","Accept":"application/json"}
out=[]
for c in CIKS:
 r=requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{c:010d}.json",headers=H,timeout=45)
 o={"cik":c,"status":r.status_code}
 if r.ok:
  p=r.json();facts=p.get("facts") or {};o["namespaces"]=sorted(facts.keys())
  cand=[]
  for ns,concepts in facts.items():
   for tag,v in (concepts or {}).items():
    lo=tag.lower()
    if "weightedaverage" in lo and ("share" in lo or "stock" in lo):
     cand.append({"namespace":ns,"tag":tag,"label":v.get("label",""),"description":v.get("description","")})
  o["share_candidates"]=cand
 out.append(o);time.sleep(.15)
Path("v4-sec-f34-custom-probe-output").mkdir(exist_ok=True)
Path("v4-sec-f34-custom-probe-output/result.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
print(json.dumps(out,indent=2))
