from __future__ import annotations
import json, os, pandas as pd
from pathlib import Path
import simfin as sf

OUT=Path("v4-simfin-probe-output"); OUT.mkdir(exist_ok=True)
sf.set_api_key("free")
sf.set_data_dir("/tmp/simfin_data")
result={}
for kind,loader in [
    ("income_q",sf.load_income),
    ("cash_q",sf.load_cashflow),
]:
    try:
        d=loader(variant="quarterly", market="us", start_date="2019-01-01", end_date="2023-01-05", refresh_days=0)
        result[kind]={
            "status":"OK","rows":int(len(d)),"index_names":list(d.index.names),
            "columns":[str(x) for x in d.columns],
        }
        # capture only schema + a few rows for known public tickers, no user private data
        q=d.reset_index()
        sample=q[q.astype(str).apply(lambda r: any(t in set(r.values) for t in ["AAL","AA","AEP"]),axis=1)].head(10)
        result[kind]["sample"]=sample.astype(object).where(pd.notna(sample),None).to_dict("records")
    except Exception as e:
        result[kind]={"status":"ERROR","error":repr(e)}
(OUT/"probe.json").write_text(json.dumps(result,indent=2,default=str),encoding="utf-8")
print(json.dumps(result,indent=2,default=str)[:30000])
