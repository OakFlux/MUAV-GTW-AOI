from __future__ import annotations

import csv
import hashlib
import html as html_lib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zipfile import ZIP_DEFLATED, ZipFile

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

OUT = Path('out_cgnne_fast_20260907')
RAW = OUT / 'raw'
PACKAGE = OUT / 'package'
DIAG = OUT / 'diagnostics'
RENDERS = OUT / 'renders'
FINAL = OUT / 'CGN_New_Energy_01811_Broker_Reports.zip'
shutil.rmtree(OUT, ignore_errors=True)
for directory in (RAW, PACKAGE, DIAG, RENDERS):
    directory.mkdir(parents=True, exist_ok=True)

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
session = requests.Session()
session.headers.update({'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'})

TARGETS = [
    ('hangyan_2024', 'https://www.hangyan.co/reports/3374738651710752209'),
    ('hangyan_2025', 'https://www.hangyan.co/reports/3545846060268127552'),
    ('sgpjbg_2021', 'https://www.sgpjbg.com/baogao/44868.html'),
    ('sgpjbg_2022', 'https://www.sgpjbg.com/baogao/70108.html'),
    ('ninefzt_2021', 'https://gmg.9fzt.com/report/HKSE/01811/679344712485.html'),
]

KNOWN = [
    {
        'key': '2021', 'date': '2021-07-11', 'broker': '国信证券',
        'title': '清洁能源新栋梁，直挂云帆济沧海',
        'type': '首次覆盖 / 公司深度', 'min_pages': 35, 'priority': 100,
        'patterns': ['清洁能源新栋梁', '直挂云帆济沧海'],
    },
    {
        'key': '2022', 'date': '2022-04-22', 'broker': '国信证券（香港）',
        'title': '稳步成长的新能源运营商',
        'type': '公司深度研究', 'min_pages': 12, 'priority': 95,
        'patterns': ['稳步成长的新能源运营商'],
    },
    {
        'key': '2024', 'date': '2024-05-23', 'broker': '国信证券（香港）',
        'title': '稳健增长，估值修复行情持续',
        'type': '港股公司研究', 'min_pages': 2, 'priority': 80,
        'patterns': ['稳健增长', '估值修复行情持续'],
    },
    {
        'key': '2025', 'date': '2025-01-15', 'broker': '国元国际',
        'title': '24年发电量微增长，期待25年估值修复',
        'type': '港股公司研究', 'min_pages': 2, 'priority': 75,
        'patterns': ['24年发电量微增长', '期待25年估值修复'],
    },
]

saved: list[dict] = []
seen_hashes: set[str] = set()
visited: set[str] = set()


def save_pdf(content: bytes, source_url: str, label: str) -> bool:
    if len(content) < 30_000 or not content.startswith(b'%PDF-'):
        return False
    digest = hashlib.sha256(content).hexdigest()
    if digest in seen_hashes:
        return True
    seen_hashes.add(digest)
    path = RAW / f'{label}_{digest[:12]}.pdf'
    path.write_bytes(content)
    saved.append({'path': str(path), 'source_url': source_url, 'label': label, 'sha256': digest})
    print('SAVED_PDF', label, len(content), source_url)
    return True


def extract_urls(text: str, base_url: str) -> list[str]:
    text = html_lib.unescape(text).replace('\\/', '/').replace('\\u002F', '/')
    urls: set[str] = set()
    for raw in re.findall(r'https?://[^"\'<>\s\\]+', text):
        urls.add(raw.rstrip('),;'))
    soup = BeautifulSoup(text, 'html.parser')
    for tag in soup.find_all(True):
        for attr in ('href', 'src', 'data', 'data-src', 'data-url', 'data-file', 'data-pdf', 'content'):
            value = tag.get(attr)
            if not value or not isinstance(value, str):
                continue
            try:
                urls.add(urljoin(base_url, value))
            except Exception:
                pass
    return sorted(urls)


def crawl(url: str, label: str, depth: int = 0) -> None:
    if url in visited or depth > 2:
        return
    visited.add(url)
    try:
        response = session.get(url, timeout=20, allow_redirects=True, headers={'Referer': url})
        content_type = response.headers.get('content-type', '')
        print('GET', response.status_code, content_type, len(response.content), url)
        if response.status_code != 200:
            return
        if save_pdf(response.content, str(response.url), label):
            return
        text = response.text
        (DIAG / f'{label}_{len(visited)}.html').write_text(text, encoding='utf-8', errors='ignore')
        candidates = extract_urls(text, str(response.url))
        interesting = []
        for candidate in candidates:
            lower = candidate.lower()
            if any(token in lower for token in ('.pdf', 'download', 'attachment', 'fileroot', 'bookread', 'view.aspx', 'bgdown', 'document')):
                interesting.append(candidate)
        print('CANDIDATES', label, len(interesting))
        for candidate in interesting[:30]:
            crawl(candidate, label + '_child', depth + 1)
    except Exception as exc:
        print('ERROR', label, url, repr(exc))


for label, url in TARGETS:
    crawl(url, label)

# Probe simple public SGPJBG viewer endpoints directly.
for report_id, label in [('44868', 'sgpjbg_2021_direct'), ('70108', 'sgpjbg_2022_direct')]:
    for url in [
        f'https://www.sgpjbg.com/sgpjbg/View.aspx?id={report_id}',
        f'https://www.sgpjbg.com/bgdown/{report_id}.html',
        f'https://www.sgpjbg.com/BookRead.aspx?id={report_id}',
    ]:
        crawl(url, label)

