"""Read-only adapters for public fundamental statistics pages.

No login, API key, proxy, captcha bypass, or anti-bot circumvention is used.
If a public page refuses access, callers keep the prior verified observation.
"""
from __future__ import annotations
import random,re,time,urllib.error,urllib.parse,urllib.request
from html.parser import HTMLParser

UA='Mozilla/5.0 (compatible; AIRankerPublicFundamentals/1.0; +https://github.com/irewon1-lgtm/Ai-rank-android)'
FINVIZ='https://finviz.com/quote.ashx?t={ticker}&p=d'
STOCKANALYSIS='https://stockanalysis.com/stocks/{slug}/statistics/'
MISSING={'-','—','N/A','n/a','NA'}
class PublicSourceError(RuntimeError): pass
class _Cells(HTMLParser):
    def __init__(self): super().__init__(convert_charrefs=True); self.in_td=0; self.buf=[]; self.cells=[]; self.text=[]
    def handle_starttag(self,tag,attrs):
        if tag.lower() in {'td','th'}: self.in_td+=1; self.buf=[]
    def handle_endtag(self,tag):
        if tag.lower() in {'td','th'} and self.in_td:
            t=' '.join(' '.join(self.buf).split())
            if t:self.cells.append(t)
            self.in_td-=1;self.buf=[]
    def handle_data(self,data):
        t=' '.join(data.split())
        if t:self.text.append(t)
        if self.in_td and t:self.buf.append(t)
def _tokens(page): p=_Cells();p.feed(page);return p.cells,p.text
def _number(s):
    if s is None:return None
    s=str(s).strip().replace(',','').replace('−','-')
    if s in MISSING or not s:return None
    s=re.sub(r'[$€£]','',s).replace('%','').replace('x','').strip();m=re.search(r'[-+]?\d+(?:\.\d+)?',s)
    return float(m.group()) if m else None
def _percent_from_composite(s):
    if s is None:return None
    matches=re.findall(r'([-+−]?\d+(?:\.\d+)?)\s*%',str(s))
    if not matches:return None
    return float(matches[-1].replace('−','-'))
def _value_after(tokens,label,max_gap=5):
    wanted=label.lower()
    for i,t in enumerate(tokens):
        if t.strip().lower()==wanted:
            for j in range(i+1,min(len(tokens),i+1+max_gap)):
                if _number(tokens[j]) is not None or tokens[j] in MISSING:return tokens[j]
    return None
def parse_finviz(page):
    cells,text=_tokens(page);tokens=cells or text
    labels={'Revenue_TTM_YoY_Pct':'Sales Y/Y TTM','Gross_Margin_TTM_Pct':'Gross Margin','Operating_Margin_TTM_Pct':'Oper. Margin','Net_Margin_TTM_Pct':'Profit Margin','ROA_TTM_Pct':'ROA','TTM_PER':'P/E','Price_Sales_TTM':'P/S','Drawdown_52W_Pct':'52W High'}
    out={}
    for key,label in labels.items():
        raw=_value_after(tokens,label)
        if key=='Drawdown_52W_Pct':
            pct=_percent_from_composite(raw);v=abs(pct) if pct is not None and pct<0 else (0.0 if pct is not None else None)
        else:v=_number(raw)
        out[key]={'raw':raw,'value':v}
    epsraw=_value_after(tokens,'EPS (ttm)') or _value_after(tokens,'EPS TTM');out['_eps_ttm']={'raw':epsraw,'value':_number(epsraw)}
    if not any(v['raw'] is not None for k,v in out.items() if not k.startswith('_')):raise PublicSourceError('FINVIZ_FIELDS_NOT_FOUND')
    return out
