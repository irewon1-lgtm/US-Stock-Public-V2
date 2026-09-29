from __future__ import annotations
import io, json, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import numpy as np, pandas as pd, requests

ROOT=Path(".")
UNIVERSE=ROOT/"v3-fast/price_universe_resolved.csv.gz"
AUDIT=ROOT/"v4-eulerpool-output/eulerpool_fetch_audit.csv"
OUT=ROOT/"v4-hf-yahoo-recovery-output"; OUT.mkdir(exist_ok=True)

u=pd.read_csv(UNIVERSE,dtype=str,keep_default_na=False,compression="gzip",low_memory=False)
u["_row_id"]=np.arange(len(u))
years=pd.to_datetime(u["snapshot_date"],errors="coerce").dt.year
if years.ge(2023).any():
    raise RuntimeError("REFUSED: 2023+ formation present")
u["ticker_norm"]=u["ticker_at_snapshot"].astype(str).str.upper().str.strip()
u["cik_num"]=pd.to_numeric(u["cik"],errors="coerce")
amb=set(u.groupby("ticker_norm")["cik_num"].nunique(dropna=True).loc[lambda s:s>1].index)

a=pd.read_csv(AUDIT,dtype=str,keep_default_na=False)
a["ticker_norm"]=a["ticker"].astype(str).str.upper().str.strip()
targets=sorted(set(a.loc[a["fetch_status"].eq("NO_DATA"),"ticker_norm"]) - amb)
print("TARGET_TICKERS",len(targets),"AMBIGUOUS_SKIPPED",len(set(a.loc[a["fetch_status"].eq("NO_DATA"),"ticker_norm"]) & amb),flush=True)

S=requests.Session(); S.headers.update({"User-Agent":"V4-HF-Yahoo-recovery/1.0"})
def fetch(t):
    url=f"https://huggingface.co/datasets/AmirTrader/YahooFinance/resolve/main/data/daily/{t}.parquet?download=true"
    last=""
    for i in range(4):
        try:
            r=S.get(url,timeout=60)
            if r.status_code==404:
                return pd.DataFrame(),"NO_FILE","HTTP_404"
            if r.status_code in {429,500,502,503,504}:
                raise RuntimeError(f"HTTP_{r.status_code}")
            r.raise_for_status()
            d=pd.read_parquet(io.BytesIO(r.content))
            cols={str(c).lower():c for c in d.columns}
            need={"date","close","volume"}
            if not need.issubset(cols):
                return pd.DataFrame(),"BAD_SCHEMA","MISSING_"+",".join(sorted(need-set(cols)))
            x=d[[cols["date"],cols["close"],cols["volume"]]].copy()
            x.columns=["date","close","volume"]
            x["date"]=pd.to_datetime(x["date"],errors="coerce").dt.tz_localize(None).dt.normalize()
            x["close"]=pd.to_numeric(x["close"],errors="coerce")
            x["volume"]=pd.to_numeric(x["volume"],errors="coerce")
            x=x.dropna(subset=["date"]).sort_values("date").drop_duplicates("date",keep="last").set_index("date")
            return x,"OK",""
        except Exception as e:
            last=repr(e)[:300]
            if i<3: time.sleep(min(10,1.5*(2**i)))
    return pd.DataFrame(),"ERROR",last

def features(d,snapshot):
    s=pd.Timestamp(snapshot).normalize()
    if d.empty or s not in d.index:
        return {"liquidity_status_hf":"SNAPSHOT_PRICE_MISSING"}
    loc=d.index.get_loc(s)
    if not isinstance(loc,(int,np.integer)):
        return {"liquidity_status_hf":"DUPLICATE_DATE"}
    raw=float(d.iloc[loc]["close"]) if pd.notna(d.iloc[loc]["close"]) else np.nan
    out={"raw_close_hf_yahoo":raw}
    hist=d.iloc[max(0,loc-59):loc+1].copy()
    if len(hist)<60:
        return out|{"liquidity_status_hf":"INSUFFICIENT_60_SESSIONS","sessions_available_hf":len(hist)}
    ok=hist["close"].gt(0)&hist["volume"].ge(0)&hist["close"].notna()&hist["volume"].notna()
    if not ok.all():
        return out|{"liquidity_status_hf":"PRICE_VOLUME_GAP","sessions_available_hf":len(hist),"valid_sessions_hf":int(ok.sum())}
    dv=hist["close"]*hist["volume"]
    return out|{"liquidity_status_hf":"OK","sessions_available_hf":60,"valid_sessions_hf":60,
                "median_dollar_volume_60d_hf":float(dv.median()),"median_close_60d_hf":float(hist["close"].median())}

