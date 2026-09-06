from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import requests
from pypdf import PdfReader

ROOT = Path('.')
COLLECT_DIRS = [Path('out_ascletis_20260906'), Path('out_ascletis_deep_v2'), Path('out_ascletis_eastmoney_sina')]
OUT = Path('deliverables/ascletis_01672')
PDF_OUT = OUT / 'reports'
FINAL_ZIP = Path('deliverables/ascletis_01672_reports.zip')
STATUS = Path('deliverables/ascletis_01672_status.json')
shutil.rmtree(OUT, ignore_errors=True)
PDF_OUT.mkdir(parents=True, exist_ok=True)
FINAL_ZIP.unlink(missing_ok=True)

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
session = requests.Session()
session.headers.update({'User-Agent': UA, 'Accept': 'application/pdf,text/html,application/json,*/*'})

# Known legal public sources. These are downloaded even if a collector missed them.
KNOWN_DOWNLOADS = [
    {
        'url': 'https://cdn.hangyan.co/documents/98/980839aeb3b9cde04c6b7c34aef205de26696bc36ac08713989fde10cddb7889.pdf',
        'path': Path('out_ascletis_known/guoyuan_20240902.pdf'),
        'broker': '国元国际控股',
        'date': '2024-09-02',
        'title': '创新药研发推进顺利，BD合作空间广阔',
        'source_page': 'https://www.hangyan.co/reports/3448696034581022433',
        'completeness': '完整公司研究报告',
    },
]

for item in KNOWN_DOWNLOADS:
    item['path'].parent.mkdir(parents=True, exist_ok=True)
    try:
        r = session.get(item['url'], headers={'Referer': item['source_page'], 'Accept': 'application/pdf,*/*'}, timeout=90)
        print('KNOWN_GET', r.status_code, r.headers.get('content-type'), len(r.content), item['url'])
        if r.status_code == 200 and r.content.startswith(b'%PDF-') and len(r.content) > 50000:
            item['path'].write_bytes(r.content)
    except Exception as exc:
        print('KNOWN_GET_ERR', repr(exc), item['url'])

metadata_by_hash: dict[str, dict] = {}
for directory in COLLECT_DIRS:
    for json_path in directory.rglob('saved_pdfs.json') if directory.exists() else []:
        try:
            rows = json.loads(json_path.read_text(encoding='utf-8'))
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                sha = str(row.get('sha256') or '').lower()
                if sha:
                    metadata_by_hash[sha] = row
        except Exception as exc:
            print('META_ERR', json_path, repr(exc))

known_by_path = {str(item['path'].resolve()): item for item in KNOWN_DOWNLOADS}

candidate_paths: list[Path] = []
for directory in COLLECT_DIRS + [Path('out_ascletis_known')]:
    if directory.exists():
        candidate_paths.extend(directory.rglob('*.pdf'))

# Deduplicate source paths and content.
unique_paths = []
seen_path = set()
for path in candidate_paths:
    key = str(path.resolve())
    if key not in seen_path:
        seen_path.add(key)
        unique_paths.append(path)

