from __future__ import annotations
import json,os,time,requests
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import pandas as pd

KEY=os.environ["EULERPOOL_API_KEY"].strip()
BASE="https://api.eulerpool.com/api/1"
OUT=Path("v4-eulerpool-output"); OUT.mkdir(parents=True,exist_ok=True)
TARGETS=json.loads(Path("v4-eulerpool/mcap_recovery_targets.json").read_text())
SNAPS=["2020-03-31","2020-06-30","2020-09-30","2020-12-31","2021-03-31","2021-06-30","2021-09-30","2021-12-31","2022-03-31","2022-06-30","2022-09-30","2022-12-30"]
H={"Authorization":f"Bearer {KEY}","Accept":"application/json","User-Agent":"V4-outcome-free-mcap-recovery/1.0"}

def get_json(path,params=None):
    last=""
    for a in range(4):
        try:
            r=requests.get(BASE+path,params=params,headers=H,timeout=60)
            q={k:v for k,v in r.headers.items() if any(x in k.lower() for x in ["rate","limit","remaining","quota","retry"])}
            if r.status_code==404: return None,"NOT_FOUND","",q
            if r.status_code==429:
                if a<3: time.sleep(min(30,max(1,float(r.headers.get("Retry-After") or 2)))); continue
                return None,"RATE_LIMIT","429",q
            if r.status_code in {500,502,503,504} and a<3:
                time.sleep(min(20,1.5*(2**a))); continue
            r.raise_for_status()
            return r.json(),"OK","",q
        except Exception as e:
            last=repr(e)[:300]
            if a<3: time.sleep(min(20,1.5*(2**a)))
    return None,"ERROR",last,{}

def one(t):
    vendor,vs,ve,vq=get_json(f"/equity/market-cap-history/{t}")
    official,os_,oe,oq=get_json(f"/equity/market-cap/{t}",{"range":"5y"})
    vm={}
    if vs=="OK" and isinstance(vendor,dict) and isinstance(vendor.get("data"),list):
        for x in vendor["data"]:
            d=str(x.get("date") or "")
            try: val=float(x.get("close"))
            except: continue
            if d in SNAPS and val>0: vm[d]=val
    om={}
    if os_=="OK" and isinstance(official,dict) and isinstance(official.get("data"),list):
        for x in official["data"]:
            try:
                d=pd.to_datetime(int(x.get("timestamp")),unit="ms",utc=True).date().isoformat()
                val=float(x.get("marketCap"))*1_000_000.0
            except: continue
            if d in SNAPS and val>0: om[d]=val
    rows=[]
    for s in SNAPS:
        vv=vm.get(s); ov=om.get(s)
        if vv is not None:
            src="EULERPOOL_VENDOR_MCAP_HISTORY"
            val=vv
        elif ov is not None:
            src="EULERPOOL_OFFICIAL_MCAP_5Y"
            val=ov
        else:
            src="UNRESOLVED"; val=None
        rel=None
        if vv is not None and ov is not None and max(abs(vv),abs(ov))>0:
            rel=abs(vv-ov)/max(abs(vv),abs(ov))
        rows.append({"ticker":t,"snapshot_date":s,"market_cap_usd":val,"source":src,"vendor_market_cap":vv,"official_market_cap":ov,"overlap_rel_diff":rel})
    return rows,{"ticker":t,"vendor_status":vs,"official_status":os_,"vendor_points":0 if not vm else len(vm),"official_points":0 if not om else len(om),"vendor_error":ve,"official_error":oe,"rate_remaining":(oq or vq).get("x-ratelimit-remaining","")}

rows=[]; audit=[]
with ThreadPoolExecutor(max_workers=6) as ex:
    futs={ex.submit(one,t):t for t in TARGETS}
    for i,f in enumerate(as_completed(futs),1):
        rr,aa=f.result(); rows.extend(rr); audit.append(aa)
        if i%50==0: print("DONE",i,"/",len(TARGETS),flush=True)
pd.DataFrame(rows).to_csv(OUT/"mcap_recovery_snapshots.csv",index=False)
pd.DataFrame(audit).sort_values("ticker").to_csv(OUT/"mcap_recovery_audit.csv",index=False)
d=pd.DataFrame(rows)
resolved=d["market_cap_usd"].notna()
overlap=d["overlap_rel_diff"].dropna()
summary={
 "schema":"V4_EULERPOOL_MCAP_RECOVERY_V1",
 "purpose":"Outcome-free historical market-cap availability recovery; no return labels.",
 "target_tickers":len(TARGETS),
 "snapshot_rows":len(d),
 "resolved_snapshot_rows":int(resolved.sum()),
 "unresolved_snapshot_rows":int((~resolved).sum()),
 "vendor_resolved_rows":int(d["source"].eq("EULERPOOL_VENDOR_MCAP_HISTORY").sum()),
 "official_5y_fallback_rows":int(d["source"].eq("EULERPOOL_OFFICIAL_MCAP_5Y").sum()),
 "overlap_count":int(len(overlap)),
 "overlap_rel_diff_median":None if overlap.empty else float(overlap.median()),
 "overlap_rel_diff_p95":None if overlap.empty else float(overlap.quantile(.95)),
 "note":"Vendor history is a current historical reconstruction. PIT/publication-time validity remains to be audited before final V4 eligibility PASS."
}
(OUT/"mcap_recovery_summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(json.dumps(summary,indent=2))
