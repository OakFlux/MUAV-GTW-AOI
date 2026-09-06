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

SRC = Path('out_ascletis_browser_rebuild')
PDFDIR = SRC / 'pdfs'
OUT = Path('out_ascletis_browser_package')
REPORTS = OUT / 'reports'
RENDERS = OUT / 'renders'
ZIP = OUT / 'ascletis_01672_reports_v3.zip'
shutil.rmtree(OUT, ignore_errors=True)
REPORTS.mkdir(parents=True)
RENDERS.mkdir(parents=True)

saved_path = SRC / 'saved_pdfs.json'
if not saved_path.exists():
    raise FileNotFoundError('saved_pdfs.json not found')
saved = json.loads(saved_path.read_text(encoding='utf-8'))


def inspect(path: Path) -> dict:
    data = path.read_bytes()
    if not data.startswith(b'%PDF-') or len(data) < 80000:
        raise RuntimeError(f'Invalid PDF {path.name}')
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 3:
        raise RuntimeError(f'Too few pages {path.name}: {pages}')
    indices = sorted(set(list(range(min(12, pages))) + [pages // 2, pages - 1]))
    parts = []
    for i in indices:
        try:
            parts.append(reader.pages[i].extract_text() or '')
        except Exception:
            pass
    text = '\n'.join(parts)
    norm = re.sub(r'\s+', '', text).lower()
    if not any(x in norm for x in ['歌礼制药', '歌禮製藥', 'ascletis', '01672', '1672.hk', '1672hk']):
        raise RuntimeError(f'Ascletis identity missing in {path.name}')
    # Render first/middle/last page.
    for pageno in sorted({1, max(1, (pages + 1) // 2), pages}):
        prefix = RENDERS / f'{path.stem}_p{pageno}'
        subprocess.run([
            'pdftoppm', '-f', str(pageno), '-l', str(pageno), '-png',
            '-singlefile', '-r', '80', str(path), str(prefix)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        image = Path(str(prefix) + '.png')
        if not image.exists() or image.stat().st_size < 4000:
            raise RuntimeError(f'Render failed: {path.name} p{pageno}')
    return {
        'pages': pages,
        'bytes': len(data),
        'sha256': hashlib.sha256(data).hexdigest(),
        'text': text,
    }


def infer(item: dict, meta: dict) -> dict:
    blob = ' '.join([
        item.get('filenameHint','') or '', item.get('title','') or '', meta.get('text','')[:12000]
    ])
    broker = '券商研究'
    for name in ['东方证券', '東方證券', '东吴证券', '東吳證券', '国元国际控股', '國元國際控股', '国元国际', '國元國際', '兴业证券', '興業證券', '中信建投', '国投证券', '國投證券', '光大证券', '光大證券']:
        if name in blob:
            broker = name
            break
    date = ''
    patterns = [
        r'(20\d{2})[-年./](\d{1,2})[-月./](\d{1,2})',
        r'(20\d{2})(\d{2})(\d{2})',
    ]
    for pat in patterns:
        m = re.search(pat, blob)
        if m:
            y, mo, d = map(int, m.groups())
            if 1 <= mo <= 12 and 1 <= d <= 31:
                date = f'{y:04d}-{mo:02d}-{d:02d}'
                break
    title = item.get('filenameHint') or item.get('title') or ''
    title = re.sub(r'\.pdf$', '', title, flags=re.I)
    deep = any(x in blob.lower() for x in ['首次覆盖', '首次覆蓋', '全新glp-1减重不减肌', '口服小分子率先破局', 'deep', 'initiation'])
    return {'broker': broker, 'date': date, 'title': title, 'deep': deep}

candidates = []
seen_hash = set()
for item in saved:
    path = Path(item['file'])
    if not path.exists():
        continue
    try:
        meta = inspect(path)
        if meta['sha256'] in seen_hash:
            continue
        seen_hash.add(meta['sha256'])
        inferred = infer(item, meta)
        candidates.append({**item, **meta, **inferred, 'path': str(path)})
    except Exception as exc:
        print('REJECT', path, repr(exc))

# Prioritize true long-form reports, then recency and page count.
def priority(x: dict):
    return (int(x['deep']), x['pages'], x['date'])

candidates.sort(key=priority, reverse=True)
selected = candidates[:3]
if len(selected) < 2:
    raise RuntimeError(f'Only {len(selected)} valid distinct reports found')

manifest = []
for i, item in enumerate(selected, 1):
    broker_ascii = {
        '东方证券': 'Orient_Securities', '東方證券': 'Orient_Securities',
        '东吴证券': 'Soochow_Securities', '東吳證券': 'Soochow_Securities',
        '国元国际控股': 'Guoyuan_International', '國元國際控股': 'Guoyuan_International',
        '国元国际': 'Guoyuan_International', '國元國際': 'Guoyuan_International',
        '兴业证券': 'Industrial_Securities', '興業證券': 'Industrial_Securities',
        '中信建投': 'CSC_Securities', '国投证券': 'SDIC_Securities', '國投證券': 'SDIC_Securities',
        '光大证券': 'Everbright_Securities', '光大證券': 'Everbright_Securities',
    }.get(item['broker'], 'Broker')
    filename = f'{i:02d}_{broker_ascii}_{item["date"] or "undated"}_Ascletis_01672_{item["pages"]}p.pdf'
    dest = REPORTS / filename
    shutil.copy2(item['path'], dest)
    manifest.append({
        'index': i,
        'broker': item['broker'],
        'date': item['date'],
        'title': item['title'],
        'report_type': '首次覆盖/深度报告' if item['deep'] else '完整公司研究报告',
        'filename': filename,
        'pages': item['pages'],
        'bytes': item['bytes'],
        'sha256': item['sha256'],
        'report_page': item.get('reportUrl',''),
        'source_pdf': item.get('sourceUrl',''),
    })

readme = [
    'Ascletis Pharma (01672.HK) broker research report package',
    '',
    f'Contains {len(manifest)} distinct and complete PDF reports.',
    'No company filings, web shortcuts, locally written summaries, or image-only previews are counted as reports.',
    '',
]
for x in manifest:
    readme.append(f"{x['index']}. {x['broker']} | {x['date']} | {x['pages']} pages | {x['report_type']} | {x['title']}")
readme += ['', 'Checks completed: PDF signature, issuer identity, page count, SHA-256, first/middle/last-page rendering, and ZIP integrity.']
(REPORTS / 'README.txt').write_text('\n'.join(readme), encoding='utf-8')
(REPORTS / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
with (REPORTS / 'manifest.csv').open('w', encoding='utf-8-sig', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(manifest[0].keys()))
    w.writeheader(); w.writerows(manifest)

with ZipFile(ZIP, 'w', ZIP_DEFLATED, compresslevel=9) as zf:
    for p in sorted(REPORTS.iterdir(), key=lambda x: x.name):
        zf.write(p, p.name)
with ZipFile(ZIP) as zf:
    if zf.testzip() is not None:
        raise RuntimeError('ZIP integrity failure')
    if len([n for n in zf.namelist() if n.lower().endswith('.pdf')]) != len(manifest):
        raise RuntimeError('PDF count mismatch')

print('PACKAGE_READY', ZIP, ZIP.stat().st_size)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
