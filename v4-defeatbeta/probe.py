import json, duckdb
from pathlib import Path
OUT=Path("v4-defeatbeta-probe-output");OUT.mkdir(exist_ok=True)
url="https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main/data/US/stock_prices.parquet?download=true"
tickers=["ADMS","AE","AEGN","AERI","AGN","AGTC","AIMC","AINC","ALBO","ATVI"]
con=duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
result={}
try:
    schema=con.execute(f"DESCRIBE SELECT * FROM read_parquet('{url}')").fetchdf()
    result["schema"]=schema.to_dict("records")
    cols=[str(x) for x in schema["column_name"].tolist()]
    tcol=next((c for c in cols if c.lower() in {"ticker","symbol"}),None)
    dcol=next((c for c in cols if c.lower() in {"date","report_date","datetime","timestamp"}),None)
    if tcol and dcol:
        lit=",".join("'" + t.replace("'","''") + "'" for t in tickers)
        q=f"""SELECT * FROM read_parquet('{url}')
               WHERE {tcol} IN ({lit})
                 AND CAST({dcol} AS DATE) BETWEEN DATE '2019-09-01' AND DATE '2023-01-05'
               ORDER BY {tcol},{dcol}"""
        d=con.execute(q).fetchdf()
        result["rows"]=int(len(d))
        result["tickers_found"]=sorted(d[tcol].astype(str).unique().tolist()) if len(d) else []
        result["counts"]=d.groupby(tcol).size().to_dict() if len(d) else {}
        result["sample"]=d.head(10).astype(object).where(d.notna(),None).to_dict("records")
    else:
        result["error"]="ticker/date column not found"
except Exception as e:
    result["error"]=repr(e)
(OUT/"probe.json").write_text(json.dumps(result,indent=2,default=str),encoding="utf-8")
print(json.dumps(result,indent=2,default=str)[:30000])
