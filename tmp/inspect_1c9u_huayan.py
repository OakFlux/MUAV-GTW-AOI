from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import quote, urljoin

import httpx

OUT=Path('out_1c9u_huayan'); OUT.mkdir(exist_ok=True)
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
client=httpx.Client(http2=True,follow_redirects=True,timeout=httpx.Timeout(60,connect=20),headers={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'})
urls=[
 'https://1c9u.com/zhishiku/%E4%BA%BA%E5%BD%A2%E6%9C%BA%E5%99%A8%E4%BA%BA%E7%9F%A5%E8%AF%86%E5%BA%93',
 'https://www.1c9u.com/zhishiku/%E4%BA%BA%E5%BD%A2%E6%9C%BA%E5%99%A8%E4%BA%BA%E7%9F%A5%E8%AF%86%E5%BA%93',
 'https://1c9u.com/search?q='+quote('华沿机器人'),
 'https://1c9u.com/?s='+quote('华沿机器人'),
]
script_urls=set(); results=[]
for idx,url in enumerate(urls):
 try:
  r=client.get(url); text=r.text
  (OUT/f'page_{idx}.html').write_text(text,encoding='utf-8',errors='ignore')
  print('PAGE',idx,r.status_code,r.headers.get('content-type'),len(r.content),r.url)
  for src in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']',text,re.I): script_urls.add(urljoin(str(r.url),html.unescape(src)))
  vals=set()
  for pat in [r'https?://[^"\'<>\s]+',r'(?:href|src|data-url|data-file|data-src|download)=["\']([^"\']+)["\']']:
   for v in re.findall(pat,text,re.I): vals.add(urljoin(str(r.url),html.unescape(v).replace('\\/','/')))
  interesting=sorted(v for v in vals if any(k in v.lower() for k in ['.pdf','download','file','attachment','oss','cos','cdn','doc','report','api']))
  contexts=[]
  for term in ['华沿机器人','華沿機器人','20260807','卖铲人','pdf','download','data-file','fileUrl','attachment','docId']:
   for m in list(re.finditer(re.escape(term),text,re.I))[:30]:
    contexts.append({'term':term,'context':re.sub(r'\s+',' ',html.unescape(text[max(0,m.start()-1000):m.end()+2000]))})
  print('INTERESTING',json.dumps(interesting,ensure_ascii=False)[:30000])
  for c in contexts[:50]: print('CTX',c['term'],c['context'][:3500])
  results.append({'url':str(r.url),'interesting':interesting,'contexts':contexts})
 except Exception as e: print('PAGE_ERR',url,repr(e))

js=[]
for idx,url in enumerate(sorted(script_urls)):
 try:
  r=client.get(url); text=r.text; (OUT/f'script_{idx}.js').write_text(text,encoding='utf-8',errors='ignore')
  if any(term.lower() in text.lower() for term in ['download','pdf','fileurl','华沿','docid']):
   print('SCRIPT',idx,r.status_code,len(r.content),r.url)
   contexts=[]
   for term in ['download','pdf','fileUrl','file_url','docId','attachment','/api/']:
    for m in list(re.finditer(re.escape(term),text,re.I))[:30]: contexts.append({'term':term,'context':text[max(0,m.start()-700):m.end()+1500]})
   paths=sorted(set(re.findall(r'["\'](\/[^"\']*(?:download|pdf|file|doc|api)[^"\']*)["\']',text,re.I)))
   absurls=sorted(set(re.findall(r'https?://[^"\'`<>\\\s]+',text)))
   print('PATHS',json.dumps(paths[:500],ensure_ascii=False)); print('URLS',json.dumps([u for u in absurls if any(k in u.lower() for k in ['pdf','download','file','api','doc'])][:300],ensure_ascii=False))
   for c in contexts[:80]: print('JSCTX',c['term'],c['context'][:3000].replace('\n',' '))
   js.append({'url':str(r.url),'paths':paths,'urls':absurls,'contexts':contexts})
 except Exception as e: print('SCRIPT_ERR',url,repr(e))
(OUT/'results.json').write_text(json.dumps({'pages':results,'scripts':js},ensure_ascii=False,indent=2),encoding='utf-8')
client.close()
