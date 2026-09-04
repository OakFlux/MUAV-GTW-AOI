from __future__ import annotations

import json
from pathlib import Path

import requests

OUT = Path('out_sdy_fufeng_search')
OUT.mkdir(exist_ok=True)
URL = 'https://api.sdyanbao.com/api/file/search'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36',
    'Referer': 'https://www.sdyanbao.com/report?keyword=%E9%98%9C%E4%B8%B0',
    'Origin': 'https://www.sdyanbao.com',
    'Content-Type': 'application/json',
    'Accept': 'application/json,text/plain,*/*',
}
variants = [
    {'device':1,'hideTrader':0,'onlyTitle':0,'order':0,'page':1,'pageSize':100,'keyword':'阜丰','pageCount':0,'dateRange':0,'startTime':'','endTime':'','typeIds':'','industryIds':'','opFrom':1},
    {'device':1,'hideTrader':0,'onlyTitle':1,'order':0,'page':1,'pageSize':100,'keyword':'阜丰集团','pageCount':0,'dateRange':0,'startTime':'','endTime':'','typeIds':'','industryIds':'','opFrom':1},
]
all_data=[]
for payload in variants:
    r=requests.post(URL,headers=HEADERS,json=payload,timeout=60)
    print('POST',r.status_code,len(r.content),r.text[:500])
    r.raise_for_status()
    data=r.json(); all_data.append({'payload':payload,'response':data})
    files=(data.get('data') or {}).get('files') or data.get('files') or []
    print('FILES',len(files))
    for f in files:
        print('FILE',json.dumps({k:f.get(k) for k in ['id','name','page_count','size','file_size','time_text','create_time','page_url','share_url','original_id','organization','researcher','type','industry']},ensure_ascii=False))
(OUT/'results.json').write_text(json.dumps(all_data,ensure_ascii=False,indent=2),encoding='utf-8')
