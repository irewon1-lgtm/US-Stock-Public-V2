from __future__ import annotations
import csv, io, json, urllib.request, urllib.parse
from pathlib import Path

TICKERS=["AAPL","ABMD","STMP","AAWW","AABA","HANS","MNST","ABT"]
OUT=Path("v4-eulerpool-output"); OUT.mkdir(parents=True,exist_ok=True)
BASE="https://stooq.com/q/d/l/"
rows=[]
for t in TICKERS:
    params={"s":t.lower()+".us","d1":"20191201","d2":"20230101","i":"d"}
    url=BASE+"?"+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 V4 outcome-free research"})
    rec={"ticker":t,"symbol":params["s"]}
    try:
        with urllib.request.urlopen(req,timeout=45) as r:
            raw=r.read().decode("utf-8","replace")
            rec["http_status"]=int(r.status); rec["bytes"]=len(raw)
        data=list(csv.DictReader(io.StringIO(raw))) if raw.strip() else []
        rec["row_count"]=len(data)
        if data:
            rec["fields"]=list(data[0].keys())
            rec["first_date"]=data[0].get("Date"); rec["last_date"]=data[-1].get("Date")
            rec["first_close"]=data[0].get("Close"); rec["first_volume"]=data[0].get("Volume")
            if t=="AAPL":
                rec["split_window"]=[x for x in data if x.get("Date") in {"2020-08-27","2020-08-28","2020-08-31","2020-09-01"}]
        else:
            rec["body_prefix"]=raw[:300]
    except Exception as e:
        rec["error"]=repr(e)[:500]
    rows.append(rec)
doc={"schema":"V4_STOOQ_DELISTED_SPLIT_PROBE_V1","purpose":"Outcome-free OHLCV availability only.","results":rows}
(OUT/"probe.json").write_text(json.dumps(doc,indent=2),encoding="utf-8")
print(json.dumps([{"ticker":x["ticker"],"status":x.get("http_status"),"rows":x.get("row_count"),"first":x.get("first_date"),"last":x.get("last_date")} for x in rows]))
