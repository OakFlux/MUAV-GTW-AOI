from __future__ import annotations

import hashlib
import html
import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

OUT = Path('out_xinyi_solar_web_search_fast')
PDFS = OUT / 'pdfs'
OUT.mkdir(exist_ok=True)
PDFS.mkdir(exist_ok=True)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36'
s = requests.Session()
s.headers.update({'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'})

queries = [
    '"全球光伏玻璃龙头，业绩底部景气拐点初显" PDF',
    '"深耕光伏玻璃行业，成本优势显著" PDF',
    '"严冬过尽绽春蕾，步入成长快车道" PDF',
    '"信义光能" "深度研究报告" filetype:pdf',
    '"Xinyi Solar" "initiation" filetype:pdf',
    '"00968.HK" "深度报告" pdf',
]

search_templates = {
    'bing': 'https://www.bing.com/search?q={q}&count=50&setlang=zh-cn',
    'baidu': 'https://www.baidu.com/s?wd={q}&rn=50',
    'sogou': 'https://www.sogou.com/web?query={q}&num=50',
    'so360': 'https://www.so.com/s?q={q}&pn=1',
    'google': 'https://www.google.com/search?q={q}&num=50&hl=zh-CN',
    'jina_google': 'https://r.jina.ai/http://www.google.com/search?q={q}',
    'jina_bing': 'https://r.jina.ai/http://www.bing.com/search?q={q}',
}

known_pages = [
    'https://www.sgpjbg.com/bgdown/622483.html',
    'https://www.sgpjbg.com/baogao/622483.html',
    'https://www.vzkoo.com/read/2025033140156a90946ec4ab421372b6.html',
    'https://www.fxbaogao.com/detail/4751513',
    'https://www.fxbaogao.com/view?id=4751513',
    'https://www.fxbaogao.com/detail/3766045',
    'https://www.fxbaogao.com/view?id=3766045',
    'https://news.futunn.com/hk/post/28255017/xinyi-solar-energy-00968-hk-deepening-the-photovoltaic-glass-industry',
    'https://www.sohu.com/a/301415039_313170',
    'https://www.hangyan.co/reports/3541189723936523517',
    'https://www.hangyan.co/reports/3402974878104552641',
    'https://www.hangyan.co/reports/3843608737805763979',
]

TARGET = re.compile(r'信义光能|信義光能|Xinyi\s*Solar|00968|0968\.HK|0968HK', re.I)
REPORT_WORDS = re.compile(r'深度|首次覆盖|initiat|研究报告|公司研究|光伏玻璃|研报', re.I)

all_urls: set[str] = set()
search_rows: list[dict] = []
page_rows: list[dict] = []
valid_pdfs: list[dict] = []
seen_sha: set[str] = set()


def normalize_url(raw: str, base: str = '') -> str | None:
    if not raw:
        return None
    raw = html.unescape(raw).replace('\\/', '/').strip('"\' <>),;')
    if raw.startswith('//'):
        raw = 'https:' + raw
    if base and not raw.startswith(('http://', 'https://')):
        raw = urljoin(base, raw)
    if not raw.startswith(('http://', 'https://')):
        return None
    parsed = urlparse(raw)
    qs = parse_qs(parsed.query)
    for key in ['url', 'u', 'target', 'r', 'link', 'redirect', 'q']:
        value = qs.get(key, [])
        if value and value[0].startswith(('http://', 'https://')):
            raw = unquote(value[0])
            break
    return raw


def extract_urls(text: str, base: str = '') -> set[str]:
    found: set[str] = set()
    for raw in re.findall(r'https?://[^\s"\'<>\\]+', text, re.I):
        u = normalize_url(raw, base)
        if u:
            found.add(u)
    for raw in re.findall(r'(?:href|src|data-url|data-file|data-src|content)=["\']([^"\']+)["\']', text, re.I):
        u = normalize_url(raw, base)
        if u:
            found.add(u)
    # Escaped JSON URLs.
    for raw in re.findall(r'https?:\\/\\/[^\s"\'<>]+', text, re.I):
        u = normalize_url(raw, base)
        if u:
            found.add(u)
    return found


