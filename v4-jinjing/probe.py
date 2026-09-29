from __future__ import annotations
import json, duckdb, pandas as pd, numpy as np
from pathlib import Path

OUT=Path("v4-jinjing-probe-output"); OUT.mkdir(exist_ok=True)
CAND_URLS=[
 "https://huggingface.co/datasets/cedwyh/jinjing-shared-data/resolve/main/delisted_unified.parquet?download=true",
 "https://huggingface.co/datasets/cedwyh/jinjing-shared-data/resolve/main/data/delisted_unified.parquet?download=true",
 "https://huggingface.co/datasets/cedwyh/jinjing-shared-data/resolve/main/us_unified.parquet?download=true",
 "https://huggingface.co/datasets/cedwyh/jinjing-shared-data/resolve/main/data/us_unified.parquet?download=true",
]
VALID=["AAPL","MSFT","JPM","XOM","HD","KO","AMZN","NVDA"]
MISSING=["CNXM","EIDX","FBM","FMCI","GTHX","IOTS","KAMN","KNL","LMNX","MEET","MTSC","MYOV","NP","NPTN","ONEM","PGTI","PRVB","VNE","VRTU","WIRE","ACI","ADAC","AIMD","AMPG","AMR","API","ASTI","ASXC"]
ALL=sorted(set(VALID+MISSING))
con=duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
res={"files":[]}
lit=",".join("'"+x.replace("'","''")+"'" for x in ALL)
for url in CAND_URLS:
    item={"url":url}
    try:
        schema=con.execute(f"DESCRIBE SELECT * FROM read_parquet('{url}')").fetchdf()
        item["status"]="OK"
        item["schema"]=schema.to_dict("records")
        q=f"""SELECT symbol,date,CAST(close AS DOUBLE) close,CAST(volume AS DOUBLE) volume
              FROM read_parquet('{url}')
              WHERE symbol IN ({lit})
                AND CAST(date AS DATE) BETWEEN DATE '2019-09-01' AND DATE '2023-01-05'
              ORDER BY symbol,date"""
        d=con.execute(q).fetchdf()
        item["rows"]=int(len(d)); item["symbols_found"]=sorted(d.symbol.astype(str).unique().tolist()) if len(d) else []
        item["counts"]=d.groupby("symbol").size().to_dict() if len(d) else {}
        if len(d):
            d.to_csv(OUT/("sample_"+str(len(res["files"]))+".csv"),index=False)
    except Exception as e:
        item["status"]="ERROR"; item["error"]=repr(e)[:1000]
    res["files"].append(item)

# Validate any accessible file with enough known rows against frozen Yahoo panel from repo.
validations=[]
try:
    y=pd.read_csv("v4-liquidity-output/liquidity_panel.csv.gz",compression="gzip",low_memory=False)
    for i,item in enumerate(res["files"]):
        if item.get("status")!="OK": continue
        f=OUT/f"sample_{i}.csv"
        if not f.exists(): continue
        d=pd.read_csv(f)
        d["date"]=pd.to_datetime(d["date"],errors="coerce").dt.normalize()
        for t in VALID:
            z=d[d.symbol.astype(str).eq(t)].copy().sort_values("date")
            if z.empty: continue
            z=z.set_index("date")
            for snap in sorted(y.loc[y.ticker_at_snapshot.astype(str).eq(t),"snapshot_date"].astype(str).unique()):
                s=pd.Timestamp(snap)
                if s not in z.index: continue
                zz=z.loc[:s].tail(60)
                if len(zz)<60: continue
                r=y[(y.ticker_at_snapshot.astype(str)==t)&(y.snapshot_date.astype(str)==snap)]
                if r.empty: continue
                r=r.iloc[0]
                yp=pd.to_numeric(pd.Series([r.get("raw_close_v4")]),errors="coerce").iloc[0]
                ym=pd.to_numeric(pd.Series([r.get("median_dollar_volume_60d")]),errors="coerce").iloc[0]
                cp=float(pd.to_numeric(pd.Series([zz.loc[s,"close"]]),errors="coerce").iloc[0])
                mdv=float((pd.to_numeric(zz.close,errors="coerce")*pd.to_numeric(zz.volume,errors="coerce")).median())
                if not all(np.isfinite(x) and x>0 for x in [yp,ym,cp,mdv]): continue
                validations.append({"file_index":i,"ticker":t,"snapshot_date":snap,
                    "yahoo_price":yp,"candidate_price":cp,"price_rel_diff":abs(cp-yp)/max(abs(cp),abs(yp)),
                    "yahoo_mdv":ym,"candidate_mdv":mdv,"mdv_rel_diff":abs(mdv-ym)/max(abs(mdv),abs(ym))})
except Exception as e:
    res["validation_error"]=repr(e)

v=pd.DataFrame(validations)
if len(v):
    v.to_csv(OUT/"validation.csv",index=False)
    agg=[]
    for fi,g in v.groupby("file_index"):
        agg.append({"file_index":int(fi),"rows":len(g),
          "price_median":float(g.price_rel_diff.median()),"price_p95":float(g.price_rel_diff.quantile(.95)),"price_max":float(g.price_rel_diff.max()),
          "mdv_median":float(g.mdv_rel_diff.median()),"mdv_p95":float(g.mdv_rel_diff.quantile(.95)),"mdv_max":float(g.mdv_rel_diff.max())})
    res["validation_aggregate"]=agg
else:
    res["validation_aggregate"]=[]

(OUT/"probe.json").write_text(json.dumps(res,indent=2,default=str),encoding="utf-8")
print(json.dumps(res,indent=2,default=str)[:30000])
