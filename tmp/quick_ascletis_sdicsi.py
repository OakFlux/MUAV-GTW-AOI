from __future__ import annotations
import hashlib, json, re, html
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

OUT=Path('out_ascletis_sdicsi_quick'); PDFS=OUT/'pdfs'; PDFS.mkdir(parents=True,exist_ok=True)
S=requests.Session(); S.headers.update({'User-Agent':'Mozilla/5.0','Accept-Language':'zh-CN,zh;q=0.9,en;q=0.8'})
BASE='https://www.sdicsi.com.hk'
seen=set(); valid=[]

def identity_text(p):
 r=PdfReader(str(p),strict=False); pages=len(r.pages); idx=list(range(min(10,pages)))
 if pages>12: idx += [pages//2,pages-1]
 text='\n'.join((r.pages[i].extract_text() or '') for i in sorted(set(idx)))
 norm=re.sub(r'\s+','',text).lower().replace('.','')
 ok=any(x in norm for x in ['歌礼制药','歌禮製藥','ascletis','01672','1672hk'])
 return pages,text,ok

def probe(url,label):
 if url in seen:return
 seen.add(url)
 try:
  r=S.get(url,timeout=20,allow_redirects=True)
  print('PROBE',r.status_code,r.headers.get('content-type'),len(r.content),r.url)
  if r.status_code!=200 or len(r.content)<50000 or not r.content.startswith(b'%PDF-'):return
  h=hashlib.sha256(r.content).hexdigest(); p=PDFS/f'{label}_{h[:12]}.pdf';p.write_bytes(r.content)
  pages,text,ok=identity_text(p)
  print('PDF_META',pages,ok,text[:500].replace('\n',' '))
  if not ok:p.unlink(missing_ok=True);return
  item={'path':str(p),'url':str(r.url),'pages':pages,'bytes':len(r.content),'sha256':h,'preview':text[:4000]};valid.append(item);print('VALID',json.dumps({k:v for k,v in item.items() if k!='preview'},ensure_ascii=False))
 except Exception as e:print('ERR',url,repr(e))

# Official tag pages and linked articles/files.
for lang in ['cn','zh','en']:
 u=f'{BASE}/{lang}/research-report/tag/1672hk'
 try:
  r=S.get(u,timeout=30);print('TAG',u,r.status_code,len(r.content),r.url);(OUT/f'tag_{lang}.html').write_bytes(r.content)
  soup=BeautifulSoup(r.text,'html.parser');print('TAG_TEXT',lang,re.sub(r'\s+',' ',soup.get_text(' '))[:3000])
  article=[]
  for a in soup.find_all('a',href=True):
   href=urljoin(str(r.url),a['href']); label=re.sub(r'\s+',' ',a.get_text(' ',strip=True))
   if '.pdf' in href.lower():probe(href,f'tag_{lang}')
   if '/research-report/' in href and '/tag/' not in href: article.append((href,label))
  for i,(href,label) in enumerate(article[:50]):
   rr=S.get(href,timeout=20);print('ARTICLE',rr.status_code,len(rr.content),href,label);(OUT/f'article_{lang}_{i}.html').write_bytes(rr.content)
   ss=BeautifulSoup(rr.text,'html.parser')
   for node in ss.find_all(['a','iframe','embed','object']):
    raw=node.get('href') or node.get('src') or node.get('data')
    if raw:
     x=urljoin(str(rr.url),raw)
     if '.pdf' in x.lower():probe(x,f'article_{lang}_{i}')
   for raw in re.findall(r'https?://[^\"\'<>\s]+\.pdf[^\"\'<>\s]*',rr.text,re.I):probe(html.unescape(raw).replace('\\/','/'),f'article_{lang}_{i}')
 except Exception as e: print('TAG_ERR',u,repr(e))

# Exact public filename convention around the identified report date plus recent periods.
dates=['20250820','20250821','20250822','20250823','20250824','20250825','20260327','20260330','20260331','20260817','20260818','20260824','20260828','20260831']
roots=[
 f'{BASE}/backend/storage/app/media/ResearchReports/CorporateReports/',
 f'{BASE}/backend/storage/app/media/ResearchReports/CompanyReports/',
]
for root in roots:
 for code in ['1672','01672']:
  for d in dates:
   for suffix in ['.pdf','_C.pdf','_c.pdf']:
    probe(f'{root}{code}-{d}{suffix}',f'{code}_{d}')

(OUT/'valid.json').write_text(json.dumps(valid,ensure_ascii=False,indent=2),encoding='utf-8')
print('DONE',len(valid))
