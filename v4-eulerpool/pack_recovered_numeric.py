from __future__ import annotations
import base64,json,zlib
from pathlib import Path
import numpy as np,pandas as pd

p=Path("v4-eulerpool-output/eulerpool_split_corrected_recovery.csv.gz")
d=pd.read_csv(p,compression="gzip")
d["_row_id"]=pd.to_numeric(d["_row_id"],errors="raise").astype(np.uint32)
d["future_split_cum_ratio"]=pd.to_numeric(d["future_split_cum_ratio"],errors="coerce").astype(np.float64)
d["as_traded_close"]=pd.to_numeric(d["as_traded_close"],errors="coerce").astype(np.float64)
d["median_dollar_volume_60d"]=pd.to_numeric(d["median_dollar_volume_60d"],errors="coerce").astype(np.float64)
d=d.sort_values("_row_id")
if d["future_split_cum_ratio"].isna().any():
    raise RuntimeError("unresolved split ratios remain")
def enc(arr):
    return base64.b64encode(zlib.compress(np.ascontiguousarray(arr).tobytes(),9)).decode()
def chunks(s,n=900):
    return [s[i:i+n] for i in range(0,len(s),n)]
out={
 "schema":"V4_EULERPOOL_SPLIT_RATIO_PACK_V1",
 "rows":len(d),
 "codec":"zlib9+base64",
 "dtypes":{"row_id":"uint32","future_split_cum_ratio":"float64","as_traded_close":"float64"},
 "row_id_chunks":chunks(enc(d["_row_id"].to_numpy(np.uint32))),
 "split_ratio_chunks":chunks(enc(d["future_split_cum_ratio"].to_numpy(np.float64))),
 "as_traded_close_chunks":chunks(enc(d["as_traded_close"].to_numpy(np.float64))),
}
Path("v4-eulerpool-output/split_ratio_pack.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
print(json.dumps({"rows":len(d),"row_chunks":len(out["row_id_chunks"]),"ratio_chunks":len(out["split_ratio_chunks"]),"close_chunks":len(out["as_traded_close_chunks"])}))
