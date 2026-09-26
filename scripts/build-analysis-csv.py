#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json,math
from datetime import datetime,timezone
from pathlib import Path

METRICS=[
("Revenue_TTM_YoY_Pct","revenue_yoy"),
("Gross_Margin_TTM_Pct","gross_margin"),
("Operating_Margin_TTM_Pct","operating_margin"),
("Net_Margin_TTM_Pct","net_margin"),
("ROA_TTM_Pct","roa"),
("FCF_Yield_TTM_Pct","fcf_yield"),
("Price_Sales_TTM","price_sales"),
("Shares_Change_YoY_Pct","shares_change_yoy"),
("Drawdown_52W_Pct","drawdown_52w"),
]
WEIGHTS={"Revenue_TTM_YoY_Pct":15,"Gross_Margin_TTM_Pct":15,"Operating_Margin_TTM_Pct":10,"Net_Margin_TTM_Pct":10,"ROA_TTM_Pct":10,"FCF_Yield_TTM_Pct":10,"Price_Sales_TTM":10,"Shares_Change_YoY_Pct":10,"Drawdown_52W_Pct":10}
BOUNDS={"Revenue_TTM_YoY_Pct":(-50,100),"Gross_Margin_TTM_Pct":(0,100),"Operating_Margin_TTM_Pct":(-50,60),"Net_Margin_TTM_Pct":(-50,60),"ROA_TTM_Pct":(-30,50),"FCF_Yield_TTM_Pct":(-20,40),"Price_Sales_TTM":(0,20),"Shares_Change_YoY_Pct":(-30,50),"Drawdown_52W_Pct":(0,80)}
LOWER={"Price_Sales_TTM","Shares_Change_YoY_Pct"}
SECTOR_KO={"Technology":"기술","Healthcare":"헬스케어","Financial":"금융","Consumer Cyclical":"경기소비재","Consumer Defensive":"필수소비재","Industrials":"산업재","Communication Services":"커뮤니케이션","Energy":"에너지","Basic Materials":"소재","Real Estate":"부동산","Utilities":"유틸리티"}

def ts(v):
    if not v:return None
    try:return datetime.fromisoformat(str(v).replace("Z","+00:00"))
    except Exception:return None

def val(r,k):
    c=(r.get("metrics") or {}).get(k) or {};v=c.get("value")
    return float(v) if c.get("status")=="NUMERIC" and isinstance(v,(int,float)) and math.isfinite(v) else None

def norm(k,v):
    if v is None:return None
    lo,hi=BOUNDS[k];x=max(lo,min(hi,v));n=(x-lo)/(hi-lo)
    if k in LOWER:n=1-n
    if k=="Drawdown_52W_Pct":n=1-max(0,min(1,abs(v-35)/45))
    return n*100

