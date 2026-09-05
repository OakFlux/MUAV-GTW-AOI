from __future__ import annotations
import json, re, html
from pathlib import Path
from urllib.parse import urljoin
import httpx

OUT=Path('out_fxbaogao_api_inspect')
OUT.mkdir(exist_ok=True)
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
client=httpx.Client(http2=True,follow_redirects=True,timeout=60,headers={'User-Agent':UA,'Referer':'https://www.fxbaogao.com/'})

urls=['https://www.fxbaogao.com/detail/4912455','https://www.fxbaogao.com/view?id=4912455']
script_urls=set()
for idx,url in enumerate(urls):
 r=client.get(url)
 print('PAGE',idx,r.status_code,len(r.content),r.headers.get('content-type'),r.url)
 OUT.joinpath(f'page_{idx}.html').write_bytes(r.content)
 for src in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']',r.text,re.I):
  script_urls.add(urljoin(str(r.url),html.unescape(src.strip())))
 print('SCRIPTS',json.dumps(sorted(script_urls),ensure_ascii=False))

# Add known app bundle and likely Next build manifests.
script_urls.update([
 'https://static.fxbaogao.com/detail_source/js/app-v1.js',
 'https://static.fxbaogao.com/detail_source/_next/static/chunks/polyfills-0d1b80a048d4787e.js',
])

all_matches={}
for i,url in enumerate(sorted(script_urls)):
 try:
  r=client.get(url)
  print('SCRIPT',i,r.status_code,len(r.content),r.headers.get('content-type'),r.url)
  text=r.text
  name=f'script_{i}.js'
  OUT.joinpath(name).write_text(text,encoding='utf-8',errors='ignore')
  contexts=[]
  patterns=[
   r'getReportPreviewImages',r'mofoun/report',r'reportId',r'download',r'\.pdf',r'fileUrl',r'file_url',r'original',r'previewImages',r'/api/',r'report-image'
  ]
  for pat in patterns:
   for m in list(re.finditer(pat,text,re.I))[:50]:
    contexts.append({'pattern':pat,'context':text[max(0,m.start()-500):m.end()+900]})
  endpoints=sorted(set(re.findall(r'https?://[^"\'`\\\s<>]+',text)))
  paths=sorted(set(re.findall(r'["\'](\/[^"\']*(?:report|download|file|pdf|mofoun)[^"\']*)["\']',text,re.I)))
  all_matches[url]={'contexts':contexts,'endpoints':endpoints[:1000],'paths':paths[:1000]}
  for c in contexts[:60]: print('CTX',url,c['pattern'],c['context'].replace('\n',' ')[:1600])
  print('ENDPOINTS',url,json.dumps([x for x in endpoints if any(k in x.lower() for k in ['api','report','download','pdf','file'])][:250],ensure_ascii=False))
  print('PATHS',url,json.dumps(paths[:250],ensure_ascii=False))
 except Exception as e:
  print('SCRIPT_ERROR',url,repr(e))

# Probe likely public report endpoints. Never send credentials or bypass access controls.
base='https://api.fxbaogao.com/mofoun/report/report/'
methods=[
 'getReportPreviewImages','getReportDetail','getReportInfo','getReportById','getReport','detail','info',
 'getReportImages','getReportAllImages','getReportFile','getReportDownloadUrl','getDownloadUrl','download'
]
probes=[]
for method in methods:
 for param in ['reportId','id','docId']:
  url=f'{base}{method}?{param}=4912455'
  try:
   r=client.get(url)
   row={'url':url,'status':r.status_code,'ct':r.headers.get('content-type',''),'bytes':len(r.content),'final':str(r.url),'preview':r.text[:2000]}
   probes.append(row)
   print('PROBE',json.dumps(row,ensure_ascii=False)[:2600])
  except Exception as e:
   print('PROBE_ERROR',url,repr(e))
OUT.joinpath('matches.json').write_text(json.dumps(all_matches,ensure_ascii=False,indent=2),encoding='utf-8')
OUT.joinpath('probes.json').write_text(json.dumps(probes,ensure_ascii=False,indent=2),encoding='utf-8')
client.close()
