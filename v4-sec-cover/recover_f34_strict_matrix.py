from __future__ import annotations
import base64, json, math, re, threading, time, zlib, hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
import requests

OUT=Path("v4-sec-f34-strict-recovery-output"); OUT.mkdir(parents=True,exist_ok=True)
SNAPS=["2020-03-31","2020-06-30","2020-09-30","2020-12-31","2021-03-31","2021-06-30","2021-09-30","2021-12-31","2022-03-31","2022-06-30","2022-09-30","2022-12-30"]
TARGET_B64="eNo1mkmW7CoSBTcUA9HDWv6p/W+j7JrnG2RYIiEEjuMN6L921vfr7dxff/v9xlzjN1s/vzknP++bv/Vu++3+8XPn+p0x+u/M0X53n+93b7u/+6j8vtd/b/T9a99c+T1v/Vrf6/H7aLPNfjq/5+P/tRt3d9vfr53RBr938ntb6tw+uH7nu/y+tPlma/md+9e/3jq/q6fvY05+916/3mf+H9Til1H9+qQvv77o76/vbzHMnfb7PpdnT8bH76PNtwb/v/et/F5k8e2+fqP1wS8Pz98Y7fI/LQ8k9d37G6s3rp+T67Yz7slTbx/ERz8bv2uM/CK8+R3ayaOX33epQ3c3v15ZH+Oa+6Nv87Q8ezKKeRZCnren/r3IBLkgk/XlXeu7e/xWazO/nQlcPZJf/dHmmpPW1koPF4M4/N5Dnf2Y9IWEOzM855ffXHk8/dvfYVy7vbuZ+o5k9vyosxH/+G2q8P86+d0fI9p73M7vypVzGNG+C0nuy9O/87UoTu/M++kDaZz+vhFV+t7vrMjq7MFbzpln83tz5X6pc1u//J5JTQT2fvebff5upvx35x1cWW+jjheNQBU/5g6FzPVHE79c2L/XZnv5ZRSvPdp8fSCZN1ARfhca+9bXqbOZNn7PG/zS0O8xC9y9feZ3jJvfjZZ+32J6wEW67Wt0HIwT3WW+W0prM6727YivfY9igKRQ2jUZA213usNEj+h2X3tSOuvSu0GjKC3LI7PLT//E/XJx3dXBRVPR0I/3B43eD1RjUFpZToJOoKz0CYyPhTMWq/uKldK6Lfe2U0Ij6A4YZwaP8R3EsgMWd+b0DKuclZlBArwWnR2ZObSQxY0K9cvjDZ3Kxd0y80zbDA6aH7w1oxoMIrrRLY3NOjh9RrUQZt/RlW/ulNr9uDf6aX84miSMFy12JuDM2Vuw7cTcd6T06FOwWQKHFcnYD0qdEW1m6gtUVqwckjj7jUdNXrOjkQi9BZdpPKxHZoXZbukSGsEyPPfuPIcBYWme118kQSPM0cF4sTLA2Lk4WVlg2TS6gN6i2yNjf69RBb1l9IBWO7gxq2BGz7GzaMhF0bDEzBqmNFhVYi0A1KAFWTyXSdm5N2PdwUIEt63vBfv5+J1ZWr19eRFmi+kIspY63eS5Tis0hkmdNIYFWFmFrEwewEpi5YFND/qX0viOiFVGAQeyZpD2bKDe1MSopCZqjTIAjABAaLmI8cnaRlkDlgBdwvJgvi+vOTTGom1dpC8Yszik9aL6FxOmj2oXHcRCYhLAjB25e/eXeziwLboXT7q0900JvcqgMbDpYCxVSnOmZzFSPE4F1A1Thd4BZiqlG0+HnWrp/GWwR8uEQc4SQaHByRxRfeQi0orxGm+mtHphvfjW7fzx+kiXN2VWaHvkcVzVF3M3MjCWMuvvPhwt/YyC9GBlwjFuIz567Awa4U4NZFT4svZXLuI4dhAjCU5e+3aP2rydZQFiBHgr/inAfGJaP9Y/YOFNMB8T/j6ceu7tvB2cLxcvncHyYgZjjL8dK0qg0Qt7FwgjUOR1xY3B3nPlIjMcw80c5eLpuLCHks/YcSxuC6YlxtUD3xCrGnTbRL8YJsafDgO6f2P6D3OLdEbeMLACufgesn74aHSXvzhRJggbATa2EjBzuZgZCNrSFXwx5iGuQ2JswhY/H8YchUgt7LvKq6N2cMeUxaWsm/r5T7b4VthR/XCwHuXUE7VxfT/R1XhFPU3EKHezXezutR1k7XVUfMpX9R8LDybGynVsgO0jz6/Ke8TXxZlbDzt1JVFBOJBgOI3+cKgxF9iq/CsJNOXued/otBTOW/VWIk25j870U24j5jnEJk45HC/eezd5E2cSG9T9SZjh/VH9xvR93mfu8j6kVs9v4iH57C9xV+/yOm7sU+LOb31DueNYn6T/EsO39PaJHCFrZ5fbv8VEOpA13OW1nZinLa/vY6W3J5/ztfvfdRqwHoHWkk+5ETMpJ4rqEVxXDufjoDdNducLt9160eeh+nkamh5OTF5IkJj+HaxUyngi9QCxKz9Mmfp6R2JqOHGJYQLBkAVvhPPVvLD07pNbeaZ7xaX8yyolIjrKh8g78X8WwpXIZYXdfjLxic6aE37lwqBA3XzLQOq+0WA4u/djdsMXN9vyQOY1N6yHxxuSTOUL8el5rk31guUXUwxZ1unX3zrCQ86EgPRSPYcz8mjJqVIf7Y48WtZF6sd9Fle33owzaInb5yoeyztRd/hWld/xPubE991nf0ZWVrjVLxivSWdatx94LPuJmCJvmJg+1sR1C3f0CKM5s+5D+7vu8Tn8tOPHHw2f47Wpv/FokktTHvuze7IviMfsUnuEGb+2m0zBett5b/t+9fzTfsDnffTXceGHs64x4/Xes5bzdQxUIf3/4/Q5s9LwOL8n/hLiEr2Pb4tciZZH5Nljby0f7UZ3ZckT+SQSyjh7JszycV4YpXLD8X19ycQgLRFsl8v+w/iT8GX9Edq+2A+M94k9wylO30v2FftIntmjvxD/HrbkS1GHuBlIN/I8YUr0HiNJ8CN35J3Etln/uU7o3hc7n3A56zgON9kJ/nNnPul2sz3CquX16zqMi8x8Qdc1PNHLMHrFZKgXWKkdfexELD5/zTTDG3vWCWFGsSunxFfp18Xp9mJyfNjtN9ax2iE2tMw/to9fukXvP8yS+wpE6WnvlV3Hubju4Rx/nPIlpOUPyz3D4Z4DWYX2IiQThmS1Xsf3pxzPm/rYg+gLacC3vE5qforH8jYVJD3Rn0HtQHYMMv+ECtN2kEL6h/eedX2YOxIEvmkZN9+legvf9rmdvDZsGWe4//iKZ/hcMiS54j+zamKnB4KIvqBMCdVi7PQXWCXtHc4y0Rq8SYkgBjxMhpR2p/sg0EgxUYd6NPCXSXpx39oHaGY8/vymy6DLcau8fc8yw4T00DIK/8kWew9X9A0n3+O/4a7r2QoIUUTbQy/CHZMtt+P686N05vP5nYQlnFO57pnEEy792cA7ZT3C67yQ/isXvJDyqJ0M+Go+WVeOIwnwksnXw2c7pLTvyRt/ihU8/+g40PLt86SSTe7rc0t/gBNw3cChfmZ/xHIWsnzK+ySEL6q/PL29/1yHI9MvsWi5Th6mHiK1Kq+rviTcTP+QbvGWHPHntl+7JaH+eTzyubTDulNv33qxAyPrzXosc++f0mesuvLHm8bOwZd+TaK7vC9M+/DlORbfiD+ZBpLh0B7PhDFD7uXzOJId3mQiuL1PezITIU45e5W1dzMBQNpLhFHMrlS4TpV39JC36B8nK6F7HTdm+SQZbtkxiP+C7bP+1d6RP63le19S02zYZJcyPH+81scaZ55IHV2f4S327nNx8OEwT5i4lcgvvKdY99dctrezGxD+tb+TT2YHZlV7+MGUMXyxAzN24JPGe0ym+Ql02wquW8yGSei6QJm+2N05Kp6F2skZ+3GKx3o3uz3hKr4aF7TdTGPeR8eKU/1idWo/knAtr2MWU3+5cwoj+J97GLf4hvdZrp+8zm/sgRzuJ8NXRJ0+ab4z915PHu0cZk0/AE/0Gitf80zqb7snFX9a/cQ50LgJXuVN3Dzd4zY7hEkzpX5v3gSSxVs0ryFff3V/lt7gNxP3EJUnuQ1Lj7OzIK/xAFnHU97EN8qXOHtZZn3kvSy3kedfAgo5sn4wyyfyXUn4Xkh8McPyD7GKmVdmWz3NNkHWG7T/0Ph5ZZO8qHxWEpEbHv1WNqfruZfNmfBFniuZVU4BiJysn0ikyze8j2IOqX1aWWGWl3nrSoC4i93njv59GTCGt/rdssEC+1f1yZZ8D+ZwWG6j7nf9OcHbPJaZ8SarP3/rDhofrPjhJ/ussus8O+PPdmt9wBU7kn2r7xWX9clfrfdK3gQcma8wdmiNCEg6vyyi9+Q03oa97k/zwIUjrefclwtf4pFsojgurFfWycLAxi5C/dZCAR0XivIs40bSbwSvvBbhRdpXgLLZjwhsyen8r7GVgw2GOYQIt/E/xqHZj3XMk6Dx71rER95/+tOV9CTtEs0qf5j1CUevU6P9R/PPFXez5U3cvZLOez+Jh9yJl+iGcR93tddEWUs9gPGTdEu/kuw96xo+nzuZEGlcnjQ+djLpU9VzAy089vOsqz6f2m+BxtHhtb097f/Z+jmeqnGeN+u5d4b1X73/fk09YbnHvqyYxbpungOv+sWv6y3HJV7vxrfQeAU+10PsTMZ9UbAjzZvw4kv9JI53nSVsrbL2kuhAu7+SHnj/GG8mPTz/aDvZ1f4lXax+Pk+SQvc9yILcl9Jcf8XldRR9yRs7hTKW3GnO/hFnKF/U1PVCuuj7HwmP17dxV1j1yC+K5nfQ+BbeqndL3qjbX3lXu1c7vN6bjv8hNvvxXAc57cr6CCP/nQ27P07vZ0mFQ/sKlcuOHZ3SdQKzYSt33Xf9E6R75olT3vWcp2mhcQtWPCd8oXlp0vB67hlnQf3jdoOkmPhoZ7+jytf+tmYes5OZH2m8vBPhWC+WXubQx3Paz+d2zl7DUe2R9vrcdr8MYeXcoyX8dvxE75nvnTBnFmeVtcs74c6T6vfuQ/2BxsnwdTlHXceT2s4qeSf/8fl9lQu0/5jzbvnM4/O3HeuTBx7Zsx52TnmPND5lVCt6sJPQZbyjq//ZzjjFEb8Bt/LHLjsO4qfYOzirjAc8xcQvOwce1t+lP8RNy/ropfePfnInwP9j9Q//lXEkfsp1Al/rZX8n9wkQHR/uwPEbEIYeiYWvrk/j8hzgVv3pvuQ2sJLmTzD7++Gq5z2JCI2zs/0Q+82icf8N5fn+uOp5lrfPYZAy/gQoU566/nLmHuGal+8EDrfo+ojfucXEF3DGToWjymv/Y/oRB/79ccg1bHfU+3Gc13aH++Zoq/nWzjaSzyUSkO4z4T70/3A5zxh89R1/5TgxoK6XGMq0g3+Kvd3Zz817WGC2w0JSjjsfJUj3hUL1BK1Tz3YyE3nsRzout/lt3Ff89s5ZldfPp1x2EsLwfvUcfm1J45GNOfQ92f/ZcrlecsZqmYWSdgkvHS/RjnaIcFZ7Q/SrfOM2bafOsbPN5PgxT+ojYY1yPeeoT6f2D+F2/PnE4hWv7b0c3YSj6vklQ5I/452dbYQjl/qNNVPvGJ7zebPDJq/2izBK/b5H/8yg9Hc76Y71c9IVvrLLMe+p/8rv72wLWW7m00Sv7j9kl/1Uef6V3e/I9rryz3cDXp/GT9B95p301uvL84n9WM5d6q/y1YV6g3mMX4y3ilyYVeOIE/9RPLELCNU8SB6pvc42/v3j8/mp3Qhj30O/rGGY0YeT+Nx2y0+ebOf7HAFM0bgUam9Z1eOzfo5jIVFT9CRhUvQKvuH1bjx5/uJ3onDX08mOifdRwyv16yeRj+Wd7zdgJlaaV0Dn9bScnEvjuzD+mMG53wpX1t3pfgPT8p2Mcsv2c+SCWzmteKs8lXNH76c0P2E5uK9/ejJfuXorHtsnY7L9VV8qsYxXleeosv4qVC689Vm+OfkNzdtjRez/yNaYvM5HthemnH4D9Rfnn2y0Hel+6MmGl/cr34Dug51sMFmv4jJovB+uv7JyHDl6ldP5GcQ1VVbvw9j1ZPOOY/p1QbiUZ9KvPId/WcUXe3aS8Ft/6N/g+6w/d11PZll0fvBSjmsmogpR5/RzXv2yZsd69/xdr/ZWTkyl9iha6zyuOmdh9OZzJwlHlzX+5SF2OJ/tbPMljIP74nDaj1V+l0XnvvnJfrzlp1+G5hc5LfG5nZNOaZycUwj1BLVWjwlLEh+F8bvxisoNB+48x5Gnv9lfTL8wCM7P8fudlt7YH9RJeaHoscsn+YnXh+e60Hwin6SoR9hVx3/rPAsa1x2iTfWZWXRebz6k8Zs7zzNjlRzXrXMoOB3vrf30UL2Fq8plT4he1Rvsb7VzzBuzS/vZfkYaPs9/4dlF84ZYG/uB1qo/2Fnn9/2tizdLDvk4Lf3L/v4r1nPHeCxRp3blVX53En7aPgmG11/pM2o+q1x68+o8AffjOUa4ZXM/8eajLssxCDJfGsKxojdxV1nvN199eX+YJ4RZXzcHztafZ0oycuuRz/je7fkdzIdCLbva3fIxziWKyncaYT7hkvV+vwPMZpj24bZaHzcn+V16PnQ9EZXa5VilbbmPP7rvcVudS/K2OX1+G/fdRDJ/X2V226/zphvNrOv6GZJ+z+2zm2C/89mNfK3qPeOz+/cdZ5i45uZAzn6+W/2rcx7oPlJY/cdchLH3eT7nrVu6nxX1jl7Bm3V7s69azLczofFQ+Py+tK96rnsOeeMu5HB/OnT+EdOq71FftTc9F7jxA/aHcNv7u/Sj1zl4qFz6KT2Cznv2h7x+Xc+wbd97zaeg+VHCm1H33e/Kt5/DdmofnWVsfhv6vSzeOusvaf0fja+g+St8zefq/B4a70HXhV8h1f1Z7XbzRpKPv3aH54f5jMv5wlveW3x1vfR8+BEdXJ6f3+xLWa/8Y1jtHc87bvyT5btrHEy77Ty/VwiTN1z8Ui+an0HziEutz+uol18MN/MUPynr0n02eJQvozvW85s4OLUjkfq1nel5YrZD6vnldyKh84b/GlW+yovhKodZ+woxp/HTKHHNQ77UzXP57O3Jbv9IC52H9bm/L73eav1C5Uo04vytyiPgiF9DO0q/CTNblc1H4VWv1ig9xYw73rVG3V/u82Adh+sYv6jcwlO8dX1/9m/7fdBdx31Hj3d93y25EF6qFwtH4HN/87c/9wXgtt7OhxlFx7eb5xLx9tqvmMFV1B7hNdRL3Ha1s9yvuvnEOOPYe9Vz2zwop/7qz679V5jP3OB1n/ImQdhF7ejOQfMfM84kAGG+Vc59rKL6cPKhUThrPhOYWF7m7bg3z0mg+1xui6Ufp75TymeBPocDcL5jwOR0H5Fo13jv5lPBLv2OIF9dqPeveU53yUds9/n1LTzu4+XUT7uSzyaQA2mN34vkK5zM28uOKPdzfBf7/shOYm8eVvG8//0fhsuUzw=="
TARGET_CIKS=json.loads(zlib.decompress(base64.b64decode(TARGET_B64)).decode())
EXCLUDED={815094,1082923,1135185}
TARGET_CIKS=[int(x) for x in TARGET_CIKS if int(x) not in EXCLUDED]
FORMS={"10-Q","10-K","10-Q/A","10-K/A"}
UA="V4-Full-Rigor-NEXT1 strict SEC PIT recovery"
SESSION=requests.Session(); SESSION.headers.update({"User-Agent":UA,"Accept-Encoding":"gzip, deflate","Accept":"application/json"})
LOCK=threading.Lock(); LAST=[0.0]

