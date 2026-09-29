from pathlib import Path
import requests, pandas as pd, json

OUT=Path("v4-yahoo-shares-output"); OUT.mkdir(exist_ok=True)
url="https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main/data/US/stock_shares_outstanding.parquet?download=true"
r=requests.get(url,timeout=120,headers={"User-Agent":"V4 shares-outstanding research"})
r.raise_for_status()
p=OUT/"stock_shares_outstanding.parquet"; p.write_bytes(r.content)
d=pd.read_parquet(p)
d.to_csv(OUT/"stock_shares_outstanding.csv",index=False)
summary={"rows":int(len(d)),"columns":[str(x) for x in d.columns]}
for c in d.columns:
    lc=str(c).lower()
    if lc in {"symbol","ticker"}: summary["symbols"]=int(d[c].astype(str).nunique())
    if "date" in lc:
        x=pd.to_datetime(d[c],errors="coerce")
        if x.notna().any(): summary["date_min"]=str(x.min().date()); summary["date_max"]=str(x.max().date())
(OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(summary)
print(d.head(30).to_string(index=False))
