from __future__ import annotations
import json, os, urllib.request, urllib.error, urllib.parse
from pathlib import Path

KEY=os.environ["EULERPOOL_API_KEY"].strip()
BASE="https://api.eulerpool.com/api/1/charting/ohlcv/AAPL"
OUT=Path("v4-eulerpool-output"); OUT.mkdir(parents=True,exist_ok=True)

TESTS=[
  {"from":1577836800,"to":1578700800,"interval":"1d"},
  {"from":1577836800000,"to":1578700800000,"interval":"1d"},
]

def run(params):
    url=BASE+"?"+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={"Authorization":f"Bearer {KEY}","Accept":"application/json","User-Agent":"V4-outcome-free-range-probe/1.0"})
    out={"params":params}
    try:
        with urllib.request.urlopen(req,timeout=45) as r:
            raw=r.read(); out["http_status"]=int(r.status)
            out["quota_headers"]={k:v for k,v in r.headers.items() if any(s in k.lower() for s in ["rate","limit","remaining","quota","retry"])}
            p=json.loads(raw.decode("utf-8"))
            out["top_keys"]=sorted(p.keys()) if isinstance(p,dict) else []
            if isinstance(p,dict) and isinstance(p.get("t"),list):
                out["row_count"]=len(p["t"])
                out["first_t"]=p["t"][0] if p["t"] else None
                out["last_t"]=p["t"][-1] if p["t"] else None
                out["volume_count"]=len(p.get("v") or [])
                out["first_close"]=(p.get("c") or [None])[0] if p["t"] else None
    except urllib.error.HTTPError as e:
        out["http_status"]=int(e.code); out["error_body_prefix"]=e.read().decode("utf-8","replace")[:800]
    except Exception as e:
        out["error"]=repr(e)[:500]
    return out

rows=[run(x) for x in TESTS]
(OUT/"probe.json").write_text(json.dumps({"schema":"V4_EULERPOOL_RANGE_DISCOVERY_V3","results":rows},indent=2),encoding="utf-8")
print(json.dumps(rows))
