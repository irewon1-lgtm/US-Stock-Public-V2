from __future__ import annotations
import json, os, time, urllib.request, urllib.error
from pathlib import Path

API="https://api.eulerpool.com/api/1/equities/{ticker}/history"
KEY=os.environ["EULERPOOL_API_KEY"].strip()
OUT=Path("v4-eulerpool-output")
OUT.mkdir(parents=True, exist_ok=True)

# Control + delisted/acquired + ticker-change/reuse stress cases.
TICKERS=["AAPL","ABMD","STMP","AAWW","AABA","HANS","MNST","ABT"]
START="2018-01-01"
END="2023-01-15"

def call(ticker:str):
    url=API.format(ticker=ticker)+f"?from={START}&to={END}"
    req=urllib.request.Request(
        url,
        headers={
            "Authorization":f"Bearer {KEY}",
            "Accept":"application/json",
            "User-Agent":"V4-outcome-free-feasibility-probe/1.0",
        },
        method="GET",
    )
    out={"ticker":ticker,"url_path":f"/api/1/equities/{ticker}/history","start":START,"end":END}
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            raw=r.read()
            out["http_status"]=int(r.status)
            # Never persist auth material. Keep only potentially useful quota metadata.
            keep_headers={}
            for k,v in r.headers.items():
                lk=k.lower()
                if any(s in lk for s in ["rate","limit","remaining","quota","retry"]):
                    keep_headers[k]=v
            out["quota_headers"]=keep_headers
            out["bytes"]=len(raw)
            payload=json.loads(raw.decode("utf-8"))
            data=payload.get("data",[]) if isinstance(payload,dict) else payload
            out["response_type"]=type(payload).__name__
            out["top_keys"]=sorted(payload.keys()) if isinstance(payload,dict) else []
            out["row_count"]=len(data) if isinstance(data,list) else None
            if isinstance(data,list) and data:
                first=data[0] if isinstance(data[0],dict) else {}
                last=data[-1] if isinstance(data[-1],dict) else {}
                out["fields"]=sorted(first.keys()) if isinstance(first,dict) else []
                out["first_date"]=first.get("date")
                out["last_date"]=last.get("date")
                # Outcome-free availability diagnostics only.
                out["volume_nonnull"]=sum(1 for x in data if isinstance(x,dict) and x.get("volume") not in (None,""))
                out["close_nonnull"]=sum(1 for x in data if isinstance(x,dict) and x.get("close") not in (None,""))
            return out
    except urllib.error.HTTPError as e:
        body=e.read().decode("utf-8","replace")[:500]
        out["http_status"]=int(e.code)
        out["error_body_prefix"]=body
        out["retry_after"]=e.headers.get("Retry-After")
        return out
    except Exception as e:
        out["http_status"]=None
        out["error"]=repr(e)[:500]
        return out

rows=[]
for t in TICKERS:
    rows.append(call(t))
    time.sleep(0.35)

summary={
    "schema":"V4_EULERPOOL_PROBE_V1",
    "purpose":"Outcome-free feasibility only; no future-return labels computed.",
    "endpoint_template":"/api/1/equities/{ticker}/history",
    "auth":"Authorization Bearer from GitHub Actions secret; secret never persisted.",
    "requested_tickers":TICKERS,
    "results":rows,
}
(OUT/"probe.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({r["ticker"]:{"http_status":r.get("http_status"),"row_count":r.get("row_count"),"first_date":r.get("first_date"),"last_date":r.get("last_date")} for r in rows},ensure_ascii=False))
