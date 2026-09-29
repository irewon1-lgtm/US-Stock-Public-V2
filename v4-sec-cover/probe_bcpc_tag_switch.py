from __future__ import annotations
import io,re,json,zipfile,requests,time
from lxml import etree
from pathlib import Path

UA="V4-Full-Rigor BCPC tag-switch probe research@example.com"
S=requests.Session(); S.headers.update({"User-Agent":UA,"Accept-Encoding":"gzip, deflate"})
XL="{http://www.w3.org/1999/xlink}"
CIK=9326
ACCNS=[
"0001628280-19-013298",
"0001628280-20-001968",
"0001628280-20-006067",
"0001628280-20-011128",
"0001628280-20-014967",
"0001628280-21-002578",
"0001628280-21-008430",
"0001628280-21-015025",
"0001628280-21-020827",
"0001628280-22-003669",
"0001628280-22-011502",
"0001628280-22-019804",
"0001628280-22-028416",
]
def get(url):
    r=S.get(url,timeout=60); print("GET",url,r.status_code,len(r.content),flush=True); r.raise_for_status(); time.sleep(.15); return r
def root(data): return etree.fromstring(data,parser=etree.XMLParser(recover=True,huge_tree=True))
def labels(z):
    out={}
    for n in z.namelist():
        if not n.endswith("_lab.xml"): continue
        rt=root(z.read(n))
        for link in rt.xpath("//*[local-name()='labelLink']"):
            loc={}; lab={}
            for x in link.xpath("./*[local-name()='loc']"):
                h=x.get(XL+"href") or ""; k=x.get(XL+"label") or ""
                if k and "#" in h: loc[k]=h.split("#")[-1]
            for x in link.xpath("./*[local-name()='label']"):
                k=x.get(XL+"label") or ""; t=" ".join("".join(x.itertext()).split()); role=x.get(XL+"role") or ""
                if k and t: lab[k]=(t,role)
            for x in link.xpath("./*[local-name()='labelArc']"):
                c=loc.get(x.get(XL+"from") or ""); p=lab.get(x.get(XL+"to") or "")
                if c and p: out.setdefault(c,[]).append(p)
    return out
def cashflow_concepts(z):
    roles={}; pres=[]
    for n in z.namelist():
        if n.endswith(".xsd"):
            try: rt=root(z.read(n))
            except: continue
            for el in rt.xpath("//*[local-name()='roleType']"):
                uri=el.get("roleURI") or ""; ds=el.xpath("./*[local-name()='definition']/text()")
                if uri: roles[uri]=" ".join(str(x) for x in ds)
    for n in z.namelist():
        if not n.endswith("_pre.xml"): continue
        rt=root(z.read(n))
        for link in rt.xpath("//*[local-name()='presentationLink']"):
            uri=link.get(XL+"role") or ""; rd=(roles.get(uri,"")+" "+uri).lower()
            if "cash" not in rd: continue
            loc={}
            for x in link.xpath("./*[local-name()='loc']"):
                h=x.get(XL+"href") or ""; k=x.get(XL+"label") or ""
                if k and "#" in h: loc[k]=h.split("#")[-1]
            order={}
            for x in link.xpath("./*[local-name()='presentationArc']"):
                to=loc.get(x.get(XL+"to") or "")
                try:o=float(x.get("order") or 0)
                except:o=0
                if to: order[to]=o
            for c in set(loc.values()):
                pres.append((c,roles.get(uri,""),order.get(c,9999)))
    return pres
def contexts(rt):
    out={}
    for c in rt.xpath("//*[local-name()='context']"):
        cid=c.get("id") or ""; starts=c.xpath(".//*[local-name()='startDate']/text()"); ends=c.xpath(".//*[local-name()='endDate']/text()"); inst=c.xpath(".//*[local-name()='instant']/text()"); dims=c.xpath(".//*[local-name()='explicitMember' or local-name()='typedMember']")
        out[cid]={"start":str(starts[0])[:10] if starts else "","end":str(ends[0])[:10] if ends else (str(inst[0])[:10] if inst else ""),"dim":bool(dims)}
    return out
for acc in ACCNS:
    ad=acc.replace("-",""); url=f"https://www.sec.gov/Archives/edgar/data/{CIK}/{ad}/{acc}-xbrl.zip"
    try:z=zipfile.ZipFile(io.BytesIO(get(url).content))
    except Exception as e: print("ZIPERR",acc,repr(e)); continue
    lbs=labels(z); pres=cashflow_concepts(z)
    wanted={c for c,role,o in pres}
    print("\n### ACCESSION",acc,"CASH_CONCEPTS",len(wanted))
    for c,role,o in sorted(pres,key=lambda x:(x[1],x[2],x[0])):
        ls=lbs.get(c,[])
        if ls:
            print("PRES",o,c,"|",role,"|"," || ".join(t for t,r in ls[:3]))
    # inline facts for cash-flow-presented concepts
    for n in z.namelist():
        if not n.lower().endswith((".htm",".html")): continue
        try:rt=root(z.read(n))
        except:continue
        ctx=contexts(rt)
        for el in rt.xpath("//*[local-name()='nonFraction']"):
            q=el.get("name") or ""
            if ":" not in q: continue
            local=q.split(":",1)[1]
            candidates=[c for c in wanted if c.endswith("_"+local) or c==local]
            if not candidates: continue
            cr=ctx.get(el.get("contextRef") or "",{})
            if cr.get("dim"): continue
            txt=" ".join("".join(el.itertext()).split())
            labs=" || ".join(t for t,r in lbs.get(candidates[0],[])[:3])
            if re.search(r"capital|property|equipment|fixed asset|purchase|addition",labs+" "+local,re.I):
                print("FACT",q,cr.get("start"),cr.get("end"),txt,"|",labs)