def inspect_pdf_bytes(data: bytes, url: str, label: str) -> dict | None:
    if len(data) < 50_000 or not data.startswith(b'%PDF-'):
        return None
    sha = hashlib.sha256(data).hexdigest()
    if sha in seen_sha:
        return None
    p = PDFS / f'{label}_{sha[:12]}.pdf'
    p.write_bytes(data)
    try:
        reader = PdfReader(str(p), strict=False)
        pages = len(reader.pages)
        indices = list(range(min(15, pages)))
        if pages > 20:
            indices.extend([pages // 2, pages - 1])
        sample = '\n'.join((reader.pages[i].extract_text() or '') for i in sorted(set(indices)))
    except Exception as exc:
        print('PDF_PARSE_ERR', url, repr(exc))
        p.unlink(missing_ok=True)
        return None
    normalized = re.sub(r'\s+', '', sample)
    identity = bool(TARGET.search(normalized))
    if not identity:
        print('PDF_REJECT_IDENTITY', pages, url, sample[:800].replace('\n', ' '))
        p.unlink(missing_ok=True)
        return None
    seen_sha.add(sha)
    row = {'url': url, 'path': str(p), 'pages': pages, 'bytes': len(data), 'sha256': sha, 'sample': sample[:5000]}
    valid_pdfs.append(row)
    print('PDF_VALID', json.dumps({k:v for k,v in row.items() if k != 'sample'}, ensure_ascii=False))
    return row


def probe_url(url: str, label: str) -> None:
    try:
        r = s.get(url, timeout=45, allow_redirects=True, headers={'Referer': 'https://www.sgpjbg.com/', 'Accept': 'application/pdf,application/octet-stream,text/html,*/*'})
        ct = r.headers.get('content-type', '')
        print('PROBE', r.status_code, ct, len(r.content), url, '=>', r.url)
        if r.status_code == 200:
            inspect_pdf_bytes(r.content, str(r.url), label)
    except Exception as exc:
        print('PROBE_ERR', url, repr(exc))


# Search engine result pages.
for engine, template in search_templates.items():
    for qi, query in enumerate(queries):
        url = template.format(q=quote(query))
        try:
            r = s.get(url, timeout=45)
            text = r.text
            (OUT / f'search_{engine}_{qi}.html').write_text(text, encoding='utf-8', errors='ignore')
            urls = extract_urls(text, str(r.url))
            print('SEARCH', engine, qi, r.status_code, len(r.content), 'urls', len(urls), r.url)
            for u in urls:
                if any(domain in urlparse(u).netloc.lower() for domain in ['bing.com','baidu.com','sogou.com','so.com','google.com','gstatic.com']):
                    continue
                if any(k in u.lower() for k in ['.pdf','report','baogao','yanbao','research','download','file','document','fileroot','oss','cdn']):
                    all_urls.add(u)
                    search_rows.append({'engine': engine, 'query': query, 'url': u})
        except Exception as exc:
            print('SEARCH_ERR', engine, qi, repr(exc))
        time.sleep(0.2)

# Inspect known pages and mine links, inline JSON and scripts.
for pi, page_url in enumerate(known_pages):
    try:
        r = s.get(page_url, timeout=60)
        text = r.text
        (OUT / f'page_{pi}.html').write_text(text, encoding='utf-8', errors='ignore')
        urls = extract_urls(text, str(r.url))
        print('PAGE', pi, r.status_code, r.headers.get('content-type'), len(r.content), r.url, 'urls', len(urls))
        selected = []
        for u in urls:
            ul = u.lower()
            if any(k in ul for k in ['.pdf','download','bookread','view.aspx','fileroot','document','attachment','fileurl','report-image','oss','cdn']):
                selected.append(u)
                all_urls.add(u)
        page_rows.append({'page': page_url, 'final': str(r.url), 'status': r.status_code, 'selected_urls': sorted(set(selected))})
        print('PAGE_LINKS', pi, json.dumps(sorted(set(selected))[:300], ensure_ascii=False))
    except Exception as exc:
        print('PAGE_ERR', pi, page_url, repr(exc))

# FxBaogao explicitly public API candidates.
for rid in ['4751513', '3766045']:
    for method in ['getReportPreviewImages','getReportDetail','getReportInfo','getReportById','getReport','getReportImages','getReportFile','getReportDownloadUrl','getDownloadUrl','download']:
        url = f'https://api.fxbaogao.com/mofoun/report/report/{method}?reportId={rid}'
        try:
            r = s.get(url, timeout=30)
            text = r.text
            (OUT / f'fx_{rid}_{method}.txt').write_text(text[:200000], encoding='utf-8', errors='ignore')
            print('FX_API', rid, method, r.status_code, r.headers.get('content-type'), len(r.content), text[:300].replace('\n',' '))
            for u in extract_urls(text, str(r.url)):
                if '.pdf' in u.lower() or 'document' in u.lower() or 'download' in u.lower():
                    all_urls.add(u)
        except Exception as exc:
            print('FX_API_ERR', rid, method, repr(exc))

# Probe only plausible file/download URLs discovered from public pages/search results.
probe_candidates = []
for u in all_urls:
    ul = u.lower()
    if any(x in ul for x in ['.pdf','cdn.hangyan.co/documents','file.sgpjbg.com','fileroot','download']) and not any(x in ul for x in ['javascript:', 'mailto:']):
        probe_candidates.append(u)

for idx, u in enumerate(sorted(set(probe_candidates))):
    probe_url(u, f'candidate_{idx:03d}')
    time.sleep(0.08)

(OUT / 'search_rows.json').write_text(json.dumps(search_rows, ensure_ascii=False, indent=2), encoding='utf-8')
(OUT / 'page_rows.json').write_text(json.dumps(page_rows, ensure_ascii=False, indent=2), encoding='utf-8')
(OUT / 'all_urls.json').write_text(json.dumps(sorted(all_urls), ensure_ascii=False, indent=2), encoding='utf-8')
(OUT / 'valid_pdfs.json').write_text(json.dumps(valid_pdfs, ensure_ascii=False, indent=2), encoding='utf-8')
print('DONE', 'urls', len(all_urls), 'probe_candidates', len(probe_candidates), 'valid_pdfs', len(valid_pdfs))
