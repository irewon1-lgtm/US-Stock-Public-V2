from __future__ import annotations
import json, os, urllib.request, urllib.error, urllib.parse, time
from pathlib import Path

KEY=os.environ["EULERPOOL_API_KEY"].strip()
ROOT="https://api.eulerpool.com/api/1"
OUT=Path("v4-eulerpool-output"); OUT.mkdir(parents=True,exist_ok=True)
QUERIES=["ABMD","STMP","AAWW","AABA","HANS","MNST","AAPL","ABT"]
FROM=1575158400
TO=1672531200

def get_json(path, params=None):
    url=ROOT+path
    if params: url += "?" + urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={"Authorization":f"Bearer {KEY}","Accept":"application/json","User-Agent":"V4-outcome-free-identifier-probe/1.0"})
    try:
        with urllib.request.urlopen(req,timeout=60) as r:
            raw=r.read()
            return {"status":int(r.status),"payload":json.loads(raw.decode("utf-8")),
                    "quota":{k:v for k,v in r.headers.items() if any(s in k.lower() for s in ["rate","limit","remaining","quota","retry"])}}
    except urllib.error.HTTPError as e:
        return {"status":int(e.code),"error":e.read().decode("utf-8","replace")[:1000]}
    except Exception as e:
        return {"status":None,"error":repr(e)[:500]}

def normalize_results(payload):
    if not isinstance(payload,dict): return []
    r=payload.get("results")
    if isinstance(r,list): return [x for x in r if isinstance(x,dict)]
    if isinstance(r,dict): return [r]
    return []

rows=[]
for q in QUERIES:
    sr=get_json("/equity/search",{"q":q})
    rec={"query":q,"search_status":sr.get("status"),"matches":[]}
    for m in normalize_results(sr.get("payload"))[:10]:
        item={k:m.get(k) for k in ["name","isin","ticker","type","currency"]}
        ident=m.get("isin") or m.get("ticker")
        if ident:
            hr=get_json("/charting/ohlcv/"+urllib.parse.quote(str(ident),safe=""),{"from":FROM,"to":TO,"interval":"1d"})
            item["history_status"]=hr.get("status")
            p=hr.get("payload")
            if isinstance(p,dict) and isinstance(p.get("t"),list):
                item["row_count"]=len(p["t"])
                item["first_t"]=p["t"][0] if p["t"] else None
                item["last_t"]=p["t"][-1] if p["t"] else None
                item["volume_count"]=len(p.get("v") or [])
            else:
                item["history_error"]=hr.get("error")
        rec["matches"].append(item)
    rec["search_error"]=sr.get("error")
    rows.append(rec)
    time.sleep(0.25)

doc={"schema":"V4_EULERPOOL_IDENTIFIER_PROBE_V5","purpose":"Outcome-free identifier resolution and OHLCV availability only.","results":rows}
(OUT/"probe.json").write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps([{x["query"]:[(m.get("ticker"),m.get("isin"),m.get("row_count")) for m in x["matches"]] for x in rows}],ensure_ascii=False))
