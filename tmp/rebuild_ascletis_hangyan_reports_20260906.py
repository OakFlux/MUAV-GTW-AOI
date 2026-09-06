from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urljoin
from zipfile import ZIP_DEFLATED, ZipFile

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

OUT = Path('out_ascletis_hangyan_rebuild')
REPORTS = OUT / 'reports'
RENDERS = OUT / 'renders'
ZIP = OUT / 'ascletis_01672_reports_new.zip'
shutil.rmtree(OUT, ignore_errors=True)
REPORTS.mkdir(parents=True)
RENDERS.mkdir(parents=True)

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
s = requests.Session()
s.headers.update({
    'User-Agent': UA,
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
})

BASE = 'https://www.hangyan.co'


def get(url: str, binary: bool = False) -> requests.Response:
    last = None
    for attempt in range(1, 6):
        try:
            r = s.get(url, timeout=90)
            print('GET', r.status_code, len(r.content), r.headers.get('content-type'), r.url)
            r.raise_for_status()
            return r
        except Exception as exc:
            last = exc
            print('RETRY', attempt, url, repr(exc))
            time.sleep(attempt * 2)
    raise RuntimeError(f'Unable to fetch {url}: {last}')


def clean_text(value: str) -> str:
    return re.sub(r'\s+', ' ', html.unescape(value or '')).strip()


def collect_report_links(url: str, title_needles: list[str]) -> list[str]:
    r = get(url)
    soup = BeautifulSoup(r.text, 'html.parser')
    found: list[str] = []
    for a in soup.find_all('a', href=True):
        text = clean_text(a.get_text(' ', strip=True))
        href = urljoin(str(r.url), a['href'])
        if '/reports/' not in href:
            continue
        if not title_needles or any(needle.lower() in text.lower() for needle in title_needles):
            found.append(href.split('#', 1)[0])
    # Some chart pages expose only a generic “阅读研究报告” link.
    if not found:
        for a in soup.find_all('a', href=True):
            text = clean_text(a.get_text(' ', strip=True))
            href = urljoin(str(r.url), a['href'])
            if '/reports/' in href and ('阅读研究报告' in text or '研究报告' in text):
                found.append(href.split('#', 1)[0])
    return list(dict.fromkeys(found))


report_urls: list[str] = [
    # Complete public company update already known and independently verified.
    'https://www.hangyan.co/reports/3448696034581022433',
]

# Dongwu Securities 1 Apr 2025 initiation/deep report.
report_urls += collect_report_links(
    'https://www.hangyan.co/charts/3601111842144912396',
    ['全新GLP-1减重不减肌', 'Best-in-Class'],
)

# Orient Securities 28 Dec 2025 initiation report. Search the listing page and
# adjacent pages because pagination can move when new reports are added.
for page in range(90, 103):
    links = collect_report_links(
        f'https://www.hangyan.co/reports?page={page}',
        ['口服小分子率先破局', '紧跟减重前沿'],
    )
    report_urls += links
    if links:
        break

# Dongwu 9 Sep 2025 follow-up report as another fallback.
report_urls += collect_report_links(
    'https://www.hangyan.co/charts/3725107781510890977',
    ['临床数据显示超长半衰期', 'ASC30有望推出季度制剂'],
)

report_urls = list(dict.fromkeys(report_urls))
print('REPORT_URLS', json.dumps(report_urls, ensure_ascii=False, indent=2))


def parse_report_page(url: str) -> dict:
    r = get(url)
    soup = BeautifulSoup(r.text, 'html.parser')
    title = clean_text((soup.find('h1') or soup.find('title')).get_text(' ', strip=True)) if (soup.find('h1') or soup.find('title')) else ''
    iframe = None
    for tag in soup.find_all(['iframe', 'embed']):
        src = tag.get('src') or ''
        if '.pdf' in src.lower():
            iframe = urljoin(str(r.url), src)
            break
    if not iframe:
        match = re.search(r'https?://[^"\'<>\s]+\.pdf(?:\?[^"\'<>\s]*)?', r.text, re.I)
        if match:
            iframe = html.unescape(match.group(0))
    filename_tag = soup.find(attrs={'data-native-pdf-filename-value': True})
    suggested = filename_tag.get('data-native-pdf-filename-value') if filename_tag else ''
    body = clean_text(soup.get_text(' ', strip=True))
    return {
        'report_url': str(r.url),
        'title': title,
        'pdf_url': iframe,
        'suggested_filename': suggested,
        'body': body[:20000],
    }


def safe_ascii(value: str) -> str:
    value = re.sub(r'[^A-Za-z0-9_.-]+', '_', value)
    return value.strip('_')[:120] or 'report'


