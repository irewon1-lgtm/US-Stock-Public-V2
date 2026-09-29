import json, requests
from pathlib import Path
OUT=Path("v4-jinjing-probe-output"); OUT.mkdir(exist_ok=True)
urls=[
 "https://huggingface.co/api/datasets/cedwyh/jinjing-shared-data/tree/main?recursive=true&expand=false",
 "https://huggingface.co/api/datasets/cedwyh/jinjing-shared-data/tree/main/data?recursive=true&expand=false",
]
items=[]
for url in urls:
    try:
        r=requests.get(url,timeout=45,headers={"User-Agent":"V4 research"})
        x={"url":url,"status":r.status_code,"bytes":len(r.content)}
        if r.ok:
            j=r.json()
            x["all_paths"]=[o.get("path") for o in j if isinstance(o,dict)][:1000]; x["matches"]=[p for p in x["all_paths"] if ("unified" in str(p).lower() or "delisted" in str(p).lower() or "ohlcv" in str(p).lower())][:500]
            x["count"]=len(j) if isinstance(j,list) else None
        else:x["prefix"]=r.text[:1000]
        items.append(x)
    except Exception as e:items.append({"url":url,"error":repr(e)})
(OUT/"tree_paths.json").write_text(json.dumps(items,indent=2),encoding="utf-8")
print(json.dumps(items,indent=2))
