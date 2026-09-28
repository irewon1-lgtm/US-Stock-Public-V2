from __future__ import annotations
import base64, json, os, time, math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import requests

ROOT=Path(".")
INPUT=ROOT/"v3-fast/price_universe_resolved.csv.gz"
MASK=ROOT/"v4-liquidity-output/liquidity_bitmask.json"
OUT=ROOT/"v4-eulerpool-output"
OUT.mkdir(parents=True,exist_ok=True)

API="https://api.eulerpool.com/api/1/charting/ohlcv/{ticker}"
KEY=os.environ["EULERPOOL_API_KEY"].strip()
START="2019-09-01"
END="2023-01-05"
START_TS=int(pd.Timestamp(START,tz="UTC").timestamp())
END_TS=int(pd.Timestamp(END,tz="UTC").timestamp())
MAX_WORKERS=8
SLEEP_BETWEEN=0.08

def decode_mask(s,n):
    b=np.frombuffer(base64.b64decode(s),dtype=np.uint8)
    a=np.unpackbits(b,bitorder="little")[:n]
    return a.astype(bool)

def norm_ticker(s):
    return str(s or "").strip().upper()

def fetch_one(ticker):
    url=API.format(ticker=ticker)
    params={"from":START_TS,"to":END_TS,"interval":"1d"}
    headers={
        "Authorization":f"Bearer {KEY}",
        "Accept":"application/json",
        "User-Agent":"V4-outcome-free-Eulerpool-recovery/1.0",
    }
    last=""
    quota={}
    for attempt in range(4):
        try:
            r=requests.get(url,params=params,headers=headers,timeout=35)
            for k,v in r.headers.items():
                if any(x in k.lower() for x in ["rate","limit","remaining","quota","retry"]):
                    quota[k]=v
            if r.status_code==404:
                return pd.DataFrame(),"NO_DATA","HTTP_404_SECURITY_NOT_FOUND",quota
            if r.status_code==429:
                retry=float(r.headers.get("Retry-After") or 2)
                if attempt<3:
                    time.sleep(min(30,max(1,retry)))
                    continue
                return pd.DataFrame(),"RATE_LIMIT","HTTP_429",quota
            if r.status_code in {500,502,503,504}:
                if attempt<3:
                    time.sleep(min(20,1.5*(2**attempt)))
                    continue
            r.raise_for_status()
            p=r.json()
            if not isinstance(p,dict) or not isinstance(p.get("t"),list):
                return pd.DataFrame(),"BAD_RESPONSE","missing_t_array",quota
            ts=p.get("t") or []
            c=p.get("c") or []
            v=p.get("v") or []
            n=len(ts)
            if n==0:
                return pd.DataFrame(),"NO_DATA","EMPTY_SERIES",quota
            if len(c)!=n or len(v)!=n:
                return pd.DataFrame(),"BAD_RESPONSE",f"length_mismatch t={n} c={len(c)} v={len(v)}",quota
            d=pd.DataFrame({
                "date":[pd.to_datetime(int(x),unit="s",utc=True).tz_localize(None).normalize() for x in ts],
                "close":pd.to_numeric(pd.Series(c),errors="coerce"),
                "volume":pd.to_numeric(pd.Series(v),errors="coerce"),
            })
            d=d.dropna(subset=["date"]).sort_values("date").drop_duplicates("date",keep="last").set_index("date")
            return d,"OK","",quota
        except Exception as e:
            last=repr(e)[:300]
            if attempt<3:
                time.sleep(min(20,1.5*(2**attempt)))
    return pd.DataFrame(),"ERROR",last,quota

