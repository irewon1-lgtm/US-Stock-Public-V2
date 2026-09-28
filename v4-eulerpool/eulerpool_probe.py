from __future__ import annotations
import json, os, urllib.request, urllib.parse, math
from datetime import date
from pathlib import Path
KEY=os.environ["EULERPOOL_API_KEY"].strip()
ROOT="https://api.eulerpool.com/api/1"
OUT=Path("v4-eulerpool-output"); OUT.mkdir(parents=True,exist_ok=True)
IDS=["AAPL","NVDA","GE"]
FROM=1577836800; TO=1578009600
def get(path,params=None):
    u=ROOT+path
    if params: u+="?"+urllib.parse.urlencode(params)
    req=urllib.request.Request(u,headers={"Authorization":f"Bearer {KEY}","Accept":"application/json","User-Agent":"V4-split-crosscheck/1.0"})
    with urllib.request.urlopen(req,timeout=45) as r: return json.loads(r.read().decode())
rows=[]
for t in IDS:
    p=get("/charting/ohlcv/"+t,{"from":FROM,"to":TO,"interval":"1d"})
    sp=get("/equity/splits/"+t)
    ts=(p.get("t") or [None])[0]; c=(p.get("c") or [None])[0]; v=(p.get("v") or [None])[0]
    day="2020-01-02"
    mult=1.0; used=[]
    for x in sp if isinstance(sp,list) else []:
        if str(x.get("date",""))>day:
            r=float(x["toFactor"])/float(x["fromFactor"])
            mult*=r; used.append({"date":x["date"],"ratio":r})
    rows.append({"ticker":t,"adjusted_close":c,"adjusted_volume":v,"future_split_cum_ratio":mult,
                 "reconstructed_as_traded_close":None if c is None else c*mult,
                 "reconstructed_as_traded_volume":None if v is None else v/mult,
                 "dollar_volume_invariance_check":None if c is None or v is None else (c*v)-(c*mult)*(v/mult),
                 "splits_used":used})
(OUT/"probe.json").write_text(json.dumps({"schema":"V4_SPLIT_CROSSCHECK_V8","rows":rows},indent=2),encoding="utf-8")
print(json.dumps(rows))