REVENUE_TAGS=[
 ("RevenueFromContractWithCustomerExcludingAssessedTax",0),
 ("RevenueFromContractWithCustomerIncludingAssessedTax",1),
 ("Revenues",2),("SalesRevenueNet",3),
 ("RegulatedAndUnregulatedOperatingRevenue",4),
]
CFO_TOTAL="NetCashProvidedByUsedInOperatingActivities"
CFO_CONT="NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"
CFO_DISC="CashProvidedByUsedInOperatingActivitiesDiscontinuedOperations"
CAPEX="PaymentsToAcquirePropertyPlantAndEquipment"
SH_DIL="WeightedAverageNumberOfDilutedSharesOutstanding"
SH_COMB="WeightedAverageNumberOfShareOutstandingBasicAndDiluted"
SH_BASIC="WeightedAverageNumberOfSharesOutstandingBasic"
NEEDED={x for x,_ in REVENUE_TAGS}|{CFO_TOTAL,CFO_CONT,CFO_DISC,CAPEX,SH_DIL,SH_COMB,SH_BASIC}

def wait_rate():
    with LOCK:
        dt=time.monotonic()-LAST[0]
        if dt<0.13: time.sleep(0.13-dt)
        LAST[0]=time.monotonic()

def get_json(url,attempts=5):
    last=""
    for i in range(attempts):
        try:
            wait_rate(); r=SESSION.get(url,timeout=45)
            if r.status_code in {429,500,502,503,504}: raise RuntimeError(f"HTTP_{r.status_code}")
            r.raise_for_status(); return r.json()
        except Exception as e:
            last=repr(e)[:300]
            if i<attempts-1: time.sleep(min(20,1.5*(2**i)))
    raise RuntimeError(last)

