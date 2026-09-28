from __future__ import annotations
import json, os, time, urllib.request, urllib.error, urllib.parse
from pathlib import Path

KEY=os.environ["EULERPOOL_API_KEY"].strip()
BASE="https://api.eulerpool.com/api/1"
OUT=Path("v4-eulerpool-output"); OUT.mkdir(parents=True,exist_ok=True)
TICKERS=["AAPL","AA","AEP","TXN","YUM","ATVI"]
TESTS=[
    ("shares","/equity/shares-outstanding/{t}",{}),
    ("mcap5y","/equity/market-cap/{t}",{"range":"5y"}),
    ("mcap_vendor","/equity/market-cap-history/{t}",{}),
]
def one(kind,path,ticker,params):
    url=BASE+path.format(t=ticker)
    if params: url += "?"+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={"Authorization":f"Bearer {KEY}","Accept":"application/json","User-Agent":"V4-outcome-free-marketcap-probe/1.0"})
    out={"kind":kind,"ticker":ticker,"path":path,"params":params}
    try:
        with urllib.request.urlopen(req,timeout=45) as r:
            raw=r.read()
            out["http_status"]=int(r.status)
            out["bytes"]=len(raw)
            out["quota_headers"]={k:v for k,v in r.headers.items() if any(x in k.lower() for x in ["rate","limit","remaining","quota","retry"])}
            try:
                p=json.loads(raw.decode("utf-8"))
                out["type"]=type(p).__name__
                if isinstance(p,dict):
                    out["top_keys"]=sorted(p.keys())
                    # bounded structural summary only
                    for key in ["data","history","shares","values"]:
                        v=p.get(key)
                        if isinstance(v,list):
                            out[key+"_count"]=len(v)
                            if v:
                                out[key+"_first"]=v[0]
                                out[key+"_last"]=v[-1]
                        elif isinstance(v,dict):
                            out[key+"_dict_keys"]=sorted(v.keys())[:50]
                            out[key+"_preview"]=str(v)[:1000]
                    out["dict_preview"]=str(p)[:1600]
                elif isinstance(p,list):
                    out["row_count"]=len(p)
                    if p:
                        out["first"]=p[0]
                        out["last"]=p[-1]
            except Exception:
                out["text_preview"]=raw.decode("utf-8","replace")[:1600]
    except urllib.error.HTTPError as e:
        out["http_status"]=int(e.code)
        out["error_body_prefix"]=e.read().decode("utf-8","replace")[:1200]
        out["retry_after"]=e.headers.get("Retry-After")
    except Exception as e:
        out["http_status"]=None
        out["error"]=repr(e)[:500]
    return out

rows=[]
for t in TICKERS:
    for kind,path,params in TESTS:
        rows.append(one(kind,path,t,params)); time.sleep(.15)
doc={"schema":"V4_EULERPOOL_MCAP_SHARES_PROBE_V1","purpose":"Outcome-free eligibility feasibility only.","results":rows}
(OUT/"mcap_shares_probe.json").write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps([{"ticker":x["ticker"],"kind":x["kind"],"status":x.get("http_status"),"type":x.get("type"),"rows":x.get("row_count"),"data_count":x.get("data_count")} for x in rows]))