rows=[]; audits=[]
def one(t):
    d,status,err=fetch(t)
    g=u[u["ticker_norm"].eq(t)]
    rr=[]
    for _,r in g.iterrows():
        rr.append({"_row_id":int(r["_row_id"]),"snapshot_date":r["snapshot_date"],"ticker_at_snapshot":t,"cik":r["cik"]}|features(d,r["snapshot_date"]))
    aa={"ticker":t,"fetch_status":status,"rows":0 if d.empty else len(d),"min_date":"" if d.empty else str(d.index.min().date()),"max_date":"" if d.empty else str(d.index.max().date()),"error":err}
    return rr,aa

with ThreadPoolExecutor(max_workers=8) as ex:
    futs={ex.submit(one,t):t for t in targets}
    for i,f in enumerate(as_completed(futs),1):
        rr,aa=f.result(); rows.extend(rr); audits.append(aa)
        if i%100==0: print("PROGRESS",i,"/",len(targets),"row_features",len(rows),flush=True)

rd=pd.DataFrame(rows)
if len(rd):
    rd["price_gate_hf_yahoo"]=np.where(pd.to_numeric(rd.get("raw_close_hf_yahoo"),errors="coerce").ge(5),"PASS",
        np.where(pd.to_numeric(rd.get("raw_close_hf_yahoo"),errors="coerce").notna(),"FAIL","UNKNOWN"))
    rd["liquidity_gate_hf_yahoo"]=np.where(
        rd.get("liquidity_status_hf","").astype(str).eq("OK"),
        np.where(pd.to_numeric(rd.get("median_dollar_volume_60d_hf"),errors="coerce").ge(5_000_000),"PASS","FAIL"),
        np.where(rd.get("liquidity_status_hf","").astype(str).eq("INSUFFICIENT_60_SESSIONS"),"FAIL","UNKNOWN")
    )
rd.to_csv(OUT/"hf_yahoo_recovery_rows.csv.gz",index=False,compression="gzip")
ad=pd.DataFrame(audits).sort_values("ticker")
ad.to_csv(OUT/"hf_yahoo_fetch_audit.csv",index=False)
summary={
 "schema":"V4_HF_YAHOO_MIRROR_RECOVERY_V1",
 "purpose":"Outcome-free price/liquidity recovery only for tickers already NO_DATA in Eulerpool/Yahoo flow.",
 "mirror":"AmirTrader/YahooFinance on Hugging Face",
 "target_tickers":len(targets),
 "ambiguous_ticker_reuse_skipped":len(set(a.loc[a["fetch_status"].eq("NO_DATA"),"ticker_norm"]) & amb),
 "file_ok":int(ad["fetch_status"].eq("OK").sum()),
 "file_missing":int(ad["fetch_status"].eq("NO_FILE").sum()),
 "errors":int(ad["fetch_status"].eq("ERROR").sum()),
 "feature_rows":int(len(rd)),
 "price_known_rows":int(pd.to_numeric(rd.get("raw_close_hf_yahoo"),errors="coerce").notna().sum()) if len(rd) else 0,
 "liquidity_ok_rows":int(rd.get("liquidity_status_hf",pd.Series(dtype=str)).eq("OK").sum()) if len(rd) else 0,
 "formation_2023_opened":False,"future_outcomes_used":False,"us3700_used":False,
 "new_corp_action_lookup_calls":0,
 "note":"Mirror close/volume schema cross-checked against existing Yahoo rows (AAPL/AAL probe). Exact snapshot date required; no ticker remapping or corporate-action lookup performed."
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(json.dumps(summary,indent=2),flush=True)
