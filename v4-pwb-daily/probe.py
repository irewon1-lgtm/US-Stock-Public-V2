from __future__ import annotations
import json, duckdb, pandas as pd, numpy as np
from pathlib import Path

OUT=Path("v4-pwb-daily-probe-output"); OUT.mkdir(exist_ok=True)
BASE="https://huggingface.co/datasets/paperswithbacktest/Stocks-Daily-Price/resolve/main/data/train-0000{n}-of-00004.parquet?download=true"
KNOWN=["AAPL","MSFT","JPM","XOM","HD"]
MISSING=["ADMS","AEGN","AERI","AGN","AGTC","AIMC","AINC","ALBO","ATVI","AE"]
ALL=KNOWN+MISSING
START="2019-09-01"; END="2023-01-05"

con=duckdb.connect(); con.execute("INSTALL httpfs; LOAD httpfs;")
parts=[]; files=[]
for n in range(4):
    url=BASE.format(n=n)
    item={"url":url}
    try:
        schema=con.execute(f"DESCRIBE SELECT * FROM read_parquet('{url}')").fetchdf()
        item["schema"]=schema.to_dict("records")
        cols=[str(x) for x in schema.column_name.tolist()]
        scol=next((c for c in cols if c.lower() in {"symbol","ticker"}),None)
        dcol=next((c for c in cols if c.lower() in {"date","report_date","datetime","timestamp"}),None)
        ccol=next((c for c in cols if c.lower()=="close"),None)
        vcol=next((c for c in cols if c.lower()=="volume"),None)
        item["detected"]={"symbol":scol,"date":dcol,"close":ccol,"volume":vcol}
        if not all([scol,dcol,ccol,vcol]):
            item["error"]="required columns missing"
        else:
            lit=",".join("'" + t.replace("'","''") + "'" for t in ALL)
            q=f"""SELECT {scol} AS ticker, CAST({dcol} AS DATE) AS date,
                         CAST({ccol} AS DOUBLE) AS close, CAST({vcol} AS DOUBLE) AS volume
                  FROM read_parquet('{url}')
                  WHERE {scol} IN ({lit})
                    AND CAST({dcol} AS DATE) BETWEEN DATE '{START}' AND DATE '{END}'
                  ORDER BY ticker,date"""
            d=con.execute(q).fetchdf()
            item["rows"]=int(len(d))
            item["tickers_found"]=sorted(d.ticker.astype(str).unique().tolist()) if len(d) else []
            if len(d): parts.append(d)
    except Exception as e:
        item["error"]=repr(e)
    files.append(item)

d=pd.concat(parts,ignore_index=True) if parts else pd.DataFrame(columns=["ticker","date","close","volume"])
if len(d):
    d["date"]=pd.to_datetime(d["date"]).dt.normalize()
    d=d.sort_values(["ticker","date"]).drop_duplicates(["ticker","date"],keep="last")
res={"files":files,"tickers_found_total":sorted(d.ticker.astype(str).unique().tolist()) if len(d) else [],
     "counts":d.groupby("ticker").size().to_dict() if len(d) else {},
     "sample_missing_present":{t:int((d.ticker==t).sum()) for t in MISSING}}

# validation vs frozen Yahoo eligibility panel
y=pd.read_csv("v4-liquidity-output/liquidity_panel.csv.gz",compression="gzip",low_memory=False)
y=y[y.ticker_at_snapshot.astype(str).isin(KNOWN) & y.liquidity_status.astype(str).eq("OK")].copy()
checks=[]
for _,r in y.iterrows():
    t=str(r.ticker_at_snapshot); s=pd.Timestamp(r.snapshot_date).normalize()
    z=d[(d.ticker.eq(t)) & (d.date<=s)].sort_values("date").tail(60)
    if len(z)<60 or s not in set(z.date): continue
    dc=float(z.loc[z.date.eq(s),"close"].iloc[-1]); mdv=float((z.close*z.volume).median())
    yc=pd.to_numeric(pd.Series([r.get("raw_close_v4")]),errors="coerce").iloc[0]
    ym=pd.to_numeric(pd.Series([r.get("median_dollar_volume_60d")]),errors="coerce").iloc[0]
    if not all(np.isfinite(x) and x>0 for x in [dc,mdv,yc,ym]): continue
    checks.append({"ticker":t,"snapshot_date":r.snapshot_date,
                   "yahoo_close":yc,"archive_close":dc,
                   "close_rel_diff":abs(dc-yc)/max(abs(dc),abs(yc)),
                   "yahoo_mdv":ym,"archive_mdv":mdv,
                   "mdv_rel_diff":abs(mdv-ym)/max(abs(mdv),abs(ym))})
v=pd.DataFrame(checks)
if len(v):
    res["validation"]={
        "rows":int(len(v)),
        "close_rel_diff_median":float(v.close_rel_diff.median()),
        "close_rel_diff_p95":float(v.close_rel_diff.quantile(.95)),
        "mdv_rel_diff_median":float(v.mdv_rel_diff.median()),
        "mdv_rel_diff_p95":float(v.mdv_rel_diff.quantile(.95)),
    }
    v.to_csv(OUT/"validation.csv",index=False)
(OUT/"probe.json").write_text(json.dumps(res,indent=2,default=str),encoding="utf-8")
print(json.dumps(res,indent=2,default=str)[:30000])
