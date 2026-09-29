from __future__ import annotations
import json,time,threading
from pathlib import Path
import numpy as np,pandas as pd,requests,duckdb

ROOT=Path(".")
T=json.loads((ROOT/"v4-sec-cover/mcap_only_31_targets.json").read_text())
OUT=ROOT/"v4-mcap-only-31-output"; OUT.mkdir(exist_ok=True)
FORMS={"10-Q","10-K","10-Q/A","10-K/A","20-F","20-F/A","40-F","40-F/A"}
UA="V4-Full-Rigor targeted mcap-only recovery research@example.com"
S=requests.Session(); S.headers.update({"User-Agent":UA,"Accept-Encoding":"gzip, deflate","Accept":"application/json"})
LOCK=threading.Lock(); LAST=[0.0]

def wait():
    with LOCK:
        dt=time.monotonic()-LAST[0]
        if dt<0.14: time.sleep(0.14-dt)
        LAST[0]=time.monotonic()

def get_json(url, attempts=5):
    last=""
    for i in range(attempts):
        try:
            wait(); r=S.get(url,timeout=45)
            if r.status_code in {429,500,502,503,504}: raise RuntimeError(f"HTTP_{r.status_code}")
            r.raise_for_status(); return r.json()
        except Exception as e:
            last=repr(e)[:400]
            if i<attempts-1: time.sleep(min(15,1.5*(2**i)))
    raise RuntimeError(last)

def parse_sub_block(a):
    out={}
    acc=a.get("accessionNumber") or []; ac=a.get("acceptanceDateTime") or []
    fm=a.get("form") or []; fd=a.get("filingDate") or []
    for i,x in enumerate(acc):
        out[str(x)]={"accepted":str(ac[i] if i<len(ac) else ""),
                     "sub_form":str(fm[i] if i<len(fm) else ""),
                     "sub_filing_date":str(fd[i] if i<len(fd) else "")}
    return out

def accession_map(cik):
    cik10=f"{int(cik):010d}"
    sub=get_json(f"https://data.sec.gov/submissions/CIK{cik10}.json")
    out=parse_sub_block(((sub.get("filings") or {}).get("recent") or {}))
    for meta in ((sub.get("filings") or {}).get("files") or []):
        frm=str(meta.get("filingFrom") or ""); to=str(meta.get("filingTo") or "")
        if frm and frm>"2022-12-30": continue
        if to and to<"2017-01-01": continue
        name=str(meta.get("name") or "").strip()
        if not name: continue
        try: out.update(parse_sub_block(get_json("https://data.sec.gov/submissions/"+name)))
        except Exception: pass
    return out

facts=[]; audits=[]
for ticker,cik in T["ticker_cik"].items():
    a={"ticker":ticker,"cik":cik,"status":"OK","fact_rows":0,"error":""}
    try:
        cf=get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json")
        amap=accession_map(cik)
        for ns,tag,role in [
            ("dei","EntityCommonStockSharesOutstanding","DEI_ENTITY_COMMON_SHARES"),
            ("us-gaap","CommonStockSharesOutstanding","USGAAP_COMMON_SHARES"),
        ]:
            concept=(((cf.get("facts") or {}).get(ns) or {}).get(tag) or {})
            for unit,items in (concept.get("units") or {}).items():
                if "share" not in str(unit).lower() or not isinstance(items,list): continue
                for r in items:
                    form=str(r.get("form") or "").upper()
                    if form not in FORMS: continue
                    end=str(r.get("end") or "")[:10]; filed=str(r.get("filed") or "")[:10]; accn=str(r.get("accn") or "")
                    if not end or end<"2017-01-01" or end>"2022-12-30": continue
                    if filed and filed>"2022-12-30": continue
                    try: val=float(r.get("val"))
                    except: continue
                    if not np.isfinite(val) or val<=0: continue
                    sm=amap.get(accn,{})
                    accepted=str(sm.get("accepted") or "")
                    if not accepted or accepted[:10]>"2022-12-30": continue
                    facts.append({"ticker":ticker,"cik":cik,"namespace":ns,"tag":tag,"role":role,
                                  "unit":unit,"value":val,"end":end,"filed":filed,"form":form,
                                  "accn":accn,"accepted":accepted})
        a["fact_rows"]=sum(1 for x in facts if x["cik"]==cik)
    except Exception as e:
        a["status"]="ERROR"; a["error"]=repr(e)[:500]
    audits.append(a)

fd=pd.DataFrame(facts)
if fd.empty:
    fd=pd.DataFrame(columns=["ticker","cik","namespace","tag","role","unit","value","end","filed","form","accn","accepted"])
fd=fd.drop_duplicates(["cik","role","value","end","accn"])
fd.to_csv(OUT/"exact_standard_shares.csv.gz",index=False,compression="gzip")
pd.DataFrame(audits).to_csv(OUT/"sec_audit.csv",index=False)

# Finnhub public archive snapshot prices: as-traded minute close at formation date, last regular-session bar <= 16:00 ET.
BASE="https://huggingface.co/datasets/mito0o852/OHLCV-1m/resolve/main/data/ohlcv_{m}.parquet?download=true"
con=duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
tickers=sorted(T["ticker_cik"])
lit=",".join("'" + x.replace("'","''") + "'" for x in tickers)
prices=[]
for snap in T["snapshots"]:
    m=snap[:7]; url=BASE.format(m=m)
    q=f"""SELECT ticker,timestamp,close
          FROM read_parquet('{url}')
          WHERE ticker IN ({lit})"""
    d=con.execute(q).fetchdf()
    if d.empty: continue
    d["timestamp"]=pd.to_datetime(d["timestamp"],utc=True)
    loc=d["timestamp"].dt.tz_convert("America/New_York")
    d["date"]=loc.dt.tz_localize(None).dt.normalize()
    d["mins_et"]=loc.dt.hour*60+loc.dt.minute
    d=d[(d["date"].eq(pd.Timestamp(snap)))&(d["mins_et"]>=570)&(d["mins_et"]<=960)].copy()
    if d.empty: continue
    d=d.sort_values(["ticker","timestamp"])
    z=d.groupby("ticker",as_index=False).agg(snapshot_close=("close","last"))
    z["snapshot_date"]=snap
    prices.append(z)
pd.concat(prices,ignore_index=True).to_csv(OUT/"finnhub_snapshot_prices.csv.gz",index=False,compression="gzip") if prices else pd.DataFrame(columns=["ticker","snapshot_close","snapshot_date"]).to_csv(OUT/"finnhub_snapshot_prices.csv.gz",index=False,compression="gzip")

summary={"schema":"V4_MCAP_ONLY_31_RECOVERY_DATA_V1","target_tickers":len(tickers),
         "sec_fact_rows":int(len(fd)),"sec_ciks_with_facts":int(fd.cik.nunique()) if len(fd) else 0,
         "sec_fetch_errors":sum(x["status"]!="OK" for x in audits),
         "formation_2023_opened":False,"future_outcomes_used":False,"us3700_used":False,
         "new_corp_action_lookup_calls":0,
         "finnhub_usage":"snapshot as-traded price only; volume not used; 2% market-cap guard required downstream"}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(json.dumps(summary,indent=2),flush=True)
