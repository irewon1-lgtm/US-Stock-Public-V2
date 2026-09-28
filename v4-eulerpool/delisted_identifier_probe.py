from __future__ import annotations
import json,os,requests,time
from pathlib import Path
KEY=os.environ["EULERPOOL_API_KEY"].strip()
BASE="https://api.eulerpool.com/api/1"
H={"Authorization":f"Bearer {KEY}","Accept":"application/json","User-Agent":"V4-delisted-identifier-probe/1.0"}
T=["ABMD","STMP","AAWW"]
FROM=1569888000; TO=1672531200
out=[]
for t in T:
    row={"ticker":t}
    for path,params,key in [
        (f"/equity/market-cap/{t}",{"range":"5y"},"mcap"),
        (f"/equity/shares-outstanding/{t}",None,"shares")]:
        try:
            r=requests.get(BASE+path,params=params,headers=H,timeout=45)
            row[key+"_status"]=r.status_code
            if r.ok:
                p=r.json()
                if isinstance(p,dict):
                    row[key+"_keys"]=sorted(p.keys())
                    if p.get("isin"): row["isin"]=p.get("isin")
                    if isinstance(p.get("data"),list): row[key+"_data_count"]=len(p["data"])
                elif isinstance(p,list): row[key+"_count"]=len(p)
        except Exception as e: row[key+"_error"]=repr(e)[:300]
    ids=[t]
    if row.get("isin"): ids.append(row["isin"])
    tests=[]
    for ident in ids:
        try:
            r=requests.get(BASE+f"/charting/ohlcv/{ident}",params={"from":FROM,"to":TO,"interval":"1d"},headers=H,timeout=45)
            z={"identifier":ident,"status":r.status_code}
            if r.ok:
                p=r.json()
                z["rows"]=len(p.get("t") or []) if isinstance(p,dict) else None
                if isinstance(p,dict) and p.get("t"):
                    z["first_t"]=p["t"][0]; z["last_t"]=p["t"][-1]; z["volume_nonnull"]=sum(x is not None for x in (p.get("v") or []))
            else:z["body"]=r.text[:400]
            tests.append(z)
        except Exception as e: tests.append({"identifier":ident,"error":repr(e)[:300]})
    row["ohlcv_tests"]=tests
    out.append(row); time.sleep(.2)
Path("v4-eulerpool-output").mkdir(exist_ok=True)
Path("v4-eulerpool-output/delisted_identifier_probe.json").write_text(json.dumps({"schema":"V4_DELISTED_IDENTIFIER_PROBE_V1","results":out},indent=2),encoding="utf-8")
print(json.dumps(out))
