from __future__ import annotations
import base64,json,zlib
from pathlib import Path
import numpy as np,pandas as pd

p=Path("v4-eulerpool-output/eulerpool_unknown_recovery.csv.gz")
d=pd.read_csv(p,compression="gzip")
ok=d["liquidity_status"].astype(str).eq("OK")
z=d.loc[ok,["_row_id","raw_close_v4","median_dollar_volume_60d"]].copy()
z["_row_id"]=pd.to_numeric(z["_row_id"],errors="raise").astype(np.uint32)
z["raw_close_v4"]=pd.to_numeric(z["raw_close_v4"],errors="raise").astype(np.float64)
z["median_dollar_volume_60d"]=pd.to_numeric(z["median_dollar_volume_60d"],errors="raise").astype(np.float64)
z=z.sort_values("_row_id")
def enc(arr):
    return base64.b64encode(zlib.compress(np.ascontiguousarray(arr).tobytes(),9)).decode()
out={
 "schema":"V4_EULERPOOL_RECOVERED_NUMERIC_PACK_V1",
 "rows":len(z),
 "dtype":{"row_id":"uint32","raw_close":"float64","median_dollar_volume_60d":"float64"},
 "codec":"zlib9+base64 little/native byteorder on GitHub ubuntu x86_64",
 "row_id_b64":enc(z["_row_id"].to_numpy(np.uint32)),
 "raw_close_b64":enc(z["raw_close_v4"].to_numpy(np.float64)),
 "median_dollar_volume_60d_b64":enc(z["median_dollar_volume_60d"].to_numpy(np.float64)),
}
Path("v4-eulerpool-output/recovered_numeric_pack.json").write_text(json.dumps(out,separators=(",",":")),encoding="utf-8")
print(json.dumps({"rows":len(z),"file":"v4-eulerpool-output/recovered_numeric_pack.json"}))
