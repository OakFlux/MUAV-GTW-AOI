from __future__ import annotations
import html,json,re
from pathlib import Path
from urllib.parse import urljoin
import httpx

OUT=Path('out_huayan_sdicsi_fast'); OUT.mkdir(exist_ok=True)
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
c=httpx.Client(http2=True,follow_redirects=True,timeout=40,headers={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9,en;q=0.8'})
page='https://www.sdicsi.com.hk/cn/research-report/tag/1021hk'
r=c.get(page)
print('TAG',r.status_code,len(r.content),r.url,r.headers.get('content-type'))
OUT.joinpath('tag.html').write_bytes(r.content)
t=r.text
# print all attributes or string literals containing 1021, pdf, media, storage or download
for term in ['1021','pdf','media','storage','download','attachment','202603']:
 print('\nTERM',term)
 for m in list(re.finditer(term,t,re.I))[:100]: print(t[max(0,m.start()-500):m.end()+1000].replace('\n',' ')[:1800])
# URLs and relative paths
vals=set()
for pat in [r'https?://[^"\'<>\s]+',r'(?:href|src|data-[\w-]+)=["\']([^"\']+)["\']',r'["\']([^"\']*(?:1021|\.pdf|storage/app/media|download)[^"\']*)["\']']:
 for x in re.findall(pat,t,re.I):
  x=html.unescape(x if isinstance(x,str) else x[0]).strip()
  if x: vals.add(urljoin(str(r.url),x))
print('VALUES',json.dumps(sorted(vals),ensure_ascii=False,indent=2))
# direct probes
bases=[
 'https://www.sdicsi.com.hk/backend/storage/app/media/ResearchReports/CorporateReports/',
 'https://www.sdicsi.com.hk/backend/storage/app/media/ResearchReports/IPOReports/',
 'https://www.sdicsi.com.hk/backend/storage/app/media/ResearchReports/IPOComments/',
 'https://www.sdicsi.com.hk/backend/storage/app/media/ResearchReports/IPO/',
 'https://www.sdicsi.com.hk/backend/storage/app/media/ResearchReports/',
]
names=[]
for d in ['20260319','20260320','20260321','20260322','20260323','20260324','20260325']:
 for code in ['1021','01021']:
  names += [f'{code}-{d}.pdf',f'{code}_{d}.pdf',f'{d}-{code}.pdf']
for base in bases:
 for name in names:
  u=base+name
  rr=c.get(u,headers={'Referer':page,'Accept':'application/pdf,*/*;q=0.8'})
  if rr.status_code==200 and rr.content.startswith(b'%PDF-'):
   fn='found_'+str(len(list(OUT.glob('found_*.pdf')))+1)+'.pdf'; OUT.joinpath(fn).write_bytes(rr.content)
   print('FOUND',fn,len(rr.content),rr.headers.get('content-type'),rr.url)
  elif rr.status_code not in [200,404]: print('ODD',rr.status_code,len(rr.content),rr.url)
c.close()
