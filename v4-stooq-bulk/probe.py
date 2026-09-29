import requests, json, zipfile, io
from pathlib import Path
url="https://static.stooq.com/db/h/d_us_txt.zip"
H={"User-Agent":"Mozilla/5.0 V4 research"}
out={}
try:
    r=requests.get(url,headers={**H,"Range":"bytes=0-2047"},timeout=60,stream=False)
    out={"status":r.status_code,"bytes":len(r.content),"content_type":r.headers.get("content-type"),
         "content_length":r.headers.get("content-length"),"content_range":r.headers.get("content-range"),
         "magic":r.content[:8].hex(),"prefix_text":r.text[:300] if not r.content.startswith(b"PK") else ""}
except Exception as e:
    out={"error":repr(e)}
Path("v4-stooq-bulk-probe-output").mkdir(exist_ok=True)
Path("v4-stooq-bulk-probe-output/probe.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
print(json.dumps(out,indent=2))
