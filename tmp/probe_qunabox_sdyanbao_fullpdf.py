from __future__ import annotations

import json
import re
import hashlib
import html
from pathlib import Path
from urllib.parse import urljoin

import requests

OUT = Path('out_qunabox_sdyanbao_fullpdf')
OUT.mkdir(exist_ok=True)
PDFS = OUT / 'pdfs'
PDFS.mkdir(exist_ok=True)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
s = requests.Session()
s.headers.update({'User-Agent': UA, 'Referer': 'https://www.sdyanbao.com/detail/853466', 'Accept-Language':'zh-CN,zh;q=0.9,en;q=0.8'})

search_url='https://api.sdyanbao.com/api/file/search'
search_bodies=[
 {'keyword':'趣致集团','page':1,'limit':100},
 {'keywords':'趣致集团','page':1,'limit':100},
 {'name':'趣致集团','page':1,'limit':100},
 {'key':'趣致集团','page':1,'limit':100},
 {'wd':'趣致集团','page':1,'limit':100},
]
objects=[]
for i,body in enumerate(search_bodies):
    for mode in ('json','form'):
        try:
            r=s.post(search_url,json=body,timeout=30) if mode=='json' else s.post(search_url,data=body,timeout=30)
            print('SEARCH',i,mode,r.status_code,r.headers.get('content-type'),len(r.content),r.text[:1000])
            (OUT/f'search_{i}_{mode}.txt').write_bytes(r.content)
            try:
                obj=r.json()
                files=((obj.get('data') or {}).get('files') or []) if isinstance(obj,dict) else []
                for x in files:
                    if isinstance(x,dict) and (x.get('id')==853466 or '趣致集团' in str(x.get('name',''))): objects.append(x)
            except Exception: pass
        except Exception as e: print('SEARCH_ERR',i,mode,repr(e))

# Seed from known metadata.
objects.append({'id':853466,'name':'趣致集团(00917.HK)AI互动营销领导者，公司业绩高速增长','page_url':'https://oss.sdyanbao.com/page/2025/1/20/1143658','share_url':'https://oss.sdyanbao.com/page/2025/1/20/1143658/0.png','file_size':2706205,'page_count':29})
# dedupe
uniq={str(x.get('id')):x for x in objects if isinstance(x,dict)}
objects=list(uniq.values())
print('OBJECTS',json.dumps(objects,ensure_ascii=False,indent=2))
(OUT/'search_objects.json').write_text(json.dumps(objects,ensure_ascii=False,indent=2),encoding='utf-8')

all_json=[]
endpoints=['detail','info','get','show','view','read','preview','download','getDetail','getInfo','fileInfo','fileDetail','getFile','down','downloadUrl','getDownloadUrl']
param_names=['id','file_id','fileId','fid']
for ep in endpoints:
    url=f'https://api.sdyanbao.com/api/file/{ep}'
    for method in ('GET','POST_JSON','POST_FORM'):
        for param in param_names:
            payload={param:853466}
            try:
                if method=='GET': r=s.get(url,params=payload,timeout=20)
                elif method=='POST_JSON': r=s.post(url,json=payload,timeout=20)
                else: r=s.post(url,data=payload,timeout=20)
                preview=r.text[:5000]
                if r.status_code not in (404,405) or len(r.content)>1000:
                    print('DETAIL_PROBE',ep,method,param,r.status_code,r.headers.get('content-type'),len(r.content),preview[:1200])
                try:
                    obj=r.json()
                    all_json.append({'endpoint':url,'method':method,'param':param,'status':r.status_code,'json':obj})
                except Exception: pass
            except Exception as e: print('DETAIL_ERR',ep,method,param,repr(e))

(OUT/'detail_responses.json').write_text(json.dumps(all_json,ensure_ascii=False,indent=2),encoding='utf-8')

# Harvest all URL-like values from JSON.
def walk(x, path=''):
    if isinstance(x,dict):
        for k,v in x.items(): yield from walk(v,path+'/'+str(k))
    elif isinstance(x,list):
        for i,v in enumerate(x): yield from walk(v,path+f'/{i}')
    else:
        s0=str(x)
        if 'http://' in s0 or 'https://' in s0 or '.pdf' in s0.lower() or '1143658' in s0:
            yield path,s0

harvest=[]
for rec in all_json:
    for path,val in walk(rec.get('json')):
        harvest.append({'endpoint':rec['endpoint'],'method':rec['method'],'path':path,'value':val})
