import json,requests,threading,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
CIKS=json.loads(Path("v4-sec-cover/f4_remaining_2021_ciks.json").read_text())["ciks"]
H={"User-Agent":"V4-Full-Rigor custom share candidate discovery","Accept":"application/json"}
lock=threading.Lock();last=[0.0]
def get(c):
  with lock:
    dt=time.monotonic()-last[0]
    if dt<.13: time.sleep(.13-dt)
    last[0]=time.monotonic()
  r=requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{c:010d}.json",headers=H,timeout=45);r.raise_for_status();p=r.json()
  out=[];namespaces=sorted((p.get("facts") or {}).keys())
  for ns,concepts in (p.get("facts") or {}).items():
    if ns=="us-gaap": continue
    for tag,v in (concepts or {}).items():
      label=str(v.get("label") or "");desc=str(v.get("description") or "")
      txt=(tag+" "+label+" "+desc).lower()
      if ("weighted average" in txt or "weightedaverage" in txt) and ("share" in txt or "stock" in txt) and ("outstanding" in txt or "earnings per share" in txt or " eps" in txt):
        bad=("exercise price","grant date fair value","contractual term","option plan","award")
        if not any(b in txt for b in bad):
          out.append({"namespace":ns,"tag":tag,"label":label,"description":desc})
  return {"cik":c,"namespaces":namespaces,"candidates":out}
rows=[];errs=[]
with ThreadPoolExecutor(max_workers=4) as ex:
  fs={ex.submit(get,c):c for c in CIKS}
  for f in as_completed(fs):
    try: rows.append(f.result())
    except Exception as e: errs.append({"cik":fs[f],"error":repr(e)})
cand=[{"cik":r["cik"],**x} for r in rows for x in r["candidates"]]
summary={"schema":"V4_NEXT1_F4_CUSTOM_NAMESPACE_SCAN_V1","target_ciks":len(CIKS),"fetch_errors":len(errs),"ciks_with_non_usgaap_share_candidates":len({x["cik"] for x in cand}),"candidate_rows":len(cand),"new_corp_action_lookup_calls":0,"formation_2023_opened":False,"future_outcomes_used":False,"us3700_used":False,"candidates":cand,"errors":errs}
Path("v4-sec-f34-custom-scan-output").mkdir(exist_ok=True)
Path("v4-sec-f34-custom-scan-output/summary.json").write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))
