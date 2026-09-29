import json, duckdb
from pathlib import Path
OUT=Path("v4-finnhub-archive-probe-output"); OUT.mkdir(exist_ok=True)
url="https://huggingface.co/datasets/mito0o852/OHLCV-1m/resolve/main/data/ohlcv_2020-03.parquet?download=true"
symbols=["ADMS","AE","AEGN","AERI","AGN","AGTC","AIMC","AINC","ALBO","ATVI","AAPL","MSFT"]
con=duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
res={}
try:
    schema=con.execute(f"DESCRIBE SELECT * FROM read_parquet('{url}')").fetchdf()
    res["schema"]=schema.to_dict("records")
    cols=[str(x) for x in schema.column_name.tolist()]
    scol=next((c for c in cols if c.lower() in {"symbol","ticker"}),None)
    tcol=next((c for c in cols if c.lower() in {"timestamp","time","datetime","date"}),None)
    if not scol or not tcol:
        raise RuntimeError(f"missing symbol/time cols: {cols}")
    lit=",".join("'" + s + "'" for s in symbols)
    q=f"""SELECT * FROM read_parquet('{url}') WHERE {scol} IN ({lit}) ORDER BY {scol},{tcol}"""
    d=con.execute(q).fetchdf()
    res["rows"]=int(len(d))
    res["symbols_found"]=sorted(d[scol].astype(str).unique().tolist()) if len(d) else []
    res["counts"]=d.groupby(scol).size().to_dict() if len(d) else {}
    res["sample"]=d.head(20).astype(object).where(d.notna(),None).to_dict("records")
except Exception as e:
    res["error"]=repr(e)
(OUT/"probe.json").write_text(json.dumps(res,indent=2,default=str),encoding="utf-8")
print(json.dumps(res,indent=2,default=str)[:30000])
