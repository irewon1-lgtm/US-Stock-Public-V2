import json,requests,time
from pathlib import Path
OUT=Path("v4-wayback-probe-output");OUT.mkdir(exist_ok=True)
T=["ADMS","AERI","AGN","ATVI","AIMC"]
CDX="https://web.archive.org/cdx/search/cdx"
patterns=[
 ("old_real","real-chart.finance.yahoo.com/table.csv?s={t}"),
 ("old_ichart","ichart.finance.yahoo.com/table.csv?s={t}"),
 ("download_v7","query1.finance.yahoo.com/v7/finance/download/{t}*"),
 ("chart_v8","query1.finance.yahoo.com/v8/finance/chart/{t}*"),
 ("history_html","finance.yahoo.com/quote/{t}/history*"),
]
H={"User-Agent":"Mozilla/5.0 V4 research"}
rows=[]
for t in T:
  for kind,p in patterns:
    url=p.format(t=t)
    params={"url":url,"output":"json","fl":"timestamp,original,statuscode,mimetype,length","filter":"statuscode:200","limit":20,"from":"2019","to":"2023"}
    try:
      r=requests.get(CDX,params=params,headers=H,timeout=45)
      item={"ticker":t,"kind":kind,"status":r.status_code,"bytes":len(r.content)}
      if r.status_code==200:
        try:
          j=r.json()
          snaps=j[1:] if isinstance(j,list) and len(j)>1 else []
          item["snapshots"]=len(snaps)
          item["first"]=snaps[:3]
          item["last"]=snaps[-3:] if snaps else []
        except Exception as e:item["parse_error"]=repr(e);item["prefix"]=r.text[:500]
      else:item["prefix"]=r.text[:500]
      rows.append(item)
    except Exception as e:rows.append({"ticker":t,"kind":kind,"error":repr(e)})
    time.sleep(.2)
(OUT/"probe.json").write_text(json.dumps(rows,indent=2),encoding="utf-8")
print(json.dumps(rows,indent=2)[:30000])
