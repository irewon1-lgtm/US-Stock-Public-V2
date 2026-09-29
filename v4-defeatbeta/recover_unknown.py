from __future__ import annotations
import base64,json,math
from pathlib import Path
import numpy as np,pandas as pd,duckdb

ROOT=Path(".")
UNIVERSE=ROOT/"v3-fast/price_universe_resolved.csv.gz"
MASK=ROOT/"v4-eulerpool-output/liquidity_mask_split_corrected.json"
EP=ROOT/"v4-eulerpool-output/eulerpool_unknown_recovery.csv.gz"
YAHOO=ROOT/"v4-liquidity-output/liquidity_panel.csv.gz"
EXCL=ROOT/"v4-sec-cover/existing_corp_action_exclusions.json"
OUT=ROOT/"v4-defeatbeta-recovery-output";OUT.mkdir(parents=True,exist_ok=True)
URL="https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main/data/US/stock_prices.parquet?download=true"
START="2019-09-01";END="2023-01-05"
VALIDATION_TICKERS=["AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","JPM","XOM","HD"]

def dec(z,n):
    b=np.frombuffer(base64.b64decode(z),dtype=np.uint8)
    return np.unpackbits(b,bitorder="little")[:n].astype(bool)

def norm_ticker(s):
    return str(s or "").strip().upper().replace(".","-").replace("/","-")

def features(d,snapshot):
    s=pd.Timestamp(snapshot).normalize()
    if d.empty or s not in d.index:
        return {"liquidity_status":"SNAPSHOT_PRICE_MISSING"}
    loc=d.index.get_loc(s)
    if not isinstance(loc,(int,np.integer)):
        return {"liquidity_status":"DUPLICATE_DATE"}
    raw=float(d.iloc[loc]["close"]) if pd.notna(d.iloc[loc]["close"]) else np.nan
    out={"raw_close_v4":raw}
    hist=d.iloc[max(0,loc-59):loc+1].copy()
    if len(hist)<60:
        return out|{"liquidity_status":"INSUFFICIENT_60_SESSIONS","sessions_available":len(hist)}
    ok=hist["close"].gt(0)&hist["volume"].ge(0)&hist["close"].notna()&hist["volume"].notna()
    if not bool(ok.all()):
        return out|{"liquidity_status":"PRICE_VOLUME_GAP","sessions_available":len(hist),"valid_sessions":int(ok.sum())}
    dv=hist["close"]*hist["volume"]
    return out|{"liquidity_status":"OK","sessions_available":60,"valid_sessions":60,
                "median_dollar_volume_60d":float(dv.median()),"median_raw_close_60d":float(hist.close.median())}

u=pd.read_csv(UNIVERSE,dtype=str,keep_default_na=False,compression="gzip")
u["_row_id"]=np.arange(len(u))
assert len(u)==42014
years=pd.to_datetime(u.snapshot_date,errors="coerce").dt.year
if years.ge(2023).any(): raise RuntimeError("REFUSED 2023+ formation")

mask=json.loads(MASK.read_text())
unknown=dec(mask["unknown_b64"],len(u))

# Preserve the already locked 60-session failures from the existing Eulerpool recovery.
ep=pd.read_csv(EP,compression="gzip",low_memory=False)
locked=set(pd.to_numeric(ep.loc[ep.liquidity_status.astype(str).eq("INSUFFICIENT_60_SESSIONS"),"_row_id"],errors="coerce").dropna().astype(int))
idx=np.where(unknown)[0]
idx=np.array([i for i in idx if i not in locked],dtype=int)

reuse=u.copy()
reuse["cik_norm"]=pd.to_numeric(reuse.cik,errors="coerce")
amb=set(reuse.groupby("ticker_at_snapshot")["cik_norm"].nunique(dropna=True).loc[lambda x:x>1].index)
policy=json.loads(EXCL.read_text())
excluded=set(str(x).upper().strip() for x in policy.get("tickers",[]))

targets=u.loc[idx].copy()
targets["ticker_norm"]=targets.ticker_at_snapshot.map(norm_ticker)
query_tickers=sorted(t for t in targets.ticker_norm.unique() if t and t not in amb and t not in excluded)

con=duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")

# 1) Validate historical raw close / volume against frozen Yahoo-known rows.
all_val=VALIDATION_TICKERS
lit=",".join("'" + x.replace("'","''") + "'" for x in all_val)
q=f"""SELECT symbol,report_date,CAST(close AS DOUBLE) AS close,CAST(volume AS DOUBLE) AS volume
      FROM read_parquet('{URL}')
      WHERE symbol IN ({lit})
        AND CAST(report_date AS DATE) BETWEEN DATE '{START}' AND DATE '{END}'
      ORDER BY symbol,report_date"""
vd=con.execute(q).fetchdf()
vd["date"]=pd.to_datetime(vd.report_date,errors="coerce").dt.normalize()
cache_val={t:g.set_index("date")[["close","volume"]].sort_index() for t,g in vd.groupby("symbol")}