records = []
seen_sha = set()
for path in unique_paths:
    try:
        data = path.read_bytes()
        if len(data) < 50000 or not data.startswith(b'%PDF-'):
            continue
        sha = hashlib.sha256(data).hexdigest()
        if sha in seen_sha:
            continue
        seen_sha.add(sha)
        reader = PdfReader(str(path), strict=False)
        pages = len(reader.pages)
        if pages < 2:
            continue
        sample_indices = list(range(min(pages, 12)))
        if pages > 15:
            sample_indices += [pages // 2, pages - 1]
        parts = []
        for index in sorted(set(sample_indices)):
            try:
                parts.append(reader.pages[index].extract_text() or '')
            except Exception:
                pass
        text = '\n'.join(parts)
        norm = re.sub(r'\s+', '', text).lower()
        if not any(token in norm for token in ['歌礼制药', '歌禮製藥', 'ascletis', '01672', '1672hk']):
            continue
        # Reject issuer filings and obvious non-broker documents.
        if any(token in norm for token in ['年度报告2025', '年度報告2025', '中期业绩', '中期業績', '翌日披露报表']) and not any(token in norm for token in ['证券研究报告', '證券研究報告', 'researchreport', '证券分析师', '分析師']):
            continue
        meta = metadata_by_hash.get(sha, {})
        known = known_by_path.get(str(path.resolve()), {})
        blob = json.dumps(meta, ensure_ascii=False) + '\n' + text[:12000] + '\n' + path.name
        low_blob = blob.lower()
        broker = known.get('broker', '')
        if not broker:
            if '东吴证券' in blob or '東吳證券' in blob:
                broker = '东吴证券'
            elif '东方证券' in blob or '東方證券' in blob:
                broker = '东方证券'
            elif '国元' in blob or '國元' in blob:
                broker = '国元国际控股'
            elif '山西证券' in blob or '山西證券' in blob:
                broker = '山西证券'
            else:
                broker = '券商研究机构'
        date = known.get('date', '')
        date_match = re.search(r'(20\d{2})[年./-]\s*(\d{1,2})[月./-]\s*(\d{1,2})日?', blob)
        if not date and date_match:
            date = f'{int(date_match.group(1)):04d}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}'
        title = known.get('title', '')
        title_map = [
            ('全新GLP-1减重不减肌', '全新GLP-1减重不减肌，有潜力成为Best-in-Class'),
            ('口服小分子率先破局', '口服小分子率先破局，紧跟减重前沿'),
            ('创新药研发推进顺利', '创新药研发推进顺利，BD合作空间广阔'),
            ('GLP-1小分子', '创新药动态更新：GLP-1小分子'),
        ]
        if not title:
            for marker, mapped in title_map:
                if marker.lower() in low_blob:
                    title = mapped
                    break
        if not title:
            title = path.stem
        source_url = known.get('url', '') or meta.get('sourceUrl', '') or meta.get('url', '')
        source_page = known.get('source_page', '') or meta.get('pageUrl', '') or meta.get('report_url', '')
        # Identify trial/partial files conservatively.
        completeness = known.get('completeness', '')
        if not completeness:
            if 'try_down' in source_url or 'trial' in low_blob or '试下载' in low_blob:
                completeness = '公开试下载版，可能非原报告全部页数'
            elif pages >= 15:
                completeness = '完整长篇券商报告（按页数和文件结构核验）'
            else:
                completeness = '完整券商公司研究/行业专题（短篇）'
        deep_score = 0
        if pages >= 15:
            deep_score += 100
        elif pages >= 8:
            deep_score += 40
        else:
            deep_score += 10
        if '首次覆盖' in blob or '公司深度' in blob or '深度报告' in blob:
            deep_score += 80
        if broker in {'东吴证券', '东方证券'}:
            deep_score += 30
        if '试下载' in completeness:
            deep_score -= 70
        if broker == '国元国际控股':
            deep_score += 5
        records.append({
            'path': path,
            'sha256': sha,
            'pages': pages,
            'bytes': len(data),
            'broker': broker,
            'date': date,
            'title': title,
            'source_url': source_url,
            'source_page': source_page,
            'completeness': completeness,
            'deep_score': deep_score,
            'sample': text[:3000],
        })
    except Exception as exc:
        print('CANDIDATE_ERR', path, repr(exc))

# De-duplicate same report across language/mirror copies by normalized broker+date+title.
def report_key(row):
    title = re.sub(r'[^a-z0-9\u4e00-\u9fff]+', '', row['title'].lower())
    return (row['broker'], row['date'], title[:80])

by_report = {}
for row in records:
    key = report_key(row)
    current = by_report.get(key)
    if current is None or (row['pages'], row['bytes']) > (current['pages'], current['bytes']):
        by_report[key] = row
records = list(by_report.values())
records.sort(key=lambda row: (row['deep_score'], row['date'], row['pages']), reverse=True)

# Prefer two or three distinct useful documents. Include a short complete company update only if needed.
selected = []
for row in records:
    if len(selected) >= 3:
        break
    # Exclude partial trials when two complete documents are already available.
    if '试下载' in row['completeness'] and sum('试下载' not in x['completeness'] for x in selected) >= 2:
        continue
    selected.append(row)

# Hard fallback: at least deliver the verified Guoyuan PDF, but do not pretend it is deep.
if len(selected) < 2:
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps({
        'success': False,
        'reason': 'Fewer than two distinct public broker PDFs could be verified.',
        'candidates': [{k:v for k,v in row.items() if k not in {'path','sample'}} for row in records],
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print('INSUFFICIENT', len(selected))
    raise SystemExit(2)

manifest = []
for index, row in enumerate(selected, 1):
    safe_broker = re.sub(r'[\\/:*?"<>|]+', '_', row['broker'])
    safe_date = row['date'] or 'undated'
    kind = 'Deep' if row['pages'] >= 15 and '试下载' not in row['completeness'] else ('Trial' if '试下载' in row['completeness'] else 'Research')
    filename = f'{index:02d}_{safe_broker}_{safe_date}_Ascletis_01672_{kind}_{row["pages"]}p.pdf'
    dest = PDF_OUT / filename
    shutil.copy2(row['path'], dest)
    # Render first/middle/last pages. Failure rejects the file.
    render_dir = OUT / 'renders' / f'{index:02d}'
    render_dir.mkdir(parents=True, exist_ok=True)
    for page_no in sorted(set([1, max(1, (row['pages'] + 1)//2), row['pages']])):
        prefix = render_dir / f'p{page_no}'
        subprocess.run(['pdftoppm','-f',str(page_no),'-l',str(page_no),'-png','-singlefile','-r','90',str(dest),str(prefix)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        image = Path(str(prefix)+'.png')
        if not image.exists() or image.stat().st_size < 5000:
            raise RuntimeError(f'Render failed for {filename} page {page_no}')
    manifest.append({
        'index': index,
        'broker': row['broker'],
        'date': row['date'],
        'title': row['title'],
        'pages': row['pages'],
        'completeness': row['completeness'],
        'filename': filename,
        'bytes': dest.stat().st_size,
        'sha256': hashlib.sha256(dest.read_bytes()).hexdigest(),
        'source_page': row['source_page'],
        'source_pdf': row['source_url'],
    })

readme_lines = [
    '歌礼制药（01672.HK）券商研究报告合集',
    '',
    '本包只包含实际PDF，不包含网页跳转文件、封面预览或公司公告。',
    '“完整性”按公开来源、实际页数、PDF结构和首/中/末页渲染结果核验。',
    '',
    '文件清单：',
]
for item in manifest:
    readme_lines.append(f"{item['index']}. {item['broker']}｜{item['date'] or '日期未识别'}｜{item['pages']}页｜{item['completeness']}｜{item['title']}")
readme_lines += [
    '',
    '说明：页数较少的公司跟踪报告不等同于长篇首次覆盖深度报告，清单已明确标注。',
    '校验项目：PDF文件签名、歌礼制药/Ascletis/01672公司身份、实际页数、首中末页渲染、SHA-256和ZIP完整性。',
    '仅供个人研究使用，版权归原券商及发布机构所有。',
]
(PDF_OUT / 'README.txt').write_text('\n'.join(readme_lines), encoding='utf-8')
(PDF_OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
with (PDF_OUT / 'manifest.csv').open('w', encoding='utf-8-sig', newline='') as handle:
    writer = csv.DictWriter(handle, fieldnames=list(manifest[0].keys()))
    writer.writeheader(); writer.writerows(manifest)

FINAL_ZIP.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(FINAL_ZIP, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(PDF_OUT.iterdir(), key=lambda p:p.name):
        archive.write(path, path.name)
with zipfile.ZipFile(FINAL_ZIP) as archive:
    bad = archive.testzip()
    if bad is not None:
        raise RuntimeError(f'ZIP corruption at {bad}')
    pdfs = [name for name in archive.namelist() if name.lower().endswith('.pdf')]
    if len(pdfs) != len(manifest):
        raise RuntimeError('ZIP PDF count mismatch')

STATUS.write_text(json.dumps({
    'success': True,
    'zip': str(FINAL_ZIP),
    'zip_bytes': FINAL_ZIP.stat().st_size,
    'zip_sha256': hashlib.sha256(FINAL_ZIP.read_bytes()).hexdigest(),
    'manifest': manifest,
}, ensure_ascii=False, indent=2), encoding='utf-8')
print('PACKAGE_READY', FINAL_ZIP, FINAL_ZIP.stat().st_size)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
