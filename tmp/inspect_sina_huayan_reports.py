from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import httpx

OUT=Path('out_huayan_sina_hkreports')
OUT.mkdir(exist_ok=True)
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
client=httpx.Client(http2=True,follow_redirects=True,timeout=httpx.Timeout(60,connect=20),headers={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'})

known_ids=['839511181107']
listing_urls=[
 'https://stock.finance.sina.com.cn/hkstock/news/01021.html',
 'https://stock.finance.sina.com.cn/hkstock/news/01021_2.html',
 'https://stock.finance.sina.com.cn/hkstock/news/01021_3.html',
 'https://stock.finance.sina.com.cn/hkstock/news/01021_4.html',
 'https://stock.finance.sina.com.cn/hkstock/news/01021_5.html',
 'https://stock.finance.sina.com.cn/hkstock/view/hk_report.php?symbol=01021',
]
patterns=['reportid','pdf','download','file','attach','research','研报','报告原文','report_url','reporturl','docurl','doc_url']
report_ids=set(known_ids)
list_rows=[]

for i,url in enumerate(listing_urls):
    try:
        r=client.get(url)
        raw=r.content
        enc='gb18030' if b'charset=gb' in raw[:5000].lower() else (r.encoding or 'utf-8')
        try:text=raw.decode(enc,errors='ignore')
        except:text=r.text
        (OUT/f'listing_{i}.html').write_text(text,encoding='utf-8')
        print('LIST',i,r.status_code,r.headers.get('content-type'),len(r.content),r.url)
        ids=set(re.findall(r'(?:reportid=|report_id["\':= ]+)(\d{6,})',text,re.I))
        report_ids.update(ids)
        links=set(re.findall(r'https?://[^"\'<>\s]+',text))
        links.update(urljoin(str(r.url),html.unescape(x)) for x in re.findall(r'(?:href|src|data-url|data-file|content)=["\']([^"\']+)["\']',text,re.I))
        relevant=[]
        for x in sorted(links):
            if 'hk_report' in x or 'reportid=' in x:
                relevant.append(x)
                m=re.search(r'reportid=(\d+)',x)
                if m: report_ids.add(m.group(1))
                print('LIST_REPORT_LINK',i,x)
        list_rows.append({'url':url,'final_url':str(r.url),'status':r.status_code,'ids':sorted(ids),'report_links':relevant})
    except Exception as exc:
        print('LIST_ERR',i,url,repr(exc))
        list_rows.append({'url':url,'error':repr(exc)})

# Search endpoint variants that may return Hong Kong report metadata.
api_urls=[]
for page in range(1,11):
    api_urls.extend([
      f'https://stock.finance.sina.com.cn/hkstock/api/openapi.php/HK_StockService.getReport?symbol=01021&page={page}&num=100',
      f'https://stock.finance.sina.com.cn/hkstock/api/openapi.php/HK_StockService.getReports?symbol=01021&page={page}&num=100',
      f'https://stock.finance.sina.com.cn/hkstock/api/openapi.php/HK_StockService.getReportList?symbol=01021&page={page}&num=100',
      f'https://stock.finance.sina.com.cn/hkstock/api/jsonp.php/var%20data=/HK_StockService.getReport?symbol=01021&page={page}&num=100',
    ])
api_rows=[]
for idx,url in enumerate(api_urls):
    try:
        r=client.get(url,headers={'Accept':'application/json,text/javascript,*/*'})
        text=r.text
        if r.status_code==200 and len(text)>20:
            print('API',idx,r.status_code,r.headers.get('content-type'),len(r.content),r.url,text[:700].replace('\n',' '))
            (OUT/f'api_{idx}.txt').write_text(text,encoding='utf-8',errors='ignore')
            ids=set(re.findall(r'(?:reportid|report_id)["\':= ]+(\d{6,})',text,re.I))
            report_ids.update(ids)
            api_rows.append({'url':url,'status':r.status_code,'bytes':len(r.content),'ids':sorted(ids),'preview':text[:5000]})
    except Exception as exc: print('API_ERR',idx,url,repr(exc))

# Inspect each candidate report page, but keep only pages that actually mention Huayan or target titles.
report_rows=[]
seen_urls=set()
for rid in sorted(report_ids):
    urls=[
      f'https://stock.finance.sina.com.cn/hkstock/view/hk_report.php?reportid={rid}',
      f'http://stock.finance.sina.com.cn/hkstock/view/hk_report.php?reportid={rid}',
    ]
    for url in urls:
      try:
        r=client.get(url)
        raw=r.content; enc='gb18030' if b'charset=gb' in raw[:5000].lower() else (r.encoding or 'utf-8')
        try:text=raw.decode(enc,errors='ignore')
        except:text=r.text
        target=any(t in text for t in ['华沿机器人','華沿機器人','HUAYAN ROBOTICS','七轴人形手臂','具身智能空间广阔','卖铲人','运动控制底层价值'])
        print('REPORT',rid,r.status_code,r.headers.get('content-type'),len(r.content),r.url,'TARGET',target)
        if not target: continue
        (OUT/f'report_{rid}.html').write_text(text,encoding='utf-8')
        links=set(re.findall(r'https?://[^"\'<>\s]+',text))
        links.update(urljoin(str(r.url),html.unescape(x)) for x in re.findall(r'(?:href|src|data-url|data-file|data-src|content)=["\']([^"\']+)["\']',text,re.I))
        interesting=[]
        for x in sorted(links):
            x=html.unescape(x).replace('\\/','/').rstrip(');,')
            if any(k in x.lower() for k in ['.pdf','download','file','attach','report','dfcfw','research']):
                interesting.append(x); print('REPORT_LINK',rid,x)
        contexts=[]
        for pat in patterns:
            for m in list(re.finditer(pat,text,re.I))[:100]:
                c=text[max(0,m.start()-700):m.end()+1600]
                contexts.append({'pattern':pat,'context':c})
                print('REPORT_CTX',rid,pat,c.replace('\n',' ')[:2300])
        scripts=[urljoin(str(r.url),html.unescape(x)) for x in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']',text,re.I)]
        script_rows=[]
        for si,surl in enumerate(scripts):
            if surl in seen_urls: continue
            seen_urls.add(surl)
            try:
                sr=client.get(surl); st=sr.text
                if any(p.lower() in st.lower() for p in patterns):
                    (OUT/f'report_{rid}_script_{si}.js').write_text(st,encoding='utf-8',errors='ignore')
                    sctx=[]
                    for pat in patterns:
                        for m in list(re.finditer(pat,st,re.I))[:100]:
                            c=st[max(0,m.start()-600):m.end()+1400]; sctx.append({'pattern':pat,'context':c})
                            if pat.lower() in ['reportid','pdf','download','file','attach','report_url','reporturl']:
                                print('SCRIPT_CTX',rid,si,pat,c.replace('\n',' ')[:2000])
                    endpoints=sorted(set(re.findall(r'https?://[^"\'`\\\s<>]+',st)))
                    paths=sorted(set(re.findall(r'["\'](\/[^"\']*(?:pdf|download|file|attach|report)[^"\']*)["\']',st,re.I)))
                    for e in endpoints:
                        if any(k in e.lower() for k in ['pdf','download','file','attach','report']): print('SCRIPT_ENDPOINT',rid,si,e)
                    for p in paths[:300]: print('SCRIPT_PATH',rid,si,p)
                    script_rows.append({'url':surl,'status':sr.status_code,'bytes':len(sr.content),'contexts':sctx,'endpoints':endpoints,'paths':paths})
            except Exception as exc: print('SCRIPT_ERR',rid,si,surl,repr(exc))
        report_rows.append({'reportid':rid,'url':url,'final_url':str(r.url),'status':r.status_code,'interesting_links':interesting,'contexts':contexts,'scripts':script_rows})
        break
      except Exception as exc: print('REPORT_ERR',rid,url,repr(exc))

# Probe only direct PDF links explicitly exposed by the public report pages.
pdf_probes=[]; seen_pdf=set()
for row in report_rows:
    for url in row['interesting_links']:
        clean=url.split('#',1)[0]
        if clean in seen_pdf or not clean.lower().split('?',1)[0].endswith('.pdf'): continue
        seen_pdf.add(clean)
        try:
            r=client.get(clean,headers={'Accept':'application/pdf,*/*','Referer':row['final_url']})
            meta={'url':clean,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(r.content),'final_url':str(r.url),'pdf_signature':r.content[:5]==b'%PDF-'}
            print('PDF_PROBE',json.dumps(meta,ensure_ascii=False)); pdf_probes.append(meta)
            if meta['pdf_signature'] and len(r.content)>80000:
                (OUT/f"report_{row['reportid']}.pdf").write_bytes(r.content)
        except Exception as exc: print('PDF_ERR',clean,repr(exc))

(OUT/'results.json').write_text(json.dumps({'listing':list_rows,'api':api_rows,'report_ids':sorted(report_ids),'reports':report_rows,'pdf_probes':pdf_probes},ensure_ascii=False,indent=2),encoding='utf-8')
print('DONE_REPORT_IDS',sorted(report_ids))
client.close()
