import io,json,requests,pandas as pd
from pathlib import Path
OUT=Path("v4-hf-price-probe-output");OUT.mkdir(exist_ok=True)
tickers=["ADMS","AE","AEGN","AERI","AGN","AGTC","AIMC","AINC","ALBO","ATVI"]
base="https://huggingface.co/datasets/AmirTrader/YahooFinance/resolve/main/data/daily/{t}.parquet?download=true"
rows=[]
for t in tickers:
    url=base.format(t=t)
    try:
        r=requests.get(url,timeout=45,headers={"User-Agent":"V4 research"})
        item={"ticker":t,"status":r.status_code,"bytes":len(r.content)}
        if r.status_code==200 and len(r.content)>1000:
            d=pd.read_parquet(io.BytesIO(r.content))
            cols=[str(x) for x in d.columns]
            item["columns"]=cols
            item["rows"]=len(d)
            if "date" in d.columns:
                dt=pd.to_datetime(d["date"],errors="coerce")
            else:
                dt=pd.to_datetime(d.index,errors="coerce")
            item["min_date"]=None if dt.isna().all() else str(dt.min().date())
            item["max_date"]=None if dt.isna().all() else str(dt.max().date())
            # sample 2020-2022 row count
            item["rows_2020_2022"]=int(((dt>=pd.Timestamp("2019-09-01"))&(dt<=pd.Timestamp("2023-01-05"))).sum())
        else:
            item["prefix"]=r.text[:300]
        rows.append(item)
    except Exception as e:
        rows.append({"ticker":t,"error":repr(e)})
(OUT/"probe.json").write_text(json.dumps(rows,indent=2),encoding="utf-8")
print(json.dumps(rows,indent=2))
