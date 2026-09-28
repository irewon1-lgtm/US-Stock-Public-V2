from __future__ import annotations
import base64,json,os,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import numpy as np,pandas as pd,requests

ROOT=Path(".")
REC=ROOT/"v4-eulerpool-output/eulerpool_unknown_recovery.csv.gz"
OLDMASK=ROOT/"v4-liquidity-output/liquidity_bitmask.json"
OUT=ROOT/"v4-eulerpool-output"; OUT.mkdir(parents=True,exist_ok=True)
KEY=os.environ["EULERPOOL_API_KEY"].strip()
API="https://api.eulerpool.com/api/1/equity/splits/{ticker}"
N=42014

def dec(s):
    a=np.unpackbits(np.frombuffer(base64.b64decode(s),dtype=np.uint8),bitorder="little")[:N]
    return a.astype(bool)
def enc(a):
    return base64.b64encode(np.packbits(np.asarray(a,dtype=np.uint8),bitorder="little").tobytes()).decode()

def fetch_splits(ticker):
    url=API.format(ticker=ticker)
    h={"Authorization":f"Bearer {KEY}","Accept":"application/json","User-Agent":"V4-split-correction/1.0"}
    last=""; quota={}
    for attempt in range(4):
        try:
            r=requests.get(url,headers=h,timeout=30)
            for k,v in r.headers.items():
                if any(x in k.lower() for x in ["rate","limit","remaining","quota","retry"]): quota[k]=v
            if r.status_code==404:
                return None,"NOT_FOUND","HTTP_404",quota
            if r.status_code==429:
                if attempt<3:
                    time.sleep(min(30,max(1,float(r.headers.get("Retry-After") or 2)))); continue
                return None,"RATE_LIMIT","HTTP_429",quota
            r.raise_for_status()
            p=r.json()
            if not isinstance(p,list): return None,"BAD_RESPONSE","not_list",quota
            clean=[]
            for x in p:
                try:
                    d=str(x.get("date") or "")
                    fr=float(x.get("fromFactor")); to=float(x.get("toFactor"))
                    if d and fr>0 and to>0: clean.append((d,to/fr))
                except Exception: pass
            return sorted(clean),"OK","",quota
        except Exception as e:
            last=repr(e)[:300]
            if attempt<3: time.sleep(min(20,1.5*(2**attempt)))
    return None,"ERROR",last,quota

d=pd.read_csv(REC,compression="gzip")
d["_row_id"]=pd.to_numeric(d["_row_id"],errors="raise").astype(int)
d["raw_close_v4"]=pd.to_numeric(d.get("raw_close_v4"),errors="coerce")
d["median_dollar_volume_60d"]=pd.to_numeric(d.get("median_dollar_volume_60d"),errors="coerce")
ok=d["liquidity_status"].astype(str).eq("OK")
tickers=sorted(d.loc[ok,"ticker_at_snapshot"].astype(str).str.upper().str.strip().unique())

splits={}; audit=[]
with ThreadPoolExecutor(max_workers=8) as ex:
    futs={ex.submit(fetch_splits,t):t for t in tickers}
    for i,f in enumerate(as_completed(futs),1):
        t=futs[f]; sp,status,err,q=f.result()
        splits[t]=sp
        audit.append({"ticker":t,"status":status,"events":None if sp is None else len(sp),"error":err,
                      "rate_limit":q.get("x-ratelimit-limit",""),"rate_remaining":q.get("x-ratelimit-remaining",""),"rate_window":q.get("x-ratelimit-window","")})
        if i%100==0: print("SPLITS",i,"/",len(tickers),flush=True)

corr=[]
for _,r in d.loc[ok].iterrows():
    t=str(r["ticker_at_snapshot"]).upper().strip(); sp=splits.get(t)
    snap=str(r["snapshot_date"])
    if sp is None:
        corr.append({"_row_id":int(r["_row_id"]),"snapshot_date":snap,"ticker_at_snapshot":t,
                     "split_status":"UNRESOLVED","adjusted_close":r["raw_close_v4"],"future_split_cum_ratio":np.nan,
                     "as_traded_close":np.nan,"median_dollar_volume_60d":r["median_dollar_volume_60d"],"corrected_status":"UNKNOWN_SPLIT_HISTORY"})
        continue
    ratio=1.0
    for dt,rr in sp:
        if dt>snap: ratio*=rr
    px=float(r["raw_close_v4"])*ratio if pd.notna(r["raw_close_v4"]) else np.nan
    mdv=float(r["median_dollar_volume_60d"]) if pd.notna(r["median_dollar_volume_60d"]) else np.nan
    if not np.isfinite(px) or not np.isfinite(mdv):
        st="UNKNOWN_NUMERIC"
    elif px<5:
        st="PRICE_FAIL"
    elif mdv<5_000_000:
        st="LIQUIDITY_FAIL"
    else:
        st="PASS"
    corr.append({"_row_id":int(r["_row_id"]),"snapshot_date":snap,"ticker_at_snapshot":t,
                 "split_status":"OK","adjusted_close":r["raw_close_v4"],"future_split_cum_ratio":ratio,
                 "as_traded_close":px,"median_dollar_volume_60d":mdv,"corrected_status":st})

