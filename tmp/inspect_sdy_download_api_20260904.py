from __future__ import annotations

import json
import re
from pathlib import Path

import requests

OUT = Path('out_sdy_download_api_inspect')
OUT.mkdir(exist_ok=True)
BASE = 'https://www.sdyanbao.com/_nuxt/'
CHUNKS = ['86c5b4f.js', '0bec462.js', '7ff3a18.js', '359ac1f.js', 'a94fdf1.js']
HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.sdyanbao.com/detail/817436'}

summary = {}
for name in CHUNKS:
    url = BASE + name
    r = requests.get(url, headers=HEADERS, timeout=60)
    print('FETCH', name, r.status_code, len(r.content), r.headers.get('content-type'))
    r.raise_for_status()
    text = r.text
    (OUT / name).write_text(text, encoding='utf-8')
    contexts = []
    patterns = [
        r'/api/file/[A-Za-z0-9_/-]+',
        r'report[-_]?down',
        r'download',
        r'original_id',
        r'file_url',
        r'page_url',
        r'unlock',
        r'vip',
    ]
    for pattern in patterns:
        for m in re.finditer(pattern, text, re.I):
            contexts.append({
                'pattern': pattern,
                'match': m.group(0),
                'context': text[max(0, m.start()-700):m.end()+1200]
            })
            if len(contexts) >= 100:
                break
        if len(contexts) >= 100:
            break
    summary[name] = contexts
    print('CONTEXT_COUNT', name, len(contexts))
    for c in contexts[:30]:
        print('\nCTX', name, c['match'])
        print(c['context'][:2200])

(OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
print('READY')