def ymd(x):
    s=str(x or "")[:10]
    return int(s.replace("-","")) if len(s)==10 and s[4]=="-" else 0

def accint(x):
    s=str(x or "")
    d="".join(ch for ch in s if ch.isdigit())
    if len(d)>=14:return int(d[:14])
    if len(d)>=8:return int(d[:8]+"235959")
    return 0

def ord8(v):
    s=str(int(v))
    try:return date(int(s[:4]),int(s[4:6]),int(s[6:8])).toordinal()
    except:return None

def qtrs_from(start,end):
    try:
        ds=date.fromisoformat(str(start)[:10]); de=date.fromisoformat(str(end)[:10]); days=(de-ds).days+1
    except:return 0
    if 60<=days<=125:return 1
    if 126<=days<=220:return 2
    if 221<=days<=320:return 3
    if 321<=days<=410:return 4
    return 0

def parse_acceptance_map(obj):
    if not isinstance(obj,dict):return {}
    a=obj.get("filings",{}).get("recent",{}) if isinstance(obj.get("filings"),dict) else obj
    acc=list(a.get("accessionNumber") or []); accepted=list(a.get("acceptanceDateTime") or [])
    out={}
    for i,ac in enumerate(acc):
        ac=str(ac or "").strip()
        if ac: out[ac]=str(accepted[i] if i<len(accepted) else "").strip()
    return out