def features(d,snapshot):
    s=pd.Timestamp(snapshot).normalize()
    if d.empty or s not in d.index:
        return {"liquidity_status":"SNAPSHOT_PRICE_MISSING"}
    loc=d.index.get_loc(s)
    if not isinstance(loc,(int,np.integer)):
        return {"liquidity_status":"DUPLICATE_DATE"}
    raw=d.iloc[loc]["close"]
    out={"raw_close_v4":raw}
    hist=d.iloc[max(0,loc-59):loc+1].copy()
    if len(hist)<60:
        return out|{"liquidity_status":"INSUFFICIENT_60_SESSIONS","sessions_available":len(hist)}
    ok=hist["close"].gt(0)&hist["volume"].ge(0)&hist["close"].notna()&hist["volume"].notna()
    if not bool(ok.all()):
        return out|{"liquidity_status":"PRICE_VOLUME_GAP","sessions_available":len(hist),"valid_sessions":int(ok.sum())}
    dv=hist["close"]*hist["volume"]
    return out|{
        "liquidity_status":"OK",
        "sessions_available":60,
        "valid_sessions":60,
        "median_dollar_volume_60d":float(dv.median()),
        "median_raw_close_60d":float(hist["close"].median()),
    }

u=pd.read_csv(INPUT,dtype=str,keep_default_na=False,compression="gzip")
u["_row_id"]=np.arange(len(u))
if len(u)!=42014:
    raise RuntimeError(f"unexpected input rows {len(u)}")
years=pd.to_datetime(u["snapshot_date"],errors="coerce").dt.year
if years.ge(2023).any():
    raise RuntimeError("REFUSED 2023+ formation snapshot")

m=json.loads(MASK.read_text(encoding="utf-8"))
unknown=decode_mask(m["unknown_b64"],len(u))
u_unknown=u.loc[unknown].copy()

# Preserve ticker-reuse ambiguity: never repair current-ticker collisions blindly.
reuse=u.copy()
reuse["cik_norm"]=pd.to_numeric(reuse["cik"],errors="coerce")
amb=set(reuse.groupby("ticker_at_snapshot")["cik_norm"].nunique(dropna=True).loc[lambda x:x>1].index)
u_unknown["ticker_norm"]=u_unknown["ticker_at_snapshot"].map(norm_ticker)
query_tickers=sorted(t for t in u_unknown["ticker_norm"].unique() if t and t not in amb)

print(json.dumps({
    "unknown_rows":int(unknown.sum()),
    "unknown_unique_tickers":int(u_unknown["ticker_norm"].nunique()),
    "ambiguous_ticker_reuse_count":len(amb),
    "query_tickers":len(query_tickers),
},indent=2),flush=True)

cache={}
audit=[]
def task(t):
    time.sleep(SLEEP_BETWEEN)
    return t,fetch_one(t)

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
    futs=[ex.submit(task,t) for t in query_tickers]
    for i,f in enumerate(as_completed(futs),1):
        t,(d,status,err,quota)=f.result()
        cache[t]=d
        audit.append({
            "ticker":t,
            "fetch_status":status,
            "rows":0 if d.empty else len(d),
            "error":err,
            "rate_limit":quota.get("x-ratelimit-limit",""),
            "rate_remaining":quota.get("x-ratelimit-remaining",""),
            "rate_window":quota.get("x-ratelimit-window",""),
        })
        if i%100==0:
            print("FETCH",i,"/",len(query_tickers),flush=True)

rows=[]
for j,(_,r) in enumerate(u_unknown.iterrows(),1):
    rid=int(r["_row_id"]); t=r["ticker_norm"]
    if t in amb:
        feat={"liquidity_status":"TICKER_REUSE_MULTIPLE_CIK"}
    else:
        feat=features(cache.get(t,pd.DataFrame()),r["snapshot_date"])
    rows.append({
        "_row_id":rid,
        "snapshot_date":r["snapshot_date"],
        "ticker_at_snapshot":r["ticker_at_snapshot"],
        "source":"EULERPOOL_SUPPLEMENT",
        **feat
    })
    if j%5000==0:
        print("FEATURE",j,"/",len(u_unknown),flush=True)

rec=pd.DataFrame(rows).sort_values("_row_id")
rec.to_csv(OUT/"eulerpool_unknown_recovery.csv.gz",index=False,compression="gzip")
pd.DataFrame(audit).sort_values("ticker").to_csv(OUT/"eulerpool_fetch_audit.csv",index=False)

