from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from pypdf import PdfReader

OUT = Path('out_cssc_defense_20260907')
RAW = OUT / 'raw_pdfs'
PACKAGE = OUT / 'package'
RENDERS = OUT / 'renders'
FINAL = OUT / 'CSSC_Offshore_Defense_600685_00317_Broker_Deep_Reports.zip'
PACKAGE.mkdir(parents=True, exist_ok=True)
RENDERS.mkdir(parents=True, exist_ok=True)

if not RAW.exists():
    raise FileNotFoundError('raw_pdfs directory was not created')

EXPECTED = [
    {
        'key': 'zheshang_20240608_deep',
        'broker': '浙商证券',
        'date': '2024-06-08',
        'title': '中船集团旗下“A+H”平台，受益船舶景气上行、竞争格局改善',
        'report_type': '公司深度报告',
        'min_pages': 15,
        'tokens': ['浙商证券', '中船集团旗下', 'A+H', '竞争格局改善'],
        'output': '01_浙商证券_2024-06-08_中船防务公司深度报告.pdf',
        'source_page': 'https://www.hangyan.co/reports/3386969413495293759',
    },
    {
        'key': 'ccbi_20250303_initiation',
        'broker': '建银国际证券',
        'date': '2025-03-03',
        'title': '顺风启航',
        'report_type': '首次覆盖 / 港股公司研究',
        'min_pages': 5,
        'tokens': ['顺风启航', '建银国际', 'CCBI', '优于大市', '317HK'],
        'output': '02_建银国际证券_2025-03-03_中船防务首次覆盖_顺风启航.pdf',
        'source_page': 'https://www.hangyan.co/reports/3584289384419034920',
    },
]

pdfs = sorted(RAW.glob('*.pdf'))
if not pdfs:
    raise RuntimeError('No PDF files were collected')

# Inspect each unique PDF once.
inspected = []
seen_hashes = set()
for path in pdfs:
    data = path.read_bytes()
    if not data.startswith(b'%PDF-') or len(data) < 50000:
        continue
    digest = hashlib.sha256(data).hexdigest()
    if digest in seen_hashes:
        continue
    seen_hashes.add(digest)
    try:
        reader = PdfReader(str(path), strict=False)
        pages = len(reader.pages)
        sample_indices = list(range(min(15, pages)))
        if pages > 20:
            sample_indices.extend([pages // 2, pages - 1])
        text_parts = []
        for i in sorted(set(sample_indices)):
            try:
                text_parts.append(reader.pages[i].extract_text() or '')
            except Exception:
                pass
        text = '\n'.join(text_parts)
    except Exception:
        continue
    normalized = re.sub(r'\s+', '', text).lower()
    identity = any(token in normalized for token in ['中船防务', '中船海洋与防务装备', '中船海洋與防務裝備', 'csscoffshore', '600685', '317hk', '00317'])
    if not identity:
        continue
    inspected.append({'path': path, 'sha256': digest, 'pages': pages, 'text': text, 'normalized': normalized, 'bytes': len(data)})

if not inspected:
    raise RuntimeError('Collected PDFs did not pass company identity validation')

selected = []
used_hashes = set()
for expected in EXPECTED:
    candidates = []
    for item in inspected:
        if item['sha256'] in used_hashes:
            continue
        hit_count = sum(token.lower().replace(' ', '') in item['normalized'] for token in expected['tokens'])
        filename_hit = expected['key'] in item['path'].name
        score = hit_count * 10 + (20 if filename_hit else 0) + min(item['pages'], 60) / 10
        if hit_count > 0 or filename_hit:
            candidates.append((score, item))
    if not candidates:
        raise RuntimeError(f"Could not identify expected report: {expected['title']}")
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    item = candidates[0][1]
    if item['pages'] < expected['min_pages']:
        raise RuntimeError(f"Report appears incomplete: {expected['title']} ({item['pages']} pages)")
    used_hashes.add(item['sha256'])
    selected.append((expected, item))

manifest = []
for expected, item in selected:
    destination = PACKAGE / expected['output']
    shutil.copy2(item['path'], destination)

    # Render cover, midpoint and last page to confirm readability.
    for page_number in sorted({1, max(1, (item['pages'] + 1) // 2), item['pages']}):
        prefix = RENDERS / f"{destination.stem}_p{page_number}"
        subprocess.run(
            ['pdftoppm', '-f', str(page_number), '-l', str(page_number), '-png', '-singlefile', '-r', '90', str(destination), str(prefix)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        image = Path(str(prefix) + '.png')
        if not image.exists() or image.stat().st_size < 8000:
            raise RuntimeError(f"Render validation failed: {destination.name} page {page_number}")

    manifest.append({
        '券商': expected['broker'],
        '日期': expected['date'],
        '报告标题': expected['title'],
        '报告类型': expected['report_type'],
        '实际页数': item['pages'],
        '文件名': destination.name,
        '文件大小_字节': destination.stat().st_size,
        'SHA256': item['sha256'],
        '来源页面': expected['source_page'],
    })

readme = [
    '中船防务（600685.SH / 00317.HK）券商深度报告合集',
    '',
    '本压缩包收录2份公开可获取、经完整性核验的实际券商PDF，不含网页跳转文件、目录页或预览图片。',
    '',
    '文件清单：',
]
for i, row in enumerate(manifest, 1):
    readme.append(f"{i}. {row['券商']}｜{row['日期']}｜{row['实际页数']}页｜{row['报告类型']}｜{row['报告标题']}")
readme.extend([
    '',
    '校验项目：PDF文件签名、公司名称/证券代码、报告标题、实际页数、文件哈希、首中末页渲染及ZIP完整性。',
    '文件仅供个人研究使用，版权归原券商及发布机构所有。',
])
(PACKAGE / 'README_文件说明.txt').write_text('\n'.join(readme), encoding='utf-8')
(PACKAGE / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
with (PACKAGE / 'manifest.csv').open('w', encoding='utf-8-sig', newline='') as handle:
    writer = csv.DictWriter(handle, fieldnames=list(manifest[0].keys()))
    writer.writeheader()
    writer.writerows(manifest)

FINAL.unlink(missing_ok=True)
with ZipFile(FINAL, 'w', ZIP_DEFLATED, compresslevel=9) as archive:
    for member in sorted(PACKAGE.iterdir(), key=lambda p: p.name):
        archive.write(member, arcname=member.name)
with ZipFile(FINAL) as archive:
    bad = archive.testzip()
    if bad is not None:
        raise RuntimeError(f'ZIP integrity failure: {bad}')
    pdf_names = [name for name in archive.namelist() if name.lower().endswith('.pdf')]
    if len(pdf_names) != 2:
        raise RuntimeError(f'Expected 2 PDFs, found {len(pdf_names)}')

print('PACKAGE_READY', FINAL, FINAL.stat().st_size)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