y=pd.read_csv(YAHOO,compression="gzip",low_memory=False)
y["ticker_norm"]=y.ticker_at_snapshot.astype(str).str.upper().str.strip().str.replace(".","-",regex=False).str.replace("/","-",regex=False)
checks=[]
for _,r in y[y.ticker_norm.isin(all_val) & y.liquidity_status.astype(str).eq("OK")].iterrows():
    t=r.ticker_norm
    feat=features(cache_val.get(t,pd.DataFrame()),r.snapshot_date)
    if feat.get("liquidity_status")!="OK": continue
    yp=pd.to_numeric(pd.Series([r.get("raw_close_v4")]),errors="coerce").iloc[0]
    yd=pd.to_numeric(pd.Series([r.get("median_dollar_volume_60d")]),errors="coerce").iloc[0]
    hp=feat.get("raw_close_v4"); hd=feat.get("median_dollar_volume_60d")
    if not all(np.isfinite(x) and x>0 for x in [yp,yd,hp,hd]): continue
    checks.append({"ticker":t,"snapshot_date":r.snapshot_date,
                   "yahoo_price":yp,"hf_price":hp,"price_rel_diff":abs(hp-yp)/max(abs(yp),abs(hp)),
                   "yahoo_mdv":yd,"hf_mdv":hd,"mdv_rel_diff":abs(hd-yd)/max(abs(yd),abs(hd))})
vc=pd.DataFrame(checks)
if vc.empty: raise RuntimeError("SOURCE_VALIDATION_EMPTY")
price_p95=float(vc.price_rel_diff.quantile(.95)); mdv_p95=float(vc.mdv_rel_diff.quantile(.95))
price_med=float(vc.price_rel_diff.median()); mdv_med=float(vc.mdv_rel_diff.median())
# Raw historical source must agree tightly enough not to alter the eligibility definition.
if price_p95>0.02 or mdv_p95>0.05:
    raise RuntimeError(f"SOURCE_VALIDATION_FAIL price_p95={price_p95} mdv_p95={mdv_p95}")
vc.to_csv(OUT/"source_validation.csv",index=False)

# 2) Query only currently unknown ticker strings in one predicate-pushed scan.
lit=",".join("'" + x.replace("'","''") + "'" for x in query_tickers)
q=f"""SELECT symbol,report_date,CAST(close AS DOUBLE) AS close,CAST(volume AS DOUBLE) AS volume
      FROM read_parquet('{URL}')
      WHERE symbol IN ({lit})
        AND CAST(report_date AS DATE) BETWEEN DATE '{START}' AND DATE '{END}'
      ORDER BY symbol,report_date"""
d=con.execute(q).fetchdf()
d["date"]=pd.to_datetime(d.report_date,errors="coerce").dt.normalize()
cache={t:g.set_index("date")[["close","volume"]].sort_index() for t,g in d.groupby("symbol")}

rows=[]
for _,r in targets.iterrows():
    t=r.ticker_norm
    if r.ticker_at_snapshot in amb:
        feat={"liquidity_status":"TICKER_REUSE_MULTIPLE_CIK"}
    elif t in excluded:
        feat={"liquidity_status":"EXISTING_CORP_ACTION_EXCLUDED"}
    else:
        feat=features(cache.get(t,pd.DataFrame()),r.snapshot_date)
    rows.append({"_row_id":int(r._row_id),"snapshot_date":r.snapshot_date,"ticker_at_snapshot":r.ticker_at_snapshot,
                 "source":"HF_DEFEATBETA_YAHOO_ARCHIVE",**feat})
rec=pd.DataFrame(rows).sort_values("_row_id")
rec.to_csv(OUT/"unknown_recovery.csv.gz",index=False,compression="gzip")

st=rec.liquidity_status.astype(str)
price=pd.to_numeric(rec.get("raw_close_v4"),errors="coerce")
mdv=pd.to_numeric(rec.get("median_dollar_volume_60d"),errors="coerce")
known=st.eq("OK")
passm=known & price.ge(5) & mdv.ge(5_000_000)
pf=known & price.lt(5)
lf=known & price.ge(5) & mdv.lt(5_000_000)
summary={
 "schema":"V4_DEFEATBETA_UNKNOWN_PRICE_RECOVERY_V1",
 "source":"public Hugging Face defeatbeta/yahoo-finance-data stock_prices.parquet",
 "target_unknown_rows":int(len(targets)),
 "query_tickers":int(len(query_tickers)),
 "source_tickers_found":int(d.symbol.nunique()) if len(d) else 0,
 "source_price_rows":int(len(d)),
 "validation_rows":int(len(vc)),
 "validation_price_rel_diff_median":price_med,
 "validation_price_rel_diff_p95":price_p95,
 "validation_mdv_rel_diff_median":mdv_med,
 "validation_mdv_rel_diff_p95":mdv_p95,
 "recovered_known_rows":int(known.sum()),
 "recovered_pass_rows":int(passm.sum()),
 "recovered_price_fail_rows":int(pf.sum()),
 "recovered_liquidity_fail_rows":int(lf.sum()),
 "remaining_unresolved_rows":int((~known).sum()),
 "formation_2023_opened":False,"future_outcomes_used":False,"us3700_used":False,
 "new_corp_action_lookup_calls":0,
 "existing_corp_action_exclusions":sorted(excluded),
 "ticker_reuse_policy":"ambiguous ticker reuse remains UNKNOWN",
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(json.dumps(summary,indent=2),flush=True)