for x in objects:
    for path,val in walk(x): harvest.append({'endpoint':'search_object','method':'','path':path,'value':val})
print('HARVEST',json.dumps(harvest,ensure_ascii=False,indent=2))
(OUT/'url_harvest.json').write_text(json.dumps(harvest,ensure_ascii=False,indent=2),encoding='utf-8')

# Inspect detail page and scripts.
for page_url in ['https://www.sdyanbao.com/detail/853466','https://m.sdyanbao.com/detail/853466']:
    try:
        r=s.get(page_url,timeout=30)
        label=re.sub(r'[^a-zA-Z0-9]+','_',page_url)
        (OUT/f'{label}.html').write_bytes(r.content)
        print('PAGE',r.status_code,r.headers.get('content-type'),len(r.content),r.url)
        scripts=[urljoin(str(r.url),html.unescape(x)) for x in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']',r.text,re.I)]
        links=[urljoin(str(r.url),html.unescape(x)) for x in re.findall(r'(?:href|src|data-url|data-file)=["\']([^"\']+)["\']',r.text,re.I)]
        print('SCRIPTS',json.dumps(scripts,ensure_ascii=False))
        print('LINKS_INTERESTING',json.dumps([u for u in links if any(k in u.lower() for k in ['pdf','download','file','oss','1143658'])],ensure_ascii=False))
        for j,u in enumerate(scripts):
            try:
                rr=s.get(u,timeout=30)
                txt=rr.text
                (OUT/f'script_{j}_{hashlib.sha1(u.encode()).hexdigest()[:10]}.js').write_text(txt,encoding='utf-8',errors='ignore')
                if any(k in txt for k in ['downloadUrl','file_url','page_url','api/file/detail','api/file/download','online_url']):
                    for pat in ['downloadUrl','file_url','page_url','api/file/detail','api/file/download','online_url','getDownload']:
                        for m in list(re.finditer(pat,txt,re.I))[:10]:
                            print('SCRIPT_CTX',u,pat,txt[max(0,m.start()-500):m.end()+1200].replace('\n',' ')[:1800])
            except Exception as e: print('SCRIPT_ERR',u,repr(e))
    except Exception as e: print('PAGE_ERR',page_url,repr(e))

# Construct plausible public object URLs from the public page object key.
base_variants=['https://oss.sdyanbao.com','http://oss.sdyanbao.com']
paths=[]
for base in base_variants:
    for p in [
        '/page/2025/1/20/1143658.pdf',
        '/page/2025/1/20/1143658/1143658.pdf',
        '/pdf/2025/1/20/1143658.pdf',
        '/file/2025/1/20/1143658.pdf',
        '/files/2025/1/20/1143658.pdf',
        '/upload/2025/1/20/1143658.pdf',
        '/uploads/2025/1/20/1143658.pdf',
        '/2025/1/20/1143658.pdf',
        '/pdf/1143658.pdf','/file/1143658.pdf','/files/1143658.pdf','/1143658.pdf',
        '/download/853466.pdf','/file/853466.pdf','/pdf/853466.pdf',
        '/page/2025/1/20/1143658/original.pdf','/page/2025/1/20/1143658/source.pdf','/page/2025/1/20/1143658/full.pdf',
    ]: paths.append(base+p)

# Add URL-like harvested values and common modifications.
for h in harvest:
    v=html.unescape(h['value']).replace('\\/','/')
    if v.startswith('http'): paths.append(v)

seen=set(); found=[]
for idx,u in enumerate(paths):
    if u in seen: continue
    seen.add(u)
    try:
        r=s.get(u,timeout=25,allow_redirects=True,headers={'User-Agent':UA,'Referer':'https://www.sdyanbao.com/detail/853466','Accept':'application/pdf,application/octet-stream,*/*'})
        ct=r.headers.get('content-type','')
        print('URL_PROBE',r.status_code,ct,len(r.content),u,'FINAL',r.url)
        if r.status_code==200 and len(r.content)>100000 and r.content[:5]==b'%PDF-':
            h=hashlib.sha256(r.content).hexdigest(); p=PDFS/f'boci_qunabox_{h[:12]}.pdf';p.write_bytes(r.content)
            found.append({'url':u,'final_url':str(r.url),'path':str(p),'bytes':len(r.content),'sha256':h})
    except Exception as e: print('URL_ERR',u,repr(e))

(OUT/'found_pdfs.json').write_text(json.dumps(found,ensure_ascii=False,indent=2),encoding='utf-8')
print('FOUND_PDFS',json.dumps(found,ensure_ascii=False,indent=2))
