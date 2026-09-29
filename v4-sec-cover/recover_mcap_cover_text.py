from __future__ import annotations
import argparse,json,re,time,threading
from pathlib import Path
from dateutil import parser as dtparser
import pandas as pd, requests
from lxml import html

ROOT=Path(".")
TARGET=json.loads((ROOT/"v4-sec-cover/mcap_cover_text_targets.json").read_text())
OUT=ROOT/"v4-sec-mcap-cover-text-output"; OUT.mkdir(exist_ok=True)
FORMS={"10-Q","10-K","10-Q/A","10-K/A","20-F","20-F/A","40-F","40-F/A"}
UA="V4-Full-Rigor cover-text shares research@example.com"
S=requests.Session(); S.headers.update({"User-Agent":UA,"Accept-Encoding":"gzip, deflate","Accept":"text/html,application/xhtml+xml"})
LOCK=threading.Lock(); LAST=[0.0]
MONTHS="January|February|March|April|May|June|July|August|September|October|November|December"
DATE_RE=re.compile(rf"\b(?:{MONTHS})\s+\d{{1,2}},\s+20\d{{2}}\b",re.I)
NUM_RE=re.compile(r"(?<![\d.])(?:\d{1,3}(?:,\d{3})+|\d{6,})(?![\d.])")
COMMON_RE=re.compile(r"\bcommon\s+(?:stock|shares?)\b",re.I)
OUT_RE=re.compile(r"\boutstanding\b",re.I)
SHARES_RE=re.compile(r"\bshares?\b",re.I)
BAD_CLASS_RE=re.compile(r"\b(?:class\s+[a-z]|series\s+[a-z0-9]|preferred|depositary|warrant|unit)\b",re.I)

def wait():
    with LOCK:
        dt=time.monotonic()-LAST[0]
        if dt<0.22: time.sleep(0.22-dt)
        LAST[0]=time.monotonic()

def get(url,timeout=45,attempts=4):
    last=""
    for i in range(attempts):
        try:
            wait(); r=S.get(url,timeout=timeout)
            if r.status_code==404:return None
            if r.status_code in {429,500,502,503,504}: raise RuntimeError(f"HTTP_{r.status_code}")
            r.raise_for_status(); return r
        except Exception as e:
            last=repr(e)[:400]
            if i<attempts-1: time.sleep(min(12,1.5*(2**i)))
    raise RuntimeError(last)

def get_json(url):
    r=get(url)
    if r is None: raise RuntimeError("NOT_FOUND "+url)
    return r.json()

def rows_block(a):
    keys=["accessionNumber","acceptanceDateTime","filingDate","form","primaryDocument"]
    n=max([len(a.get(k) or []) for k in keys]+[0]); out=[]
    for i in range(n):
        def v(k):
            z=a.get(k) or []
            return str(z[i] if i<len(z) else "").strip()
        form=v("form").upper(); acc=v("accessionNumber"); primary=v("primaryDocument")
        if form not in FORMS or not acc or not primary: continue
        accepted=v("acceptanceDateTime"); filed=v("filingDate")
        ds=(accepted or filed)[:10]
        if not ds or ds<"2018-01-01" or ds>"2022-12-30": continue
        out.append({"accn":acc,"accepted":accepted,"filed":filed,"form":form,"primary":primary})
    return out

def filings(cik):
    sub=get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    out=rows_block(((sub.get("filings") or {}).get("recent") or {}))
    for meta in ((sub.get("filings") or {}).get("files") or []):
        name=str(meta.get("name") or "").strip()
        if not name: continue
        frm=str(meta.get("filingFrom") or ""); to=str(meta.get("filingTo") or "")
        if frm and frm>"2022-12-30": continue
        if to and to<"2018-01-01": continue
        try:
            old=get_json("https://data.sec.gov/submissions/"+name)
            out.extend(rows_block(old if isinstance(old,dict) else {}))
        except: pass
    d={}
    for x in out:d[x["accn"]]=x
    return sorted(d.values(),key=lambda x:(x.get("accepted") or x.get("filed") or "",x["accn"]))

