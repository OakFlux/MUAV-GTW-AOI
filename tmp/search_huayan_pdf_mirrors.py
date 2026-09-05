from __future__ import annotations

import hashlib
import html
import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

OUT = Path('out_huayan_pdf_search')
PDF_DIR = OUT / 'pdfs'
OUT.mkdir(exist_ok=True)
PDF_DIR.mkdir(exist_ok=True)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
client = httpx.Client(http2=True, follow_redirects=True, timeout=httpx.Timeout(45, connect=20), headers={
    'User-Agent': UA,
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
})

QUERIES = [
    '"头部协作机器人公司，七轴人形手臂放量可期" filetype:pdf',
    '"协作机器人头部企业，具身智能空间广阔" filetype:pdf',
    '"人形机器人行业系列（4）" "华沿机器人" filetype:pdf',
    '"运动控制底层价值有望重估" filetype:pdf',
    '"华沿机器人" "1021.HK" 研报 PDF',
    '"华沿机器人" "余小丽" PDF',
    '"华沿机器人" "肖群稀" PDF',
    '"华沿机器人" "陈庆" PDF',
    '"华沿机器人" "德银" PDF',
    '"華沿機器人" 1021 PDF 研究報告',
]


def unwrap(url: str, base: str = '') -> str:
    url = html.unescape(url).strip()
    if base:
        url = urljoin(base, url)
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    for key in ('uddg', 'url', 'u', 'target', 'dest', 'destination', 'rurl'):
        if key in qs and qs[key]:
            candidate = unquote(qs[key][0])
            if candidate.startswith('http'):
                return candidate
    # Bing sometimes uses base64-ish u=a1...; leave it alone unless it embeds an URL.
    match = re.search(r'https?%3A%2F%2F[^&]+', url, re.I)
    if match:
        return unquote(match.group(0))
    return url


def extract_links(page: str, base: str) -> set[str]:
    links: set[str] = set()
    soup = BeautifulSoup(page, 'html.parser')
    for a in soup.find_all('a', href=True):
        href = unwrap(str(a['href']), base)
        if href.startswith('http'):
            links.add(href)
    for raw in re.findall(r'https?://[^"\'<>\s]+', page):
        links.add(unwrap(raw.rstrip('.,);]'), base))
    return links


def search_engine_urls(query: str, index: int) -> set[str]:
    endpoints = [
        ('bing', 'https://www.bing.com/search?q=' + quote_plus(query) + '&count=50'),
        ('duckduckgo', 'https://html.duckduckgo.com/html/?q=' + quote_plus(query)),
        ('baidu', 'https://www.baidu.com/s?wd=' + quote_plus(query) + '&rn=50'),
        ('sogou', 'https://www.sogou.com/web?query=' + quote_plus(query) + '&num=50'),
    ]
    found: set[str] = set()
    for engine, url in endpoints:
        try:
            response = client.get(url, headers={'Referer': 'https://www.google.com/'})
            text = response.text
            (OUT / f'search_{index}_{engine}.html').write_text(text, encoding='utf-8', errors='ignore')
            links = extract_links(text, str(response.url))
            print('SEARCH', index, engine, response.status_code, len(response.content), len(links), response.url)
            for link in links:
                if any(token in link.lower() for token in [
                    '.pdf', 'download', 'report', 'research', 'yanbao', 'baogao', 'attachment',
                    'file', 'oss', 'cos', 'cdn', 'bocom', 'xyzq', 'gtja', 'gtht', 'dfcfw',
                ]):
                    found.add(link)
        except Exception as exc:
            print('SEARCH_ERR', index, engine, repr(exc))
    return found


