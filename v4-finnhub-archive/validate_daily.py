from __future__ import annotations
import json, duckdb, pandas as pd, numpy as np
from pathlib import Path

OUT=Path("v4-finnhub-archive-validation-output"); OUT.mkdir(exist_ok=True)
MONTHS=["2020-01","2020-02","2020-03"]
TICKERS=["MSFT","JPM","XOM","HD","KO"]
BASE="https://huggingface.co/datasets/mito0o852/OHLCV-1m/resolve/main/data/ohlcv_{m}.parquet?download=true"

con=duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
parts=[]
lit=",".join("'" + t + "'" for t in TICKERS)
for m in MONTHS:
    url=BASE.format(m=m)
    q=f"""SELECT ticker,timestamp,close,volume
          FROM read_parquet('{url}')
          WHERE ticker IN ({lit})
          ORDER BY ticker,timestamp"""
    d=con.execute(q).fetchdf()
    if len(d): parts.append(d)
if not parts: raise RuntimeError("NO_FINNHUB_ROWS")
d=pd.concat(parts,ignore_index=True)
d["timestamp"]=pd.to_datetime(d["timestamp"],utc=True)
local=d["timestamp"].dt.tz_convert("America/New_York")
mins=local.dt.hour*60+local.dt.minute
d=d[(mins>=570)&(mins<=960)].copy()  # include 16:00 ET closing-auction bar
d["date"]=local[d.index].dt.tz_localize(None).dt.normalize()
d=d.sort_values(["ticker","timestamp"])
daily=d.groupby(["ticker","date"],as_index=False).agg(close=("close","last"),volume=("volume","sum"))
daily["dollar_volume"]=daily["close"]*daily["volume"]

# Frozen Yahoo-known eligibility inputs.
y=pd.read_csv("v4-liquidity-output/liquidity_panel.csv.gz",compression="gzip",low_memory=False)
ys=y[(y["snapshot_date"].astype(str)=="2020-03-31") & y["ticker_at_snapshot"].astype(str).isin(TICKERS)].copy()
rows=[]
for _,r in ys.iterrows():
    t=str(r["ticker_at_snapshot"])
    z=daily[daily.ticker.eq(t)].sort_values("date")
    s=pd.Timestamp("2020-03-31")
    if s not in set(z.date):
        continue
    z=z[z.date<=s].tail(60)
    if len(z)<60: continue
    f_close=float(z.loc[z.date.eq(s),"close"].iloc[-1])
    f_mdv=float(z["dollar_volume"].median())
    y_close=float(pd.to_numeric(pd.Series([r.get("raw_close_v4")]),errors="coerce").iloc[0])
    y_mdv=float(pd.to_numeric(pd.Series([r.get("median_dollar_volume_60d")]),errors="coerce").iloc[0])
    rows.append({
        "ticker":t,"snapshot_date":"2020-03-31",
        "yahoo_close":y_close,"finnhub_close":f_close,
        "close_rel_diff":abs(f_close-y_close)/max(abs(f_close),abs(y_close)),
        "yahoo_mdv":y_mdv,"finnhub_mdv":f_mdv,
        "mdv_rel_diff":abs(f_mdv-y_mdv)/max(abs(f_mdv),abs(y_mdv)),
        "finnhub_sessions":len(z)
    })
v=pd.DataFrame(rows)
if v.empty: raise RuntimeError("VALIDATION_EMPTY")
summary={
 "schema":"V4_FINNHUB_MINUTE_ARCHIVE_VALIDATION_V1",
 "tickers":TICKERS,
 "validation_rows":int(len(v)),
 "close_rel_diff_median":float(v.close_rel_diff.median()),
 "close_rel_diff_p95":float(v.close_rel_diff.quantile(.95)),
 "mdv_rel_diff_median":float(v.mdv_rel_diff.median()),
 "mdv_rel_diff_p95":float(v.mdv_rel_diff.quantile(.95)),
 "pass_close_p95_le_0_005":bool(v.close_rel_diff.quantile(.95)<=0.005),
 "pass_mdv_p95_le_0_03":bool(v.mdv_rel_diff.quantile(.95)<=0.03),
 "session_rule":"US regular session 09:30<=ET<=16:00 including closing-auction bar; daily close=last minute close; daily volume=sum minute volume",
 "formation_2023_opened":False,"future_outcomes_used":False,"us3700_used":False
}
v.to_csv(OUT/"validation.csv",index=False)
(OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(json.dumps(summary,indent=2))
print(v.to_string(index=False))
if not (summary["pass_close_p95_le_0_005"] and summary["pass_mdv_p95_le_0_03"]):
    raise RuntimeError("FINNHUB_VALIDATION_FAIL")
