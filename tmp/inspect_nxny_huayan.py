from __future__ import annotations
import html, json, re, hashlib
from pathlib import Path
from urllib.parse import urljoin
import httpx
from pypdf import PdfReader

OUT=Path('out_huayan_nxny'); OUT.mkdir(exist_ok=True); PDFS=OUT/'pdfs'; PDFS.mkdir(exist_ok=True)
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
client=httpx.Client(http2=True,follow_redirects=True,timeout=httpx.Timeout(60,connect=20),headers={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'})
PAGES=[
 'https://www.nxny.com/stype_47_p38/',
 'https://www.nxny.com/stype_1025_p42/',
 'https://www.nxny.com/stype_601/',
 'https://www3.nxny.com/stype_47_p38/',
 'https://www3.nxny.com/stype_1025_p42/',
]

def decode(r):
 raw=r.content
 for enc in ['utf-8','gb18030','gbk']:
  try:
   t=raw.decode(enc)
   if '华沿机器人' in t or '研报' in t: return t
  except: pass
 return raw.decode('utf-8',errors='ignore')

def valid_pdf(url,label):
 try:
  r=client.get(url,headers={'Referer':'https://www.nxny.com/','Accept':'application/pdf,application/octet-stream,*/*'})
  print('PROBE',r.status_code,r.headers.get('content-type'),len(r.content),url)
  if r.status_code==200 and len(r.content)>80000 and r.content.startswith(b'%PDF-'):
   h=hashlib.sha256(r.content).hexdigest(); p=PDFS/f'{label}_{h[:12]}.pdf'; p.write_bytes(r.content)
   rd=PdfReader(str(p),strict=False); pages=len(rd.pages)
   text='\n'.join((pg.extract_text() or '') for pg in rd.pages[:min(10,pages)])
   ident=any(x in re.sub(r'\s+','',text).lower() for x in ['华沿机器人','華沿機器人','huayanrobotics','01021','1021hk'])
   print('VALID_PDF',p,pages,ident,text[:500].replace('\n',' '))
   return {'path':str(p),'url':url,'pages':pages,'identity_ok':ident,'sha256':h}
 except Exception as e: print('PROBE_ERR',url,repr(e))
 return None

report_links=[]; allinfo={'report_links':[],'details':[],'valid_pdfs':[]}
for i,u in enumerate(PAGES):
 try:
  r=client.get(u); t=decode(r); (OUT/f'index_{i}.html').write_text(t,encoding='utf-8')
  print('INDEX',i,r.status_code,len(t),r.url)
  for m in re.finditer(r'<a\b([^>]*)href=["\']([^"\']+)["\']([^>]*)>(.*?)</a>',t,re.I|re.S):
   txt=re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',html.unescape(m.group(4)))).strip(); href=urljoin(str(r.url),html.unescape(m.group(2)))
   if '华沿机器人' in txt or '華沿機器人' in txt:
    print('TARGET_LINK',txt,href,m.group(1)[:300],m.group(3)[:300]); report_links.append({'text':txt,'url':href})
 except Exception as e: print('INDEX_ERR',u,repr(e))
# dedupe
seen=set(); report_links=[x for x in report_links if not (x['url'] in seen or seen.add(x['url']))]
allinfo['report_links']=report_links
print('REPORT_LINKS',json.dumps(report_links,ensure_ascii=False,indent=2))

for i,item in enumerate(report_links):
 u=item['url']
 try:
  r=client.get(u); t=decode(r); (OUT/f'detail_{i}.html').write_text(t,encoding='utf-8')
  print('DETAIL',i,r.status_code,len(t),r.url,item['text'])
  ctx=[]
  for pat in ['pdf','down','file','attach','login','会员','下载','data-url','data-file','onclick','iframe','object','embed']:
   for m in list(re.finditer(pat,t,re.I))[:40]: ctx.append({'pat':pat,'text':t[max(0,m.start()-350):m.end()+700]})
  urls=set(re.findall(r'https?://[^"\'<>\s]+',t))
  urls.update(urljoin(str(r.url),html.unescape(x)) for x in re.findall(r'(?:href|src|action|data-url|data-file|data-src)=["\']([^"\']+)["\']',t,re.I))
  interesting=[]
  for x in sorted(urls):
   x=x.replace('\\/','/').rstrip(');,')
   if any(k in x.lower() for k in ['.pdf','download','down','file','attach','report']):
    interesting.append(x); print('DETAIL_URL',i,x)
    if x.lower().split('?',1)[0].endswith('.pdf'):
     m=valid_pdf(x,f'nxny_{i}')
     if m: allinfo['valid_pdfs'].append(m)
  allinfo['details'].append({'item':item,'final_url':str(r.url),'interesting_urls':interesting,'contexts':ctx})
 except Exception as e: print('DETAIL_ERR',u,repr(e))

(OUT/'results.json').write_text(json.dumps(allinfo,ensure_ascii=False,indent=2),encoding='utf-8')
client.close()
