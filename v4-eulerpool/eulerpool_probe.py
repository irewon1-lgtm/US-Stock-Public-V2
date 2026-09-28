from __future__ import annotations
import json, os, urllib.request, urllib.error, urllib.parse, time
from pathlib import Path

KEY=os.environ["EULERPOOL_API_KEY"].strip()
BASE="https://api.eulerpool.com/api/1/charting/ohlcv/{ticker}"
OUT=Path("v4-eulerpool-output"); OUT.mkdir(parents=True,exist_ok=True)
TICKERS=["AAPL","ABMD","STMP","AAWW","AABA","HANS","MNST","ABT"]
FROM=1575158400  # 2019-12-01 UTC
TO=1672531200    # 2023-01-01 UTC

def run(ticker):
    url=BASE.format(ticker=ticker)+"?"+urllib.parse.urlencode({"from":FROM,"to":TO,"interval":"1d"})
    req=urllib.request.Request(url,headers={"Authorization":f"Bearer {KEY}","Accept":"application/json","User-Agent":"V4-outcome-free-delisted-probe/1.0"})
    out={"ticker":ticker}
    try:
        with urllib.request.urlopen(req,timeout=60) as r:
            raw=r.read(); out["http_status"]=int(r.status)
            out["quota_headers"]={k:v for k,v in r.headers.items() if any(s in k.lower() for s in ["rate","limit","remaining","quota","retry"])}
            p=json.loads(raw.decode("utf-8"))
            if isinstance(p,dict) and isinstance(p.get("t"),list):
                out["row_count"]=len(p["t"])
                out["first_t"]=p["t"][0] if p["t"] else None
                out["last_t"]=p["t"][-1] if p["t"] else None
                out["volume_count"]=len(p.get("v") or [])
                out["nonnull_volume"]=sum(x is not None for x in (p.get("v") or []))
                out["nonnull_close"]=sum(x is not None for x in (p.get("c") or []))
    except urllib.error.HTTPError as e:
        out["http_status"]=int(e.code); out["error_body_prefix"]=e.read().decode("utf-8","replace")[:800]
    except Exception as e:
        out["error"]=repr(e)[:500]
    return out

rows=[]
for t in TICKERS:
    rows.append(run(t)); time.sleep(0.25)
doc={"schema":"V4_EULERPOOL_DELISTED_PROBE_V4","purpose":"Outcome-free availability only.","results":rows}
(OUT/"probe.json").write_text(json.dumps(doc,indent=2),encoding="utf-8")
print(json.dumps(rows))
