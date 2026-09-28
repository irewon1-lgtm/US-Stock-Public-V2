from __future__ import annotations
import json,os,requests,time
from pathlib import Path
KEY=os.environ["EULERPOOL_API_KEY"].strip()
BASE="https://api.eulerpool.com/api/1"
H={"Authorization":f"Bearer {KEY}","Accept":"application/json","User-Agent":"V4-factor-source-probe/1.0"}
T=["AA","AEP","APA"]
EPS=[
 ("income_q","/equity/income-statement-quarterly/{t}"),
 ("cash_q","/equity/cashflow-statement-quarterly/{t}"),
 ("fund_q","/equity/fundamentals-quarterly/{t}"),
]
rows=[]
for t in T:
 for kind,path in EPS:
  o={"ticker":t,"kind":kind,"path":path}
  try:
   r=requests.get(BASE+path.format(t=t),headers=H,timeout=45)
   o["status"]=r.status_code
   if r.ok:
    p=r.json();o["type"]=type(p).__name__
    if isinstance(p,list):
      o["row_count"]=len(p)
      if p:
       o["fields"]=sorted(set().union(*[set(x.keys()) for x in p[:min(10,len(p))] if isinstance(x,dict)]))
       o["first"]=p[0];o["last"]=p[-1]
    elif isinstance(p,dict):
      o["keys"]=sorted(p.keys());o["preview"]=str(p)[:2500]
   else:o["body"]=r.text[:1000]
  except Exception as e:o["error"]=repr(e)[:400]
  rows.append(o);time.sleep(.15)
Path("v4-eulerpool-output").mkdir(exist_ok=True)
Path("v4-eulerpool-output/factor_source_probe.json").write_text(json.dumps({"schema":"V4_FACTOR_SOURCE_PROBE_V1","results":rows},indent=2),encoding="utf-8")
print(json.dumps([{"t":x["ticker"],"kind":x["kind"],"status":x.get("status"),"rows":x.get("row_count"),"fields":x.get("fields")} for x in rows]))
