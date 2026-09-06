from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import requests
from pypdf import PdfReader

OUT = Path('out_qunabox_eastmoney_exact')
PDFS = OUT / 'pdfs'
OUT.mkdir(exist_ok=True)
PDFS.mkdir(exist_ok=True)

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36',
    'Referer': 'https://data.eastmoney.com/report/',
    'Accept': 'application/json,text/plain,*/*',
})

keywords = [
    '趣致集团', '趣致集團', 'Qunabox', '00917', '0917.HK',
    '国内领先的AIoT营销服务平台', 'AI互动营销领导者', '深耕KA客户',
    '物理AI构建营销闭环', 'AI营销加速放量', '存量终端迈入AI变现周期'
]
windows = [
    ('2024-09-15', '2024-09-26'),
    ('2025-01-10', '2025-01-21'),
    ('2026-03-08', '2026-03-18'),
    ('2026-07-20', '2026-08-31'),
]


def relevant(item: dict) -> bool:
    blob = json.dumps(item, ensure_ascii=False).lower()
    return any(k.lower() in blob for k in keywords)


def request_json(url: str, *, method='get', **kwargs):
    for attempt in range(1, 5):
        try:
            r = session.request(method, url, timeout=60, **kwargs)
            print('HTTP', method.upper(), r.status_code, len(r.content), r.url)
            if r.status_code == 200:
                return r.json()
        except Exception as exc:
            print('HTTP_ERR', attempt, url, repr(exc))
        time.sleep(attempt)
    return None


matches: dict[str, dict] = {}
raw_meta = []
list_url = 'https://reportapi.eastmoney.com/report/list'

# Traverse every page in narrow publication windows. This avoids relying on the
# stock-code filter, which is inconsistent for Hong Kong reports.
for begin, end in windows:
    page = 1
    while page <= 100:
        params = {
            'code': '', 'pageSize': 100, 'pageNo': page,
            'beginTime': begin, 'endTime': end, 'qType': 0, 'fields': '',
            'industryCode': '*', 'industry': '*', 'rating': '*', 'ratingChange': '*',
            'orgCode': '', 'rcode': '', 'p': page, 'pageNum': page, 'pageNumber': page,
        }
        obj = request_json(list_url, params=params)
        if not isinstance(obj, dict):
            break
        data = obj.get('data') or []
        raw_meta.append({'source': 'list', 'begin': begin, 'end': end, 'page': page,
                         'total_page': obj.get('TotalPage'), 'hits': obj.get('hits'), 'count': len(data)})
        print('PAGE', begin, end, page, 'of', obj.get('TotalPage'), 'rows', len(data))
        for item in data:
            if relevant(item):
                key = str(item.get('infoCode') or json.dumps(item, sort_keys=True, ensure_ascii=False))
                matches[key] = item
                print('MATCH_LIST', json.dumps(item, ensure_ascii=False))
        total_page = int(obj.get('TotalPage') or 1)
        if page >= total_page or not data:
            break
        page += 1
        time.sleep(0.15)

# New POST endpoint, with common code variants and keyword-like codes.
list2_url = 'https://reportapi.eastmoney.com/report/list2'
for code in ['00917', '0917', '917', 'HK00917', '00917.HK', 'Qunabox', '趣致集团']:
    for begin, end in windows:
        body = {
            'pageSize': 5000, 'pageNo': 1, 'p': 1, 'pageNum': 1, 'pageNumber': 1,
            'beginTime': begin, 'endTime': end, 'code': code,
            'industryCode': '*', 'rating': None, 'ratingChange': None,
            'orgCode': None, 'rcode': '',
        }
        obj = request_json(list2_url, method='post', json=body)
        data = (obj or {}).get('data') or [] if isinstance(obj, dict) else []
        print('LIST2', code, begin, end, 'rows', len(data))
        for item in data:
            if relevant(item):
                key = str(item.get('infoCode') or json.dumps(item, sort_keys=True, ensure_ascii=False))
                matches[key] = item
                print('MATCH_LIST2', json.dumps(item, ensure_ascii=False))