def clean_text(blob):
    try:
        doc=html.fromstring(blob)
        for bad in doc.xpath("//script|//style|//noscript"): bad.drop_tree()
        txt=doc.text_content()
    except Exception:
        txt=blob.decode("utf-8","ignore") if isinstance(blob,(bytes,bytearray)) else str(blob)
    txt=re.sub(r"\s+"," ",txt)
    return txt

def parse_window(w):
    if not COMMON_RE.search(w) or not OUT_RE.search(w) or not SHARES_RE.search(w): return []
    if BAD_CLASS_RE.search(w): return []
    dates=DATE_RE.findall(w)
    nums=NUM_RE.findall(w)
    nums=[int(x.replace(",","")) for x in nums if int(x.replace(",",""))>=1000]
    dates=list(dict.fromkeys(dates)); nums=list(dict.fromkeys(nums))
    if len(dates)!=1 or len(nums)!=1: return []
    try: dd=pd.Timestamp(dtparser.parse(dates[0])).normalize()
    except: return []
    return [(dd,nums[0])]

def extract(text,cik,fil):
    rows=[]; seen=set()
    # Sentence-like windows around each 'outstanding'; strict single date + single large integer + common stock.
    for m in OUT_RE.finditer(text):
        a=max(0,m.start()-380); b=min(len(text),m.end()+380); w=text[a:b]
        for dd,num in parse_window(w):
            key=(dd.date().isoformat(),num)
            if key in seen: continue
            seen.add(key)
            rows.append({"cik":cik,"accn":fil["accn"],"accepted":fil["accepted"],"filed":fil["filed"],"form":fil["form"],
                         "primary":fil["primary"],"share_date":dd.date().isoformat(),"shares":num,
                         "context":w[:900],"rule":"STRICT_SINGLE_COMMON_STOCK_OUTSTANDING_DATE_AND_COUNT"})
    return rows

def one(cik):
    rows=[]; aud={"cik":cik,"status":"OK","filings":0,"docs_ok":0,"candidates":0,"error":""}
    try:
        fs=filings(cik); aud["filings"]=len(fs)
        for f in fs:
            ad=f["accn"].replace("-","")
            url=f"https://www.sec.gov/Archives/edgar/data/{cik}/{ad}/{f['primary']}"
            r=get(url,60)
            if r is None: continue
            aud["docs_ok"]+=1
            text=clean_text(r.content)
            rows.extend(extract(text,cik,f))
        aud["candidates"]=len(rows)
    except Exception as e:
        aud["status"]="ERROR"; aud["error"]=repr(e)[:500]
    return rows,aud

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--shard",type=int,required=True); ap.add_argument("--nshards",type=int,default=4)
    a=ap.parse_args()
    ciks=[int(c) for c in TARGET["ciks"] if int(c)%a.nshards==a.shard]
    rows=[]; audits=[]
    for i,cik in enumerate(ciks,1):
        rr,aa=one(cik); rows.extend(rr); audits.append(aa)
        if i%10==0: print("PROGRESS",a.shard,i,"/",len(ciks),"candidates",len(rows),flush=True)
    d=pd.DataFrame(rows)
    if d.empty:d=pd.DataFrame(columns=["cik","accn","accepted","filed","form","primary","share_date","shares","context","rule"])
    d.to_csv(OUT/f"cover_text_shares_{a.shard:02d}.csv.gz",index=False,compression="gzip")
    pd.DataFrame(audits).to_csv(OUT/f"audit_{a.shard:02d}.csv",index=False)
    summary={"schema":"V4_MCAP_COVER_TEXT_SHARD_V1","shard":a.shard,"target_ciks":len(ciks),"candidate_rows":int(len(d)),
             "ciks_with_candidates":int(d.cik.nunique()) if len(d) else 0,"fetch_errors":sum(x["status"]!="OK" for x in audits),
             "formation_2023_opened":False,"future_outcomes_used":False,"us3700_used":False,"new_corp_action_lookup_calls":0}
    (OUT/f"summary_{a.shard:02d}.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print(json.dumps(summary,indent=2),flush=True)
if __name__=="__main__":main()
