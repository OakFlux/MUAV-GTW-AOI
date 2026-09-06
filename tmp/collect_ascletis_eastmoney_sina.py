from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from pypdf import PdfReader

OUT = Path('out_ascletis_eastmoney_sina')
PDFDIR = OUT / 'pdfs'
OUT.mkdir(exist_ok=True)
PDFDIR.mkdir(exist_ok=True)

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
s = requests.Session()
s.headers.update({'User-Agent': UA, 'Accept': 'application/json,text/html,*/*'})
terms = ['歌礼制药', '歌禮製藥', 'Ascletis', '01672', '1672.HK', '全新GLP-1减重不减肌', '口服小分子率先破局']

def relevant(obj) -> bool:
    blob = json.dumps(obj, ensure_ascii=False).lower()
    return any(term.lower() in blob for term in terms)

def save_pdf(data: bytes, label: str, url: str, meta: dict, saved: list, hashes: set):
    if len(data) < 50000 or not data.startswith(b'%PDF-'):
        return
    sha = hashlib.sha256(data).hexdigest()
    if sha in hashes:
        return
    hashes.add(sha)
    path = PDFDIR / f'{label}_{sha[:12]}.pdf'
    path.write_bytes(data)
    try:
        reader = PdfReader(str(path), strict=False)
        pages = len(reader.pages)
        text = '\n'.join((page.extract_text() or '') for page in reader.pages[:min(12, pages)])
    except Exception as exc:
        pages, text = -1, ''
        print('PARSE_ERR', path, repr(exc))
    normalized = re.sub(r'\s+', '', text).lower()
    identity_ok = any(x in normalized for x in ['歌礼制药', '歌禮製藥', 'ascletis', '01672', '1672hk'])
    item = {'path': str(path), 'url': url, 'pages': pages, 'bytes': len(data), 'sha256': sha, 'identity_ok': identity_ok, 'metadata': meta, 'sample': text[:5000]}
    saved.append(item)
    print('SAVED', json.dumps({k:v for k,v in item.items() if k not in ['sample','metadata']}, ensure_ascii=False))

saved = []
hashes = set()
matches = []

# Eastmoney legacy and POST endpoints across narrow date windows.
windows = [
    ('2024-08-28','2024-09-06'),
    ('2025-03-28','2025-04-08'),
    ('2025-12-23','2026-01-05'),
]
codes = ['', '01672', '1672', 'HK01672', '01672.HK', '116.01672']
for begin, end in windows:
    for qtype in ['0','1','2','3']:
        for code in codes:
            params = {
                'code': code, 'pageSize': '5000', 'pageNo': '1', 'beginTime': begin, 'endTime': end,
                'qType': qtype, 'fields': '', 'industryCode': '*', 'industry': '*', 'rating': '*',
                'ratingChange': '*', 'orgCode': '', 'rcode': '', 'p': '1', 'pageNum': '1', 'pageNumber': '1',
            }
            try:
                r = s.get('https://reportapi.eastmoney.com/report/list', params=params, headers={'Referer':'https://data.eastmoney.com/report/'}, timeout=60)
                obj = r.json()
                rows = obj.get('data') or [] if isinstance(obj, dict) else []
                print('EM_GET', begin, end, qtype, code or '*', r.status_code, len(rows), len(r.content))
                for row in rows:
                    if relevant(row):
                        matches.append({'source':'eastmoney_get','query':params,'row':row})
                        print('EM_MATCH', json.dumps(row, ensure_ascii=False))
            except Exception as exc:
                print('EM_GET_ERR', begin, qtype, code, repr(exc))
            time.sleep(0.1)

            body = {
                'pageSize': 5000, 'pageNo': 1, 'p':1, 'pageNum':1, 'pageNumber':1,
                'beginTime': begin, 'endTime': end, 'code': code, 'industryCode':'*',
                'rating': None, 'ratingChange': None, 'orgCode': None, 'rcode':'',
            }
            try:
                r = s.post('https://reportapi.eastmoney.com/report/list2', json=body, headers={'Referer':'https://data.eastmoney.com/report/'}, timeout=60)
                obj = r.json()
                rows = obj.get('data') or [] if isinstance(obj, dict) else []
                print('EM_POST', begin, end, code or '*', r.status_code, len(rows), len(r.content))
                for row in rows:
                    if relevant(row):
                        matches.append({'source':'eastmoney_post','query':body,'row':row})
                        print('EM_POST_MATCH', json.dumps(row, ensure_ascii=False))
            except Exception as exc:
                print('EM_POST_ERR', begin, code, repr(exc))