c=pd.DataFrame(corr).sort_values("_row_id")
c.to_csv(OUT/"eulerpool_split_corrected_recovery.csv.gz",index=False,compression="gzip")
pd.DataFrame(audit).sort_values("ticker").to_csv(OUT/"eulerpool_split_audit.csv",index=False)

m=json.loads(OLDMASK.read_text())
passm=dec(m["pass_price_liquidity_b64"]); unkm=dec(m["unknown_b64"]); pfm=dec(m["price_fail_b64"]); lfm=dec(m["liquidity_fail_b64"])

# Only replace original UNKNOWN rows when split history is resolved.
for st,col in [("PASS",passm),("PRICE_FAIL",pfm),("LIQUIDITY_FAIL",lfm)]:
    ids=c.loc[c["corrected_status"].eq(st),"_row_id"].astype(int).to_numpy()
    col[ids]=True
resolved_ids=c.loc[c["corrected_status"].isin(["PASS","PRICE_FAIL","LIQUIDITY_FAIL"]),"_row_id"].astype(int).to_numpy()
unkm[resolved_ids]=False

# Any rows with unresolved split history remain UNKNOWN; do not classify them.
by=[]
base=pd.read_csv(ROOT/"v3-fast/price_universe_resolved.csv.gz",dtype=str,keep_default_na=False,compression="gzip")
base["_row_id"]=np.arange(len(base))
for snap,g in base.groupby("snapshot_date",sort=True):
    ids=g["_row_id"].astype(int).to_numpy()
    by.append({"snapshot_date":snap,"rows":len(ids),"pass_price_liquidity":int(passm[ids].sum()),"unknown":int(unkm[ids].sum()),"price_fail":int(pfm[ids].sum()),"liquidity_fail":int(lfm[ids].sum())})

summary={
 "schema":"V4_EULERPOOL_SPLIT_CORRECTED_MASK_V1",
 "purpose":"Outcome-free eligibility only.",
 "adjustment_rule":"Eulerpool OHLCV is split-adjusted. Reconstruct as-traded close by multiplying by product(toFactor/fromFactor) for split events strictly after snapshot date. Dollar volume is invariant under this price/volume split adjustment.",
 "recovered_ok_rows_input":int(ok.sum()),
 "split_history_resolved_rows":int(c["corrected_status"].isin(["PASS","PRICE_FAIL","LIQUIDITY_FAIL"]).sum()),
 "split_history_unresolved_rows":int(c["corrected_status"].str.startswith("UNKNOWN").sum()),
 "corrected_pass_rows":int(c["corrected_status"].eq("PASS").sum()),
 "corrected_price_fail_rows":int(c["corrected_status"].eq("PRICE_FAIL").sum()),
 "corrected_liquidity_fail_rows":int(c["corrected_status"].eq("LIQUIDITY_FAIL").sum()),
 "remaining_unknown_rows":int(unkm.sum()),
 "pass_price_liquidity_b64":enc(passm),"unknown_b64":enc(unkm),"price_fail_b64":enc(pfm),"liquidity_fail_b64":enc(lfm),
 "by_snapshot":by
}
(OUT/"liquidity_mask_split_corrected.json").write_text(json.dumps(summary,separators=(",",":")),encoding="utf-8")
(OUT/"split_correction_summary.json").write_text(json.dumps({k:v for k,v in summary.items() if not k.endswith("_b64")},indent=2),encoding="utf-8")
print(json.dumps({k:v for k,v in summary.items() if k in ["recovered_ok_rows_input","split_history_resolved_rows","split_history_unresolved_rows","corrected_pass_rows","corrected_price_fail_rows","corrected_liquidity_fail_rows","remaining_unknown_rows","by_snapshot"]},indent=2),flush=True)
