from __future__ import annotations
import json, duckdb, pandas as pd, numpy as np
from pathlib import Path

OUT=Path("v4-defeatbeta-shares-probe-output"); OUT.mkdir(exist_ok=True)
URL="https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main/data/US/stock_shares_outstanding.parquet?download=true"
VALID=["AAPL","MSFT","JPM","XOM","HD","KO","AMZN","NVDA","EA","F"]
TARGET=["BPMP","HI","PS","TGE","LORL","VIACP","VMEO","ADTH","CVT","EQRX","PRDS","INFA","SIRE","ZFOX"]
ALL=sorted(set(VALID+TARGET))
con=duckdb.connect(); con.execute("INSTALL httpfs; LOAD httpfs;")
lit=",".join("'"+x+"'" for x in ALL)
res={}
try:
    schema=con.execute(f"DESCRIBE SELECT * FROM read_parquet('{URL}')").fetchdf()
    res["schema"]=schema.to_dict("records")
    q=f"""SELECT symbol,report_date,CAST(shares_outstanding AS DOUBLE) shares_outstanding
          FROM read_parquet('{URL}')
          WHERE symbol IN ({lit})
            AND CAST(report_date AS DATE) BETWEEN DATE '2017-01-01' AND DATE '2022-12-30'
          ORDER BY symbol,report_date"""
    d=con.execute(q).fetchdf()
    res["rows"]=int(len(d)); res["symbols_found"]=sorted(d.symbol.astype(str).unique().tolist()) if len(d) else []
    res["counts"]=d.groupby("symbol").size().to_dict() if len(d) else {}
    d.to_csv(OUT/"shares_sample.csv",index=False)
except Exception as e:
    res["error"]=repr(e)

(OUT/"probe.json").write_text(json.dumps(res,indent=2,default=str),encoding="utf-8")
print(json.dumps(res,indent=2,default=str))