def validate_pdf(path: Path) -> tuple[int, str, str]:
    data = path.read_bytes()
    if not data.startswith(b'%PDF-') or len(data) < 80000:
        raise RuntimeError(f'Invalid PDF: {path.name}')
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 3:
        raise RuntimeError(f'Too few pages: {path.name}: {pages}')
    indices = sorted(set(list(range(min(pages, 12))) + [pages // 2, pages - 1]))
    parts = []
    for i in indices:
        try:
            parts.append(reader.pages[i].extract_text() or '')
        except Exception:
            pass
    text = '\n'.join(parts)
    norm = re.sub(r'\s+', '', text).lower()
    if not any(token in norm for token in ['歌礼制药', '歌禮製藥', 'ascletis', '01672', '1672.hk', '1672hk']):
        raise RuntimeError(f'Ascletis identity not found: {path.name}')
    return pages, hashlib.sha256(data).hexdigest(), text


candidates: list[dict] = []
seen_pdf_urls: set[str] = set()
seen_hashes: set[str] = set()
for idx, url in enumerate(report_urls, 1):
    try:
        info = parse_report_page(url)
        print('PAGE_INFO', json.dumps({k: v for k, v in info.items() if k != 'body'}, ensure_ascii=False))
        pdf_url = info.get('pdf_url')
        if not pdf_url or pdf_url in seen_pdf_urls:
            continue
        seen_pdf_urls.add(pdf_url)
        r = get(pdf_url)
        raw = OUT / f'candidate_{idx}.pdf'
        raw.write_bytes(r.content)
        pages, digest, text = validate_pdf(raw)
        if digest in seen_hashes:
            raw.unlink(missing_ok=True)
            continue
        seen_hashes.add(digest)
        # First, middle and last page render checks.
        rendered = []
        for pageno in sorted({1, max(1, (pages + 1) // 2), pages}):
            prefix = RENDERS / f'{digest[:12]}_p{pageno}'
            subprocess.run([
                'pdftoppm', '-f', str(pageno), '-l', str(pageno), '-png',
                '-singlefile', '-r', '80', str(raw), str(prefix)
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            image = Path(str(prefix) + '.png')
            if not image.exists() or image.stat().st_size < 4000:
                raise RuntimeError(f'Render failed for {raw.name} page {pageno}')
            rendered.append(image.name)
        info.update({
            'raw_path': str(raw),
            'pages': pages,
            'bytes': raw.stat().st_size,
            'sha256': digest,
            'text_sample': text[:5000],
            'rendered': rendered,
        })
        candidates.append(info)
    except Exception as exc:
        print('CANDIDATE_ERROR', url, repr(exc))

print('VALID_CANDIDATES', len(candidates))
for item in candidates:
    print(json.dumps({k:v for k,v in item.items() if k not in ['body','text_sample','raw_path']}, ensure_ascii=False))

# Prefer long-form initiation/deep reports, then other complete company research.
def priority(item: dict) -> tuple:
    blob = (item.get('title','') + ' ' + item.get('suggested_filename','') + ' ' + item.get('body','')).lower()
    deep = int(any(x in blob for x in ['首次覆盖', '首次覆蓋', 'deep', 'initiation', 'best-in-class', '口服小分子率先破局']))
    year = 0
    m = re.search(r'20\d{2}', blob)
    if m: year = int(m.group(0))
    return (deep, item['pages'], year)

candidates.sort(key=priority, reverse=True)
selected = candidates[:3]
if len(selected) < 2:
    raise RuntimeError(f'Only {len(selected)} valid distinct Ascletis reports found')

manifest = []
for idx, item in enumerate(selected, 1):
    blob = item.get('suggested_filename') or item.get('title') or f'report_{idx}'
    date_match = re.search(r'(20\d{2})[-年/]?(\d{2})[-月/]?(\d{2})', blob)
    date = '-'.join(date_match.groups()) if date_match else ''
    broker = ''
    for name in ['东方证券', '東方證券', '东吴证券', '東吳證券', '国元国际控股', '國元國際控股', '国元国际', '國元國際']:
        if name in blob or name in item.get('body','')[:3000]:
            broker = name
            break
    if not broker:
        broker = 'Broker'
    filename = f'{idx:02d}_{safe_ascii(broker)}_{date or "report"}_Ascletis_01672_{item["pages"]}p.pdf'
    dest = REPORTS / filename
    shutil.copy2(item['raw_path'], dest)
    manifest.append({
        'index': idx,
        'broker': broker,
        'date': date,
        'title': item.get('suggested_filename') or item.get('title'),
        'filename': filename,
        'pages': item['pages'],
        'bytes': item['bytes'],
        'sha256': item['sha256'],
        'report_page': item['report_url'],
        'source_pdf': item['pdf_url'],
    })

readme = [
    'Ascletis Pharma (01672.HK) broker research report package',
    '',
    f'This package contains {len(manifest)} distinct, complete PDF files downloaded from publicly accessible report pages.',
    'No web shortcuts, self-written summaries, company announcements or preview images are counted as reports.',
    '',
]
for item in manifest:
    readme.append(f"{item['index']}. {item['broker']} | {item['date']} | {item['pages']} pages | {item['title']}")
readme += ['', 'Validation: PDF signature, Ascletis/01672 identity, page count, SHA-256, first/middle/last-page rendering and ZIP integrity.']
(REPORTS / 'README.txt').write_text('\n'.join(readme), encoding='utf-8')
(REPORTS / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
with (REPORTS / 'manifest.csv').open('w', encoding='utf-8-sig', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=list(manifest[0].keys()))
    writer.writeheader(); writer.writerows(manifest)

with ZipFile(ZIP, 'w', ZIP_DEFLATED, compresslevel=9) as zf:
    for path in sorted(REPORTS.iterdir(), key=lambda p: p.name):
        zf.write(path, path.name)
with ZipFile(ZIP) as zf:
    bad = zf.testzip()
    if bad is not None:
        raise RuntimeError(f'ZIP integrity failure: {bad}')
    if len([n for n in zf.namelist() if n.lower().endswith('.pdf')]) != len(manifest):
        raise RuntimeError('PDF count mismatch in ZIP')

print('PACKAGE_READY', ZIP, ZIP.stat().st_size)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
