from __future__ import annotations

import hashlib
import html
import json
import re
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

OUT = Path('out_ascletis_sdicsi')
PDFS = OUT / 'pdfs'
OUT.mkdir(exist_ok=True)
PDFS.mkdir(exist_ok=True)
BASE = 'https://www.sdicsi.com.hk'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
S = requests.Session()
S.headers.update({'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'})

KEYS = ('歌礼制药', '歌禮製藥', 'ASCLETIS', '01672', '1672.HK', '1672HK')
seen_urls = set()
seen_hashes = set()
valid = []
page_log = []


def request(url: str, attempts: int = 3):
    last = None
    for i in range(1, attempts + 1):
        try:
            r = S.get(url, timeout=45, allow_redirects=True)
            print('GET', r.status_code, r.headers.get('content-type'), len(r.content), r.url)
            return r
        except Exception as exc:
            last = exc
            print('RETRY', i, url, repr(exc))
            time.sleep(i)
    raise RuntimeError(f'GET failed {url}: {last}')


def clean(text: str) -> str:
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', text))).strip()


def relevant(text: str) -> bool:
    low = text.lower().replace(' ', '')
    return any(k.lower().replace(' ', '') in low for k in KEYS)


def validate_pdf(data: bytes, url: str, label: str):
    if len(data) < 50_000 or not data.startswith(b'%PDF-'):
        return None
    digest = hashlib.sha256(data).hexdigest()
    if digest in seen_hashes:
        return None
    path = PDFS / f'{label}_{digest[:12]}.pdf'
    path.write_bytes(data)
    try:
        reader = PdfReader(str(path), strict=False)
        pages = len(reader.pages)
        indices = list(range(min(12, pages)))
        if pages > 15:
            indices += [pages // 2, pages - 1]
        text = '\n'.join((reader.pages[i].extract_text() or '') for i in sorted(set(indices)))
        norm = re.sub(r'\s+', '', text).lower()
        identity = any(k.lower().replace('.', '').replace(' ', '') in norm.replace('.', '') for k in KEYS)
        if not identity:
            print('REJECT_IDENTITY', pages, url, text[:300].replace('\n', ' '))
            path.unlink(missing_ok=True)
            return None
        item = {'path': str(path), 'url': url, 'pages': pages, 'bytes': len(data), 'sha256': digest, 'text_preview': text[:5000]}
        valid.append(item)
        seen_hashes.add(digest)
        print('VALID', json.dumps({k:v for k,v in item.items() if k != 'text_preview'}, ensure_ascii=False))
        return item
    except Exception as exc:
        print('PDF_PARSE_ERROR', url, repr(exc))
        path.unlink(missing_ok=True)
        return None


def probe_pdf(url: str, label: str):
    if url in seen_urls:
        return
    seen_urls.add(url)
    try:
        r = request(url, attempts=2)
        if r.status_code == 200:
            validate_pdf(r.content, str(r.url), label)
    except Exception as exc:
        print('PROBE_ERROR', url, repr(exc))


# 1) Official tag pages and all linked report articles.
article_links = set()
for lang in ('cn', 'zh', 'en'):
    for tag in ('1672hk', '01672hk', '1672-hk'):
        url = f'{BASE}/{lang}/research-report/tag/{tag}'
        try:
            r = request(url)
            page_log.append({'url': url, 'status': r.status_code, 'final': str(r.url), 'bytes': len(r.content)})
            (OUT / f'tag_{lang}_{tag}.html').write_bytes(r.content)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, 'html.parser')
            print('TAG_TEXT', clean(soup.get_text(' '))[:2500])
            for a in soup.find_all('a', href=True):
                href = urljoin(str(r.url), a.get('href'))
                label = clean(a.get_text(' ', strip=True))
                if '/research-report/' in urlparse(href).path and '/tag/' not in urlparse(href).path:
                    if relevant(label + ' ' + href) or tag.startswith('1672'):
                        article_links.add(href)
                        print('ARTICLE_LINK', label, href)
                if '.pdf' in href.lower():
                    probe_pdf(href, f'tag_{lang}_{tag}')
        except Exception as exc:
            page_log.append({'url': url, 'error': repr(exc)})

for idx, url in enumerate(sorted(article_links)):
    try:
        r = request(url)
        (OUT / f'article_{idx}.html').write_bytes(r.content)
        soup = BeautifulSoup(r.text, 'html.parser')
        text = clean(soup.get_text(' '))
        print('ARTICLE', idx, text[:1800])
        for raw in re.findall(r'https?://[^\"\'<>\s]+', r.text):
            u = html.unescape(raw).replace('\\/', '/').rstrip('),;]')
            if '.pdf' in u.lower():
                probe_pdf(u, f'article_{idx}')
        for node in soup.find_all(['a', 'iframe', 'embed', 'object'], href=True):
            u = urljoin(str(r.url), node.get('href'))
            if '.pdf' in u.lower():
                probe_pdf(u, f'article_{idx}')
        for node in soup.find_all(['iframe', 'embed', 'object'], src=True):
            u = urljoin(str(r.url), node.get('src'))
            if '.pdf' in u.lower():
                probe_pdf(u, f'article_{idx}')
    except Exception as exc:
        print('ARTICLE_ERROR', url, repr(exc))

# 2) Brute-force documented public filename convention around known publication dates.
base_paths = [
    f'{BASE}/backend/storage/app/media/ResearchReports/CorporateReports/',
    f'{BASE}/backend/storage/app/media/ResearchReports/CompanyReports/',
]
windows = [
    (date(2024, 8, 25), date(2024, 9, 5)),
    (date(2025, 8, 15), date(2025, 9, 12)),
    (date(2025, 12, 20), date(2025, 12, 31)),
    (date(2026, 3, 25), date(2026, 4, 10)),
    (date(2026, 7, 15), date(2026, 8, 31)),
]
for start, end in windows:
    day = start
    while day <= end:
        ymd = day.strftime('%Y%m%d')
        for base_path in base_paths:
            for code in ('1672', '01672'):
                for suffix in ('.pdf', '_C.pdf', '_c.pdf', '-CN.pdf'):
                    probe_pdf(f'{base_path}{code}-{ymd}{suffix}', f'probe_{code}_{ymd}')
        day += timedelta(days=1)

(OUT / 'page_log.json').write_text(json.dumps(page_log, ensure_ascii=False, indent=2), encoding='utf-8')
(OUT / 'valid.json').write_text(json.dumps(valid, ensure_ascii=False, indent=2), encoding='utf-8')
print('DONE', len(valid), 'valid PDFs')
