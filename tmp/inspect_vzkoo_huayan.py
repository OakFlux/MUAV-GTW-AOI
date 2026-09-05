from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import httpx

OUT = Path('out_vzkoo_huayan')
OUT.mkdir(exist_ok=True)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
client = httpx.Client(http2=True, follow_redirects=True, timeout=httpx.Timeout(60, connect=20), headers={'User-Agent': UA})

pages = [
    'https://www.vzkoo.com/read/1136817497660001144e2b0d6510.html',
    'https://www.vzkoo.com/search?keyword=%E5%8D%8E%E6%B2%BF%E6%9C%BA%E5%99%A8%E4%BA%BA',
    'https://www.vzkoo.com/search.html?keyword=%E5%8D%8E%E6%B2%BF%E6%9C%BA%E5%99%A8%E4%BA%BA',
]
script_urls = set()
page_results = []
for idx, url in enumerate(pages):
    try:
        r = client.get(url)
        text = r.text
        (OUT / f'page_{idx}.html').write_text(text, encoding='utf-8', errors='ignore')
        print('PAGE', idx, r.status_code, r.headers.get('content-type'), len(r.content), r.url)
        for src in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', text, re.I):
            script_urls.add(urljoin(str(r.url), html.unescape(src)))
        values = set()
        for pat in [r'https?://[^"\'<>\s]+', r'(?:href|src|data-url|data-file|file-url|pdf-url)=["\']([^"\']+)["\']']:
            for value in re.findall(pat, text, re.I):
                values.add(urljoin(str(r.url), html.unescape(value).replace('\\/', '/')))
        interesting = sorted(v for v in values if any(k in v.lower() for k in ['.pdf', 'download', 'file', 'attachment', 'oss', 'cos', 'cdn', 'report', 'api']))
        contexts=[]
        for term in ['pdf', 'download', 'fileUrl', 'file_url', 'pdfUrl', 'pdf_url', 'attachment', 'reportId', '1136817497660001144e2b0d6510', '登录', '扫码']:
            for m in list(re.finditer(re.escape(term), text, re.I))[:30]:
                contexts.append({'term':term,'context':re.sub(r'\s+',' ',html.unescape(text[max(0,m.start()-700):m.end()+1500]))})
        print('INTERESTING', idx, json.dumps(interesting, ensure_ascii=False)[:20000])
        for c in contexts[:20]: print('CTX', idx, c['term'], c['context'][:2500])
        page_results.append({'url':str(r.url),'interesting':interesting,'contexts':contexts})
    except Exception as exc:
        print('PAGE_ERR', idx, url, repr(exc))

js_results=[]
for idx, url in enumerate(sorted(script_urls)):
    try:
        r=client.get(url)
        text=r.text
        (OUT/f'script_{idx}.js').write_text(text,encoding='utf-8',errors='ignore')
        print('SCRIPT',idx,r.status_code,len(r.content),r.headers.get('content-type'),r.url)
        contexts=[]
        for term in ['pdf','download','fileUrl','file_url','pdfUrl','pdf_url','reportId','/api/','read/','attachment']:
            for m in list(re.finditer(re.escape(term),text,re.I))[:50]:
                contexts.append({'term':term,'context':text[max(0,m.start()-600):m.end()+1200]})
        urls=sorted(set(re.findall(r'https?://[^"\'`<>\\\s]+',text)))
        paths=sorted(set(re.findall(r'["\'](\/[^"\']*(?:pdf|download|file|report|api)[^"\']*)["\']',text,re.I)))
        print('JS_URLS',idx,json.dumps([u for u in urls if any(k in u.lower() for k in ['pdf','download','file','api','report'])][:200],ensure_ascii=False))
        print('JS_PATHS',idx,json.dumps(paths[:300],ensure_ascii=False))
        for c in contexts[:30]: print('JS_CTX',idx,c['term'],c['context'][:2200].replace('\n',' '))
        js_results.append({'url':str(r.url),'urls':urls,'paths':paths,'contexts':contexts})
    except Exception as exc:
        print('SCRIPT_ERR',url,repr(exc))

(OUT/'results.json').write_text(json.dumps({'pages':page_results,'scripts':js_results},ensure_ascii=False,indent=2),encoding='utf-8')
client.close()
