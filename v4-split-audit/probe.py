import json,duckdb
from pathlib import Path
OUT=Path("v4-split-audit-output");OUT.mkdir(exist_ok=True)
T=json.loads(Path("v4-split-audit/targets.json").read_text())["tickers"]
url="https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main/data/US/stock_split_events.parquet?download=true"
con=duckdb.connect();con.execute("INSTALL httpfs; LOAD httpfs;")
schema=con.execute(f"DESCRIBE SELECT * FROM read_parquet('{url}')").fetchdf()
cols=[str(x) for x in schema.column_name.tolist()]
scol=next((c for c in cols if c.lower() in {"symbol","ticker"}),None)
lit=",".join("'" + x.replace("'","''") + "'" for x in T)
rows=[]
if scol:
    d=con.execute(f"SELECT * FROM read_parquet('{url}') WHERE {scol} IN ({lit})").fetchdf()
    rows=d.astype(object).where(d.notna(),None).to_dict("records")
res={"schema":schema.to_dict("records"),"rows":rows,"tickers_with_events":sorted({str(r.get(scol)) for r in rows}) if scol else []}
Path("v4-split-audit-output/split_events.json").write_text(json.dumps(res,indent=2,default=str))
print(json.dumps({"columns":cols,"rows":len(rows),"tickers_with_events":res["tickers_with_events"]},indent=2))
