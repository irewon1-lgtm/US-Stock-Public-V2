from __future__ import annotations
import json, os, urllib.request, urllib.error, urllib.parse
from pathlib import Path

KEY=os.environ["EULERPOOL_API_KEY"].strip()
BASE="https://api.eulerpool.com/api/1"
OUT=Path("v4-eulerpool-output")
OUT.mkdir(parents=True, exist_ok=True)

TESTS=[
    ("/equity/candles/AAPL", {}),
    ("/equity/candles/AAPL", {"from":"2020-01-01","to":"2020-01-10","interval":"1d"}),
    ("/equity/candles/AAPL", {"startDate":"2020-01-01","endDate":"2020-01-10","interval":"1d"}),
    ("/charting/ohlcv/AAPL", {}),
    ("/charting/ohlcv/AAPL", {"from":"2020-01-01","to":"2020-01-10","interval":"1d"}),
    ("/charting/ohlcv/AAPL", {"startDate":"2020-01-01","endDate":"2020-01-10","interval":"1d"}),
]

def run(path, params):
    qs=urllib.parse.urlencode(params)
    url=BASE+path+("?" + qs if qs else "")
    req=urllib.request.Request(url, headers={
        "Authorization":f"Bearer {KEY}",
        "Accept":"application/json",
        "User-Agent":"V4-outcome-free-endpoint-discovery/1.0",
    })
    out={"path":path,"params":params}
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            raw=r.read()
            out["http_status"]=int(r.status)
            out["bytes"]=len(raw)
            keep={}
            for k,v in r.headers.items():
                lk=k.lower()
                if any(s in lk for s in ["rate","limit","remaining","quota","retry"]):
                    keep[k]=v
            out["quota_headers"]=keep
            try:
                payload=json.loads(raw.decode("utf-8"))
                out["response_type"]=type(payload).__name__
                if isinstance(payload,dict):
                    out["top_keys"]=sorted(payload.keys())
                    data=payload.get("data")
                    if isinstance(data,list):
                        out["row_count"]=len(data)
                        if data and isinstance(data[0],dict):
                            out["fields"]=sorted(data[0].keys())
                            out["first_row"]=data[0]
                            out["last_row"]=data[-1]
                    else:
                        # Bound output, no secret or large payload.
                        out["payload_preview"]=str(payload)[:1200]
                elif isinstance(payload,list):
                    out["row_count"]=len(payload)
                    if payload and isinstance(payload[0],dict):
                        out["fields"]=sorted(payload[0].keys())
                        out["first_row"]=payload[0]
                        out["last_row"]=payload[-1]
            except Exception:
                out["text_preview"]=raw.decode("utf-8","replace")[:1200]
    except urllib.error.HTTPError as e:
        body=e.read().decode("utf-8","replace")[:1200]
        out["http_status"]=int(e.code)
        out["error_body_prefix"]=body
        out["retry_after"]=e.headers.get("Retry-After")
    except Exception as e:
        out["http_status"]=None
        out["error"]=repr(e)[:500]
    return out

rows=[run(p,q) for p,q in TESTS]
doc={
    "schema":"V4_EULERPOOL_ENDPOINT_DISCOVERY_V2",
    "purpose":"Outcome-free endpoint/parameter discovery only.",
    "results":rows,
}
(OUT/"probe.json").write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps([{"path":r["path"],"params":r["params"],"status":r.get("http_status"),"rows":r.get("row_count")} for r in rows],ensure_ascii=False))
