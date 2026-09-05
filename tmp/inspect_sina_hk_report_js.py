from __future__ import annotations

import json, re, html, hashlib
from pathlib import Path
from urllib.parse import urljoin
import httpx
from pypdf import PdfReader

OUT=Path('out_sina_hk_report_js'); OUT.mkdir(exist_ok=True)
PDFS=OUT/'pdfs'; PDFS.mkdir(exist_ok=True)
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
client=httpx.Client(http2=True,follow_redirects=True,timeout=httpx.Timeout(60,connect=20),headers={'User-Agent':UA,'Referer':'https://stock.finance.sina.com.cn/hkstock/view/hk_report.php?reportid=839511181107'})

js_url='https://n.sinaimg.cn/finance/hk/report/stockReportDetail.js?ts=3.99'
r=client.get(js_url)
print('JS',r.status_code,r.headers.get('content-type'),len(r.content),r.url)
text=r.text
(OUT/'stockReportDetail.js').write_text(text,encoding='utf-8',errors='ignore')
urls=sorted(set(re.findall(r'https?://[^"\'`\\\s<>]+',text)))
paths=sorted(set(m.group(1) for m in re.finditer(r'["\']([^"\']*(?:report|研报|api|pdf|download|file)[^"\']*)["\']',text,re.I)))
print('URLS',json.dumps(urls,ensure_ascii=False))
print('PATHS',json.dumps(paths,ensure_ascii=False))
for pat in ['reportid','rptid','api','ajax','jsonp','callback','detail','pdf','download','getReport','report_detail']:
 for i,m in enumerate(re.finditer(pat,text,re.I)):
  if i>=30:break
  print('CTX',pat,text[max(0,m.start()-700):m.end()+1400].replace('\n',' ')[:2400])

candidates=set()
for u in urls:
 candidates.add(u)
for p in paths:
 if p.startswith('//'): candidates.add('https:'+p)
 elif p.startswith('/'): candidates.add(urljoin('https://stock.finance.sina.com.cn/',p))
 elif 'report' in p.lower() or 'api' in p.lower(): candidates.add(urljoin('https://stock.finance.sina.com.cn/hkstock/view/',p))

RID='839511181107'
common=[
 f'https://quotes.sina.cn/hk/api/openapi.php/HK_ReportService.getShow?rptid={RID}&simple=1',
 f'https://quotes.sina.cn/hk/api/openapi.php/HK_ReportService.getShow?rptid={RID}&simple=0',
 f'https://quotes.sina.cn/hk/api/openapi.php/HK_ReportService.getShow?rptid={RID}',
 f'https://quotes.sina.cn/hk/api/openapi.php/HK_ReportService.getShow?reportid={RID}&simple=1',
 'https://quotes.sina.cn/hk/api/openapi.php/HK_ReportService.getList?symbol=01021&page=1&num=100',
 'https://quotes.sina.cn/hk/api/openapi.php/HK_ReportService.getList?symbol=hk01021&page=1&num=100',
 'https://quotes.sina.cn/hk/api/openapi.php/HK_ReportService.getReportList?symbol=01021&page=1&num=100',
 'https://quotes.sina.cn/hk/api/openapi.php/HK_ReportService.getStockReports?symbol=01021&page=1&num=100',
 f'https://quotes.sina.cn/hk/api/openapi.php/HK_StockService.getReportDetail?reportid={RID}',
 f'https://quotes.sina.cn/hk/api/openapi.php/HK_StockService.getReportInfo?reportid={RID}',
 f'https://quotes.sina.cn/hk/api/openapi.php/HK_StockService.getReport?reportid={RID}',
 f'https://quotes.sina.cn/hk/api/openapi.php/HK_StockService.getResearchReportDetail?reportid={RID}',
 f'https://stock.finance.sina.com.cn/hkstock/api/openapi.php/HK_StockService.getReportDetail?reportid={RID}',
 f'https://stock.finance.sina.com.cn/hkstock/view/api.php?reportid={RID}',
]
candidates.update(common)

results=[]
def maybe_pdf(resp,label,url):
 data=resp.content
 if len(data)>60000 and data.startswith(b'%PDF-'):
  h=hashlib.sha256(data).hexdigest(); p=PDFS/f'{label}_{h[:12]}.pdf';p.write_bytes(data)
  rd=PdfReader(str(p),strict=False);pages=len(rd.pages); sample='\n'.join((pg.extract_text() or '') for pg in rd.pages[:min(pages,20)])
  norm=re.sub(r'\s+','',sample).lower();ok=any(x in norm for x in ['华沿机器人','華沿機器人','huayanrobotics','1021hk','01021'])
  row={'url':url,'path':str(p),'bytes':len(data),'pages':pages,'sha256':h,'identity_ok':ok,'sample':sample[:3000]};print('PDF',json.dumps({k:v for k,v in row.items() if k!='sample'},ensure_ascii=False));return row
 return None

for idx,u in enumerate(sorted(candidates)):
 if any(x in u.lower() for x in ['.css','.png','.jpg','.gif','.svg','weibo.com','baidu.com']): continue
 try:
  variants=[u]
  if 'reportid' in u.lower() and RID not in u:
   variants.append(u+('&' if '?' in u else '?')+f'reportid={RID}')
  if 'rptid' in u.lower() and RID not in u:
   variants.append(u+('&' if '?' in u else '?')+f'rptid={RID}&simple=1')
  for j,v in enumerate(variants):
   rr=client.get(v,headers={'Accept':'application/json,text/plain,application/pdf,*/*'})
   ct=rr.headers.get('content-type',''); print('PROBE',idx,j,rr.status_code,ct,len(rr.content),rr.url)
   pdf=maybe_pdf(rr,f'p_{idx}_{j}',str(rr.url))
   preview=''
   if not pdf and len(rr.content)<4_000_000:
    try: preview=rr.text[:500000]
    except: pass
   if preview:
    for term in ['pdf','download','attachment','file','url','reportinfo','source']:
     pos=preview.lower().find(term.lower())
     if pos>=0: print('PREVIEW_CTX',idx,j,term,preview[max(0,pos-500):pos+1800].replace('\n',' ')[:2300])
   results.append({'requested':v,'final':str(rr.url),'status':rr.status_code,'ct':ct,'bytes':len(rr.content),'preview':preview,'pdf':pdf})
 except Exception as e: print('ERR',u,repr(e))

(OUT/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
client.close()
