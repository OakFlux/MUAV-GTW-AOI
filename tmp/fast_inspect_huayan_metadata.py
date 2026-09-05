from __future__ import annotations
import html,json,re,time
from pathlib import Path
from urllib.parse import urljoin,quote
import httpx

OUT=Path('out_huayan_metadata_fast'); OUT.mkdir(exist_ok=True)
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
c=httpx.Client(http2=True,follow_redirects=True,timeout=httpx.Timeout(60,connect=20),headers={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9,en;q=0.8'})

# Inspect report pages for public static file metadata and Next.js data.
for rid in ['5435007','5497229','5587624']:
    u=f'https://www.fxbaogao.com/detail/{rid}'
    r=c.get(u,headers={'Referer':'https://www.fxbaogao.com/'})
    print('\nFXPAGE',rid,r.status_code,len(r.content),r.url,r.headers.get('content-type'))
    OUT.joinpath(f'fx_{rid}.html').write_bytes(r.content)
    t=r.text
    for pat in [r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});']:
        m=re.search(pat,t,re.I|re.S)
        if m:
            v=html.unescape(m.group(1)); OUT.joinpath(f'fx_{rid}_data.txt').write_text(v,encoding='utf-8')
            print('DATA',rid,len(v),v[:2000])
    values=set()
    for pat in [r'https?://[^"\'<>\\\s]+',r'(?:href|src|data-[\w-]+|content)=["\']([^"\']+)["\']',r'["\']([^"\']*(?:pdf|download|file|attachment|source|oss|cos|storage|reportId)[^"\']*)["\']']:
        for x in re.findall(pat,t,re.I):
            x=html.unescape(x if isinstance(x,str) else x[0]).strip()
            if x: values.add(urljoin(str(r.url),x))
    interesting=sorted(v for v in values if any(k in v.lower() for k in ['.pdf','download','file','attachment','source','oss','cos','storage','api','report-image']))
    print('VALUES',rid,json.dumps(interesting[:500],ensure_ascii=False))
    for term in ['pdfUrl','fileUrl','downloadUrl','sourceUrl','attachment','reportId','ossKey','objectKey','.pdf','infoCode','5497229','5435007','5587624']:
        for m in list(re.finditer(re.escape(term),t,re.I))[:30]:
            print('CTX',rid,term,t[max(0,m.start()-600):m.end()+1400].replace('\n',' ')[:2400])

# Eastmoney: scan narrow date windows without a stock filter for matching HK reports.
windows=[('2026-05-20','2026-05-29'),('2026-06-20','2026-07-02'),('2026-08-01','2026-08-14')]
for begin,end in windows:
    matches=[]
    for page in range(1,31):
        params={'code':'','pageSize':'100','pageNo':str(page),'beginTime':begin,'endTime':end,'qType':'0','fields':'','industryCode':'*','industry':'*','rating':'*','ratingChange':'*','orgCode':'','rcode':'','p':str(page),'pageNum':str(page),'pageNumber':str(page)}
        try:
            r=c.get('https://reportapi.eastmoney.com/report/list',params=params,headers={'Referer':'https://data.eastmoney.com/report/'})
            obj=r.json(); data=obj.get('data') or []
            print('EM_PAGE',begin,end,page,r.status_code,len(data),obj.get('TotalPage'),obj.get('hits'))
            for item in data:
                blob=json.dumps(item,ensure_ascii=False)
                if any(k in blob for k in ['华沿机器人','華沿機器人','01021','1021.HK','1021HK']):
                    matches.append(item); print('EM_MATCH',json.dumps(item,ensure_ascii=False))
            if not data or page >= int(obj.get('TotalPage') or obj.get('totalPage') or 9999): break
        except Exception as e:
            print('EM_ERR',begin,end,page,repr(e)); break
    OUT.joinpath(f'em_{begin}_{end}.json').write_text(json.dumps(matches,ensure_ascii=False,indent=2),encoding='utf-8')

# Sina report search by HK symbols and exact titles; inspect any matching report pages for PDF links.
queries=[
 'http://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?symbol=hk01021&orgname=&industry=&title=&t1=all',
 'http://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?symbol=01021&orgname=&industry=&title=&t1=all',
 'http://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?symbol=&orgname=&industry=&title='+quote('华沿机器人')+'&t1=all',
 'http://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?symbol=&orgname=&industry=&title='+quote('七轴人形手臂')+'&t1=all',
]
rpt_urls=set()
for i,u in enumerate(queries):
    try:
        r=c.get(u,headers={'Referer':'https://finance.sina.com.cn/'})
        print('SINA_LIST',i,r.status_code,len(r.content),r.url,r.encoding)
        r.encoding='gbk' if 'gb' in (r.headers.get('content-type') or '').lower() else r.encoding
        t=r.text; OUT.joinpath(f'sina_list_{i}.html').write_text(t,encoding='utf-8',errors='ignore')
        for x in re.findall(r'href=["\']([^"\']*vReport_Show[^"\']*)["\']',t,re.I): rpt_urls.add(urljoin(str(r.url),html.unescape(x)))
        for term in ['华沿机器人','七轴人形手臂','具身智能空间广阔','卖铲人']:
            if term in t:
                print('SINA_HAS',i,term)
    except Exception as e: print('SINA_LIST_ERR',i,repr(e))
print('SINA_RPTS',json.dumps(sorted(rpt_urls),ensure_ascii=False))
for i,u in enumerate(sorted(rpt_urls)):
    try:
        r=c.get(u,headers={'Referer':'https://stock.finance.sina.com.cn/'})
        t=r.text; OUT.joinpath(f'sina_rpt_{i}.html').write_text(t,encoding='utf-8',errors='ignore')
        if not any(k in t for k in ['华沿机器人','華沿機器人','七轴人形手臂','具身智能空间广阔','卖铲人']): continue
        print('SINA_REPORT_MATCH',i,r.status_code,len(r.content),r.url)
        vals=sorted(set(urljoin(str(r.url),html.unescape(x)) for x in re.findall(r'(?:href|src)=["\']([^"\']+)["\']',t,re.I)))
        print('SINA_REPORT_URLS',json.dumps([x for x in vals if any(k in x.lower() for k in ['pdf','download','file','attach'])],ensure_ascii=False))
    except Exception as e: print('SINA_RPT_ERR',i,repr(e))

# SGPJBG source, only to identify public metadata (do not access gated file endpoints).
u='https://www.sgpjbg.com/bgdown/1272177.html'
r=c.get(u,headers={'Referer':'https://www.sgpjbg.com/'})
print('SGP',r.status_code,len(r.content),r.url)
OUT.joinpath('sgp.html').write_bytes(r.content)
for term in ['1272177','.pdf','file_url','download_url','pdfUrl','sourceUrl','oss']:
    for m in list(re.finditer(re.escape(term),r.text,re.I))[:30]: print('SGP_CTX',term,r.text[max(0,m.start()-500):m.end()+1200].replace('\n',' ')[:2000])

c.close(); print('DONE')
