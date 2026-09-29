from pathlib import Path
import glob,json,pandas as pd
OUT=Path("v4-sec-custom-xbrl-output")
cs=[]
for p in glob.glob("downloaded/**/candidates_*.csv.gz",recursive=True):
    try: cs.append(pd.read_csv(p))
    except: pass
d=pd.concat(cs,ignore_index=True) if cs else pd.DataFrame()
if len(d):
    d.to_csv(OUT/"custom_candidate_labels.csv.gz",index=False,compression="gzip")
    ex=d.assign(label_key=d["labels"].fillna("").astype(str))
    s=(ex.groupby(["categories","concept","label_key"],dropna=False)
       .agg(unique_ciks=("cik","nunique"),rows=("cik","size"),role_examples=("role_definitions",lambda x:" || ".join(sorted(set(str(v) for v in x if str(v) and str(v)!="nan"))[:5])))
       .reset_index().sort_values(["categories","unique_ciks","rows"],ascending=[True,False,False]))
    s.to_csv(OUT/"custom_candidate_summary.csv",index=False)
else:
    pd.DataFrame().to_csv(OUT/"custom_candidate_summary.csv",index=False)
aud=[]
for p in glob.glob("downloaded/**/audit_*.csv",recursive=True):
    try: aud.append(pd.read_csv(p))
    except: pass
a=pd.concat(aud,ignore_index=True) if aud else pd.DataFrame()
a.to_csv(OUT/"custom_discovery_audit.csv",index=False)
meta={"schema":"V4_SEC_CUSTOM_XBRL_DISCOVERY_V1","target_ciks":int(a.cik.nunique()) if len(a) else 0,"fetch_errors":int((a.status=="ERROR").sum()) if len(a) else 0,"no_xbrl_zip":int((a.status=="NO_XBRL_ZIP").sum()) if len(a) else 0,"candidate_rows":int(len(d)),"candidate_concepts":int(d.concept.nunique()) if len(d) else 0,"formation_2023_opened":False,"future_outcomes_used":False,"us3700_used":False,"new_corp_action_lookup_calls":0,"note":"Discovery only. No custom concept is admitted until semantic review."}
(OUT/"custom_discovery_summary.json").write_text(json.dumps(meta,indent=2))
print(json.dumps(meta,indent=2))
