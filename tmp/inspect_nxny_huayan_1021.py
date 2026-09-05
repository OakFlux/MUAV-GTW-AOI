from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import httpx

OUT = Path('out_nxny_huayan_1021')
OUT.mkdir(exist_ok=True)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
client = httpx.Client(http2=True, follow_redirects=True, timeout=httpx.Timeout(45, connect=20), headers={'User-Agent': UA})

TARGETS = [
    '华沿机器人', '華沿機器人', '1021.HK', '01021',
    '头部协作机器人公司', '协作机器人头部企业', '卖铲人', '运动控制底层价值'
]

def clean_markup(value: str) -> str:
    value = re.sub(r'<[^>]+>', ' ', value, flags=re.S)
    return re.sub(r'\s+', ' ', html.unescape(value)).strip()


def fetch(url: str, label: str):
    response = client.get(url)
    print('GET', label, response.status_code, response.headers.get('content-type'), len(response.content), response.url)
    text = response.text
    (OUT / f'{label}.html').write_text(text, encoding='utf-8', errors='ignore')
    return response, text


def extract_links(text: str, base: str):
    links = []
    for match in re.finditer(r'<a\b([^>]*)href=["\']([^"\']+)["\']([^>]*)>(.*?)</a>', text, re.I | re.S):
        attrs = match.group(1) + match.group(3)
        href = urljoin(base, html.unescape(match.group(2)).strip())
        label = clean_markup(match.group(4))
        links.append({'text': label, 'href': href, 'attrs': attrs[:1200]})
    return links


all_candidates = []
# Crawl likely research-category pages. Stop only after several pages with no target hits.
category_roots = [
    'https://www.nxny.com/stype_601/',
    'https://www.nxny.com/stype_1025/',
    'https://www.nxny.com/stype_47/',
    'https://www.nxny.com/stype_1025_p42/',
    'https://www.nxny.com/stype_47_p38/',
]
for root_index, root in enumerate(category_roots):
    urls = [root]
    if root.endswith('/') and '_p' not in root:
        stem = root.rstrip('/')
        urls.extend([f'{stem}_p{page}/' for page in range(2, 16)])
    for page_index, url in enumerate(urls):
        try:
            r, text = fetch(url, f'index_{root_index}_{page_index}')
        except Exception as exc:
            print('INDEX_ERR', url, repr(exc)); continue
        links = extract_links(text, str(r.url))
        hits = []
        for item in links:
            hay = (item['text'] + ' ' + item['href']).lower()
            if any(term.lower() in hay for term in TARGETS):
                hits.append(item)
                all_candidates.append(item)
        print('INDEX_HITS', url, json.dumps(hits, ensure_ascii=False)[:10000])

# Deduplicate candidate detail pages.
unique = []
seen = set()
for item in all_candidates:
    if item['href'] not in seen:
        seen.add(item['href']); unique.append(item)
print('UNIQUE_CANDIDATES', json.dumps(unique, ensure_ascii=False, indent=2))

results = []
for idx, item in enumerate(unique):
    try:
        r, text = fetch(item['href'], f'detail_{idx}')
    except Exception as exc:
        print('DETAIL_ERR', item['href'], repr(exc)); continue
    links = extract_links(text, str(r.url))
    values = set()
    # URLs from common HTML/JS attributes and raw absolute URLs.
    for pattern in [
        r'(?:href|src|data-file|data-url|data-src|file|url)\s*=\s*["\']([^"\']+)["\']',
        r'https?://[^"\'<>\s]+',
    ]:
        for value in re.findall(pattern, text, re.I):
            values.add(urljoin(str(r.url), html.unescape(value).replace('\\/', '/').strip()))
    interesting = sorted(v for v in values if any(token in v.lower() for token in ['.pdf', 'download', 'file', 'attachment', 'oss', 'cdn', 'report']))
    contexts = []
    for keyword in ['.pdf', 'download', 'data-file', 'fileurl', 'file_url', 'pdfurl', 'pdf_url', 'attachment', 'reportid']:
        for match in list(re.finditer(re.escape(keyword), text, re.I))[:20]:
            contexts.append({'keyword': keyword, 'context': clean_markup(text[max(0, match.start()-900):match.end()+1400])})
    record = {'candidate': item, 'final_url': str(r.url), 'links': links, 'interesting_values': interesting, 'contexts': contexts}
    results.append(record)
    print('DETAIL_RESULT', idx, json.dumps({'candidate': item, 'interesting_values': interesting, 'contexts': contexts[:8]}, ensure_ascii=False)[:25000])

(OUT / 'results.json').write_text(json.dumps({'candidates': unique, 'details': results}, ensure_ascii=False, indent=2), encoding='utf-8')
client.close()
