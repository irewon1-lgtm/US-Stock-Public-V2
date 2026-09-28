from __future__ import annotations
import argparse, json, math, os, time, urllib.request, urllib.error, urllib.parse
from pathlib import Path
import numpy as np
import pandas as pd

API_ROOT="https://api.eulerpool.com/api/1"
START="2019-09-01"
END="2023-01-05"
FROM=int(pd.Timestamp(START,tz="UTC").timestamp())
TO=int(pd.Timestamp(END,tz="UTC").timestamp())

def auth_headers():
    key=os.environ["EULERPOOL_API_KEY"].strip()
    if not key:
        raise RuntimeError("EULERPOOL_API_KEY missing")
    return {"Authorization":f"Bearer {key}","Accept":"application/json","User-Agent":"V4-outcome-free-recovery/1.0"}

def api_json(path, params=None, attempts=4):
    url=API_ROOT+path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    last=""
    for a in range(attempts):
        try:
            req=urllib.request.Request(url,headers=auth_headers())
            with urllib.request.urlopen(req,timeout=60) as r:
                raw=r.read()
                return int(r.status),json.loads(raw.decode("utf-8")),dict(r.headers)
        except urllib.error.HTTPError as e:
            body=e.read().decode("utf-8","replace")[:600]
            if e.code in (404,400):
                return int(e.code),{"_error":body},dict(e.headers)
            last=f"HTTP {e.code} {body}"
            ra=e.headers.get("Retry-After")
            if e.code==429:
                time.sleep(min(60,float(ra) if ra and str(ra).replace(".","",1).isdigit() else 8*(a+1)))
            else:
                time.sleep(min(15,2**a))
        except Exception as e:
            last=repr(e)[:600]
            if a<attempts-1: time.sleep(min(15,2**a))
    return None,{"_error":last},{}

def fetch_ohlcv(ticker):
    path="/charting/ohlcv/"+urllib.parse.quote(str(ticker),safe="")
    st,p,h=api_json(path,{"from":FROM,"to":TO,"interval":"1d"})
    if st!=200 or not isinstance(p,dict) or not isinstance(p.get("t"),list):
        return pd.DataFrame(),st,p.get("_error") if isinstance(p,dict) else "BAD_PAYLOAD",h
    t=p.get("t") or []; c=p.get("c") or []; v=p.get("v") or []
    n=min(len(t),len(c),len(v))
    if n==0: return pd.DataFrame(),st,"NO_ROWS",h
    d=pd.DataFrame({"date":[pd.to_datetime(int(x),unit="s",utc=True).tz_localize(None).normalize() for x in t[:n]],
                    "close_adj_like":pd.to_numeric(c[:n],errors="coerce"),
                    "volume_adj_like":pd.to_numeric(v[:n],errors="coerce")})
    d=d.dropna(subset=["date"]).sort_values("date").drop_duplicates("date",keep="last").set_index("date")
    return d,st,"",h

def fetch_splits(ticker):
    path="/equity/splits/"+urllib.parse.quote(str(ticker),safe="")
    st,p,h=api_json(path)
    if st!=200 or not isinstance(p,list):
        return [],st,p.get("_error") if isinstance(p,dict) else "BAD_PAYLOAD",h
    out=[]
    for x in p:
        try:
            dt=pd.Timestamp(str(x.get("date"))).normalize()
            f=float(x.get("fromFactor")); to=float(x.get("toFactor"))
            if f>0 and to>0 and math.isfinite(f) and math.isfinite(to):
                out.append((dt,to/f))
        except Exception:
            pass
    out.sort(key=lambda z:z[0])
    return out,st,"",h

def cumulative_future_split_ratio(splits,snapshot):
    s=pd.Timestamp(snapshot).normalize()
    m=1.0
    for dt,r in splits:
        if dt>s:
            m*=r
    return m

