import io, zipfile, requests, json
from pathlib import Path
OUT=Path("v4-stooq-bulk-probe-output"); OUT.mkdir(exist_ok=True)
S=requests.Session()
H={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/140 Safari/537.36","Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8","Accept-Language":"en-US,en;q=0.9"}
p=S.get("https://stooq.com/db/h/",headers=H,timeout=60)
print("PAGE",p.status_code,p.url,len(p.content),"COOKIES",S.cookies.get_dict(),flush=True)
print("PAGE_PREFIX",p.text[:200].replace("\n"," "),flush=True)
H2=H|{"Referer":"https://stooq.com/db/h/","Accept":"application/zip,application/octet-stream,*/*"}
for url in ["https://stooq.com/db/h/db/d/?b=d_us_txt","http://stooq.com/db/h/db/d/?b=d_us_txt"]:
    try:
        r=S.get(url,headers=H2,timeout=60,allow_redirects=True,stream=True)
        print("TRY",url,"=>",r.status_code,r.url,r.headers.get("content-type"),r.headers.get("content-length"),r.headers.get("content-disposition"),"COOKIES",S.cookies.get_dict(),flush=True)
        first=next(r.iter_content(1024),b"")
        print("FIRST",first[:100],flush=True)
    except Exception as e: print("ERR",url,repr(e),flush=True)
(OUT/"summary.json").write_text(json.dumps({"page_status":p.status_code,"cookies":S.cookies.get_dict()},indent=2),encoding="utf-8")