def parse_stockanalysis(page):
    cells,text=_tokens(page);tokens=cells if cells else text;out={};flat=' | '.join(text)
    for key,labels in {'FCF_Yield_TTM_Pct':['FCF Yield','Free Cash Flow Yield'],'Shares_Change_YoY_Pct':['Shares Change (YoY)','Shares Change YoY']}.items():
        raw=None
        for label in labels:
            raw=_value_after(tokens,label)
            if raw is not None:break
        if raw is None:
            for label in labels:
                m=re.search(re.escape(label)+r'.{0,160}?([-+−]?\d+(?:\.\d+)?\s*%|N/A|n/a|—|-)',flat,re.I)
                if m:raw=m.group(1);break
        out[key]={'raw':raw,'value':_number(raw)}
    if not any(v['raw'] is not None for v in out.values()):raise PublicSourceError('STOCKANALYSIS_FIELDS_NOT_FOUND')
    return out
def _fetch(url,timeout=20,attempts=2):
    last=None
    for attempt in range(attempts):
        time.sleep(random.uniform(0.15,0.35))
        req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'text/html,application/xhtml+xml','Accept-Language':'en-US,en;q=0.8'})
        try:
            with urllib.request.urlopen(req,timeout=timeout) as r:
                body=r.read(4_000_001)
                if len(body)>4_000_000:raise PublicSourceError('BODY_TOO_LARGE')
                return body.decode('utf-8','replace')
        except urllib.error.HTTPError as e:
            last=e
            if e.code in {401,403}:raise PublicSourceError(f'PUBLIC_ACCESS_REFUSED_{e.code}')
            if e.code==429 and attempt+1<attempts:
                try:delay=min(30.0,max(1.0,float(e.headers.get('Retry-After') or 3)))
                except Exception:delay=3.0
                time.sleep(delay);continue
            if e.code==429:raise PublicSourceError('PUBLIC_ACCESS_REFUSED_429')
            raise PublicSourceError(f'HTTP_{e.code}')
        except (TimeoutError,urllib.error.URLError) as e:
            last=e
            if attempt+1<attempts:time.sleep(1.0+attempt);continue
            raise PublicSourceError(type(e).__name__)
        except PublicSourceError:raise
        except Exception as e:raise PublicSourceError(type(e).__name__)
    raise PublicSourceError(type(last).__name__ if last else 'FETCH_FAILED')
def fetch_finviz(ticker):
    url=FINVIZ.format(ticker=urllib.parse.quote(str(ticker).upper(),safe='.-'));return url,parse_finviz(_fetch(url))
def _stockanalysis_slugs(ticker):
    """Return public-page slug candidates without bypassing access controls.

    Our canonical universe uses dash-form share classes (for example MOG-A),
    while StockAnalysis publishes those pages with a dot-form symbol (MOG.A).
    Try the canonical spelling first, then the documented dot-form class symbol.
    """
    raw=str(ticker).strip().lower().replace('/','-')
    out=[raw]
    if re.fullmatch(r'[a-z0-9]+-[a-z]',raw):out.append(raw.rsplit('-',1)[0]+'.'+raw.rsplit('-',1)[1])
    return list(dict.fromkeys(out))
def fetch_stockanalysis(ticker):
    last=None
    for slug in _stockanalysis_slugs(ticker):
        url=STOCKANALYSIS.format(slug=urllib.parse.quote(slug,safe='.-'))
        try:return url,parse_stockanalysis(_fetch(url))
        except PublicSourceError as e:
            last=e
            if str(e)!='HTTP_404':raise
    raise last or PublicSourceError('HTTP_404')