(OUT / 'collected.json').write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding='utf-8')


def inspect(path: Path) -> dict | None:
    data = path.read_bytes()
    try:
        reader = PdfReader(str(path), strict=False)
        pages = len(reader.pages)
        if pages < 2:
            return None
        indexes = list(range(min(15, pages)))
        if pages > 20:
            indexes.extend([pages // 2, pages - 1])
        text = '\n'.join((reader.pages[i].extract_text() or '') for i in sorted(set(indexes)))
    except Exception as exc:
        print('PDF_ERROR', path.name, repr(exc))
        return None
    normalized = re.sub(r'\s+', '', text).lower()
    if not any(token in normalized for token in ['中广核新能源', '中廣核新能源', 'cgnnewenergy', '1811.hk', '01811']):
        print('REJECT_IDENTITY', path.name, pages)
        return None
    return {
        'path': path, 'pages': pages, 'bytes': len(data),
        'sha256': hashlib.sha256(data).hexdigest(), 'normalized': normalized,
        'source_url': next((row['source_url'] for row in saved if Path(row['path']).name == path.name), ''),
    }

inspected = [item for path in sorted(RAW.glob('*.pdf')) if (item := inspect(path))]
print('INSPECTED', len(inspected))

matches = []
for definition in KNOWN:
    candidates = []
    for item in inspected:
        hits = sum(pattern.replace(' ', '').lower() in item['normalized'] for pattern in definition['patterns'])
        if hits:
            candidates.append((hits * 100 + min(item['pages'], 60), item))
    if candidates:
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        item = candidates[0][1]
        if item['pages'] >= definition['min_pages']:
            matches.append((definition, item))
            print('MATCH', definition['key'], item['pages'], item['path'].name)
        else:
            print('SHORT', definition['key'], item['pages'])

matches.sort(key=lambda pair: (pair[0]['priority'], pair[1]['pages']), reverse=True)
selected = []
used_hashes = set()
for definition, item in matches:
    if item['sha256'] in used_hashes:
        continue
    selected.append((definition, item))
    used_hashes.add(item['sha256'])
    if len(selected) == 3:
        break

if len(selected) < 2:
    raise RuntimeError(f'Only {len(selected)} distinct complete reports found; collected={len(saved)}, inspected={len(inspected)}')

manifest = []
for index, (definition, item) in enumerate(selected, 1):
    output_name = f'{index:02d}_{definition["date"]}_{definition["broker"]}_中广核新能源.pdf'
    destination = PACKAGE / output_name
    shutil.copy2(item['path'], destination)
    for page_number in sorted({1, max(1, (item['pages'] + 1) // 2), item['pages']}):
        prefix = RENDERS / f'r{index}_p{page_number}'
        subprocess.run(
            ['pdftoppm', '-f', str(page_number), '-l', str(page_number), '-png', '-singlefile', '-r', '90', str(destination), str(prefix)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        image = Path(str(prefix) + '.png')
        if not image.exists() or image.stat().st_size < 8_000:
            raise RuntimeError(f'Render failed: {output_name} page {page_number}')
    manifest.append({
        '序号': index, '券商': definition['broker'], '发布日期': definition['date'],
        '报告标题': definition['title'], '报告性质': definition['type'],
        '实际页数': item['pages'], '文件名': output_name,
        '文件大小_字节': item['bytes'], 'SHA256': item['sha256'],
        '来源地址': item['source_url'],
    })

readme = [
    '中广核新能源（01811.HK）券商研究报告合集', '',
    f'本包收录{len(manifest)}份公开可直接取得的实际PDF，不含网页快捷方式、预览图片或自制摘要。', '',
    '文件清单：',
]
for row in manifest:
    readme.append(f"{row['序号']}. {row['券商']}｜{row['发布日期']}｜{row['实际页数']}页｜{row['报告性质']}｜{row['报告标题']}")
readme.extend(['', '已检查PDF签名、公司名称/股票代码、实际页数、SHA-256、首中末页渲染及ZIP完整性。', '仅供个人研究使用，版权归原券商及发布机构所有。'])
(PACKAGE / 'README_文件说明.txt').write_text('\n'.join(readme), encoding='utf-8')
(PACKAGE / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
with (PACKAGE / 'manifest.csv').open('w', encoding='utf-8-sig', newline='') as handle:
    writer = csv.DictWriter(handle, fieldnames=list(manifest[0].keys()))
    writer.writeheader()
    writer.writerows(manifest)

with ZipFile(FINAL, 'w', ZIP_DEFLATED, compresslevel=9) as archive:
    for member in sorted(PACKAGE.iterdir(), key=lambda p: p.name):
        archive.write(member, member.name)
with ZipFile(FINAL) as archive:
    bad = archive.testzip()
    if bad is not None:
        raise RuntimeError(f'ZIP integrity failure: {bad}')
    if len([name for name in archive.namelist() if name.lower().endswith('.pdf')]) != len(manifest):
        raise RuntimeError('ZIP PDF count mismatch')

print('PACKAGE_READY', FINAL, FINAL.stat().st_size)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
session.close()
