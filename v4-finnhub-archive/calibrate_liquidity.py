from __future__ import annotations
import argparse,json,duckdb,pandas as pd,numpy as np
from pathlib import Path

ROOT=Path(".")
T=json.loads((ROOT/"v4-finnhub-archive/price_only_targets.json").read_text())
OUT=ROOT/"v4-finnhub-liquidity-cal-output";OUT.mkdir(exist_ok=True)
FBASE="https://huggingface.co/datasets/mito0o852/OHLCV-1m/resolve/main/data/ohlcv_{ym}.parquet?download=true"
DBETA="https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main/data/US/stock_prices.parquet?download=true"
SNAPS=T["snapshots"]
TICKERS=sorted(set(T["tickers"]))

def features(d,snap):
    s=pd.Timestamp(snap)
    z=d[d.date<=s].sort_values("date")
    if z.empty or s not in set(z.date): return None
    z=z.tail(60)
    if len(z)<60:return {"status":"INSUFFICIENT_60_SESSIONS","sessions":len(z)}
    ok=z.close.gt(0)&z.volume.ge(0)&z.close.notna()&z.volume.notna()
    if not bool(ok.all()):return {"status":"PRICE_VOLUME_GAP","sessions":len(z),"valid":int(ok.sum())}
    dv=z.close*z.volume
    return {"status":"OK","sessions":60,"snapshot_close":float(z.loc[z.date.eq(s),"close"].iloc[-1]),"mdv":float(dv.median())}

def load_finnhub_year(con,year,tickers):
    lit=",".join("'" + x.replace("'","''") + "'" for x in tickers)
    parts=[]
    for month in range(1,13):
        ym=f"{year}-{month:02d}";url=FBASE.format(ym=ym)
        q=f"""SELECT ticker,timestamp,close,volume FROM read_parquet('{url}') WHERE ticker IN ({lit})"""
        d=con.execute(q).fetchdf()
        if d.empty:continue
        d["timestamp"]=pd.to_datetime(d["timestamp"],utc=True)
        local=d["timestamp"].dt.tz_convert("America/New_York")
        d["date"]=local.dt.tz_localize(None).dt.normalize()
        d["mins_et"]=local.dt.hour*60+local.dt.minute
        # close from regular session, volume from extended archive session to best match Yahoo daily consolidated volume.
        rth=d[(d.mins_et>=570)&(d.mins_et<=960)].sort_values(["ticker","timestamp"]).groupby(["ticker","date"],as_index=False).agg(close=("close","last"))
        vol=d[(d.mins_et>=240)&(d.mins_et<=1200)].groupby(["ticker","date"],as_index=False).agg(volume=("volume","sum"))
        daily=rth.merge(vol,on=["ticker","date"],how="inner")
        parts.append(daily)
    return pd.concat(parts,ignore_index=True) if parts else pd.DataFrame(columns=["ticker","date","close","volume"])

def load_defeatbeta_year(con,year,tickers):
    lit=",".join("'" + x.replace("'","''") + "'" for x in tickers)
    q=f"""SELECT symbol AS ticker,CAST(report_date AS DATE) AS date,CAST(close AS DOUBLE) AS close,CAST(volume AS DOUBLE) AS volume
          FROM read_parquet('{DBETA}')
          WHERE symbol IN ({lit}) AND CAST(report_date AS DATE) BETWEEN DATE '{year}-01-01' AND DATE '{year}-12-31'"""
    d=con.execute(q).fetchdf()
    d["date"]=pd.to_datetime(d["date"]).dt.normalize()
    return d

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--year",type=int,required=True);a=ap.parse_args()
    year=a.year
    snaps=[s for s in SNAPS if int(s[:4])==year]
    con=duckdb.connect();con.execute("INSTALL httpfs; LOAD httpfs;")
    f=load_finnhub_year(con,year,TICKERS)
    y=load_defeatbeta_year(con,year,TICKERS)
    fby={t:g[["date","close","volume"]].sort_values("date") for t,g in f.groupby("ticker")}
    yby={t:g[["date","close","volume"]].sort_values("date") for t,g in y.groupby("ticker")}
    rows=[];val=[]
    for snap in snaps:
        for t in TICKERS:
            ff=features(fby.get(t,pd.DataFrame(columns=["date","close","volume"])),snap)
            if ff:
                rows.append({"ticker":t,"snapshot_date":snap,"source":"FINNHUB_MINUTE_ARCHIVE",**ff})
            yy=features(yby.get(t,pd.DataFrame(columns=["date","close","volume"])),snap)
            if ff and yy and ff.get("status")=="OK" and yy.get("status")=="OK":
                val.append({"ticker":t,"snapshot_date":snap,"finnhub_mdv":ff["mdv"],"yahoo_mdv":yy["mdv"],
                            "finnhub_close":ff["snapshot_close"],"yahoo_close":yy["snapshot_close"],
                            "finnhub_pass":ff["mdv"]>=5_000_000,"yahoo_pass":yy["mdv"]>=5_000_000,
                            "mdv_ratio":ff["mdv"]/yy["mdv"] if yy["mdv"]>0 else np.nan})
    rd=pd.DataFrame(rows);vd=pd.DataFrame(val)
    rd.to_csv(OUT/f"features_{year}.csv.gz",index=False,compression="gzip")
    vd.to_csv(OUT/f"validation_{year}.csv",index=False)
    summary={"schema":"V4_FINNHUB_LIQUIDITY_CAL_YEAR_V1","year":year,"target_tickers":len(TICKERS),
             "feature_rows":len(rd),"ok_rows":int((rd.status=="OK").sum()) if len(rd) else 0,
             "validation_rows":len(vd),"validation_false_pass":int(((vd.finnhub_pass)&(~vd.yahoo_pass)).sum()) if len(vd) else 0,
             "validation_false_fail":int(((~vd.finnhub_pass)&(vd.yahoo_pass)).sum()) if len(vd) else 0,
             "formation_2023_opened":False,"future_outcomes_used":False,"us3700_used":False}
    (OUT/f"summary_{year}.json").write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))

if __name__=="__main__":main()
