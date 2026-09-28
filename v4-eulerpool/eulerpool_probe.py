from __future__ import annotations
import json, os, urllib.request, urllib.error, urllib.parse
from pathlib import Path

KEY=os.environ["EULERPOOL_API_KEY"].strip()
BASE="https://api.eulerpool.com/api/1/charting/ohlcv/AAPL"
OUT=Path("v4-eulerpool-output"); OUT.mkdir(parents=True,exist_ok=True)
FROM=1577836800
TO=1578700800
TESTS=[
 ("default",{}),
 ("adjusted_false",{"adjusted":"false"}),
 ("adjusted_zero",{"adjusted":"0"}),
 ("adjust_false",{"adjust":"false"}),
 ("unadjusted_true",{"unadjusted":"true"}),
 ("adjustment_none",{"adjustment":"none"}),
 ("adjustments_none",{"adjustments":"none"}),
]

def run(label,extra):
    params={"from":FROM,"to":TO,"interval":"1d"}|extra
    url=BASE+"?"+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={"Authorization":f"Bearer {KEY}","Accept":"application/json","User-Agent":"V4-unadjusted-probe/1.0"})
    out={"label":label,"params":params}
    try:
        with urllib.request.urlopen(req,timeout=45) as r:
            p=json.loads(r.read().decode("utf-8"))
            out["http_status"]=int(r.status)
            out["quota_headers"]={k:v for k,v in r.headers.items() if any(s in k.lower() for s in ["rate","limit","remaining","quota","retry"])}
            if isinstance(p,dict) and isinstance(p.get("t"),list):
                out["row_count"]=len(p["t"])
                out["first_t"]=p["t"][0] if p["t"] else None
                out["first_close"]=(p.get("c") or [None])[0] if p["t"] else None
                out["first_volume"]=(p.get("v") or [None])[0] if p["t"] else None
    except urllib.error.HTTPError as e:
        out["http_status"]=int(e.code); out["error"]=e.read().decode("utf-8","replace")[:500]
    return out

rows=[run(a,b) for a,b in TESTS]
(OUT/"probe.json").write_text(json.dumps({"schema":"V4_EULERPOOL_UNADJUSTED_PROBE_V6","results":rows},indent=2),encoding="utf-8")
print(json.dumps(rows))