# De-duplicate Eastmoney rows and fetch original PDF URLs.
unique_rows = {}
for item in matches:
    row = item['row']
    key = str(row.get('infoCode') or row.get('encodeUrl') or json.dumps(row, sort_keys=True, ensure_ascii=False))
    unique_rows[key] = row
for idx, (key, row) in enumerate(unique_rows.items()):
    urls = []
    info = row.get('infoCode') or row.get('INFOCODE')
    if info:
        urls.extend([f'https://pdf.dfcfw.com/pdf/H3_{info}_1.pdf', f'https://pdf.dfcfw.com/pdf/H3_{info}.pdf'])
    blob = json.dumps(row, ensure_ascii=False)
    urls.extend(re.findall(r'https?://[^"\'\\\s<>]+', blob))
    for j, url in enumerate(dict.fromkeys(urls)):
        url = url.replace('\\/','/')
        try:
            r = s.get(url, headers={'Referer':'https://data.eastmoney.com/report/','Accept':'application/pdf,*/*'}, timeout=90)
            print('EM_PDF', r.status_code, r.headers.get('content-type'), len(r.content), url)
            save_pdf(r.content, f'eastmoney_{idx}_{j}', url, row, saved, hashes)
        except Exception as exc:
            print('EM_PDF_ERR', url, repr(exc))

# Sina report list/search and exact title search pages.
sina_urls = [
    'https://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?symbol=hk01672&orgname=&industry=&title=&t1=all',
    'https://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?symbol=&orgname=&industry=&title=%E6%AD%8C%E7%A4%BC%E5%88%B6%E8%8D%AF&t1=all',
    'https://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?symbol=&orgname=&industry=&title=%E5%85%A8%E6%96%B0GLP-1%E5%87%8F%E9%87%8D%E4%B8%8D%E5%87%8F%E8%82%8C&t1=all',
]
show_pages = set()
for idx, url in enumerate(sina_urls):
    try:
        r = s.get(url, timeout=60)
        raw = r.content
        text = raw.decode('gb18030', errors='ignore')
        (OUT / f'sina_list_{idx}.html').write_text(text, encoding='utf-8')
        print('SINA_LIST', idx, r.status_code, len(raw), r.url)
        for href in re.findall(r'(?:href|url)=["\']([^"\']*vReport_Show[^"\']*)["\']', text, re.I):
            show_pages.add(urljoin(str(r.url), href.replace('&amp;','&')))
    except Exception as exc:
        print('SINA_LIST_ERR', idx, repr(exc))

for idx, url in enumerate(sorted(show_pages)):
    try:
        r = s.get(url, timeout=60)
        text = r.content.decode('gb18030', errors='ignore')
        if not relevant({'text': text}):
            continue
        (OUT / f'sina_show_{idx}.html').write_text(text, encoding='utf-8')
        print('SINA_SHOW_MATCH', url, len(text))
        candidates = set(re.findall(r'https?://[^"\'<>\s]+', text))
        candidates.update(urljoin(str(r.url), href) for href in re.findall(r'(?:href|src)=["\']([^"\']+)["\']', text, re.I))
        for j, candidate in enumerate(sorted(candidates)):
            candidate = candidate.replace('&amp;','&').replace('\\/','/')
            if not any(token in candidate.lower() for token in ['.pdf','download','attachment','dfcfw']):
                continue
            try:
                rr = s.get(candidate, headers={'Referer':url,'Accept':'application/pdf,*/*'}, timeout=90)
                print('SINA_PDF', rr.status_code, rr.headers.get('content-type'), len(rr.content), candidate)
                save_pdf(rr.content, f'sina_{idx}_{j}', candidate, {'page':url}, saved, hashes)
            except Exception as exc:
                print('SINA_PDF_ERR', candidate, repr(exc))
    except Exception as exc:
        print('SINA_SHOW_ERR', url, repr(exc))

(OUT / 'matches.json').write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding='utf-8')
(OUT / 'saved_pdfs.json').write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding='utf-8')
print('DONE', len(unique_rows), len(saved))
