from __future__ import annotations
import base64,json
from pathlib import Path
import numpy as np,pandas as pd

N=42014
src=Path("v4-eulerpool-output/recovery")
files=sorted(src.glob("rows_*.csv.gz"))
if len(files)!=16: raise RuntimeError(f"expected 16 shards, got {len(files)}")
d=pd.concat([pd.read_csv(p,dtype=str,keep_default_na=False,compression="gzip") for p in files],ignore_index=True)
rid=pd.to_numeric(d["_row_id"],errors="raise").astype(int)
if rid.duplicated().any(): raise RuntimeError("duplicate row ids in Eulerpool recovery")
status=d["ep_status"].astype(str)
mdv=pd.to_numeric(d.get("ep_median_dollar_volume_60d"),errors="coerce")
price=pd.to_numeric(d.get("ep_raw_close_reconstructed"),errors="coerce")
pass_row=(status.eq("OK") & price.ge(5) & mdv.ge(5_000_000)).to_numpy()
price_fail=(status.eq("OK") & price.lt(5)).to_numpy()
liq_fail=(status.eq("OK") & price.ge(5) & mdv.lt(5_000_000)).to_numpy()
def reindex(mask):
    a=np.zeros(N,dtype=np.uint8); a[rid.to_numpy()]=np.asarray(mask,dtype=np.uint8); return a
def enc(a): return base64.b64encode(np.packbits(a,bitorder="little").tobytes()).decode()
passmask=reindex(pass_row); knownmask=reindex(status.eq("OK").to_numpy())
# Existing Yahoo status determines which rows Eulerpool was allowed to fill.
base=pd.read_csv("v4-liquidity-output/liquidity_panel.csv.gz",dtype=str,keep_default_na=False,compression="gzip")
brid=pd.to_numeric(base["_row_id"],errors="raise").astype(int)
bst=base["liquidity_status"].astype(str)
existing_known=np.zeros(N,dtype=np.uint8); existing_known[brid.to_numpy()]=bst.eq("OK").astype(np.uint8).to_numpy()
existing_pass=np.zeros(N,dtype=np.uint8)
bmdv=pd.to_numeric(base.get("median_dollar_volume_60d"),errors="coerce"); bp=pd.to_numeric(base.get("raw_close_v4"),errors="coerce")
existing_pass[brid.to_numpy()]=(bst.eq("OK")&bp.ge(5)&bmdv.ge(5_000_000)).astype(np.uint8).to_numpy()
combined_known=((existing_known>0)|(knownmask>0)).astype(np.uint8)
combined_pass=((existing_pass>0)|(passmask>0)).astype(np.uint8)
combined_unknown=(combined_known==0).astype(np.uint8)
u=pd.read_csv("v3-fast/price_universe_resolved.csv.gz",dtype=str,keep_default_na=False,compression="gzip")
by=[]
for snap,idx in u.groupby("snapshot_date",sort=True).groups.items():
    ii=np.asarray(list(idx),dtype=int)
    by.append({"snapshot_date":snap,"rows":len(ii),"combined_known":int(combined_known[ii].sum()),"combined_pass_price_liquidity":int(combined_pass[ii].sum()),"combined_unknown":int(combined_unknown[ii].sum())})
out={"schema":"V4_EULERPOOL_RECOVERY_SUMMARY_V1","purpose":"Outcome-free price/liquidity recovery only; no 3y targets.","row_count":N,"recovered_row_records":len(d),"bitorder":"little",
     "combined_known_b64":enc(combined_known),"combined_pass_price_liquidity_b64":enc(combined_pass),"combined_unknown_b64":enc(combined_unknown),
     "by_snapshot":by}
Path("v4-eulerpool-output/recovery_summary.json").write_text(json.dumps(out,separators=(",",":")),encoding="utf-8")
Path("v4-eulerpool-output/recovery_summary_readable.json").write_text(json.dumps({k:v for k,v in out.items() if not k.endswith("_b64")},indent=2),encoding="utf-8")
print(json.dumps(out["by_snapshot"],indent=2))
