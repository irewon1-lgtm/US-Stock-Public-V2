import json,duckdb
from pathlib import Path
REV="925b7866b77f8623e80751c859a659b7de9509ad"
url=f"https://huggingface.co/datasets/cedwyh/jinjing-shared-data/resolve/{REV}/delisted_unified.parquet?download=true"
con=duckdb.connect(); con.execute("INSTALL httpfs; LOAD httpfs;")
res={}
try:
    res["sample_symbols"]=con.execute(f"SELECT DISTINCT symbol FROM read_parquet('{url}') ORDER BY symbol LIMIT 100").fetchdf()["symbol"].astype(str).tolist()
    pats=["ADMS","AEGN","AERI","AGN","AGTC","AIMC","AINC","ALBO","ATVI","AE"]
    out={}
    for p in pats:
        q=f"""SELECT symbol, MIN(CAST(date AS DATE)) AS min_date, MAX(CAST(date AS DATE)) AS max_date, COUNT(*) AS n
              FROM read_parquet('{url}')
              WHERE UPPER(symbol) LIKE '%{p}%'
              GROUP BY symbol ORDER BY symbol LIMIT 50"""
        out[p]=con.execute(q).fetchdf().astype(str).to_dict("records")
    res["matches"]=out
except Exception as e: res["error"]=repr(e)
Path("v4-jinjing-daily-probe-output").mkdir(exist_ok=True)
Path("v4-jinjing-daily-probe-output/delisted_symbols.json").write_text(json.dumps(res,indent=2),encoding="utf-8")
print(json.dumps(res,indent=2)[:30000])
