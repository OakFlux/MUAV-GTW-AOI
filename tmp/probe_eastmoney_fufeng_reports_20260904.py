from __future__ import annotations

import json
from pathlib import Path
import requests

OUT = Path('out_eastmoney_fufeng_probe')
OUT.mkdir(exist_ok=True)
URL = 'https://reportapi.eastmoney.com/report/list'
variants = ['00546', '0546', '546', 'HK00546', '00546.HK', '116.00546']
base = {
    'industryCode': '*',
    'pageSize': '5000',
    'industry': '*',
    'rating': '*',
    'ratingChange': '*',
    'beginTime': '2010-01-01',
    'endTime': '2026-09-05',
    'pageNo': '1',
    'fields': '',
    'qType': '0',
    'orgCode': '',
    'rcode': '',
    'p': '1',
    'pageNum': '1',
    'pageNumber': '1',
}
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36',
    'Referer': 'https://data.eastmoney.com/report/stock.jshtml',
    'Accept': 'application/json,text/plain,*/*',
}
all_results = {}
for code in variants:
    params = dict(base, code=code)
    try:
        r = requests.get(URL, params=params, headers=headers, timeout=60)
        print('QUERY', code, r.status_code, len(r.content), r.url)
        print(r.text[:1000])
        r.raise_for_status()
        data = r.json()
        all_results[code] = data
        rows = data.get('data') or []
        print('ROWS', code, len(rows), 'TotalCount', data.get('TotalCount'), 'TotalPage', data.get('TotalPage'))
        for row in rows[:30]:
            print('ROW', code, json.dumps({k: row.get(k) for k in ['stockCode','stockName','title','orgSName','publishDate','infoCode','attachPages','attachSize','encodeUrl']}, ensure_ascii=False))
    except Exception as e:
        all_results[code] = {'error': str(e)}
        print('ERR', code, repr(e))
(OUT/'results.json').write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding='utf-8')
