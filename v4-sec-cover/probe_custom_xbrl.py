import io, zipfile, requests, re, xml.etree.ElementTree as ET
UA="V4-Full-Rigor custom-XBRL probe research@example.com"; H={"User-Agent":UA,"Accept-Encoding":"gzip, deflate"}
cik=6201; acc="0000006201-22-000086"; ad=acc.replace("-","")
url=f"https://www.sec.gov/Archives/edgar/data/{cik}/{ad}/{acc}-xbrl.zip"
r=requests.get(url,headers=H,timeout=60); print("ZIP",r.status_code,len(r.content),r.headers.get("content-type")); r.raise_for_status()
z=zipfile.ZipFile(io.BytesIO(r.content)); print("FILES",z.namelist())
need=re.compile(r"(capital|property|plant|equipment|weighted average|diluted|operating activities|revenue|sales)",re.I)
for name in z.namelist():
    if not name.lower().endswith((".xml",".xsd")): continue
    try: txt=z.read(name).decode("utf-8","ignore")
    except: continue
    hits=[]
    for line in txt.splitlines():
        plain=re.sub(r"<[^>]+>"," ",line)
        plain=re.sub(r"\s+"," ",plain).strip()
        if need.search(plain):
            hits.append(plain[:1000])
    if hits:
        print("\n###",name,"HITS",len(hits))
        for h in hits[:80]: print(h)
