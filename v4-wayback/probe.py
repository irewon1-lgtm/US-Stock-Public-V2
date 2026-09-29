from __future__ import annotations
import io,json,time
from pathlib import Path
import pandas as pd,requests

OUT=Path("v4-wayback-probe-output");OUT.mkdir(exist_ok=True)
TICKERS=["ADMS","AEGN","AERI","AGN","AGTC","AIMC","AINC","ALBO","ATVI","ADSW"]
CDX="https://web.archive.org/cdx/search/cdx"
FETCH="https://web.archive.org/web"
EPS=[
 "real-chart.finance.yahoo.com/table.csv?s={ticker}",
 "ichart.finance.yahoo.com/table.csv?s={ticker}",
 "chart.finance.yahoo.com/table.csv?s={ticker}",
]
H={"User-Agent":"Mozilla/5.0 V4 research"}

def find(t,e):
    url=e.format(ticker=t)
    p={"url":url,"output":"json","fl":"timestamp,original,length,statuscode",
       "filter":"statuscode:200","limit":20}
    r=requests.get(CDX,params=p,headers=H,timeout=45)
    if r.status_code!=200:return []
    try:j=r.json()
    except:return []
    if len(j)<=1:return []
    out=[]
    for row in j[1:]:
        try:ln=int(row[2])
        except:ln=0
        out.append((ln,row[0],row[1]))
    return sorted(out,reverse=True)

rows=[]
for t in TICKERS:
    rec={"ticker":t,"status":"NOT_FOUND","best_rows":0,"start":"","end":"","columns":[],"endpoint":"","snapshot":""}
    for e in EPS:
        snaps=find(t,e)
        for ln,ts,orig in snaps[:5]:
            try:
                r=requests.get(f"{FETCH}/{ts}id_/{orig}",headers=H,timeout=60)
                if r.status_code!=200:continue
                d=pd.read_csv(io.StringIO(r.text))
                if not {"Date","Close","Volume"}.issubset(d.columns):continue
                d["Date"]=pd.to_datetime(d["Date"],errors="coerce")
                d=d.dropna(subset=["Date"]).sort_values("Date")
                n=int(((d.Date>=pd.Timestamp("2019-09-01"))&(d.Date<=pd.Timestamp("2023-01-05"))).sum())
                if n>rec["best_rows"]:
                    rec={"ticker":t,"status":"OK","best_rows":n,
                         "start":str(d.Date.min().date()) if len(d) else "",
                         "end":str(d.Date.max().date()) if len(d) else "",
                         "columns":[str(x) for x in d.columns],
                         "endpoint":e,"snapshot":ts}
                if n>=60:break
            except Exception:
                continue
        if rec["best_rows"]>=60:break
        time.sleep(.5)
    rows.append(rec);print(json.dumps(rec),flush=True)
    time.sleep(.5)
(OUT/"probe.json").write_text(json.dumps(rows,indent=2),encoding="utf-8")
