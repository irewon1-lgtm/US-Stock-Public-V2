import hashlib,re,requests,io,json,time
import pandas as pd
from pathlib import Path

OUT=Path("v4-stooq-probe-output");OUT.mkdir(exist_ok=True)
S=requests.Session()
H={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/125 Safari/537.36"}

def solve():
    r=S.get("https://stooq.com/q/d/l/",params={"s":"ae.us","d1":"20190901","d2":"20230105","i":"d"},headers=H,timeout=30)
    txt=r.text
    if "This site requires JavaScript to verify your browser" not in txt:
        return {"challenge":False,"pre_status":r.status_code,"pre_len":len(txt)}
    m=re.search(r'const c="([^"]+)",d=(\d+)',txt)
    if not m:
        raise RuntimeError("challenge_parse_failed")
    c=m.group(1); d=int(m.group(2)); prefix="0"*d
    n=0
    while True:
        if hashlib.sha256((c+str(n)).encode()).hexdigest().startswith(prefix):
            break
        n+=1
    vr=S.post("https://stooq.com/__verify",data={"c":c,"n":str(n)},headers={**H,"Referer":r.url},timeout=30)
    return {"challenge":True,"nonce":n,"verify_status":vr.status_code,"cookies":S.cookies.get_dict()}

meta=solve()
r=S.get("https://stooq.com/q/d/l/",params={"s":"ae.us","d1":"20190901","d2":"20230105","i":"d"},headers=H,timeout=30)
meta["final_status"]=r.status_code;meta["final_len"]=len(r.content);meta["prefix"]=r.text[:300]
try:
    d=pd.read_csv(io.StringIO(r.text))
    meta["rows"]=len(d);meta["columns"]=list(d.columns)
    meta["date_min"]=str(d["Date"].min()) if "Date" in d.columns and len(d) else None
    meta["date_max"]=str(d["Date"].max()) if "Date" in d.columns and len(d) else None
except Exception as e:
    meta["parse_error"]=repr(e)
(OUT/"pow_probe.json").write_text(json.dumps(meta,indent=2),encoding="utf-8")
(OUT/"ae.csv").write_text(r.text,encoding="utf-8")
print(json.dumps(meta,indent=2))
