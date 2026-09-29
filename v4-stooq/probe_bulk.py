import io, zipfile, requests, re, json, csv
from pathlib import Path
OUT=Path("v4-stooq-bulk-probe-output"); OUT.mkdir(exist_ok=True)
url="https://stooq.com/db/h/db/d/?b=d_us_txt"
r=requests.get(url,timeout=180,headers={"User-Agent":"Mozilla/5.0 V4 research"},stream=True)
print("HTTP",r.status_code,r.headers.get("content-type"),r.headers.get("content-length"),r.headers.get("content-disposition"),flush=True)
r.raise_for_status()
buf=io.BytesIO()
for ch in r.iter_content(1024*1024):
    if ch: buf.write(ch)
print("BYTES",buf.tell(),"SIG",buf.getvalue()[:4],flush=True)
buf.seek(0)
z=zipfile.ZipFile(buf)
names=z.namelist()
print("MEMBERS",len(names),flush=True)
# map basenames
for q in ["aapl.us","adms.us","atvi.us","ae.us"]:
    hits=[n for n in names if Path(n).stem.lower()==q.lower() or Path(n).name.lower() in {q.lower()+".txt",q.lower()+".csv"} or q.lower() in Path(n).name.lower()]
    print("HITS",q,hits[:10],flush=True)
    for n in hits[:1]:
        txt=z.read(n).decode("utf-8","ignore")
        lines=txt.splitlines()
        print("FILE",n,"HEAD",lines[:3],flush=True)
        wanted=[x for x in lines if "20200828" in x or "2020-08-28" in x or "20210930" in x or "2021-09-30" in x]
        print("WANTED",wanted[:10],flush=True)
summary={"status":"OK","bytes":buf.tell(),"members":len(names)}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