def features(d,splits,snapshot):
    s=pd.Timestamp(snapshot).normalize()
    if d.empty or s not in d.index:
        return {"ep_status":"SNAPSHOT_PRICE_MISSING"}
    loc=d.index.get_loc(s)
    if not isinstance(loc,(int,np.integer)):
        return {"ep_status":"DUPLICATE_DATE"}
    c=d.iloc[loc]["close_adj_like"]
    if pd.isna(c) or float(c)<=0:
        return {"ep_status":"SNAPSHOT_PRICE_MISSING"}
    mult=cumulative_future_split_ratio(splits,s)
    raw=float(c)*float(mult)
    hist=d.iloc[max(0,loc-59):loc+1].copy()
    out={"ep_raw_close_reconstructed":raw,"ep_future_split_ratio":mult}
    if len(hist)<60:
        return out|{"ep_status":"INSUFFICIENT_60_SESSIONS","ep_sessions_available":len(hist)}
    ok=hist["close_adj_like"].gt(0)&hist["volume_adj_like"].ge(0)&hist["close_adj_like"].notna()&hist["volume_adj_like"].notna()
    if not ok.all():
        return out|{"ep_status":"PRICE_VOLUME_GAP","ep_sessions_available":len(hist),"ep_valid_sessions":int(ok.sum())}
    # Eulerpool historical c/v are split-normalized inversely; c*v is invariant.
    dv=hist["close_adj_like"]*hist["volume_adj_like"]
    return out|{"ep_status":"OK","ep_sessions_available":60,"ep_valid_sessions":60,
                "ep_median_dollar_volume_60d":float(dv.median())}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--shard",type=int,required=True)
    ap.add_argument("--nshards",type=int,default=16)
    a=ap.parse_args()
    out=Path("v4-eulerpool-output/recovery"); out.mkdir(parents=True,exist_ok=True)
    u=pd.read_csv("v3-fast/price_universe_resolved.csv.gz",dtype=str,keep_default_na=False,compression="gzip")
    liq=pd.read_csv("v4-liquidity-output/liquidity_panel.csv.gz",dtype=str,keep_default_na=False,compression="gzip")
    if len(u)!=len(liq) or len(u)!=42014:
        raise RuntimeError(f"row count mismatch {len(u)} {len(liq)}")
    if pd.to_datetime(u["snapshot_date"],errors="coerce").dt.year.ge(2023).any():
        raise RuntimeError("REFUSED 2023+ formation snapshot")
    if "_row_id" not in liq:
        raise RuntimeError("liquidity panel missing _row_id")
    rid=pd.to_numeric(liq["_row_id"],errors="raise").astype(int)
    if rid.nunique()!=42014 or rid.min()!=0 or rid.max()!=42013:
        raise RuntimeError("row id integrity failure")
    base=u.copy(); base["_row_id"]=np.arange(len(base))
    lmini=liq[["_row_id","liquidity_status"]].copy()
    lmini["_row_id"]=pd.to_numeric(lmini["_row_id"],errors="raise").astype(int)
    base=base.merge(lmini,on="_row_id",how="left",validate="one_to_one")
    need=base[base["liquidity_status"].astype(str).ne("OK")].copy()
    # Preserve known ticker reuse as unresolved. Never substitute current issuer.
    ciknum=pd.to_numeric(base["cik"],errors="coerce")
    tmp=base.assign(_cik=ciknum)
    amb=set(tmp.groupby(base["ticker_at_snapshot"].astype(str).str.upper().str.strip())["_cik"].nunique(dropna=True).loc[lambda x:x>1].index)
    tickers=sorted(need["ticker_at_snapshot"].astype(str).str.upper().str.strip().unique())
    tickers=[t for i,t in enumerate(tickers) if i%a.nshards==a.shard]
    rows=[]; audit=[]
    last_remaining=None
    for i,t in enumerate(tickers,1):
        g=need[need["ticker_at_snapshot"].astype(str).str.upper().str.strip().eq(t)]
        if t in amb:
            for _,r in g.iterrows():
                rows.append({"_row_id":int(r["_row_id"]),"snapshot_date":r["snapshot_date"],"ticker_at_snapshot":t,"ep_status":"TICKER_REUSE_MULTIPLE_CIK"})
            audit.append({"ticker":t,"status":"AMBIGUOUS_TICKER_REUSE","ohlcv_rows":0})
            continue
        d,hs,he,hh=fetch_ohlcv(t)
        remaining=hh.get("x-ratelimit-remaining") or hh.get("X-RateLimit-Remaining")
        if remaining is not None:
            try: last_remaining=int(remaining)
            except: pass
        if d.empty:
            for _,r in g.iterrows():
                rows.append({"_row_id":int(r["_row_id"]),"snapshot_date":r["snapshot_date"],"ticker_at_snapshot":t,"ep_status":"NO_OHLCV"})
            audit.append({"ticker":t,"status":"NO_OHLCV","http_status":hs,"ohlcv_rows":0,"error":he})
            continue
        splits,ss,se,sh=fetch_splits(t)
        remaining=sh.get("x-ratelimit-remaining") or sh.get("X-RateLimit-Remaining")
        if remaining is not None:
            try: last_remaining=int(remaining)
            except: pass
        for _,r in g.iterrows():
            rows.append({"_row_id":int(r["_row_id"]),"snapshot_date":r["snapshot_date"],"ticker_at_snapshot":t}|features(d,splits,r["snapshot_date"]))
        audit.append({"ticker":t,"status":"OK","http_status":hs,"ohlcv_rows":len(d),"split_count":len(splits),"split_http_status":ss})
        if i%50==0:
            print(json.dumps({"shard":a.shard,"done":i,"total":len(tickers),"remaining":last_remaining}),flush=True)
        # Quota guard: 100k/month. Abort far before exhaustion.
        if last_remaining is not None and last_remaining<20000:
            raise RuntimeError(f"QUOTA_GUARD remaining={last_remaining}")
        time.sleep(.03)
    pd.DataFrame(rows).to_csv(out/f"rows_{a.shard}.csv.gz",index=False,compression="gzip")
    pd.DataFrame(audit).to_csv(out/f"audit_{a.shard}.csv",index=False)
    (out/f"meta_{a.shard}.json").write_text(json.dumps({"shard":a.shard,"nshards":a.nshards,"ticker_count":len(tickers),"last_quota_remaining":last_remaining},indent=2),encoding="utf-8")

if __name__=="__main__": main()
