import io,zipfile,requests
from lxml import etree
UA="V4-Full-Rigor BCPC rendered-row probe research@example.com";H={"User-Agent":UA}
CIK=9326
for acc in ["0001628280-19-013298","0001628280-20-001968","0001628280-20-006067","0001628280-20-014967","0001628280-21-002578","0001628280-21-008430"]:
 ad=acc.replace("-","");u=f"https://www.sec.gov/Archives/edgar/data/{CIK}/{ad}/{acc}-xbrl.zip"
 r=requests.get(u,headers=H,timeout=60);print("\nACC",acc,r.status_code);r.raise_for_status();z=zipfile.ZipFile(io.BytesIO(r.content))
 for n in z.namelist():
  if not n.lower().endswith((".htm",".html")):continue
  try:rt=etree.fromstring(z.read(n),parser=etree.XMLParser(recover=True,huge_tree=True))
  except:continue
  for el in rt.xpath("//*[local-name()='nonFraction']"):
   name=el.get("name") or ""
   if name.endswith(":PaymentsToAcquireOtherProductiveAssets"):
    trs=el.xpath("ancestor::*[local-name()='tr'][1]")
    node=trs[0] if trs else el.getparent()
    row=" ".join("".join(node.itertext()).split()) if node is not None else ""
    print("ROW",n,el.get("contextRef") or "","|",row[:2500])