# Probe likely HK research datasets in Eastmoney's data-center API.
dc_url = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
report_names = [
    'RPT_HKF10_RESEARCHREPORT', 'RPT_HKF10_RESEARCH', 'RPT_HKF10_ORG_RATING',
    'RPT_HKF10_ORG_PREDICT', 'RPT_HK_RESEARCH_REPORT', 'RPT_HK_RESEARCH'
]
for report_name in report_names:
    params = {
        'sortColumns': 'REPORT_DATE,NOTICE_DATE', 'sortTypes': '-1,-1',
        'pageSize': 500, 'pageNumber': 1, 'reportName': report_name,
        'columns': 'ALL', 'filter': '(SECURITY_CODE="00917")',
    }
    obj = request_json(dc_url, params=params)
    data = (((obj or {}).get('result') or {}).get('data') or []) if isinstance(obj, dict) else []
    print('DATACENTER', report_name, 'rows', len(data))
    for item in data:
        if relevant(item):
            key = str(item.get('INFO_CODE') or item.get('REPORT_ID') or json.dumps(item, sort_keys=True, ensure_ascii=False))
            matches[key] = item
            print('MATCH_DC', json.dumps(item, ensure_ascii=False))

valid = []
seen_sha = set()
for idx, (key, item) in enumerate(matches.items(), 1):
    candidate_urls = []
    info = item.get('infoCode') or item.get('INFO_CODE') or item.get('REPORT_ID')
    if info:
        candidate_urls += [
            f'https://pdf.dfcfw.com/pdf/H3_{info}_1.pdf',
            f'https://pdf.dfcfw.com/pdf/H3_{info}.pdf',
        ]
    for field, value in item.items():
        if isinstance(value, str) and value.startswith('http'):
            candidate_urls.append(value.replace('\\/', '/'))
    for u in dict.fromkeys(candidate_urls):
        try:
            r = session.get(u, timeout=90, headers={'Accept': 'application/pdf,application/octet-stream,*/*'})
            print('PDF_PROBE', r.status_code, r.headers.get('content-type'), len(r.content), u)
            if r.status_code != 200 or len(r.content) < 50000 or not r.content.startswith(b'%PDF-'):
                continue
            sha = hashlib.sha256(r.content).hexdigest()
            if sha in seen_sha:
                break
            seen_sha.add(sha)
            p = PDFS / f'{idx:02d}_{sha[:12]}.pdf'
            p.write_bytes(r.content)
            try:
                reader = PdfReader(str(p), strict=False)
                pages = len(reader.pages)
                sample = '\n'.join((pg.extract_text() or '') for pg in reader.pages[:min(12, pages)])
            except Exception as exc:
                print('PARSE_ERR', repr(exc))
                pages, sample = -1, ''
            norm = re.sub(r'\s+', '', sample).lower()
            identity_ok = any(x in norm for x in ['趣致集团', '趣致集團', 'qunabox', '00917', '0917hk'])
            row = {'path': str(p), 'url': u, 'bytes': len(r.content), 'sha256': sha,
                   'pages': pages, 'identity_ok': identity_ok, 'metadata': item, 'sample': sample[:5000]}
            valid.append(row)
            print('PDF_VALID', json.dumps({k:v for k,v in row.items() if k not in ['metadata','sample']}, ensure_ascii=False))
            break
        except Exception as exc:
            print('PDF_ERR', u, repr(exc))

(OUT/'raw_meta.json').write_text(json.dumps(raw_meta, ensure_ascii=False, indent=2), encoding='utf-8')
(OUT/'matches.json').write_text(json.dumps(list(matches.values()), ensure_ascii=False, indent=2), encoding='utf-8')
(OUT/'valid.json').write_text(json.dumps(valid, ensure_ascii=False, indent=2), encoding='utf-8')
print('DONE matches', len(matches), 'valid', len(valid))
