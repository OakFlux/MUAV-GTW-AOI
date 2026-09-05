from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import shutil
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import requests
from pypdf import PdfReader

OUT = Path('out_china_tower_two_reports')
REPORTS = OUT / 'reports'
RENDERS = OUT / 'renders'
ZIP_PATH = OUT / 'China_Tower_00788_Broker_Research_Reports_2.zip'
shutil.rmtree(OUT, ignore_errors=True)
REPORTS.mkdir(parents=True)
RENDERS.mkdir(parents=True)

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
})

SOURCES = [
    {
        'page_url': 'https://www.hangyan.co/reports/3429851902681023749',
        'broker': '浙商证券',
        'date': '2024-08-08',
        'title': '中国铁塔2024年中期业绩点评报告：业绩符合预期，首次中期派息',
        'output': '01_浙商证券_2024-08-08_中国铁塔2024年中期业绩点评报告.pdf',
    },
    {
        'page_url': 'https://www.hangyan.co/reports/3485236846772881072',
        'broker': '德邦证券',
        'date': '2024-10-23',
        'title': '一体两翼营收稳定，利润提升支撑分红增长',
        'output': '02_德邦证券_2024-10-23_中国铁塔一体两翼营收稳定.pdf',
    },
]


def extract_pdf_url(page_url: str) -> tuple[str, str]:
    r = session.get(page_url, timeout=60)
    r.raise_for_status()
    text = r.text
    matches = re.findall(r'https?://[^"\'<>\s]+\.pdf(?:\?[^"\'<>\s]*)?', text, flags=re.I)
    matches = [html.unescape(u).replace('\\/', '/') for u in matches]
    matches = [u for u in matches if 'cdn.hangyan.co/documents/' in u]
    if not matches:
        # Fallback to meta/escaped JSON forms.
        for m in re.findall(r'https?:\\?/\\?/cdn\.hangyan\.co\\?/documents\\?/[^"\']+?\.pdf', text, flags=re.I):
            matches.append(m.replace('\\/', '/'))
    if not matches:
        raise RuntimeError(f'No public report PDF found on {page_url}')
    return matches[0], text


def validate_pdf(path: Path) -> dict:
    with path.open('rb') as f:
        if f.read(5) != b'%PDF-':
            raise RuntimeError(f'Not a PDF: {path}')
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 3:
        raise RuntimeError(f'Too few pages: {path}: {pages}')
    sample = '\n'.join((page.extract_text() or '') for page in reader.pages[:min(pages, 8)])
    normalized = re.sub(r'\s+', '', sample).lower()
    if not any(token in normalized for token in ['中国铁塔', '中國鐵塔', 'chinatower', '00788', '0788']):
        raise RuntimeError(f'China Tower identity not found: {path}')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    prefix = RENDERS / path.stem
    subprocess.run(['pdftoppm','-f','1','-l','1','-png','-singlefile','-r','100',str(path),str(prefix)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    png = Path(str(prefix) + '.png')
    if not png.exists() or png.stat().st_size < 8000:
        raise RuntimeError(f'Cover render failed: {path}')
    return {'pages': pages, 'bytes': path.stat().st_size, 'sha256': digest, 'text_preview': sample[:2000], 'render_bytes': png.stat().st_size}

manifest = []
for src in SOURCES:
    pdf_url, page_html = extract_pdf_url(src['page_url'])
    out = REPORTS / src['output']
    r = session.get(pdf_url, timeout=120, headers={'Referer': src['page_url'], 'Accept':'application/pdf,*/*'})
    r.raise_for_status()
    out.write_bytes(r.content)
    meta = validate_pdf(out)
    manifest.append({
        'broker': src['broker'],
        'date': src['date'],
        'title': src['title'],
        'filename': out.name,
        'page_url': src['page_url'],
        'source_pdf_url': pdf_url,
        'pages': meta['pages'],
        'bytes': meta['bytes'],
        'sha256': meta['sha256'],
    })
    print('VALID', json.dumps(manifest[-1], ensure_ascii=False))

readme = [
    '中国铁塔（00788.HK）券商公司研究报告合集',
    '',
    '本包收录两份公开可获取的完整券商研究报告原始PDF。',
    '说明：两份均为公司研究/业绩跟踪报告，其中德邦证券报告为4页、浙商证券报告页数以PDF实际校验为准；并非将网页预览另行打印生成。',
    '',
    '文件清单：',
]
for i, item in enumerate(manifest, 1):
    readme.append(f"{i}. {item['broker']}｜{item['date']}｜{item['pages']}页｜{item['title']}")
readme.extend(['', '已校验：PDF签名、公司名称/代码、实际页数、首页渲染、SHA-256、ZIP完整性。'])
(REPORTS / 'README_报告说明.txt').write_text('\n'.join(readme), encoding='utf-8')
(REPORTS / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
with (REPORTS / 'manifest.csv').open('w', encoding='utf-8-sig', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=list(manifest[0].keys()))
    writer.writeheader(); writer.writerows(manifest)

with ZipFile(ZIP_PATH, 'w', ZIP_DEFLATED, compresslevel=9) as zf:
    for p in sorted(REPORTS.iterdir(), key=lambda x: x.name):
        zf.write(p, arcname=p.name)
with ZipFile(ZIP_PATH) as zf:
    if zf.testzip() is not None:
        raise RuntimeError('ZIP integrity failure')
    pdfs = [n for n in zf.namelist() if n.lower().endswith('.pdf')]
    if len(pdfs) != 2:
        raise RuntimeError(f'Unexpected PDF count: {len(pdfs)}')
print('PACKAGE_READY', ZIP_PATH, ZIP_PATH.stat().st_size)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
