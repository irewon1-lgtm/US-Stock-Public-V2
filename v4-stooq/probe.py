import requests, pathlib
url="https://stooq.com/q/d/l/"
params={"s":"ae.us","d1":"20190901","d2":"20230105","i":"d"}
r=requests.get(url,params=params,timeout=30,headers={"User-Agent":"Mozilla/5.0"})
pathlib.Path("v4-stooq-probe-output").mkdir(exist_ok=True)
pathlib.Path("v4-stooq-probe-output/challenge.html").write_text(r.text,encoding="utf-8")
print("status",r.status_code,"len",len(r.text))
print(r.text)
