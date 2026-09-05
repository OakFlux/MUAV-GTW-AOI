from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import httpx

OUT = Path('out_huayan_1c9u_doc')
OUT.mkdir(exist_ok=True)
URL = 'https://www.1c9u.com/zhishiku/document/z-5Lq65b2i5py65Zmo5Lq655-l6K-G5bqTADQ06aG1LTIwMjYwODA3LeS6pOmTtuWbvemZhS3ljY7msr_mnLrlmajkurotMTAyMS5ISy3kurrlvaLmnLrlmajkurrooYzkuJrns7vliJfvvIg077yJ77ya4oCc5Y2W6ZOy5Lq64oCd5Z6L5bmz5Y-w5YWs5Y-477yM6L-Q5Yqo5o6n5Yi25bqV5bGC5Lu35YC85pyJ5pyb6YeN5LywLnBkZg'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
client = httpx.Client(http2=True, follow_redirects=True, timeout=httpx.Timeout(60, connect=20), headers={'User-Agent': UA, 'Accept-Language':'zh-CN,zh;q=0.9,en;q=0.8'})

r = client.get(URL)
print('PAGE', r.status_code, r.headers.get('content-type'), len(r.content), r.url)
r.raise_for_status()
text = r.text
(OUT/'page.html').write_text(text, encoding='utf-8')

scripts = [urljoin(str(r.url), html.unescape(x)) for x in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', text, re.I)]
links = set(re.findall(r'https?://[^"\'<>\s]+', text))
links.update(urljoin(str(r.url), html.unescape(x)) for x in re.findall(r'(?:href|src|data-url|data-file|data-src|content)=["\']([^"\']+)["\']', text, re.I))

patterns = ['downloadable','download','fileUrl','file_url','storage','oss','cos','r2','s3','pdf','document','docId','objectKey','signed','presign','token','douyinbao','微信','免费获取']
contexts=[]
for pat in patterns:
    for m in list(re.finditer(pat, text, re.I))[:50]:
        context=text[max(0,m.start()-600):m.end()+1600]
        contexts.append({'pattern':pat,'context':context})
        print('PAGE_CTX',pat,context.replace('\n',' ')[:2200])

print('SCRIPTS', json.dumps(scripts, ensure_ascii=False, indent=2))
interesting_links=[]
for x in sorted(links):
    x=html.unescape(x).replace('\\/','/').rstrip(');,')
    if any(k in x.lower() for k in ['.pdf','download','file','attach','storage','oss','cos','r2','s3','api','document']):
        interesting_links.append(x)
        print('PAGE_LINK',x)

script_findings=[]
for i,surl in enumerate(scripts):
    try:
        sr=client.get(surl)
        print('SCRIPT',i,sr.status_code,sr.headers.get('content-type'),len(sr.content),surl)
        st=sr.text
        (OUT/f'script_{i}.js').write_text(st,encoding='utf-8',errors='ignore')
        sctx=[]
        for pat in patterns:
            for m in list(re.finditer(pat,st,re.I))[:100]:
                c=st[max(0,m.start()-500):m.end()+1300]
                sctx.append({'pattern':pat,'context':c})
                if pat.lower() in ['downloadable','download','fileurl','file_url','objectkey','presign','signed','pdf']:
                    print('SCRIPT_CTX',i,pat,c.replace('\n',' ')[:1900])
        endpoints=sorted(set(re.findall(r'https?://[^"\'`\\\s<>]+',st)))
        api_paths=sorted(set(re.findall(r'["\'](\/[^"\']*(?:api|download|file|document|pdf|storage|object)[^"\']*)["\']',st,re.I)))
        script_findings.append({'url':surl,'contexts':sctx,'endpoints':endpoints,'paths':api_paths})
        for e in endpoints:
            if any(k in e.lower() for k in ['api','download','file','document','pdf','storage','oss','cos','r2','s3']): print('SCRIPT_ENDPOINT',i,e)
        for p in api_paths[:300]: print('SCRIPT_PATH',i,p)
    except Exception as exc:
        print('SCRIPT_ERROR',i,surl,repr(exc))

# Probe only openly referenced API URLs; do not send credentials or guess protected tokens.
probes=[]
for u in interesting_links:
    if u.lower().endswith('.pdf') or '/api/' in u.lower():
        try:
            pr=client.get(u,headers={'Referer':str(r.url),'Accept':'application/json,application/pdf,*/*'})
            row={'url':u,'status':pr.status_code,'content_type':pr.headers.get('content-type',''),'bytes':len(pr.content),'final_url':str(pr.url),'preview':pr.text[:2000] if 'json' in pr.headers.get('content-type','').lower() or 'text' in pr.headers.get('content-type','').lower() else ''}
            probes.append(row); print('PROBE',json.dumps(row,ensure_ascii=False)[:2600])
        except Exception as exc: print('PROBE_ERROR',u,repr(exc))

(OUT/'results.json').write_text(json.dumps({'page_url':str(r.url),'scripts':scripts,'interesting_links':interesting_links,'page_contexts':contexts,'script_findings':script_findings,'probes':probes},ensure_ascii=False,indent=2),encoding='utf-8')
client.close()
