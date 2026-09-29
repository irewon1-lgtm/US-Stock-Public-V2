from __future__ import annotations
import json, duckdb, pandas as pd, numpy as np
from pathlib import Path

ROOT=Path(".")
T=json.loads((ROOT/"v4-finnhub-archive/mcap_price_r2_targets.json").read_text())
OUT=ROOT/"v4-finnhub-mcap-price-r2-output"; OUT.mkdir(exist_ok=True)
BASE="https://huggingface.co/datasets/mito0o852/OHLCV-1m/resolve/main/data/ohlcv_{m}.parquet?download=true"
VALID=["MSFT","JPM","XOM","HD","KO"]
MONTH_BY_SNAP={s:s[:7] for s in T["snapshots"]}

con=duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
all_targets=sorted(set(T["tickers"])|set(VALID))
lit=",".join("'" + x.replace("'","''") + "'" for x in all_targets)
parts=[]
for snap in T["snapshots"]:
    m=MONTH_BY_SNAP[snap]
    url=BASE.format(m=m)
    q=f"""SELECT ticker,timestamp,close
          FROM read_parquet('{url}')
          WHERE ticker IN ({lit})"""
    d=con.execute(q).fetchdf()
    if d.empty: continue
    d["timestamp"]=pd.to_datetime(d["timestamp"],utc=True)
    local=d["timestamp"].dt.tz_convert("America/New_York")
    d["date"]=local.dt.tz_localize(None).dt.normalize()
    d["mins_et"]=local.dt.hour*60+local.dt.minute
    s=pd.Timestamp(snap)
    d=d[(d["date"].eq(s))&(d["mins_et"]>=570)&(d["mins_et"]<960)].copy()
    if d.empty: continue
    d=d.sort_values(["ticker","timestamp"])
    z=d.groupby("ticker",as_index=False).agg(snapshot_close=("close","last"))
    z["snapshot_date"]=snap
    parts.append(z)
res=pd.concat(parts,ignore_index=True) if parts else pd.DataFrame(columns=["ticker","snapshot_close","snapshot_date"])

# Multi-snapshot validation on no-split known tickers.
y=pd.read_csv("v4-liquidity-output/liquidity_panel.csv.gz",compression="gzip",low_memory=False)
vy=y[y.ticker_at_snapshot.astype(str).isin(VALID) & y.snapshot_date.astype(str).isin(T["snapshots"])].copy()
v=vy.merge(res,left_on=["ticker_at_snapshot","snapshot_date"],right_on=["ticker","snapshot_date"],how="inner")
v["yahoo_close"]=pd.to_numeric(v["raw_close_v4"],errors="coerce")
v["finnhub_close"]=pd.to_numeric(v["snapshot_close"],errors="coerce")
v=v[v.yahoo_close.gt(0)&v.finnhub_close.gt(0)].copy()
v["close_rel_diff"]=(v.finnhub_close-v.yahoo_close).abs()/np.maximum(v.finnhub_close.abs(),v.yahoo_close.abs())
if len(v)<40: raise RuntimeError(f"VALIDATION_TOO_SMALL {len(v)}")
p95=float(v.close_rel_diff.quantile(.95)); med=float(v.close_rel_diff.median()); maxdiff=float(v.close_rel_diff.max()); vmax=float(v.close_rel_diff.max())
if vmax>0.02: raise RuntimeError(f"PRICE_VALIDATION_FAIL_MAX max={vmax}")
v[["ticker_at_snapshot","snapshot_date","yahoo_close","finnhub_close","close_rel_diff"]].to_csv(OUT/"price_validation.csv",index=False)

o=res[res.ticker.isin(T["tickers"])].copy()
px=pd.to_numeric(o.snapshot_close,errors="coerce")
# Guarantee original Yahoo-like raw price is still < $5 even under worst observed validation error.
fail_cutoff=5.0*(1.0-vmax)
pass_cutoff=5.0/(1.0-vmax)
o["price_gate_finnhub"]=np.where(px.lt(fail_cutoff),"FAIL",np.where(px.ge(pass_cutoff),"PASS","UNKNOWN_NEAR_5"))
o["validation_fail_cutoff"]=fail_cutoff
o["validation_pass_cutoff"]=pass_cutoff
o.to_csv(OUT/"snapshot_prices.csv.gz",index=False,compression="gzip")
summary={
 "schema":"V4_FINNHUB_MCAP_PRICE_R2_V1",
 "target_tickers":len(T["tickers"]),
 "target_snapshots":len(T["snapshots"]),
 "resolved_ticker_snapshot_rows":int(len(o)),
 "resolved_tickers":int(o.ticker.nunique()) if len(o) else 0,
 "price_fail_rows":int(o.price_gate_finnhub.eq("FAIL").sum()) if len(o) else 0,
 "price_pass_rows":int(o.price_gate_finnhub.eq("PASS").sum()) if len(o) else 0,
 "validation_rows":int(len(v)),"validation_close_rel_diff_median":med,"validation_close_rel_diff_p95":p95,"validation_close_rel_diff_max":maxdiff,
 "validation_close_rel_diff_max":vmax,
 "guaranteed_price_fail_cutoff":float(5.0*(1.0-vmax)),
 "guaranteed_price_pass_cutoff":float(5.0/(1.0-vmax)),
 "liquidity_inferred":False,
 "formation_2023_opened":False,"future_outcomes_used":False,"us3700_used":False,
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(json.dumps(summary,indent=2))
