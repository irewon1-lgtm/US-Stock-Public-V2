import pandas as pd,numpy as np,base64,json
from pathlib import Path
p=Path('v4-liquidity-output/liquidity_panel.csv.gz')
d=pd.read_csv(p,dtype=str,keep_default_na=False,compression='gzip').sort_values('_row_id')
rid=pd.to_numeric(d['_row_id'],errors='coerce').astype(int).to_numpy()
if len(d)!=42014 or not np.array_equal(rid,np.arange(42014)): raise RuntimeError(f'row alignment failed n={len(d)}')
status=d['liquidity_status'].astype(str)
mdv=pd.to_numeric(d.get('median_dollar_volume_60d'),errors='coerce')
price=pd.to_numeric(d.get('raw_close_v4'),errors='coerce')
known=status.eq('OK')
pass_mask=(known & mdv.ge(5_000_000) & price.ge(5)).to_numpy(dtype=np.uint8)
unknown=(~known).to_numpy(dtype=np.uint8)
price_fail=(known & price.lt(5)).to_numpy(dtype=np.uint8)
liq_fail=(known & price.ge(5) & mdv.lt(5_000_000)).to_numpy(dtype=np.uint8)
def enc(a): return base64.b64encode(np.packbits(a,bitorder='little').tobytes()).decode()
by=[]
for snap,g in d.groupby('snapshot_date',sort=True):
 ix=pd.to_numeric(g['_row_id']).astype(int).to_numpy()
 by.append({'snapshot_date':snap,'rows':len(g),'known_ok':int(known.loc[g.index].sum()),'pass_price_liquidity':int(pass_mask[ix].sum()),'unknown':int(unknown[ix].sum()),'price_fail':int(price_fail[ix].sum()),'liquidity_fail':int(liq_fail[ix].sum())})
out={'schema':'V4_LIQUIDITY_BITMASK_V1','row_count':len(d),'row_order':'_row_id_0_to_42013_matches_v3_fast_price_universe_resolved_input_order','thresholds':{'raw_price_min':5.0,'median_dollar_volume_60d_min':5000000},'bitorder':'little','pass_price_liquidity_b64':enc(pass_mask),'unknown_b64':enc(unknown),'price_fail_b64':enc(price_fail),'liquidity_fail_b64':enc(liq_fail),'by_snapshot':by}
Path('v4-liquidity-output/liquidity_bitmask.json').write_text(json.dumps(out,separators=(',',':')),encoding='utf-8')
Path('v4-liquidity-output/liquidity_summary.json').write_text(json.dumps({k:v for k,v in out.items() if not k.endswith('_b64')},indent=2),encoding='utf-8')
print(json.dumps(out['by_snapshot'],indent=2))