def latest(raw,cutoff,roles):
    best={}
    for r in raw:
        if r["role"] not in roles or r["accepted"]<=0 or r["accepted"]>cutoff:continue
        k=(r["role"],r["end"],r["qtrs"])
        cand=(r["accepted"],-r["priority"],r["value"])
        old=best.get(k)
        if old is None or cand[:2]>old[:2]:best[k]=cand
    return {k:v[2] for k,v in best.items()}

def discrete(best,role,avg=False):
    byq={1:[],2:[],3:[],4:[]}
    for (rr,dd,q),val in best.items():
        if rr==role and q in byq:byq[q].append((dd,val))
    for q in byq:byq[q].sort()
    out={}
    for dd,val in byq[1]:out[dd]=(1,val)
    for k in (2,3,4):
        prev=byq[k-1]
        for dd,val in byq[k]:
            d1=ord8(dd); candidates=[]
            for pdd,pval in prev:
                if pdd>=dd:continue
                d0=ord8(pdd)
                if d0 is None or d1 is None:continue
                gap=d1-d0
                if 60<=gap<=125:candidates.append((gap,pdd,pval))
            if not candidates:continue
            _,pdd,pval=min(candidates,key=lambda x:x[0])
            v=(k*val-(k-1)*pval) if avg else (val-pval)
            if not math.isfinite(v):continue
            old=out.get(dd); cand=(0,v)
            if old is None or cand[0]>old[0]:out[dd]=cand
    return {dd:v for dd,(_,v) in sorted(out.items())}

