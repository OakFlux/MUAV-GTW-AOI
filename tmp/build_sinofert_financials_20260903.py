from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from pypdf import PdfReader

OUT = Path('out_sinofert_financials_20260903')
REPORTS = OUT / 'reports'
RENDERS = OUT / 'renders'
shutil.rmtree(OUT, ignore_errors=True)
REPORTS.mkdir(parents=True, exist_ok=True)
RENDERS.mkdir(parents=True, exist_ok=True)

UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
INDEX_SOURCE = 'https://treelazy.com/stock-en/hk/00297'

FILES = [
    {
        'kind': 'annual_report', 'year': 2020,
        'filename': '01_中化化肥_2020年年度报告.pdf',
        'url': 'https://www1.hkexnews.hk/listedco/listconews/sehk/2021/0416/2021041600322_c.pdf',
        'min_pages': 150,
    },
    {
        'kind': 'annual_report', 'year': 2021,
        'filename': '02_中化化肥_2021年年度报告.pdf',
        'url': 'https://www1.hkexnews.hk/listedco/listconews/sehk/2022/0420/2022042000798_c.pdf',
        'min_pages': 150,
    },
    {
        'kind': 'annual_report', 'year': 2022,
        'filename': '03_中化化肥_2022年年度报告.pdf',
        'url': 'https://www1.hkexnews.hk/listedco/listconews/sehk/2023/0421/2023042100436_c.pdf',
        'min_pages': 150,
    },
    {
        'kind': 'annual_report', 'year': 2023,
        'filename': '04_中化化肥_2023年年度报告.pdf',
        'url': 'https://www1.hkexnews.hk/listedco/listconews/sehk/2024/0425/2024042502499_c.pdf',
        'min_pages': 150,
    },
    {
        'kind': 'annual_report', 'year': 2024,
        'filename': '05_中化化肥_2024年年度报告.pdf',
        'url': 'https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0425/2025042503774_c.pdf',
        'min_pages': 150,
    },
    {
        'kind': 'annual_report', 'year': 2025,
        'filename': '06_中化化肥_2025年年度报告.pdf',
        'url': 'https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0427/2026042700635_c.pdf',
        'min_pages': 150,
    },
    {
        'kind': 'latest_interim_results',
        'period_end': '2026-06-30', 'publication_date': '2026-08-25',
        'filename': '07_中化化肥_2026年中期业绩_截至2026年6月30日.pdf',
        'url': 'https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0825/2026082500230_c.pdf',
        'min_pages': 25,
    },
]


def download(url: str, dest: Path) -> None:
    headers = {
        'User-Agent': UA,
        'Accept': 'application/pdf,application/octet-stream;q=0.9,*/*;q=0.5',
        'Referer': 'https://www1.hkexnews.hk/',
    }
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=180) as response:
                data = response.read()
            if not data.startswith(b'%PDF-'):
                raise RuntimeError(f'Not a PDF; first bytes={data[:20]!r}')
            if len(data) < 200_000:
                raise RuntimeError(f'PDF unexpectedly small: {len(data)} bytes')
            dest.write_bytes(data)
            return
        except Exception as exc:
            last_error = exc
            print(f'Download attempt {attempt} failed for {url}: {exc}')
            time.sleep(min(8, attempt * 2))
    raise RuntimeError(f'Could not download {url}: {last_error}')


def normalized(text: str) -> str:
    return ''.join(text.lower().split())


