from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import requests
from pypdf import PdfReader

OUT = Path('out_ascletis_eastmoney')
PDFS = OUT / 'pdfs'
OUT.mkdir(exist_ok=True)
PDFS.mkdir(exist_ok=True)

S = requests.Session()
S.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36',
    'Referer': 'https://data.eastmoney.com/report/stock.jshtml',
    'Accept': 'application/json,text/plain,*/*',
})

KEYS = ['歌礼制药', '歌禮製藥', 'ASCLETIS', '01672', '1672.HK', '全新GLP-1减重不减肌', '口服小分子率先破局']
WINDOWS = [
    ('2025-03-28', '2025-04-05'),
    ('2025-08-12', '2025-08-22'),
    ('2025-12-24', '2026-01-05'),
    ('2026-03-28', '2026-04-10'),
    ('2026-08-01', '2026-09-06'),
]

def relevant(item: dict) -> bool:
    blob = json.dumps(item, ensure_ascii=False).lower()
    return any(k.lower() in blob for k in KEYS)

matches: dict[str, dict] = {}
raw_meta = []

# Legacy GET endpoint. Query direct code variants and every report in narrow date windows.
for begin, end in WINDOWS:
    for code in ['', '01672', '1672', 'HK01672', '116.01672']:
        for qtype in ['0', '1', '2']:
            page = 1
            while page <= 30:
                params = {
                    'pageNo': page, 'pageSize': 100, 'code': code,
                    'industryCode': '*', 'industry': '*', 'rating': '*', 'ratingChange': '*',
                    'beginTime': begin, 'endTime': end, 'fields': '', 'qType': qtype,
                    'orgCode': '', 'rcode': '', 'p': page, 'pageNum': page, 'pageNumber': page,
                }
                try:
                    r = S.get('https://reportapi.eastmoney.com/report/list', params=params, timeout=60)
                    obj = r.json()
                    data = obj.get('data') or [] if isinstance(obj, dict) else []
                    total = int(obj.get('TotalPage') or 1) if isinstance(obj, dict) else 1
                    print('GET_LIST', begin, end, code or '*', qtype, page, r.status_code, len(data), total)
                    raw_meta.append({'endpoint':'list','begin':begin,'end':end,'code':code,'qtype':qtype,'page':page,'rows':len(data),'total':total})
                    for item in data:
                        if relevant(item):
                            key = str(item.get('infoCode') or item.get('encodeUrl') or json.dumps(item, sort_keys=True, ensure_ascii=False))
                            matches[key] = item
                            print('MATCH_GET', json.dumps(item, ensure_ascii=False))
                    if page >= total or not data:
                        break
                    page += 1
                    time.sleep(0.15)
                except Exception as exc:
                    print('GET_ERR', begin, end, code, qtype, page, repr(exc))
                    break

# New POST endpoint, trying common schemas/code variants.
for begin, end in WINDOWS:
    for code in ['01672', '1672', 'HK01672', '01672.HK', '1672.HK', '116.01672', '']:
        for market in [None, 'HK', '116']:
            payload = {
                'pageSize': 5000, 'pageNo': 1, 'p': 1, 'pageNum': 1, 'pageNumber': 1,
                'beginTime': begin, 'endTime': end, 'code': code, 'industryCode': '*',
                'rating': None, 'ratingChange': None, 'orgCode': None, 'rcode': '',
            }
            if market is not None:
                payload['market'] = market
            try:
                r = S.post('https://reportapi.eastmoney.com/report/list2', json=payload, timeout=60)
                obj = r.json()
                data = obj.get('data') or [] if isinstance(obj, dict) else []
                print('POST_LIST2', begin, end, code or '*', market, r.status_code, len(data))
                raw_meta.append({'endpoint':'list2','begin':begin,'end':end,'code':code,'market':market,'rows':len(data)})
                for item in data:
                    if relevant(item):
                        key = str(item.get('infoCode') or item.get('encodeUrl') or json.dumps(item, sort_keys=True, ensure_ascii=False))
                        matches[key] = item
                        print('MATCH_POST', json.dumps(item, ensure_ascii=False))
            except Exception as exc:
                print('POST_ERR', begin, end, code, market, repr(exc))

valid = []
seen = set()
for idx, (key, item) in enumerate(matches.items(), 1):
    info_codes = []
    for field in ['infoCode', 'INFO_CODE', 'reportId', 'id']:
        value = item.get(field)
        if value:
            info_codes.append(str(value))
    urls = []
    blob = json.dumps(item, ensure_ascii=False)
    urls.extend(re.findall(r'https?://[^"\\\s<>]+', blob))
    for info in info_codes:
        urls.extend([
            f'https://pdf.dfcfw.com/pdf/H3_{info}_1.pdf',
            f'https://pdf.dfcfw.com/pdf/H3_{info}.pdf',
            f'https://pdf.dfcfw.com/pdf/H2_{info}_1.pdf',
        ])
    for uidx, url in enumerate(dict.fromkeys(urls)):
        url = url.replace('\\/', '/')
        try:
            r = S.get(url, timeout=90, headers={'Accept':'application/pdf,*/*', 'Referer':'https://data.eastmoney.com/'})
            print('PDF_PROBE', idx, uidx, r.status_code, r.headers.get('content-type'), len(r.content), url)
            if r.status_code != 200 or len(r.content) < 50000 or not r.content.startswith(b'%PDF-'):
                continue
            sha = hashlib.sha256(r.content).hexdigest()
            if sha in seen:
                continue
            seen.add(sha)
            p = PDFS / f'{idx:02d}_{sha[:12]}.pdf'
            p.write_bytes(r.content)
            reader = PdfReader(str(p), strict=False)
            pages = len(reader.pages)
            text = '\n'.join((pg.extract_text() or '') for pg in reader.pages[:min(12, pages)])
            norm = re.sub(r'\s+', '', text).lower()
            identity_ok = any(token in norm for token in ['歌礼制药', '歌禮製藥', 'ascletis', '01672', '1672.hk'])
            result = {'path':str(p),'url':url,'pages':pages,'bytes':len(r.content),'sha256':sha,'identity_ok':identity_ok,'item':item,'sample':text[:6000]}
            valid.append(result)
            print('PDF_VALID', json.dumps({k:v for k,v in result.items() if k not in ['item','sample']}, ensure_ascii=False))
        except Exception as exc:
            print('PDF_ERR', url, repr(exc))

(OUT/'matches.json').write_text(json.dumps(list(matches.values()), ensure_ascii=False, indent=2), encoding='utf-8')
(OUT/'valid.json').write_text(json.dumps(valid, ensure_ascii=False, indent=2), encoding='utf-8')
(OUT/'raw_meta.json').write_text(json.dumps(raw_meta, ensure_ascii=False, indent=2), encoding='utf-8')
print('DONE', len(matches), len(valid))