def valid(ds):
    if len(ds)<2:return True
    o=[ord8(x) for x in ds]
    return all(x is not None for x in o) and all(65<=o[i+1]-o[i]<=125 for i in range(len(o)-1))

def eval_f3(raw,snap):
    cutoff=int(snap.replace("-","")+"235959"); si=int(snap.replace("-",""))
    roles={"REVENUE","CFO_TOTAL","CFO_CONT","CFO_DISC","CAPEX"}
    b=latest(raw,cutoff,roles)
    # Revenue cross-tag latest with semantic priority already embedded in raw priority.
    revbest={}
    for r in raw:
        if r["role"]!="REVENUE" or r["accepted"]<=0 or r["accepted"]>cutoff:continue
        k=("REVENUE",r["end"],r["qtrs"]); cand=(r["accepted"],-r["priority"],r["value"])
        old=revbest.get(k)
        if old is None or cand[:2]>old[:2]:revbest[k]=cand
    for k,v in revbest.items():b[k]=v[2]
    # exact CFO composition: total CFO preferred; otherwise continuing + discontinued only when same period/qtrs.
    tot=discrete(b,"CFO_TOTAL",False)
    cont=discrete(b,"CFO_CONT",False); disc=discrete(b,"CFO_DISC",False)
    for dd in set(cont)&set(disc):
        if dd not in tot: tot[dd]=cont[dd]+disc[dd]
    rev=discrete(b,"REVENUE",False); cap=discrete(b,"CAPEX",False)
    q=[d for d in sorted(rev) if d<=si]
    if len(q)<4:return False,"REVENUE_LT4"
    last=q[-4:]
    if not valid(last):return False,"REVENUE_GAP"
    if any(d not in tot for d in last):return False,"CFO_MISSING"
    if any(d not in cap for d in last):return False,"CAPEX_MISSING"
    rv=[rev[d] for d in last];cv=[tot[d] for d in last];pv=[cap[d] for d in last]
    if any((not math.isfinite(x)) for x in rv+cv+pv) or any(x==0 for x in rv):return False,"INVALID"
    return True,("NONPOSITIVE_CFO" if sum(cv)<=0 else "OK")

