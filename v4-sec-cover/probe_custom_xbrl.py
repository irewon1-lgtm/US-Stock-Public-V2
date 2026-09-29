import json, requests, re
UA="V4-Full-Rigor custom-XBRL probe research@example.com"
H={"User-Agent":UA,"Accept-Encoding":"gzip, deflate"}
cik=6201
s=requests.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json",headers=H,timeout=30); print("SUB",s.status_code); s.raise_for_status(); j=s.json()
r=j["filings"]["recent"]
pick=None
for i,(form,fd,acc,pd) in enumerate(zip(r["form"],r["filingDate"],r["accessionNumber"],r["primaryDocument"])):
    if form in {"10-Q","10-K"} and fd<="2022-12-30":
        pick=(form,fd,acc,pd); break
print("PICK",pick)
form,fd,acc,pd=pick
ad=acc.replace("-","")
base=f"https://www.sec.gov/Archives/edgar/data/{cik}/{ad}/"
for url in [base+"index.json",base+pd]:
    x=requests.get(url,headers=H,timeout=30)
    print("GET",url,x.status_code,x.headers.get("content-type"),len(x.content))
    print(x.text[:500].replace("\n"," ") if x.text else "")
