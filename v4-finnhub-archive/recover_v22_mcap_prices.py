from __future__ import annotations
import json,duckdb,pandas as pd
from pathlib import Path
ROOT=Path(".")
OUT=ROOT/"v4-v22-mcap-finnhub-output";OUT.mkdir(exist_ok=True)
# Exact V22 mcap-only ticker/snapshot pairs, embedded to avoid touching private/future data.
pairs=[["COKE","2020-03-31"],["DKS","2020-03-31"],["HI","2020-03-31"],["JBSS","2020-03-31"],["MODV","2020-03-31"],["PS","2020-03-31"],["SUN","2020-03-31"],["TGE","2020-03-31"],["UNF","2020-03-31"],["VICR","2020-03-31"],["WSC","2020-03-31"],["COKE","2020-06-30"],["DKS","2020-06-30"],["F","2020-06-30"],["JBSS","2020-06-30"],["MODV","2020-06-30"],["PS","2020-06-30"],["SUN","2020-06-30"],["TR","2020-06-30"],["UNF","2020-06-30"],["VICR","2020-06-30"],["WSC","2020-06-30"],["COKE","2020-09-30"],["DKS","2020-09-30"],["F","2020-09-30"],["GTM","2020-09-30"],["MODV","2020-09-30"],["PS","2020-09-30"],["SUN","2020-09-30"],["TR","2020-09-30"],["UNF","2020-09-30"],["VICR","2020-09-30"],["COKE","2020-12-31"],["DKS","2020-12-31"],["F","2020-12-31"],["GTM","2020-12-31"],["MODV","2020-12-31"],["PS","2020-12-31"],["SUN","2020-12-31"],["TR","2020-12-31"],["UNF","2020-12-31"],["VICR","2020-12-31"],["COKE","2021-03-31"],["DKS","2021-03-31"],["F","2021-03-31"],["GRYP","2021-03-31"],["GTM","2021-03-31"],["HLMN","2021-03-31"],["KPLT","2021-03-31"],["LORL","2021-03-31"],["SUN","2021-03-31"],["TALK","2021-03-31"],["TR","2021-03-31"],["UNF","2021-03-31"],["VICR","2021-03-31"],["COKE","2021-06-30"],["DKS","2021-06-30"],["F","2021-06-30"],["GTM","2021-06-30"],["HLMN","2021-06-30"],["JOBY","2021-06-30"],["KPLT","2021-06-30"],["LCID","2021-06-30"],["ORGN","2021-06-30"],["SUN","2021-06-30"],["TALK","2021-06-30"],["TR","2021-06-30"],["UNF","2021-06-30"],["VIACP","2021-06-30"],["VICR","2021-06-30"],["COKE","2021-09-30"],["DKS","2021-09-30"],["F","2021-09-30"],["GTM","2021-09-30"],["SUN","2021-09-30"],["UNF","2021-09-30"],["VICR","2021-09-30"],["VMEO","2021-09-30"],["BPMP","2021-12-31"],["COKE","2021-12-31"],["DKS","2021-12-31"],["F","2021-12-31"],["GTM","2021-12-31"],["MOV","2021-12-31"],["RDW","2021-12-31"],["SUN","2021-12-31"],["UNF","2021-12-31"],["VICR","2021-12-31"],["VMEO","2021-12-31"],["BPMP","2022-03-31"],["BSM","2022-03-31"],["COKE","2022-03-31"],["DKS","2022-03-31"],["F","2022-03-31"],["INFA","2022-03-31"],["SUN","2022-03-31"],["UNF","2022-03-31"],["VICR","2022-03-31"],["VMEO","2022-03-31"],["VSH","2022-03-31"],["COKE","2022-06-30"],["DKS","2022-06-30"],["F","2022-06-30"],["INFA","2022-06-30"],["RDW","2022-06-30"],["SUN","2022-06-30"],["UNF","2022-06-30"],["VICR","2022-06-30"],["VMEO","2022-06-30"],["VSH","2022-06-30"],["COKE","2022-09-30"],["DKS","2022-09-30"],["F","2022-09-30"],["INFA","2022-09-30"],["RDUS","2022-09-30"],["SUN","2022-09-30"],["UNF","2022-09-30"],["VICR","2022-09-30"],["VMEO","2022-09-30"],["VSH","2022-09-30"],["COKE","2022-12-30"],["DKS","2022-12-30"],["F","2022-12-30"],["INFA","2022-12-30"],["RDUS","2022-12-30"],["SUN","2022-12-30"],["UNF","2022-12-30"],["VICR","2022-12-30"],["VMEO","2022-12-30"],["VSH","2022-12-30"]]
BASE="https://huggingface.co/datasets/mito0o852/OHLCV-1m/resolve/main/data/ohlcv_{m}.parquet?download=true"
con=duckdb.connect();con.execute("INSTALL httpfs; LOAD httpfs;")
rows=[]
for snap in sorted(set(s for _,s in pairs)):
    m=snap[:7]; tickers=sorted(set(t for t,s in pairs if s==snap))
    lit=",".join("'" + t.replace("'","''") + "'" for t in tickers)
    url=BASE.format(m=m)
    q=f"""SELECT ticker,timestamp,close FROM read_parquet('{url}') WHERE ticker IN ({lit})"""
    d=con.execute(q).fetchdf()
    if d.empty:continue
    d["timestamp"]=pd.to_datetime(d["timestamp"],utc=True)
    loc=d["timestamp"].dt.tz_convert("America/New_York")
    d["date"]=loc.dt.tz_localize(None).dt.normalize(); d["mins"]=loc.dt.hour*60+loc.dt.minute
    d=d[(d.date.eq(pd.Timestamp(snap)))&(d.mins>=570)&(d.mins<=960)].sort_values(["ticker","timestamp"])
    if d.empty:continue
    z=d.groupby("ticker",as_index=False).agg(snapshot_close=("close","last"))
    z["snapshot_date"]=snap
    rows.extend(z.to_dict("records"))
o=pd.DataFrame(rows)
if o.empty:o=pd.DataFrame(columns=["ticker","snapshot_close","snapshot_date"])
o.to_csv(OUT/"snapshot_prices.csv.gz",index=False,compression="gzip")
summary={"schema":"V4_V22_MCAP_ONLY_FINNHUB_AS_TRADED_PRICE_V1","requested_pairs":len(pairs),"resolved_pairs":len(o),
         "resolved_tickers":int(o.ticker.nunique()) if len(o) else 0,"price_error_guard":0.02,
         "formation_2023_opened":False,"future_outcomes_used":False,"us3700_used":False,"new_corp_action_lookup_calls":0}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(json.dumps(summary,indent=2))
