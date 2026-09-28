from __future__ import annotations
import json,os,requests
from pathlib import Path
KEY=os.environ["EULERPOOL_API_KEY"].strip()
H={"Authorization":f"Bearer {KEY}","Accept":"application/json","User-Agent":"V4-v1-history-probe/1.0"}
tickers=["AAPL","ABMD","STMP","AAWW"]
bases=[
 "https://api.eulerpool.com/v1/equities/{t}/history",
 "https://api.eulerpool.com/api/1/equities/{t}/history",
]
params_list=[
 {"from":"2019-09-01","to":"2023-01-05","interval":"1d"},
 {"from":"2019-09-01","to":"2023-01-05","interval":"1d","adjusted":"false"},
]
rows=[]
for t in tickers:
 for b in bases:
  for params in params_list:
   url=b.format(t=t)
   o={"ticker":t,"url":url,"params":params}
   try:
    r=requests.get(url,params=params,headers=H,timeout=45)
    o["status"]=r.status_code
    o["content_type"]=r.headers.get("Content-Type","")
    if r.ok:
      try:
       p=r.json(); o["type"]=type(p).__name__
       if isinstance(p,dict):
        o["keys"]=sorted(p.keys())
        d=p.get("data")
        if isinstance(d,list):
          o["rows"]=len(d)
          if d:o["first"]=d[0];o["last"]=d[-1]
       elif isinstance(p,list):
        o["rows"]=len(p)
        if p:o["first"]=p[0];o["last"]=p[-1]
      except Exception:o["body"]=r.text[:1200]
    else:o["body"]=r.text[:1200]
   except Exception as e:o["error"]=repr(e)[:500]
   rows.append(o)
Path("v4-eulerpool-output").mkdir(exist_ok=True)
Path("v4-eulerpool-output/v1_history_probe.json").write_text(json.dumps({"schema":"V4_V1_HISTORY_PROBE_V1","results":rows},indent=2),encoding="utf-8")
print(json.dumps([{"t":x["ticker"],"url":x["url"],"adjusted":x["params"].get("adjusted"),"status":x.get("status"),"rows":x.get("rows")} for x in rows]))