def eval_f4(raw,snap):
    cutoff=int(snap.replace("-","")+"235959"); si=int(snap.replace("-",""))
    b=latest(raw,cutoff,{"DILUTED","COMBINED","BASIC"})
    for role,method in [("DILUTED","DILUTED"),("COMBINED","BASIC_DILUTED_COMBINED"),("BASIC","BASIC_FALLBACK")]:
        h=discrete(b,role,True); ds=[d for d in sorted(h) if d<=si]
        if len(ds)<6:continue
        last=ds[-6:]
        if not valid(last):continue
        vals=[h[d] for d in last]
        if all(math.isfinite(x) for x in vals) and vals[0]>0 and vals[1]>0:return True,method
    return False,"NO_VALID_6Q"

def process(cik):
    cik10=f"{cik:010d}"; audit={"cik":cik,"status":"OK","facts":0,"accepted_missing":0,"archive_files":0,"error":""}
    try:
        cf=get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json")
        us=((cf.get("facts") or {}).get("us-gaap") or {})
        temp=[]
        for tag in NEEDED:
            concept=us.get(tag) or {}
            for unit,items in (concept.get("units") or {}).items():
                ul=str(unit).lower().strip()
                if ul not in {"usd","shares","share"} or not isinstance(items,list):continue
                for x in items:
                    form=str(x.get("form") or "").upper().strip()
                    filed=str(x.get("filed") or "")[:10]; end=str(x.get("end") or "")[:10]; start=str(x.get("start") or "")[:10]
                    if form not in FORMS or not filed or filed>"2022-12-31" or not end or end>"2022-12-31" or end<"2017-01-01":continue
                    q=qtrs_from(start,end)
                    if q not in {1,2,3,4}:continue
                    try:v=float(x.get("val"))
                    except:continue
                    if not math.isfinite(v):continue
                    if tag in dict(REVENUE_TAGS):role="REVENUE";pri=dict(REVENUE_TAGS)[tag]
                    elif tag==CFO_TOTAL:role="CFO_TOTAL";pri=0
                    elif tag==CFO_CONT:role="CFO_CONT";pri=0
                    elif tag==CFO_DISC:role="CFO_DISC";pri=0
                    elif tag==CAPEX:role="CAPEX";pri=0
                    elif tag==SH_DIL:role="DILUTED";pri=0
                    elif tag==SH_COMB:role="COMBINED";pri=0
                    elif tag==SH_BASIC:role="BASIC";pri=0
                    else:continue
                    temp.append({"role":role,"priority":pri,"end":ymd(end),"qtrs":q,"value":v,"accn":str(x.get("accn") or "").strip(),"filed":filed})
        audit["facts"]=len(temp)
        needed={r["accn"] for r in temp if r["accn"]}
        sub=get_json(f"https://data.sec.gov/submissions/CIK{cik10}.json")
        amap=parse_acceptance_map(sub); missing=needed-set(amap)
        files=((sub.get("filings") or {}).get("files") or []) if isinstance(sub,dict) else []
        if missing:
            minfile=min([r["filed"] for r in temp if r["filed"]] or ["2017-01-01"])
            maxfile=max([r["filed"] for r in temp if r["filed"]] or ["2022-12-31"])
            for meta in files:
                if not missing:break
                name=str(meta.get("name") or "").strip(); frm=str(meta.get("filingFrom") or ""); to=str(meta.get("filingTo") or "")
                if not name or (frm and frm>maxfile) or (to and to<minfile):continue
                try:
                    old=get_json("https://data.sec.gov/submissions/"+name);audit["archive_files"]+=1
                    amap.update(parse_acceptance_map(old));missing=needed-set(amap)
                except:pass
        raw=[]
        for r in temp:
            a=accint(amap.get(r["accn"],""))
            if not a:audit["accepted_missing"]+=1
            raw.append({**r,"accepted":a})
        f3=[];f4=[];fm=[]
        for s in SNAPS:
            a,b=eval_f3(raw,s); c,d=eval_f4(raw,s)
            f3.append(bool(a));f4.append(bool(c));fm.append(d)
        return cik,f3,f4,fm,audit
    except Exception as e:
        audit["status"]="ERROR";audit["error"]=repr(e)[:400]
        return cik,[False]*len(SNAPS),[False]*len(SNAPS),["ERROR"]*len(SNAPS),audit

