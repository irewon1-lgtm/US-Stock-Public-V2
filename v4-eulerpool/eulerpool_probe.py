from __future__ import annotations
import json, os, urllib.request, urllib.error, urllib.parse
from pathlib import Path

KEY=os.environ["EULERPOOL_API_KEY"].strip()
ROOT="https://api.eulerpool.com/api/1"
OUT=Path("v4-eulerpool-output"); OUT.mkdir(parents=True,exist_ok=True)
IDS=["AAPL","TSLA","NVDA","CMG","GE"]

def call(identifier):
    url=ROOT+"/equity/splits/"+urllib.parse.quote(identifier,safe="")
    req=urllib.request.Request(url,headers={"Authorization":f"Bearer {KEY}","Accept":"application/json","User-Agent":"V4-split-probe/1.0"})
    out={"identifier":identifier}
    try:
        with urllib.request.urlopen(req,timeout=45) as r:
            raw=r.read(); out["http_status"]=int(r.status)
            out["quota_headers"]={k:v for k,v in r.headers.items() if any(s in k.lower() for s in ["rate","limit","remaining","quota","retry"])}
            p=json.loads(raw.decode("utf-8"))
            out["response_type"]=type(p).__name__
            out["payload"]=p
    except urllib.error.HTTPError as e:
        out["http_status"]=int(e.code); out["error"]=e.read().decode("utf-8","replace")[:1000]
    except Exception as e:
        out["error"]=repr(e)[:500]
    return out

rows=[call(x) for x in IDS]
(OUT/"probe.json").write_text(json.dumps({"schema":"V4_EULERPOOL_SPLIT_PROBE_V7","results":rows},ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps([{"id":r["identifier"],"status":r.get("http_status"),"type":r.get("response_type")} for r in rows]))
