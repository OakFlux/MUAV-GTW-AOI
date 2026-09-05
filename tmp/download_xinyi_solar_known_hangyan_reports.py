from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path

import requests
from pypdf import PdfReader

OUT = Path('out_xinyi_solar_known_hangyan')
PDFS = OUT / 'pdfs'
OUT.mkdir(exist_ok=True)
PDFS.mkdir(exist_ok=True)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
s = requests.Session()
s.headers.update({'User-Agent': UA, 'Accept-Language':'zh-CN,zh;q=0.9,en;q=0.8'})

REPORTS = [
    ('2024_bocom', 'https://www.hangyan.co/reports/3402974878104552641'),
    ('2025_guoyuan', 'https://www.hangyan.co/reports/3541189723936523517'),
    ('2025_guosheng', 'https://www.hangyan.co/reports/3693579618444379624'),
    ('2026_guojin', 'https://www.hangyan.co/reports/3843608737805763979'),
]

manifest=[]
for label,page_url in REPORTS:
    r=s.get(page_url,timeout=60)
    print('PAGE',label,r.status_code,len(r.content),r.url)
    text=r.text
    (OUT/f'{label}.html').write_text(text,encoding='utf-8',errors='ignore')
    candidates=set(html.unescape(x).replace('\\/','/') for x in re.findall(r'https?://[^\"\'<>\\\s]+\.pdf(?:\?[^\"\'<>\\\s]*)?',text,re.I))
    print('CANDIDATES',label,json.dumps(sorted(candidates),ensure_ascii=False))
    for idx,url in enumerate(sorted(candidates)):
        rr=s.get(url,timeout=90,headers={'Referer':page_url,'Accept':'application/pdf,*/*'})
        print('PDF',label,rr.status_code,rr.headers.get('content-type'),len(rr.content),url)
        if rr.status_code!=200 or len(rr.content)<50000 or not rr.content.startswith(b'%PDF-'):
            continue
        sha=hashlib.sha256(rr.content).hexdigest()
        p=PDFS/f'{label}_{idx}_{sha[:12]}.pdf';p.write_bytes(rr.content)
        reader=PdfReader(str(p),strict=False);pages=len(reader.pages)
        sample='\n'.join((pg.extract_text() or '') for pg in reader.pages[:min(10,pages)])
        norm=re.sub(r'\s+','',sample).lower()
        ok=any(k in norm for k in ['信义光能','信義光能','xinyisolar','00968','968hk'])
        if not ok:
            p.unlink(missing_ok=True); print('REJECT_IDENTITY',label,pages);continue
        title_match=re.search(r'<title>(.*?)</title>',text,re.I|re.S)
        title=re.sub(r'\s+',' ',html.unescape(title_match.group(1))).strip() if title_match else label
        meta_match=re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',text,re.I)
        if meta_match:title=html.unescape(meta_match.group(1))
        row={'label':label,'page_url':page_url,'title':title,'pdf_url':url,'path':str(p),'pages':pages,'bytes':len(rr.content),'sha256':sha,'sample':sample[:2500]}
        manifest.append(row);print('VALID',json.dumps({k:v for k,v in row.items() if k!='sample'},ensure_ascii=False))

(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print('DONE',len(manifest))
