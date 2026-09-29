import json,requests,datetime as dt
from pathlib import Path
OUT=Path("v4-yahoo-direct-probe-output");OUT.mkdir(exist_ok=True)
tickers=["ADMS","AE","AEGN","AERI","AGN","AGTC","AIMC","AINC","ALBO","ATVI"]
p1=int(dt.datetime(2019,9,1,tzinfo=dt.timezone.utc).timestamp())
p2=int(dt.datetime(2023,1,6,tzinfo=dt.timezone.utc).timestamp())
rows=[]
for t in tickers:
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{t}"
    try:
        r=requests.get(url,params={"period1":p1,"period2":p2,"interval":"1d","events":"div,splits","includeAdjustedClose":"true"},headers={"User-Agent":"Mozilla/5.0"},timeout=30)
        obj={}
        try:obj=r.json()
        except:pass
        result=((obj.get("chart") or {}).get("result") or [])
        n=len(result[0].get("timestamp") or []) if result else 0
        meta=(result[0].get("meta") or {}) if result else {}
        err=(obj.get("chart") or {}).get("error") if obj else None
        rows.append({"ticker":t,"status":r.status_code,"rows":n,"symbol":meta.get("symbol"),"exchangeName":meta.get("exchangeName"),"currency":meta.get("currency"),"error":err})
    except Exception as e: rows.append({"ticker":t,"error":repr(e)})
(OUT/"probe.json").write_text(json.dumps(rows,indent=2),encoding="utf-8")
print(json.dumps(rows,indent=2))
