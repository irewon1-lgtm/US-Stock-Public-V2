import io, zipfile, requests, re
from lxml import etree
UA="V4-Full-Rigor CAL probe research@example.com"; H={"User-Agent":UA,"Accept-Encoding":"gzip, deflate"}
cik=6201; acc="0000006201-22-000086"; ad=acc.replace("-","")
url=f"https://www.sec.gov/Archives/edgar/data/{cik}/{ad}/{acc}-xbrl.zip"
r=requests.get(url,headers=H,timeout=60); print("ZIP",r.status_code,len(r.content)); r.raise_for_status()
z=zipfile.ZipFile(io.BytesIO(r.content)); XL="{http://www.w3.org/1999/xlink}"
def root(name): return etree.fromstring(z.read(name),parser=etree.XMLParser(recover=True,huge_tree=True))
# labels
labels={}
for n in z.namelist():
 if not n.endswith("_lab.xml"): continue
 rt=root(n)
 for link in rt.xpath("//*[local-name()='labelLink']"):
  loc={}; lab={}
  for x in link.xpath("./*[local-name()='loc']"):
   h=x.get(XL+"href") or ""; k=x.get(XL+"label") or ""
   if k and "#" in h: loc[k]=h.split("#")[-1]
  for x in link.xpath("./*[local-name()='label']"):
   k=x.get(XL+"label") or ""; txt=" ".join("".join(x.itertext()).split()); role=x.get(XL+"role") or ""
   if k and txt: lab[k]=(txt,role)
  for x in link.xpath("./*[local-name()='labelArc']"):
   c=loc.get(x.get(XL+"from") or ""); p=lab.get(x.get(XL+"to") or "")
   if c and p: labels.setdefault(c,[]).append(p)
# print capex-ish concepts
keys=[c for c,ls in labels.items() if any(re.search(r"capital expenditure|property.*equipment|aircraft.*purchase|purchase.*aircraft",t,re.I) for t,_ in ls)]
print("KEYS",len(keys))
for c in keys:
 print("CONCEPT",c)
 for t,role in labels[c]: print("  LABEL",role,t)
# calculation arcs touching those concepts
for n in z.namelist():
 if not n.endswith("_cal.xml"): continue
 rt=root(n)
 for link in rt.xpath("//*[local-name()='calculationLink']"):
  role=link.get(XL+"role") or ""; loc={}
  for x in link.xpath("./*[local-name()='loc']"):
   h=x.get(XL+"href") or ""; k=x.get(XL+"label") or ""
   if k and "#" in h: loc[k]=h.split("#")[-1]
  arcs=[]
  for x in link.xpath("./*[local-name()='calculationArc']"):
   fr=loc.get(x.get(XL+"from") or ""); to=loc.get(x.get(XL+"to") or ""); w=x.get("weight") or ""
   if fr and to and (fr in keys or to in keys): arcs.append((fr,to,w))
  if arcs:
   print("CALROLE",role)
   for a in arcs: print("  ARC",a)