# Build revised masks: only replace rows that were previously UNKNOWN and are now known.
status=rec["liquidity_status"].astype(str)
rid=pd.to_numeric(rec["_row_id"],errors="raise").astype(int).to_numpy()
price=pd.to_numeric(rec.get("raw_close_v4"),errors="coerce")
mdv=pd.to_numeric(rec.get("median_dollar_volume_60d"),errors="coerce")
new_known=status.eq("OK").to_numpy()
new_pass=(status.eq("OK") & price.ge(5) & mdv.ge(5_000_000)).to_numpy()
new_price_fail=(status.eq("OK") & price.lt(5)).to_numpy()
new_liq_fail=(status.eq("OK") & price.ge(5) & mdv.lt(5_000_000)).to_numpy()

old_pass=decode_mask(m["pass_price_liquidity_b64"],len(u))
old_unknown=decode_mask(m["unknown_b64"],len(u))
old_price_fail=decode_mask(m["price_fail_b64"],len(u))
old_liq_fail=decode_mask(m["liquidity_fail_b64"],len(u))

pass_mask=old_pass.copy()
unk_mask=old_unknown.copy()
pf_mask=old_price_fail.copy()
lf_mask=old_liq_fail.copy()

pass_mask[rid[new_pass]]=True
pf_mask[rid[new_price_fail]]=True
lf_mask[rid[new_liq_fail]]=True
unk_mask[rid[new_known]]=False

def enc(a):
    return base64.b64encode(np.packbits(np.asarray(a,dtype=np.uint8),bitorder="little").tobytes()).decode()

by=[]
for snap,g in u.groupby("snapshot_date",sort=True):
    rr=g["_row_id"].astype(int).to_numpy()
    by.append({
        "snapshot_date":snap,
        "rows":len(rr),
        "pass_price_liquidity":int(pass_mask[rr].sum()),
        "unknown":int(unk_mask[rr].sum()),
        "price_fail":int(pf_mask[rr].sum()),
        "liquidity_fail":int(lf_mask[rr].sum()),
    })

summary={
    "schema":"V4_LIQUIDITY_BITMASK_EULERPOOL_SUPPLEMENT_V1",
    "purpose":"Outcome-free eligibility recovery only.",
    "row_count":len(u),
    "source_precedence":"Original Yahoo known results preserved; Eulerpool only fills previously UNKNOWN rows.",
    "ticker_reuse":"Multiple-CIK ticker strings remain UNKNOWN.",
    "thresholds":{"raw_price_min":5.0,"median_dollar_volume_60d_min":5000000},
    "period":{"start":START,"end":END},
    "api_quota":{"requests_planned":len(query_tickers),"monthly_limit_observed":100000},
    "old_unknown_rows":int(old_unknown.sum()),
    "recovered_known_rows":int(new_known.sum()),
    "remaining_unknown_rows":int(unk_mask.sum()),
    "recovered_pass_rows":int(new_pass.sum()),
    "recovered_price_fail_rows":int(new_price_fail.sum()),
    "recovered_liquidity_fail_rows":int(new_liq_fail.sum()),
    "pass_price_liquidity_b64":enc(pass_mask),
    "unknown_b64":enc(unk_mask),
    "price_fail_b64":enc(pf_mask),
    "liquidity_fail_b64":enc(lf_mask),
    "by_snapshot":by,
}
(OUT/"liquidity_bitmask_eulerpool_supplement.json").write_text(json.dumps(summary,separators=(",",":")),encoding="utf-8")
(OUT/"liquidity_recovery_summary.json").write_text(json.dumps({k:v for k,v in summary.items() if not k.endswith("_b64")},indent=2),encoding="utf-8")
print(json.dumps({k:v for k,v in summary.items() if k in ["old_unknown_rows","recovered_known_rows","remaining_unknown_rows","recovered_pass_rows","by_snapshot"]},indent=2),flush=True)
