from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlencode

import httpx

OUT = Path('out_gtht_huayan_public')
OUT.mkdir(exist_ok=True)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
client = httpx.Client(http2=True, follow_redirects=True, timeout=httpx.Timeout(45, connect=20), headers={
    'User-Agent': UA,
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Referer': 'https://irs.gtht.com/irs/reports/public',
})

bundle_urls = {
    'index': 'https://irs.gtht.com/irs/js/index.671a8b3b.js',
    'reports': 'https://irs.gtht.com/irs/js/reports.17757cc2.js',
    'vendors': 'https://irs.gtht.com/irs/js/chunk-vendors.da61fe9e.js',
}
texts = {}
for key, url in bundle_urls.items():
    try:
        r = client.get(url)
        text = r.text
        texts[key] = text
        (OUT / f'{key}.js').write_text(text, encoding='utf-8', errors='ignore')
        print('BUNDLE', key, r.status_code, r.headers.get('content-type'), len(r.content), r.url)
    except Exception as exc:
        print('BUNDLE_ERR', key, repr(exc))

# Print compact contexts around report APIs and their call sites.
needles = [
    'qryCompName','qryHomePage','qryNewest','qryRecommend','qryReptDatails','qryReptType','qryIndustryInfo',
    'inreptFrontPage','inreptGetDetail','inreptDownload','onrept','/reports/public','filePath','fileName',
    'reportTitle','companyName','compName','stockCode','pageNum','pageSize','publishDate','researchReport',
]
contexts = []
for key, text in texts.items():
    for needle in needles:
        for match in list(re.finditer(re.escape(needle), text, re.I))[:40]:
            context = text[max(0, match.start()-1800):match.end()+3600]
            record = {'bundle': key, 'needle': needle, 'context': context}
            contexts.append(record)
            print('\nCTX', key, needle, '\n', context[:8000])
(OUT / 'contexts.json').write_text(json.dumps(contexts, ensure_ascii=False, indent=2), encoding='utf-8')

# Extract likely API paths and absolute URLs.
all_text = '\n'.join(texts.values())
paths = sorted(set(re.findall(r'["\'](\/[^"\']*(?:onrept|inrept|report|research|download|file)[^"\']*)["\']', all_text, re.I)))
urls = sorted(set(re.findall(r'https?://[^"\'`<>\\\s]+', all_text)))
print('PATHS', json.dumps(paths[:1000], ensure_ascii=False))
print('URLS', json.dumps([u for u in urls if any(k in u.lower() for k in ['irs','api','report','research','download','pdf'])][:1000], ensure_ascii=False))
(OUT / 'paths.json').write_text(json.dumps({'paths': paths, 'urls': urls}, ensure_ascii=False, indent=2), encoding='utf-8')

# Probe only unauthenticated public-looking endpoints with ordinary search payloads.
bases = [
    'https://irs.gtht.com/irs/api',
    'https://irs.gtht.com/irs/api/fesServer',
    'https://irs.gtht.com/api',
]
endpoints = ['onrept/qryCompName','onrept/qryHomePage','onrept/qryNewest','onrept/qryRecommend','onrept/qryReptType','onrept/qryIndustryInfo']
payloads = [
    {},
    {'compName': '华沿机器人'},
    {'companyName': '华沿机器人'},
    {'keyword': '华沿机器人'},
    {'keyWord': '华沿机器人'},
    {'stockCode': '01021'},
    {'stockCode': '1021'},
    {'pageNum': 1, 'pageSize': 50, 'keyword': '华沿机器人'},
    {'pageNo': 1, 'pageSize': 50, 'compName': '华沿机器人'},
    {'current': 1, 'size': 50, 'companyName': '华沿机器人'},
]
probe_results = []
for base in bases:
    for endpoint in endpoints:
        url = f'{base}/{endpoint}'
        for method in ['GET','POST_JSON','POST_FORM']:
            for payload in payloads:
                try:
                    if method == 'GET':
                        r = client.get(url, params=payload, headers={'Accept':'application/json,text/plain,*/*'})
                    elif method == 'POST_JSON':
                        r = client.post(url, json=payload, headers={'Accept':'application/json,text/plain,*/*','Content-Type':'application/json'})
                    else:
                        r = client.post(url, data=payload, headers={'Accept':'application/json,text/plain,*/*'})
                    preview = r.text[:12000]
                    row = {'method':method,'url':str(r.url),'payload':payload,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(r.content),'preview':preview}
                    probe_results.append(row)
                    if r.status_code != 404 or len(r.content) > 200:
                        print('PROBE', json.dumps(row, ensure_ascii=False)[:15000])
                    # Stop payload variations after a clearly successful data response.
                    if r.status_code == 200 and any(term in preview for term in ['华沿机器人','華沿機器人','1021','data','rows','records']):
                        pass
                except Exception as exc:
                    print('PROBE_ERR', method, url, payload, repr(exc))
(OUT / 'probes.json').write_text(json.dumps(probe_results, ensure_ascii=False, indent=2), encoding='utf-8')
client.close()