res={}; audits=[]
with ThreadPoolExecutor(max_workers=6) as ex:
    futs={ex.submit(process,c):c for c in TARGET_CIKS}
    for i,f in enumerate(as_completed(futs),1):
        cik,a,b,m,au=f.result();res[cik]=(a,b,m);audits.append(au)
        if i%100==0:print("PROGRESS",i,"/",len(TARGET_CIKS),flush=True)

def pack(bits):
    by=bytearray((len(bits)+7)//8)
    for i,v in enumerate(bits):
        if v:by[i//8]|=1<<(i%8)
    return base64.b64encode(bytes(by)).decode()

payload={"schema":"V4_NEXT1_STRICT_CF_RECOVERY_BITMASK_V1","target_count":len(TARGET_CIKS),
 "target_sha256":hashlib.sha256(json.dumps(TARGET_CIKS,separators=(",",":")).encode()).hexdigest(),
 "snapshots":SNAPS,"new_corp_action_lookup_calls":0,"excluded_ciks":sorted(EXCLUDED),
 "formation_2023_opened":False,"future_outcomes_used":False,"us3700_used":False,
 "by_snapshot":[],"fetch_errors":sum(a["status"]!="OK" for a in audits)}
for j,s in enumerate(SNAPS):
    fb=[res.get(c,([False]*12,[False]*12,[]))[0][j] for c in TARGET_CIKS]
    sb=[res.get(c,([False]*12,[False]*12,[]))[1][j] for c in TARGET_CIKS]
    methods={}
    for c in TARGET_CIKS:
        m=res.get(c,([],[],["ERROR"]*12))[2][j];methods[m]=methods.get(m,0)+1
    payload["by_snapshot"].append({"snapshot_date":s,"f3_usable_b64":pack(fb),"f4_usable_b64":pack(sb),
      "f3_usable_target_ciks":sum(fb),"f4_usable_target_ciks":sum(sb),"f4_methods":methods})
(OUT/"recovery_bitmask.json").write_text(json.dumps(payload,indent=2),encoding="utf-8")
(OUT/"fetch_audit.json").write_text(json.dumps(audits,indent=2),encoding="utf-8")
print(json.dumps({k:v for k,v in payload.items() if k!="by_snapshot"}|{"snapshot_counts":[{k:v for k,v in x.items() if not k.endswith("_b64")} for x in payload["by_snapshot"]]},indent=2))
