import pandas as pd,numpy as np,base64,json
from pathlib import Path
p=Path('v4-liquidity-output/liquidity_panel.csv.gz')
d=pd.read_csv(p,dtype=str,keep_default_na=False,compression='gzip')
rid=pd.to_numeric(d['_row_id'],errors='coerce')
diag={'n':len(d),'rid_na':int(rid.isna().sum()),'rid_unique':int(rid.nunique(dropna=True)),'rid_min':None if rid.dropna().empty else int(rid.min()),'rid_max':None if rid.dropna().empty else int(rid.max())}
if len(d)!=42014 or diag['rid_na'] or diag['rid_unique']!=42014 or diag['rid_min']<0 or diag['rid_max']>=42014:
    raise RuntimeError(f'row id integrity failed {diag}')
rid=rid.astype(int).to_numpy()
status=d['liquidity_status'].astype(str)
mdv=pd.to_numeric(d.get('median_dollar_volume_60d'),errors='coerce')
price=pd.to_numeric(d.get('raw_close_v4'),errors='coerce')
known=status.eq('OK').to_numpy()
pass_row=(status.eq('OK') & mdv.ge(5_000_000) & price.ge(5)).to_numpy()
unknown_row=(status.ne('OK')).to_numpy()
price_fail_row=(status.eq('OK') & price.lt(5)).to_numpy()
liq_fail_row=(status.eq('OK') & price.ge(5) & mdv.lt(5_000_000)).to_numpy()
def reindex(rowmask):
    a=np.zeros(42014,dtype=np.uint8); a[rid]=np.asarray(rowmask,dtype=np.uint8); return a
pass_mask=reindex(pass_row); unknown=reindex(unknown_row); price_fail=reindex(price_fail_row); liq_fail=reindex(liq_fail_row)
def enc(a): return base64.b64encode(np.packbits(a,bitorder='little').tobytes()).decode()
by=[]
for snap,g in d.groupby('snapshot_date',sort=True):
    idx=g.index
    by.append({'snapshot_date':snap,'rows':len(g),'known_ok':int((status.loc[idx]=='OK').sum()),'pass_price_liquidity':int(pass_row[idx].sum()),'unknown':int(unknown_row[idx].sum()),'price_fail':int(price_fail_row[idx].sum()),'liquidity_fail':int(liq_fail_row[idx].sum())})
out={'schema':'V4_LIQUIDITY_BITMASK_V2','row_count':len(d),'row_id_diagnostics':diag,'row_order':'bit position equals _row_id from v3-fast/price_universe_resolved input','thresholds':{'raw_price_min':5.0,'median_dollar_volume_60d_min':5000000},'bitorder':'little','pass_price_liquidity_b64':enc(pass_mask),'unknown_b64':enc(unknown),'price_fail_b64':enc(price_fail),'liquidity_fail_b64':enc(liq_fail),'by_snapshot':by}
Path('v4-liquidity-output/liquidity_bitmask.json').write_text(json.dumps(out,separators=(',',':')),encoding='utf-8')
Path('v4-liquidity-output/liquidity_summary.json').write_text(json.dumps({k:v for k,v in out.items() if not k.endswith('_b64')},indent=2),encoding='utf-8')
print(json.dumps({'diag':diag,'by_snapshot':by},indent=2))
