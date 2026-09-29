import hashlib, re, requests, io, pandas as pd, json
from pathlib import Path

OUT=Path("v4-stooq-probe-output");OUT.mkdir(exist_ok=True)
BASE="https://stooq.com"
UA="Mozilla/5.0 V4 research"

def solve_challenge(session, text):
    m=re.search(r'const c="([^"]+)",d=(\d+)',text)
    if not m:
        return False,{}
    c=m.group(1); d=int(m.group(2)); target="0"*d
    n=0
    while True:
        h=hashlib.sha256((c+str(n)).encode()).hexdigest()
        if h.startswith(target): break
        n+=1
    r=session.post(BASE+"/__verify",data={"c":c,"n":str(n)},headers={"User-Agent":UA,"Referer":BASE+"/"},timeout=30)
    return r.ok,{"c":c,"d":d,"n":n,"verify_status":r.status_code,"cookies":session.cookies.get_dict()}

def fetch(t):
    s=requests.Session()
    params={"s":t.lower()+".us","d1":"20190901","d2":"20230105","i":"d"}
    r=s.get(BASE+"/q/d/l/",params=params,timeout=30,headers={"User-Agent":UA})
    challenge=None
    if "__verify" in r.text and "crypto.subtle.digest" in r.text:
        ok,challenge=solve_challenge(s,r.text)
        if ok:
            r=s.get(BASE+"/q/d/l/",params=params,timeout=30,headers={"User-Agent":UA})
    item={"ticker":t,"status":r.status_code,"bytes":len(r.content),"challenge":challenge,"prefix":r.text[:300]}
    try:
        d=pd.read_csv(io.StringIO(r.text))
        item["columns"]=list(d.columns);item["rows"]=len(d)
        if len(d):
            item["first"]=d.head(2).to_dict("records");item["last"]=d.tail(2).to_dict("records")
    except Exception as e:item["parse_error"]=repr(e)
    return item

rows=[fetch("AE"),fetch("MSFT")]
(OUT/"probe.json").write_text(json.dumps(rows,indent=2,default=str),encoding="utf-8")
print(json.dumps(rows,indent=2,default=str))
