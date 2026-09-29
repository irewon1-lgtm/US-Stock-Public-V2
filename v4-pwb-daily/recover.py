from __future__ import annotations
import json,duckdb,pandas as pd
from pathlib import Path
ROOT=Path("."); T=json.loads((ROOT/"v4-pwb-daily/targets.json").read_text())
OUT=ROOT/"v4-pwb-daily-recovery-output";OUT.mkdir(exist_ok=True)
BASE="https://huggingface.co/datasets/paperswithbacktest/Stocks-Daily-Price/resolve/main/data/train-0000{n}-of-00004.parquet?download=true"
con=duckdb.connect();con.execute("INSTALL httpfs; LOAD httpfs;")
lit=",".join("'" + x.replace("'","''") + "'" for x in T["tickers"])
parts=[]
for n in range(4):
    url=BASE.format(n=n)
    q=f"""SELECT symbol AS ticker, CAST(date AS DATE) AS date,
                 CAST(close AS DOUBLE) AS close, CAST(volume AS DOUBLE) AS volume
          FROM read_parquet('{url}')
          WHERE symbol IN ({lit})
            AND CAST(date AS DATE) BETWEEN DATE '{T["start"]}' AND DATE '{T["end"]}'
          ORDER BY ticker,date"""
    d=con.execute(q).fetchdf()
    if len(d):parts.append(d)
d=pd.concat(parts,ignore_index=True) if parts else pd.DataFrame(columns=["ticker","date","close","volume"])
if len(d):
    d["date"]=pd.to_datetime(d["date"]).dt.normalize()
    d=d.sort_values(["ticker","date"]).drop_duplicates(["ticker","date"],keep="last")
d.to_csv(OUT/"daily_rows.csv.gz",index=False,compression="gzip")
summary={"schema":"V4_PWB_DAILY_RECOVERY_V1","target_tickers":len(T["tickers"]),
         "found_tickers":int(d.ticker.nunique()) if len(d) else 0,"rows":int(len(d)),
         "formation_2023_opened":False,"future_outcomes_used":False,"us3700_used":False,
         "validation_reference":"probe matched frozen Yahoo close+60d MDV exactly on 60 rows"}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(json.dumps(summary,indent=2))
