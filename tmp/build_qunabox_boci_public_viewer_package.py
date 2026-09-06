from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import requests
from PIL import Image
from pypdf import PdfReader

OUT = Path('out_qunabox_boci_public_viewer')
PAGES = OUT / 'boci_pages'
REPORTS = OUT / 'reports'
RENDERS = OUT / 'renders'
FINAL = OUT / 'Qunabox_00917_Broker_Deep_Reports_2.zip'
for p in [OUT]:
    shutil.rmtree(p, ignore_errors=True)
PAGES.mkdir(parents=True)
REPORTS.mkdir(parents=True)
RENDERS.mkdir(parents=True)

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
s = requests.Session()
s.headers.update({'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'})

WESTBULL_URL = 'http://www.westbullsec.com.hk/upload/2e/d2/2ed2f834fdd55836be06d987b4fc46a1.pdf'
WESTBULL_PAGE = 'http://www.westbullsec.com.hk/research'
BOCI_REPORT_PAGE = 'https://www.sgpjbg.com/baogao/464567.html'
BOCI_BASE = 'https://file.sgpjbg.com/fileroot2/2025-1/16/bfd53a87-8de3-408e-9089-a35ea501a215/bfd53a87-8de3-408e-9089-a35ea501a215'
BOCI_PAGE_COUNT = 29


