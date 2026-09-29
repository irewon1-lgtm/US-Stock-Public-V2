import json,requests
from pathlib import Path
OUT=Path("v4-nasdaq-probe-output");OUT.mkdir(exist_ok=True)
tickers=["ADMS","AE","AEGN","AERI","AGN","AGTC","AIMC","AINC","ALBO","ATVI"]
H={"User-Agent":"Mozilla/5.0","Accept":"application/json, text/plain, */*","Referer":"https://www.nasdaq.com/"}
rows=[]
for t in tickers:
    url=f"https://api.nasdaq.com/api/quote/{t}/historical"
    params={"assetclass":"stocks","fromdate":"09/01/2019","todate":"01/05/2023","limit":"5000"}
    try:
        r=requests.get(url,params=params,headers=H,timeout=30)
        j=None; err=""
        try:j=r.json()
        except Exception as e: err=repr(e)
        data=(j or {}).get("data") if isinstance(j,dict) else None
        trs=((data or {}).get("tradesTable") or {}).get("rows") if isinstance(data,dict) else None
        rows.append({"ticker":t,"status":r.status_code,"bytes":len(r.content),"row_count":0 if not isinstance(trs,list) else len(trs),"sample":None if not isinstance(trs,list) or not trs else trs[:2],"error":err,"prefix":r.text[:300]})
    except Exception as e:
        rows.append({"ticker":t,"error":repr(e)})
(OUT/"probe.json").write_text(json.dumps(rows,indent=2),encoding="utf-8")
print(json.dumps(rows,indent=2))