def score(r):
    total=used=0.0
    for k,_ in METRICS:
        n=norm(k,val(r,k))
        if n is None:continue
        w=WEIGHTS[k];total+=n*w;used+=w
    return None if used<=0 else round(total/used,2)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--state",required=True);ap.add_argument("--out",required=True);a=ap.parse_args()
    state=json.loads(Path(a.state).read_text(encoding="utf-8"));rows=state.get("records") or []
    if state.get("recordCount")!=3700 or len(rows)!=3700 or len({str(r.get("ticker")).upper() for r in rows})!=3700:raise SystemExit("ANALYSIS_CSV_BAD_UNIVERSE")
    snapshot=state.get("generatedAt") or "";snap=ts(snapshot) or datetime.now(timezone.utc)
    ranked=[]
    for r in rows:
        x=dict(r);x["_score"]=score(r);ranked.append(x)
    ranked.sort(key=lambda r:(-(r["_score"] if r["_score"] is not None else -1e18),str(r.get("ticker") or "")))
    overall={r["ticker"]:i+1 for i,r in enumerate(ranked)}
    by_sector={}
    for r in ranked:by_sector.setdefault(str(r.get("sector") or ""),[]).append(r)
    srank={};scount={s:len(xs) for s,xs in by_sector.items()}
    for s,xs in by_sector.items():
        for i,r in enumerate(xs):srank[r["ticker"]]=i+1
    cols=["snapshot_generated_at","rank_model","overall_rank","overall_percentile","sector_rank","sector_count","sector_percentile","quantitative_score","ticker","company","sector","sector_ko","industry","exchange","cik","numeric_count","resolved_count","na_basis_count","hold_count","is_9of9_numeric","is_8plus_numeric","last_attempt_at","last_successful_refresh_at","oldest_metric_updated_at","latest_metric_updated_at","oldest_metric_age_hours","stale_metric_count_48h","data_quality_flag"]
    for _,alias in METRICS:cols += [f"{alias}_value",f"{alias}_status",f"{alias}_source",f"{alias}_updated_at"]
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("w",encoding="utf-8-sig",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=cols);w.writeheader()
        for r in ranked:
            ms=r.get("metrics") or {};updates=[ts((ms.get(k) or {}).get("updatedAt")) for k,_ in METRICS];updates=[x for x in updates if x]
            oldest=min(updates) if updates else None;latest=max(updates) if updates else None
            stale=sum(1 for k,_ in METRICS if ts((ms.get(k) or {}).get("updatedAt")) is None or (snap-ts((ms.get(k) or {}).get("updatedAt"))).total_seconds()>172800)
            na=sum(1 for k,_ in METRICS if (ms.get(k) or {}).get("status")=="NA_BASIS");hold=sum(1 for k,_ in METRICS if (ms.get(k) or {}).get("status")=="HOLD")
            nr=int(r.get("numericCount") or 0);sr=srank[r["ticker"]];sc=scount.get(str(r.get("sector") or ""),0)
            quality="HOLD_PRESENT" if hold else "STALE_METRIC_PRESENT" if stale else "COMPLETE_9OF9" if nr==9 else "RESOLVED_8OF9" if nr>=8 else "BELOW_8OF9"
            row={"snapshot_generated_at":snapshot,"rank_model":"APP_UI_DEFAULT_V1_15_15_10_10_10_10_10_10_10","overall_rank":overall[r["ticker"]],"overall_percentile":round(100*(1-(overall[r["ticker"]]-1)/3699),4),"sector_rank":sr,"sector_count":sc,"sector_percentile":round(100*(1-(sr-1)/max(1,sc-1)),4) if sc else "","quantitative_score":r["_score"],"ticker":r.get("ticker"),"company":r.get("company"),"sector":r.get("sector"),"sector_ko":SECTOR_KO.get(str(r.get("sector") or ""),"기타"),"industry":r.get("industry"),"exchange":r.get("exchange"),"cik":r.get("cik"),"numeric_count":nr,"resolved_count":r.get("resolvedCount"),"na_basis_count":na,"hold_count":hold,"is_9of9_numeric":1 if nr==9 else 0,"is_8plus_numeric":1 if nr>=8 else 0,"last_attempt_at":r.get("lastAttemptAt"),"last_successful_refresh_at":r.get("lastSuccessfulRefreshAt"),"oldest_metric_updated_at":oldest.isoformat().replace("+00:00","Z") if oldest else "","latest_metric_updated_at":latest.isoformat().replace("+00:00","Z") if latest else "","oldest_metric_age_hours":round((snap-oldest).total_seconds()/3600,3) if oldest else "","stale_metric_count_48h":stale,"data_quality_flag":quality}
            for k,alias in METRICS:
                c=ms.get(k) or {};row[f"{alias}_value"]=c.get("value") if c.get("status")=="NUMERIC" else "";row[f"{alias}_status"]=c.get("status") or "";row[f"{alias}_source"]=c.get("source") or "";row[f"{alias}_updated_at"]=c.get("updatedAt") or ""
            w.writerow(row)
    print(json.dumps({"ok":True,"rows":len(ranked),"columns":len(cols),"snapshot":snapshot,"file":str(out)},separators=(",",":")))

if __name__=="__main__":main()