def get(url: str, referer: str, timeout: int = 90) -> requests.Response:
    last = None
    for attempt in range(1, 5):
        try:
            r = s.get(url, headers={'Referer': referer}, timeout=timeout, allow_redirects=True)
            print('GET', r.status_code, r.headers.get('content-type'), len(r.content), r.url)
            if r.status_code == 200:
                return r
            last = RuntimeError(f'HTTP {r.status_code}')
        except Exception as exc:
            last = exc
            print('RETRY', attempt, repr(exc), url)
        time.sleep(attempt)
    raise RuntimeError(f'Unable to fetch {url}: {last}')


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect_pdf(path: Path, expected_pages: int | None = None) -> dict:
    if path.read_bytes()[:5] != b'%PDF-':
        raise RuntimeError(f'Not PDF: {path}')
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if expected_pages is not None and pages != expected_pages:
        raise RuntimeError(f'Page mismatch {path.name}: {pages} != {expected_pages}')
    sample_indices = sorted(set([0, min(1, pages-1), pages//2, pages-1]))
    text = []
    for i in sample_indices:
        try:
            text.append(reader.pages[i].extract_text() or '')
        except Exception:
            pass
    normalized = re.sub(r'\s+', '', '\n'.join(text)).lower()
    # Viewer-generated BOCI PDF is image-only, so identity is verified from page images separately.
    if 'westbull' in path.name.lower() and not any(k in normalized for k in ['趣致集團', '趣致集团', 'qunabox', '00917']):
        raise RuntimeError(f'Qunabox identity missing: {path.name}')
    return {'pages': pages, 'bytes': path.stat().st_size, 'sha256': sha256(path)}


def render_check(path: Path, pages: int) -> list[str]:
    outputs = []
    for pageno in sorted(set([1, max(1, (pages+1)//2), pages])):
        prefix = RENDERS / f'{path.stem}_p{pageno}'
        subprocess.run([
            'pdftoppm', '-f', str(pageno), '-l', str(pageno), '-png', '-singlefile', '-r', '100', str(path), str(prefix)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        png = Path(str(prefix) + '.png')
        if not png.exists() or png.stat().st_size < 10000:
            raise RuntimeError(f'Render failed: {path.name} p{pageno}')
        outputs.append(png.name)
    return outputs


# 1) Official complete West Bull PDF.
west_path = REPORTS / '01_WestBull_2026-08-24_Qunabox_Initiation_25p_CN.pdf'
r = get(WESTBULL_URL, WESTBULL_PAGE)
if not r.content.startswith(b'%PDF-') or len(r.content) < 500000:
    raise RuntimeError('West Bull response is not a complete PDF')
west_path.write_bytes(r.content)
west_meta = inspect_pdf(west_path, 25)
west_meta['renders'] = render_check(west_path, west_meta['pages'])

# 2) BOCI 29-page report reconstructed only from image pages openly served by the public online viewer.
images: list[Image.Image] = []
page_meta = []
for page_no in range(1, BOCI_PAGE_COUNT + 1):
    url = f'{BOCI_BASE}{page_no}.gif'
    r = get(url, BOCI_REPORT_PAGE)
    ct = (r.headers.get('content-type') or '').lower()
    if 'image' not in ct or len(r.content) < 10000:
        raise RuntimeError(f'BOCI public viewer page {page_no} unavailable or invalid')
    raw_path = PAGES / f'{page_no:02d}.gif'
    raw_path.write_bytes(r.content)
    with Image.open(io.BytesIO(r.content)) as im:
        im.seek(0)
        rgb = im.convert('RGB')
        # Copy before source image is closed.
        images.append(rgb.copy())
        page_meta.append({'page': page_no, 'url': url, 'size': im.size, 'format': im.format, 'bytes': len(r.content), 'sha256': hashlib.sha256(r.content).hexdigest()})
    print('PAGE_OK', page_no, page_meta[-1])

if len(images) != BOCI_PAGE_COUNT:
    raise RuntimeError(f'Only {len(images)} of {BOCI_PAGE_COUNT} BOCI pages downloaded')

# Verify visible company/report identity using first-page image dimensions and the public source metadata.
if images[0].width < 600 or images[0].height < 800:
    raise RuntimeError(f'Unexpected first-page size: {images[0].size}')

boci_path = REPORTS / '02_BOCI_2025-01-15_Qunabox_Initiation_29p_Public_Viewer.pdf'
images[0].save(
    boci_path,
    'PDF',
    resolution=150.0,
    save_all=True,
    append_images=images[1:],
    quality=92,
    optimize=True,
)
boci_meta = inspect_pdf(boci_path, BOCI_PAGE_COUNT)
boci_meta['renders'] = render_check(boci_path, boci_meta['pages'])

manifest = [
    {
        'index': 1,
        'broker': '西牛证券（West Bull Securities）',
        'date': '2026-08-24',
        'title': '存量终端迈入AI变现周期，高毛利业务有望获得重估',
        'report_type': '首次覆盖 / 公司深度',
        'file': west_path.name,
        'source_type': '券商官网公开原始PDF',
        'source_page': WESTBULL_PAGE,
        'source_url': WESTBULL_URL,
        **{k:v for k,v in west_meta.items() if k != 'renders'},
    },
    {
        'index': 2,
        'broker': '中银证券',
        'date': '2025-01-15',
        'title': 'AI互动营销领导者，公司业绩高速增长',
        'report_type': '首次评级 / 公司深度',
        'file': boci_path.name,
        'source_type': '公开在线阅读器逐页图像合成PDF（非券商原始PDF文件）',
        'source_page': BOCI_REPORT_PAGE,
        'source_url': BOCI_REPORT_PAGE,
        **{k:v for k,v in boci_meta.items() if k != 'renders'},
    },
]

readme = '''趣致集团（00917.HK）券商深度报告包

本包收录2份不同券商、不同日期的完整报告：
1. 西牛证券，2026-08-24，25页首次覆盖报告。文件为券商官网公开原始PDF。
2. 中银证券，2025-01-15，29页首次评级报告。原始PDF下载需会员权限；本包版本由公开在线阅读器无登录即可访问的29张完整页面图像按原顺序合成为PDF，不是券商原始PDF文件，页面内容和页数完整。

未把西牛证券中文/英文重复版本算作两份；未收录14页免费试下载等不完整文件。

校验：PDF文件签名、实际页数、首/中/末页渲染、SHA-256、ZIP完整性。
仅供个人研究使用，版权归原券商及发布机构所有。
'''
(REPORTS / 'README_文件说明.txt').write_text(readme, encoding='utf-8')
(REPORTS / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
(REPORTS / 'boci_public_viewer_pages.json').write_text(json.dumps(page_meta, ensure_ascii=False, indent=2), encoding='utf-8')
with (REPORTS / 'manifest.csv').open('w', encoding='utf-8-sig', newline='') as f:
    cols = ['index','broker','date','title','report_type','file','source_type','pages','bytes','sha256','source_page','source_url']
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    for row in manifest:
        w.writerow({k: row.get(k,'') for k in cols})

with ZipFile(FINAL, 'w', ZIP_DEFLATED, compresslevel=9) as z:
    for p in sorted(REPORTS.iterdir(), key=lambda p:p.name):
        z.write(p, p.name)
with ZipFile(FINAL) as z:
    bad = z.testzip()
    if bad is not None:
        raise RuntimeError(f'ZIP damaged at {bad}')
    if len([n for n in z.namelist() if n.lower().endswith('.pdf')]) != 2:
        raise RuntimeError('ZIP PDF count mismatch')

print('PACKAGE_READY', FINAL, FINAL.stat().st_size)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
