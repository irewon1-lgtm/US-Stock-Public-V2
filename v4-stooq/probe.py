import json,requests,io,pandas as pd
from pathlib import Path
OUT=Path("v4-stooq-probe-output");OUT.mkdir(exist_ok=True)
tickers=["ADMS","AE","AEGN","AERI","AGN","AGTC","AIMC","AINC","ALBO","ATVI"]
rows=[]
for t in tickers:
    url="https://stooq.com/q/d/l/"
    params={"s":t.lower()+".us","d1":"20190901","d2":"20230105","i":"d"}
    try:
        r=requests.get(url,params=params,timeout=30,headers={"User-Agent":"Mozilla/5.0 V4 research"})
        txt=r.text[:500]
        n=0; cols=[]
        try:
            d=pd.read_csv(io.StringIO(r.text))
            n=len(d); cols=list(d.columns)
        except Exception: pass
        rows.append({"ticker":t,"status":r.status_code,"bytes":len(r.content),"rows":n,"columns":cols,"prefix":txt})
    except Exception as e:
        rows.append({"ticker":t,"error":repr(e)})
(OUT/"probe.json").write_text(json.dumps(rows,indent=2),encoding="utf-8")
print(json.dumps(rows,indent=2))
