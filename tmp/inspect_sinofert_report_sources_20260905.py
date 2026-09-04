from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

OUT = Path('out_sinofert_source_inspect')
OUT.mkdir(exist_ok=True)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
client = httpx.Client(http2=True, follow_redirects=True, timeout=45, headers={'User-Agent': UA})

all_results = {}

# Eastmoney public research-report API, testing common HK code variants.
for code in ['00297', '297', 'HK00297', '116.00297']:
    params = {
        'code': code,
        'pageSize': '200',
        'pageNo': '1',
        'beginTime': '2010-01-01',
        'endTime': '2026-09-05',
        'qType': '0',
        'fields': '',
        'industryCode': '*',
        'industry': '*',
        'rating': '*',
        'ratingChange': '*',
        'orgCode': '',
        'rcode': '',
        'p': '1', 'pageNum': '1', 'pageNumber': '1',
    }
    url = 'https://reportapi.eastmoney.com/report/list'
    try:
        r = client.get(url, params=params, headers={'Referer': 'https://data.eastmoney.com/report/'})
        print('EM', code, r.status_code, r.headers.get('content-type'), len(r.content), r.url)
        text = r.text
        try:
            obj = r.json()
        except Exception:
            # Strip JSONP if present.
            m = re.search(r'^[^(]*\((.*)\)\s*;?$', text, re.S)
            obj = json.loads(m.group(1)) if m else {'raw': text[:1000]}
        data = obj.get('data', []) if isinstance(obj, dict) else []
        all_results[f'em_{code}'] = obj
        print('  data count', len(data))
        for item in data:
            title = item.get('title') or item.get('TITLE') or ''
            print('  ITEM', item.get('publishDate'), item.get('orgSName'), item.get('infoCode'), title)
    except Exception as exc:
        print('EM ERROR', code, repr(exc))

# Eastmoney HK data-center candidate report names.
report_names = [
    'RPT_HKF10_FN_GONGBU',
    'RPT_HKF10_RESEARCHREPORT',
    'RPT_HKF10_RESEARCH',
    'RPT_HKF10_ORG_RATING',
    'RPT_HKF10_ORG_PREDICT',
]
for report_name in report_names:
    params = {
        'sortColumns': 'REPORT_DATE,NOTICE_DATE',
        'sortTypes': '-1,-1',
        'pageSize': '200',
        'pageNumber': '1',
        'reportName': report_name,
        'columns': 'ALL',
        'filter': '(SECURITY_CODE="00297")',
    }
    url = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
    try:
        r = client.get(url, params=params, headers={'Referer': 'https://emweb.securities.eastmoney.com/'})
        print('DC', report_name, r.status_code, len(r.content), r.url)
        try:
            obj = r.json()
        except Exception:
            obj = {'raw': r.text[:1000]}
        all_results[f'dc_{report_name}'] = obj
        data = ((obj.get('result') or {}).get('data') or []) if isinstance(obj, dict) else []
        print('  data count', len(data))
        for item in data[:30]:
            print('  ITEM', json.dumps(item, ensure_ascii=False)[:1500])
    except Exception as exc:
        print('DC ERROR', report_name, repr(exc))

# Inspect candidate public index pages for embedded full-PDF links or metadata.
pages = {
    'fx_4912455': 'https://www.fxbaogao.com/detail/4912455',
    'fx_5026697': 'https://www.fxbaogao.com/detail/5026697',
    'fx_5056484': 'https://www.fxbaogao.com/detail/5056484',
    'fx_5327100': 'https://www.fxbaogao.com/detail/5327100',
    'hangyan_3660300256878265796': 'https://www.hangyan.co/reports/3660300256878265796',
    'hangyan_3598151030379906883': 'https://www.hangyan.co/reports/3598151030379906883',
    'joestudy_46058': 'https://yanbao.joestudy.net/46058',
}
for key, url in pages.items():
    try:
        r = client.get(url)
        print('PAGE', key, r.status_code, r.headers.get('content-type'), len(r.content), r.url)
        OUT.joinpath(key + '.html').write_bytes(r.content)
        patterns = sorted(set(re.findall(r'https?://[^\"\'<>\\ ]+', r.text)))
        interesting = [u for u in patterns if any(s in u.lower() for s in ['.pdf', 'download', 'report', 'file', 'oss', 'cos', 'cdn'])]
        print('  INTERESTING', json.dumps(interesting[:100], ensure_ascii=False))
        for pat in ['infoCode', 'pdfUrl', 'pdf_url', 'downloadUrl', 'download_url', 'fileUrl', 'file_url', 'report-image', '4912455', '5026697', '5056484', '5327100']:
            if pat in r.text:
                idx = r.text.find(pat)
                print('  CONTEXT', pat, r.text[max(0, idx-300):idx+800].replace('\n', ' ')[:1200])
    except Exception as exc:
        print('PAGE ERROR', key, repr(exc))

OUT.joinpath('all_results.json').write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding='utf-8')
client.close()
