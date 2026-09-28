from __future__ import annotations
import argparse,json,math,os,time,urllib.request,urllib.error,urllib.parse
from pathlib import Path
import numpy as np,pandas as pd
ROOT="https://api.eulerpool.com/api/1"
def headers():
    k=os.environ["EULERPOOL_API_KEY"].strip()
    if not k: raise RuntimeError("missing EULERPOOL_API_KEY")
    return {"Authorization":f"Bearer {k}","Accept":"application/json","User-Agent":"V4-split-factor-recovery/1.0"}
def fetch_splits(t,attempts=4):
    url=ROOT+"/equity/splits/"+urllib.parse.quote(t,safe="")
    last=""
    for a in range(attempts):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=headers()),timeout=45) as r:
                p=json.loads(r.read().decode("utf-8")); h=dict(r.headers)
                if not isinstance(p,list): return [],"BAD_PAYLOAD","",h
                out=[]
                for x in p:
                    try:
                        dt=pd.Timestamp(str(x.get("date"))).normalize()
                        f=float(x.get("fromFactor")); to=float(x.get("toFactor"))
                        if f>0 and to>0 and math.isfinite(f) and math.isfinite(to): out.append((dt,to/f))
                    except: pass
                return sorted(out,key=lambda z:z[0]),"OK","",h
        except urllib.error.HTTPError as e:
            body=e.read().decode("utf-8","replace")[:500]
            if e.code in (400,404): return [],f"HTTP_{e.code}",body,dict(e.headers)
            last=f"HTTP_{e.code}:{body}"; time.sleep(min(10,2**a))
        except Exception as e:
            last=repr(e)[:500]
            if a<attempts-1: time.sleep(min(10,2**a))
    return [],"ERROR",last,{}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--shard",type=int,required=True); ap.add_argument("--nshards",type=int,default=16); a=ap.parse_args()
    out=Path("v4-eulerpool-output/splits"); out.mkdir(parents=True,exist_ok=True)
    u=pd.read_csv("v3-fast/price_universe_resolved.csv.gz",dtype=str,keep_default_na=False,compression="gzip"); u["_row_id"]=np.arange(len(u))
    if len(u)!=42014 or pd.to_datetime(u.snapshot_date,errors="coerce").dt.year.ge(2023).any(): raise RuntimeError("input integrity/refused 2023+")
    tmp=u.copy(); tmp["_cik"]=pd.to_numeric(tmp["cik"],errors="coerce")
    amb=set(tmp.groupby(tmp.ticker_at_snapshot.astype(str).str.upper().str.strip())["_cik"].nunique(dropna=True).loc[lambda x:x>1].index)
    tickers=sorted(u.ticker_at_snapshot.astype(str).str.upper().str.strip().unique()); tickers=[t for i,t in enumerate(tickers) if i%a.nshards==a.shard]
    rows=[]; audit=[]; remaining=None
    for i,t in enumerate(tickers,1):
        g=u[u.ticker_at_snapshot.astype(str).str.upper().str.strip().eq(t)]
        if t in amb:
            for _,r in g.iterrows(): rows.append({"_row_id":int(r["_row_id"]),"split_status":"TICKER_REUSE_MULTIPLE_CIK","future_split_ratio":np.nan})
            audit.append({"ticker":t,"status":"AMBIGUOUS_TICKER_REUSE","split_count":0}); continue
        sp,st,err,h=fetch_splits(t)
        rem=h.get("x-ratelimit-remaining") or h.get("X-RateLimit-Remaining")
        if rem is not None:
            try: remaining=int(rem)
            except: pass
        # HTTP_404 means Eulerpool has no security identity: ratio is UNKNOWN, not 1.
        for _,r in g.iterrows():
            if st!="OK":
                rows.append({"_row_id":int(r["_row_id"]),"split_status":st,"future_split_ratio":np.nan})
                continue
            s=pd.Timestamp(r["snapshot_date"]).normalize(); m=1.0
            for dt,rat in sp:
                if dt>s: m*=rat
            rows.append({"_row_id":int(r["_row_id"]),"split_status":"OK","future_split_ratio":m})
        audit.append({"ticker":t,"status":st,"split_count":len(sp),"error":err})
        if i%50==0: print(json.dumps({"shard":a.shard,"done":i,"total":len(tickers),"remaining":remaining}),flush=True)
        if remaining is not None and remaining<15000: raise RuntimeError(f"QUOTA_GUARD {remaining}")
        time.sleep(.02)
    pd.DataFrame(rows).to_csv(out/f"rows_{a.shard}.csv.gz",index=False,compression="gzip")
    pd.DataFrame(audit).to_csv(out/f"audit_{a.shard}.csv",index=False)
    (out/f"meta_{a.shard}.json").write_text(json.dumps({"shard":a.shard,"ticker_count":len(tickers),"last_quota_remaining":remaining}),encoding="utf-8")
if __name__=="__main__": main()
