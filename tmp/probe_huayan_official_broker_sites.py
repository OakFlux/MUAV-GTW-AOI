from __future__ import annotations

import html, json, re
from pathlib import Path
from urllib.parse import urljoin, urlencode
import httpx

OUT=Path('out_huayan_official_sites'); OUT.mkdir(exist_ok=True)
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
client=httpx.Client(http2=True,follow_redirects=True,timeout=httpx.Timeout(45,connect=15),headers={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9,en;q=0.8'})
terms=['华沿机器人','華沿機器人','01021','1021 HK','七轴人形手臂','卖铲人','具身智能空间广阔']
roots=[
 ('bocom','https://research.bocomgroup.com/'),
 ('bocom_http','http://research.bocomgroup.com/'),
 ('gtht','https://www.gtht.com/'),
 ('gtja_research','https://research.gtja.com/'),
 ('xyzq_research','https://research.xyzq.com.cn/'),
 ('xyzq','https://www.xyzq.com.cn/'),
 ('xyzq_hk','https://www.xyzq.com.hk/'),
]
paths=['','robots.txt','sitemap.xml','sitemap_index.xml','api','search','search?keyword=%E5%8D%8E%E6%B2%BF%E6%9C%BA%E5%99%A8%E4%BA%BA','?keyword=%E5%8D%8E%E6%B2%BF%E6%9C%BA%E5%99%A8%E4%BA%BA','?q=1021']
rows=[]
script_urls=set()
for label,root in roots:
 for pi,p in enumerate(paths):
  u=urljoin(root,p)
  try:
   r=client.get(u,headers={'Accept':'text/html,application/json,text/plain,*/*'})
   ct=r.headers.get('content-type',''); text=r.text
   print('GET',label,pi,r.status_code,ct,len(r.content),r.url)
   safe=f'{label}_{pi}'.replace('/','_'); (OUT/f'{safe}.txt').write_text(text,encoding='utf-8',errors='ignore')
   hit=[t for t in terms if t.lower() in text.lower()]
   if hit: print('HIT',label,pi,hit)
   scripts=[urljoin(str(r.url),html.unescape(x)) for x in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']',text,re.I)]
   script_urls.update(scripts)
   links=set(re.findall(r'https?://[^"\'<>\s]+',text))
   links.update(urljoin(str(r.url),html.unescape(x)) for x in re.findall(r'(?:href|src|data-url|data-file|content)=["\']([^"\']+)["\']',text,re.I))
   interesting=[x for x in sorted(links) if any(k in x.lower() for k in ['pdf','report','research','download','file','search','api'])]
   for x in interesting[:100]: print('LINK',label,pi,x)
   rows.append({'label':label,'path':p,'url':u,'status':r.status_code,'final_url':str(r.url),'content_type':ct,'bytes':len(r.content),'hits':hit,'scripts':scripts,'interesting_links':interesting})
  except Exception as e:
   print('ERR',label,pi,u,repr(e)); rows.append({'label':label,'path':p,'url':u,'error':repr(e)})

# Inspect scripts from reachable official sites for search/report/download endpoints.
script_rows=[]
for i,u in enumerate(sorted(script_urls)):
 try:
  r=client.get(u)
  text=r.text
  if len(text)>3_000_000: text=text[:3_000_000]
  patterns=['download','report','research','pdf','fileUrl','file_url','attachment','search','api/','1021']
  if not any(p.lower() in text.lower() for p in patterns): continue
  (OUT/f'script_{i}.js').write_text(text,encoding='utf-8',errors='ignore')
  ctx=[]
  for pat in patterns:
   for m in list(re.finditer(pat,text,re.I))[:30]:
    c=text[max(0,m.start()-350):m.end()+700]; ctx.append({'pattern':pat,'context':c})
    if pat.lower() in ['download','report','pdf','fileurl','file_url','attachment','api/']:
     print('SCRIPT_CTX',i,pat,c.replace('\n',' ')[:1200])
  endpoints=sorted(set(re.findall(r'https?://[^"\'`\\\s<>]+',text)))
  apis=sorted(set(re.findall(r'["\'](\/[^"\']*(?:api|search|report|research|download|file|pdf)[^"\']*)["\']',text,re.I)))
  script_rows.append({'url':u,'status':r.status_code,'bytes':len(r.content),'contexts':ctx,'endpoints':endpoints,'paths':apis})
 except Exception as e: print('SCRIPT_ERR',u,repr(e))

(OUT/'results.json').write_text(json.dumps({'pages':rows,'scripts':script_rows},ensure_ascii=False,indent=2),encoding='utf-8')
client.close()
