from __future__ import annotations
import io,json,time,threading,zipfile
from pathlib import Path
import requests,pandas as pd
from lxml import etree

ROOT=Path("."); T=json.loads((ROOT/"v4-sec-cover/security_title_targets.json").read_text()); OUT=ROOT/"v4-sec-security-title-output";OUT.mkdir(exist_ok=True)
FORMS=set(T["forms"]); START=pd.Timestamp(T["start"],tz="UTC"); END=pd.Timestamp(T["end"]+"T23:59:59Z")
UA="V4-Full-Rigor security-title research@example.com"; S=requests.Session();S.headers.update({"User-Agent":UA,"Accept-Encoding":"gzip, deflate"})
LOCK=threading.Lock();LAST=[0.0]
def wait():
    with LOCK:
        dt=time.monotonic()-LAST[0]
        if dt<0.30:time.sleep(0.30-dt)
        LAST[0]=time.monotonic()
def get(url,timeout=60):
    last=""
    for i in range(4):
        try:
            wait();r=S.get(url,timeout=timeout)
            if r.status_code==404:return None
            if r.status_code in {429,500,502,503,504}:raise RuntimeError(f"HTTP_{r.status_code}")
            r.raise_for_status();return r
        except Exception as e:
            last=repr(e)
            if i<3:time.sleep(min(15,1.5*(2**i)))
    raise RuntimeError(last)
def filings(cik):
    r=get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json",45)
    if r is None:return []
    j=r.json();a=(j.get("filings") or {}).get("recent") or {};out=[]
    n=len(a.get("accessionNumber") or [])
    for i in range(n):
        acc=str(a["accessionNumber"][i]); form=str((a.get("form") or [""]*n)[i]).upper()
        if form not in FORMS:continue
        ac=str((a.get("acceptanceDateTime") or [""]*n)[i]); fd=str((a.get("filingDate") or [""]*n)[i])
        try:t=pd.Timestamp(ac or fd)
        except:continue
        if t.tzinfo is None:t=t.tz_localize("UTC")
        else:t=t.tz_convert("UTC")
        if START<=t<=END:out.append({"accn":acc,"accepted":ac,"filed":fd,"form":form})
    return out
def clean(el):
    return " ".join("".join(el.itertext()).replace("\xa0"," ").split()).strip()
rows=[];aud=[]
for cik in T["ciks"]:
    rr=[];err=""
    try:
        fs=filings(int(cik))
        for fil in fs:
            acc=fil["accn"];ad=acc.replace("-","");zreq=get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{ad}/{acc}-xbrl.zip",75)
            if zreq is None:continue
            try:z=zipfile.ZipFile(io.BytesIO(zreq.content))
            except:continue
            for name in z.namelist():
                if not name.lower().endswith((".htm",".html")):continue
                try:root=etree.fromstring(z.read(name),parser=etree.XMLParser(recover=True,huge_tree=True))
                except:continue
                byctx={}
                for el in root.xpath("//*[local-name()='nonNumeric']"):
                    nm=str(el.get("name") or "")
                    if nm not in {"dei:TradingSymbol","dei:Security12bTitle"}:continue
                    ctx=str(el.get("contextRef") or "");txt=clean(el)
                    if not txt:continue
                    byctx.setdefault(ctx,{})[nm.split(":")[-1]]=txt
                for ctx,v in byctx.items():
                    if "TradingSymbol" in v or "Security12bTitle" in v:
                        rr.append({"cik":int(cik),"accn":acc,"accepted":fil["accepted"],"filed":fil["filed"],"form":fil["form"],"context_ref":ctx,"trading_symbol":v.get("TradingSymbol",""),"security_title":v.get("Security12bTitle",""),"source_file":name})
        rows.extend(rr)
    except Exception as e:err=repr(e)[:500]
    aud.append({"cik":int(cik),"rows":len(rr),"error":err})
d=pd.DataFrame(rows)
if d.empty:d=pd.DataFrame(columns=["cik","accn","accepted","filed","form","context_ref","trading_symbol","security_title","source_file"])
d=d.drop_duplicates()
d.to_csv(OUT/"security_titles.csv",index=False)
pd.DataFrame(aud).to_csv(OUT/"audit.csv",index=False)
summary={"schema":"V4_SECURITY_TITLE_EXTRACT_V1","target_ciks":len(T["ciks"]),"rows":len(d),"ciks_with_rows":int(d.cik.nunique()) if len(d) else 0,"errors":sum(bool(x["error"]) for x in aud),"formation_2023_opened":False,"future_outcomes_used":False,"us3700_used":False,"new_corp_action_lookup_calls":0}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2));print(d.head(200).to_string(index=False))