def validate_pdf(data: bytes, url: str) -> dict | None:
    if len(data) < 80_000 or not data.startswith(b'%PDF-'):
        return None
    digest = hashlib.sha256(data).hexdigest()
    path = PDF_DIR / f'{digest[:16]}.pdf'
    path.write_bytes(data)
    try:
        reader = PdfReader(str(path), strict=False)
        pages = len(reader.pages)
        sample_parts = []
        indices = list(range(min(15, pages)))
        if pages > 20:
            indices.extend([pages // 2, pages - 1])
        for i in sorted(set(indices)):
            try:
                sample_parts.append(reader.pages[i].extract_text() or '')
            except Exception:
                pass
        sample = '\n'.join(sample_parts)
        normalized = re.sub(r'\s+', '', sample).lower()
        identity = any(token in normalized for token in [
            '华沿机器人', '華沿機器人', 'huayanrobotics', '1021hk', '01021',
            '广东华沿机器人', '廣東華沿機器人',
        ])
        deep_title = any(token in normalized for token in [
            '七轴人形手臂放量可期', '七軸人形手臂放量可期',
            '协作机器人头部企业', '協作機器人頭部企業',
            '运动控制底层价值有望重估', '運動控制底層價值有望重估',
            '卖铲人', '賣鏟人',
        ])
        meta = {
            'url': url,
            'path': str(path),
            'sha256': digest,
            'bytes': len(data),
            'pages': pages,
            'identity_ok': identity,
            'deep_title_ok': deep_title,
            'sample': sample[:5000],
        }
        print('PDF', json.dumps({k: v for k, v in meta.items() if k != 'sample'}, ensure_ascii=False))
        if not identity:
            path.unlink(missing_ok=True)
        return meta
    except Exception as exc:
        print('PDF_PARSE_ERR', url, repr(exc))
        path.unlink(missing_ok=True)
        return None


all_links: set[str] = set()
for i, query in enumerate(QUERIES):
    print('QUERY', i, query)
    all_links.update(search_engine_urls(query, i))

# Add several documented public index pages so their outgoing links are crawled.
seed_pages = [
    'https://www.fxbaogao.com/detail/5435007',
    'https://www.fxbaogao.com/detail/5497229',
    'https://www.fxbaogao.com/detail/5587624',
    'https://www.vzkoo.com/read/1136817497660001144e2b0d6510.html',
    'https://www.gelonghui.com/news/5259181',
    'https://www.hstong.com/news/detail/26052514583478094',
    'https://www.hstong.com/news/detail/26060611082313115',
]
for i, url in enumerate(seed_pages):
    try:
        r = client.get(url)
        text = r.text
        (OUT / f'seed_{i}.html').write_text(text, encoding='utf-8', errors='ignore')
        links = extract_links(text, str(r.url))
        print('SEED', i, r.status_code, len(r.content), len(links), r.url)
        all_links.update(links)
    except Exception as exc:
        print('SEED_ERR', i, url, repr(exc))

# Keep plausible public files/pages. Skip known login/user endpoints and irrelevant assets.
def plausible(url: str) -> bool:
    low = url.lower()
    if any(bad in low for bad in ['/login', '/signin', '/register', '/user/download', 'javascript:', 'wechat/qr']):
        return False
    if any(ext in low for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.css', '.js', '.ico']):
        return False
    return any(key in low for key in ['.pdf', 'download', 'attachment', 'file', 'report', 'research', 'yanbao', 'baogao', 'oss', 'cos', 'cdn'])

candidates = sorted({unwrap(url) for url in all_links if plausible(unwrap(url))})
(OUT / 'candidate_urls.json').write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding='utf-8')
print('CANDIDATES', len(candidates))

valid: list[dict] = []
seen_hashes: set[str] = set()
for i, url in enumerate(candidates[:700]):
    try:
        r = client.get(url, headers={'Accept': 'application/pdf,application/octet-stream,text/html;q=0.7,*/*;q=0.5'})
        print('FETCH', i, r.status_code, r.headers.get('content-type'), len(r.content), r.url)
        meta = validate_pdf(r.content, str(r.url))
        if meta and meta['identity_ok'] and meta['sha256'] not in seen_hashes:
            seen_hashes.add(meta['sha256']); valid.append(meta)
        elif 'text/html' in (r.headers.get('content-type') or '').lower() and len(r.content) < 2_000_000:
            # Crawl one more public HTML layer for direct file links.
            links = extract_links(r.text, str(r.url))
            for j, link in enumerate(links):
                if not plausible(link):
                    continue
                try:
                    rr = client.get(link, headers={'Accept': 'application/pdf,application/octet-stream,*/*'})
                    print('CHILD', i, j, rr.status_code, rr.headers.get('content-type'), len(rr.content), rr.url)
                    child = validate_pdf(rr.content, str(rr.url))
                    if child and child['identity_ok'] and child['sha256'] not in seen_hashes:
                        seen_hashes.add(child['sha256']); valid.append(child)
                except Exception as exc:
                    print('CHILD_ERR', link, repr(exc))
    except Exception as exc:
        print('FETCH_ERR', i, url, repr(exc))

(OUT / 'valid_pdfs.json').write_text(json.dumps(valid, ensure_ascii=False, indent=2), encoding='utf-8')
print('VALID_COUNT', len(valid))
client.close()