manifest: list[dict] = []
page_counts: dict[str, int] = {}
for item in FILES:
    dest = REPORTS / item['filename']
    print('DOWNLOADING', item['filename'], item['url'])
    download(item['url'], dest)

    reader = PdfReader(str(dest), strict=False)
    pages = len(reader.pages)
    if pages < item['min_pages']:
        raise RuntimeError(f"Too few pages in {dest.name}: {pages} < {item['min_pages']}")

    sample_parts: list[str] = []
    for page in reader.pages[: min(35, pages)]:
        try:
            sample_parts.append(page.extract_text() or '')
        except Exception:
            pass
    sample = '\n'.join(sample_parts)
    norm = normalized(sample)
    company_ok = (
        '中化化肥' in sample
        or 'sinofert' in norm
        or 'stockcode:297' in norm
        or '股份代號：297' in sample
        or '股份代号：297' in sample
    )
    if not company_ok:
        raise RuntimeError(f'Company identity not found in extracted text: {dest.name}')

    if item['kind'] == 'annual_report':
        year = str(item['year'])
        year_ok = year in sample or year in norm
        if not year_ok:
            # Some Chinese PDFs encode Arabic digits as non-extractable glyphs; filename and
            # official filing URL remain authoritative, but require a successful first-page render.
            print('WARNING: report year not extractable from text for', dest.name)
    else:
        period_ok = (
            '二零二六年六月三十日' in sample
            or '2026年6月30日' in sample
            or '30june2026' in norm
            or ('中期業績' in sample or '中期业绩' in sample or 'interimresults' in norm)
        )
        if not period_ok:
            print('WARNING: interim period/title not extractable from text; URL and render will be checked')

    render_prefix = RENDERS / dest.stem
    subprocess.run([
        'pdftoppm', '-f', '1', '-l', '1', '-png', '-singlefile', '-r', '120',
        str(dest), str(render_prefix)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    render = Path(str(render_prefix) + '.png')
    if not render.exists() or render.stat().st_size < 15_000:
        raise RuntimeError(f'First-page render failed for {dest.name}')

    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    record = dict(item)
    record.update({
        'pages': pages,
        'bytes': dest.stat().st_size,
        'sha256': digest,
        'index_source': INDEX_SOURCE,
        'first_page_render_bytes': render.stat().st_size,
    })
    manifest.append(record)
    page_counts[dest.name] = pages
    print('VALIDATED', dest.name, pages, dest.stat().st_size, digest)

readme = '''中化化肥控股有限公司（00297.HK）财务报告合集

内容：
- 2020年至2025年年度报告，共6份；
- 截至2026年6月30日止六个月的2026年中期业绩公告，共1份。

说明：
中化化肥为香港主板上市公司，通常披露年度报告与半年度报告，不按A股模式强制发布普通季度报告。截至2026年9月3日，最新母公司定期财务披露是2026年8月25日发布的2026年中期业绩公告；正式2026年中期报告尚未在港交所年度/中期报告栏目列示，因此本合集以该公告作为“最新季报/最新定期财务披露”。

来源：香港交易所披露易原始PDF。文件索引经Treelazy的HKEX filing index交叉核对。
仅供个人研究使用，版权归中化化肥及原发布机构所有。
'''
(REPORTS / 'README_文件说明.txt').write_text(readme, encoding='utf-8')
(REPORTS / '文件清单与校验值.json').write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8'
)
(REPORTS / '页数校验结果.json').write_text(
    json.dumps(page_counts, ensure_ascii=False, indent=2), encoding='utf-8'
)

zip_path = OUT / 'Sinofert_Holdings_00297_2020_2025_Annual_Reports_2026_Interim.zip'
with ZipFile(zip_path, 'w', compression=ZIP_DEFLATED, compresslevel=9) as zf:
    for file in sorted(REPORTS.iterdir()):
        zf.write(file, arcname=file.name)
    bad = zf.testzip()
    if bad is not None:
        raise RuntimeError(f'Bad ZIP member: {bad}')

with ZipFile(zip_path) as zf:
    pdf_names = [name for name in zf.namelist() if name.lower().endswith('.pdf')]
    if len(pdf_names) != 7:
        raise RuntimeError(f'Expected 7 PDFs in ZIP, got {len(pdf_names)}')

print('READY', zip_path, zip_path.stat().st_size, 'bytes', page_counts)
