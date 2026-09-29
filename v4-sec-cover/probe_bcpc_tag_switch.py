import io,zipfile,requests
from lxml import etree
UA="V4-Full-Rigor BCPC preferred-label probe research@example.com";H={"User-Agent":UA}
XL="{http://www.w3.org/1999/xlink}"
CIK=9326
for acc in ["0001628280-19-013298","0001628280-20-001968","0001628280-20-006067","0001628280-20-014967","0001628280-21-002578"]:
 ad=acc.replace("-","");u=f"https://www.sec.gov/Archives/edgar/data/{CIK}/{ad}/{acc}-xbrl.zip"
 r=requests.get(u,headers=H,timeout=60);print("\nACC",acc,r.status_code);r.raise_for_status();z=zipfile.ZipFile(io.BytesIO(r.content))
 labels={}
 for n in z.namelist():
  if not n.endswith("_lab.xml"):continue
  rt=etree.fromstring(z.read(n),parser=etree.XMLParser(recover=True,huge_tree=True))
  for link in rt.xpath("//*[local-name()='labelLink']"):
   loc={};lab={}
   for x in link.xpath("./*[local-name()='loc']"):
    h=x.get(XL+"href") or "";k=x.get(XL+"label") or ""
    if k and "#" in h:loc[k]=h.split("#")[-1]
   for x in link.xpath("./*[local-name()='label']"):
    k=x.get(XL+"label") or "";role=x.get(XL+"role") or "";txt=" ".join("".join(x.itertext()).split())
    if k:lab[k]=(role,txt)
   for x in link.xpath("./*[local-name()='labelArc']"):
    c=loc.get(x.get(XL+"from") or "");p=lab.get(x.get(XL+"to") or "")
    if c and p:labels.setdefault(c,[]).append(p)
 target="us-gaap_PaymentsToAcquireOtherProductiveAssets"
 print("LABELS",target,labels.get(target))
 for n in z.namelist():
  if not n.endswith("_pre.xml"):continue
  rt=etree.fromstring(z.read(n),parser=etree.XMLParser(recover=True,huge_tree=True))
  for link in rt.xpath("//*[local-name()='presentationLink']"):
   loc={}
   for x in link.xpath("./*[local-name()='loc']"):
    h=x.get(XL+"href") or "";k=x.get(XL+"label") or ""
    if k and "#" in h:loc[k]=h.split("#")[-1]
   for x in link.xpath("./*[local-name()='presentationArc']"):
    to=loc.get(x.get(XL+"to") or "")
    if to==target:
     pref=x.get("preferredLabel") or ""
     print("PRE ARC role",link.get(XL+"role"),"preferredLabel",pref,"order",x.get("order"))
     if pref:
      print("PREFERRED TEXT",[txt for role,txt in labels.get(target,[]) if role==pref])