def _cell(value,source_url,as_of,reason='Public page direct metric'):return {'status':'NUMERIC','value':float(value),'reason':reason,'asOf':as_of,'sourceUrls':[source_url],'sourceType':'PUBLIC_PAGE_DIRECT'}
def _na(display,reason,source_url=None,as_of=None):return {'status':'NA_BASIS','value':None,'displayValue':display,'reason':reason,'asOf':as_of,'sourceUrls':[source_url] if source_url else [],'sourceType':'PUBLIC_PAGE_DIRECT'}
def _hold(reason,as_of=None):return {'status':'HOLD','value':None,'reason':reason,'asOf':as_of,'sourceUrls':[],'sourceType':'PUBLIC_PAGE_DIRECT'}
def collect_ticker(identity,as_of,previous=None,fetchers=None):
    ticker=str(identity['ticker']).upper();sector=str(identity.get('sector') or identity.get('category') or '');previous=(previous or {}).get('metrics') or {};metrics={};errors=[]
    ff,ss=(fetchers or {}).get('finviz',fetch_finviz),(fetchers or {}).get('stockanalysis',fetch_stockanalysis)
    try:
        fu,f=ff(ticker)
        for key in ['Revenue_TTM_YoY_Pct','Gross_Margin_TTM_Pct','Operating_Margin_TTM_Pct','Net_Margin_TTM_Pct','ROA_TTM_Pct','Price_Sales_TTM','Drawdown_52W_Pct']:
            row=f.get(key,{}) ;v=row.get('value');raw=row.get('raw')
            if v is not None:metrics[key]=_cell(v,fu,as_of)
            elif raw in MISSING:metrics[key]=_na('N/A','공개 페이지가 해당 지표를 N/A로 표시',fu,as_of)
            else:metrics[key]=_hold('FINVIZ_VALUE_UNAVAILABLE',as_of)
        perow=f.get('TTM_PER',{});pe=perow.get('value');eps=f.get('_eps_ttm',{}).get('value')
        if pe is not None and pe>0:metrics['TTM_PER']=_cell(pe,fu,as_of)
        elif eps is not None and eps<=0:metrics['TTM_PER']=_na('적자','TTM EPS가 양수가 아니어서 PER 비적용',fu,as_of)
        elif perow.get('raw') in MISSING:metrics['TTM_PER']=_na('N/A','공개 페이지가 PER을 N/A로 표시',fu,as_of)
        else:metrics['TTM_PER']=_hold('FINVIZ_PER_UNAVAILABLE',as_of)
    except Exception as e:errors.append('FINVIZ:'+str(e))
    try:
        su,s=ss(ticker)
        for key in ['FCF_Yield_TTM_Pct','Shares_Change_YoY_Pct']:
            row=s.get(key,{});v=row.get('value');raw=row.get('raw')
            if v is not None:metrics[key]=_cell(v,su,as_of)
            elif raw in MISSING:metrics[key]=_na('N/A','공개 페이지가 해당 지표를 N/A로 표시',su,as_of)
            else:metrics[key]=_hold('STOCKANALYSIS_VALUE_UNAVAILABLE',as_of)
    except Exception as e:errors.append('STOCKANALYSIS:'+str(e))
    if re.search(r'financial|bank|insurance|은행|보험',sector,re.I):
        if metrics.get('Gross_Margin_TTM_Pct',{}).get('status')!='NUMERIC':metrics['Gross_Margin_TTM_Pct']=_na('업종 N/A','금융업은 Gross Margin 공통비교 비적용',as_of=as_of)
        if metrics.get('FCF_Yield_TTM_Pct',{}).get('status')=='HOLD':metrics['FCF_Yield_TTM_Pct']=_na('업종 N/A','금융업은 FCF Yield 공통순위 비적용',as_of=as_of)
    for key in ['Revenue_TTM_YoY_Pct','Gross_Margin_TTM_Pct','Operating_Margin_TTM_Pct','Net_Margin_TTM_Pct','ROA_TTM_Pct','FCF_Yield_TTM_Pct','TTM_PER','Price_Sales_TTM','Shares_Change_YoY_Pct','Drawdown_52W_Pct']:
        if key not in metrics or metrics[key].get('status')=='HOLD':
            old=previous.get(key)
            if old and old.get('status') in {'NUMERIC','NA_BASIS'}:metrics[key]=dict(old,reason='최신 공개페이지 수집 실패로 직전 검증값 유지')
            elif key not in metrics:metrics[key]=_hold('; '.join(errors)[:300] or 'PUBLIC_SOURCE_UNAVAILABLE',as_of)
    return {**identity,'ticker':ticker,'metrics':metrics,'collectionErrors':errors}
