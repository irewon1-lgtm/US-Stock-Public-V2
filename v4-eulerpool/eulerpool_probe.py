from __future__ import annotations
import json, os, urllib.request, urllib.parse
from pathlib import Path
KEY=os.environ["EULERPOOL_API_KEY"].strip()
BASE="https://api.eulerpool.com/api/1/charting/ohlcv/AAPL"
FROM=1598400000  # 2020-08-26 UTC
TO=1599091200    # 2020-09-03 UTC
url=BASE+"?"+urllib.parse.urlencode({"from":FROM,"to":TO,"interval":"1d"})
req=urllib.request.Request(url,headers={"Authorization":f"Bearer {KEY}","Accept":"application/json","User-Agent":"V4-split-basis-probe/1.0"})
with urllib.request.urlopen(req,timeout=45) as r:
    p=json.loads(r.read().decode("utf-8"))
rows=[]
for t,o,h,l,c,v in zip(p.get("t",[]),p.get("o",[]),p.get("h",[]),p.get("l",[]),p.get("c",[]),p.get("v",[])):
    rows.append({"t":t,"o":o,"h":h,"l":l,"c":c,"v":v})
out={"schema":"V4_EULERPOOL_SPLIT_BASIS_PROBE_V1","rows":rows}
Path("v4-eulerpool-output").mkdir(parents=True,exist_ok=True)
Path("v4-eulerpool-output/probe.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
print(json.dumps(out))
