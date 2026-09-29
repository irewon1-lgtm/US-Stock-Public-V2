import json, pandas as pd, requests, io
from pathlib import Path
OUT=Path("v4-hf-stooq-probe-output"); OUT.mkdir(exist_ok=True)
tickers=["AAPL","ADMS","ATVI","AE","AERI","ALBO","ACI","AAL"]
rows=[]
for t in tickers:
    first=t[0].upper()
    url=f"https://huggingface.co/datasets/DWK-Partners/trading-data/resolve/main/us/prices/company/{first}/{t}.parquet?download=true"
    try:
        r=requests.get(url,timeout=60,headers={"User-Agent":"V4-research"})
        rec={"ticker":t,"status":r.status_code,"bytes":len(r.content),"url":r.url}
        if r.status_code==200:
            try:
                d=pd.read_parquet(io.BytesIO(r.content))
                rec["columns"]=[str(c) for c in d.columns]
                rec["rows"]=len(d)
                # normalize date
                datecol=next((c for c in d.columns if str(c).lower() in {"date","datetime","time","timestamp"}),None)
                if datecol is not None:
                    ds=pd.to_datetime(d[datecol],errors="coerce")
                    rec["min_date"]=str(ds.min())[:10]
                    rec["max_date"]=str(ds.max())[:10]
                    for q in ["2020-08-28","2020-03-31","2021-12-31","2022-09-30"]:
                        x=d[ds.dt.strftime("%Y-%m-%d").eq(q)]
                        if len(x):
                            rec[q]=x.head(1).astype(object).where(pd.notna(x),None).to_dict("records")[0]
            except Exception as e:
                rec["parse_error"]=repr(e)
        rows.append(rec)
    except Exception as e:
        rows.append({"ticker":t,"error":repr(e)})
(OUT/"probe.json").write_text(json.dumps(rows,indent=2,default=str),encoding="utf-8")
print(json.dumps(rows,indent=2,default=str))
