from __future__ import annotations

import json
import re
import urllib.request
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

OUT = Path('out_sinofert_indexes_20260903')
OUT.mkdir(parents=True, exist_ok=True)
URLS = [
    'https://treelazy.com/stock-en/hk/00297',
    'https://treelazy.com/stock-zh/hk/00297',
    'https://financialfilings.com/companies/sinofert-holdings-limited/',
    'https://financialfilings.com/companies/sinofert-holdings-limited/?page=2',
    'http://www.sinofert.com/',
]
headers = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}
rows = []
for url in URLS:
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=90) as r:
            body = r.read().decode('utf-8', 'replace')
            final = r.geturl()
            status = getattr(r, 'status', 200)
        name = re.sub(r'[^A-Za-z0-9]+', '_', url).strip('_')[:100] + '.html'
        (OUT / name).write_text(body, encoding='utf-8')
        anchors = []
        for m in re.finditer(r'<a\b[^>]*?href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', body, re.I | re.S):
            href = urljoin(final, unescape(m.group(1)))
            text = re.sub(r'<[^>]+>', ' ', m.group(2))
            text = unescape(re.sub(r'\s+', ' ', text)).strip()
            if re.search(r'\.pdf(?:$|[?#])|annual|interim|report|result|年報|年报|中期|業績|业绩', f'{text} {href}', re.I):
                anchors.append({'text': text, 'url': href})
        rows.append({'url':url,'final_url':final,'status':status,'bytes':len(body.encode()),'anchors':anchors})
        print('OK', status, len(body), final)
        for a in anchors:
            print('LINK', a['text'], '::', a['url'])
    except Exception as e:
        rows.append({'url':url,'error':repr(e)})
        print('ERR', url, repr(e))
(OUT/'summary.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
