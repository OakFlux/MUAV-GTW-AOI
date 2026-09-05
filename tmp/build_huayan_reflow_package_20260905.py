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
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
from bs4 import BeautifulSoup
from PIL import Image
from pypdf import PdfReader
from weasyprint import HTML

OUT = Path('out_huayan_reflow_package')
REPORTS_DIR = OUT / 'reports'
RENDERS_DIR = OUT / 'renders'
FINAL_ZIP = OUT / 'Huayan_Robotics_01021_Broker_Research_Reports_3.zip'
shutil.rmtree(OUT, ignore_errors=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
RENDERS_DIR.mkdir(parents=True, exist_ok=True)

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
client = httpx.Client(
    http2=True,
    follow_redirects=True,
    timeout=httpx.Timeout(120.0, connect=30.0),
    headers={
        'User-Agent': UA,
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    },
)

REPORTS = [
    {
        'id': '5587624',
        'date': '2026-08-07',
        'broker': '交银国际',
        'analysts': '陈庆、李柳晓',
        'title': '人形机器人行业系列（4）：“卖铲人”型平台公司，运动控制底层价值有望重估',
        'report_type': '首次覆盖 / 公司深度',
        'source_url': 'https://www.fxbaogao.com/detail/5587624',
        'filename': '01_交银国际_2026-08-07_华沿机器人_卖铲人型平台公司_首次覆盖深度_公开全文重排版.pdf',
        'minimum_chars': 28000,
        'minimum_pdf_pages': 18,
        'required_terms': ['华沿机器人', '核心运动部件', '目标价HK$23.13', '投资概要', '免责声明'],
    },
    {
        'id': '5435007',
        'date': '2026-05-24',
        'broker': '兴证国际',
        'analysts': '余小丽、张忠业',
        'title': '头部协作机器人公司，七轴人形手臂放量可期',
        'report_type': '首次覆盖 / 公司深度',
        'source_url': 'https://www.fxbaogao.com/detail/5435007',
        'filename': '02_兴证国际_2026-05-24_华沿机器人_七轴人形手臂放量可期_首次覆盖深度_公开全文重排版.pdf',
        'minimum_chars': 12000,
        'minimum_pdf_pages': 8,
        'required_terms': ['华沿机器人', '七轴人形手臂', '首次覆盖', '风险提示', '免责声明'],
    },
    {
        'id': '5497229',
        'date': '2026-06-26',
        'broker': '国泰海通证券',
        'analysts': '肖群稀、刘麒硕',
        'title': '协作机器人头部企业，具身智能空间广阔',
        'report_type': '首次覆盖 / 公司研究',
        'source_url': 'https://www.fxbaogao.com/detail/5497229',
        'filename': '03_国泰海通证券_2026-06-26_华沿机器人_具身智能空间广阔_首次覆盖_公开全文重排版.pdf',
        'minimum_chars': 6500,
        'minimum_pdf_pages': 4,
        'required_terms': ['华沿机器人', '具身智能空间广阔', '盈利预测与估值', '分析师声明', '免责声明'],
    },
]


def fetch_html(url: str) -> str:
    last_error = None
    for attempt in range(1, 6):
        try:
            response = client.get(url, headers={'Referer': 'https://www.fxbaogao.com/'})
            response.raise_for_status()
            if len(response.content) < 30000:
                raise RuntimeError(f'HTML too small: {len(response.content)}')
            return response.text
        except Exception as exc:
            last_error = exc
            print('FETCH_RETRY', attempt, url, repr(exc))
            time.sleep(attempt * 2)
    raise RuntimeError(f'Unable to fetch {url}: {last_error}')


def normalize_text(text: str) -> str:
    text = html_lib.unescape(text)
    text = text.replace('\u00a0', ' ').replace('\u200b', '').replace('\ufeff', '')
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # Preserve line structure while removing excessive blank lines and horizontal spacing.
    lines = []
    for raw_line in text.splitlines():
        line = re.sub(r'[ \t]+', ' ', raw_line).strip()
        if line:
            lines.append(line)
        elif lines and lines[-1] != '':
            lines.append('')
    cleaned = '\n'.join(lines).strip()
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned


def extract_report_text(page_html: str, report: dict) -> tuple[str, dict]:
    soup = BeautifulSoup(page_html, 'html.parser')
    candidates = []
    for node in soup.find_all(['p', 'div']):
        text = normalize_text(node.get_text('\n', strip=False))
        if '华沿机器人' not in text and '華沿機器人' not in text:
            continue
        score = len(text)
        if any(term in text for term in report['required_terms']):
            score += 10000
        if '免责声明' in text or '免責聲明' in text:
            score += 10000
        if '分析师' in text or '分析師' in text:
            score += 3000
        candidates.append((score, len(text), text, node.name, ' '.join(node.get('class', []))))
    if not candidates:
        raise RuntimeError(f'No report-text candidate found for {report["id"]}')
    candidates.sort(reverse=True, key=lambda x: (x[0], x[1]))
    _, length, text, tag, cls = candidates[0]

    # Some container nodes repeat the same report text through nested children. Detect repeated halves.
    midpoint = len(text) // 2
    if len(text) > report['minimum_chars'] * 2:
        first = text[:midpoint]
        second = text[midpoint:]
        prefix = text[: min(1200, len(text))]
        if second.find(prefix[:300]) >= 0:
            repeat_at = text.find(prefix[:600], 1000)
            if repeat_at > report['minimum_chars']:
                text = text[:repeat_at].rstrip()

    meta = {
        'candidate_count': len(candidates),
        'selected_tag': tag,
        'selected_class': cls,
        'selected_chars': len(text),
        'top_candidate_lengths': [item[1] for item in candidates[:10]],
    }
    return text, meta


def validate_source_text(text: str, report: dict) -> dict:
    if len(text) < report['minimum_chars']:
        raise RuntimeError(f'Report text too short for {report["id"]}: {len(text)} < {report["minimum_chars"]}')
    missing = [term for term in report['required_terms'] if term not in text]
    if missing:
        raise RuntimeError(f'Missing completeness markers for {report["id"]}: {missing}')
    denominators = [int(x) for x in re.findall(r'\b\d+\s*/\s*(\d{1,3})\b', text)]
    return {
        'text_chars': len(text),
        'text_lines': len(text.splitlines()),
        'page_number_hints': sorted(set(denominators)),
        'text_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
    }


def html_document(report: dict, text: str) -> str:
    paragraphs = []
    for block in re.split(r'\n\s*\n', text):
        block = block.strip()
        if not block:
            continue
        escaped = html_lib.escape(block).replace('\n', '<br>')
        cls = 'body'
        if len(block) <= 80 and any(k in block for k in ['目录', '投资概要', '核心逻辑', '风险提示', '盈利预测', '公司简介', '免责声明', '分析师声明', '评级说明']):
            cls = 'section'
        paragraphs.append(f'<p class="{cls}">{escaped}</p>')
    body = '\n'.join(paragraphs)
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 18mm 17mm 18mm 17mm;
  @bottom-center {{ content: "华沿机器人（01021.HK）券商研究报告 - 公开全文重排版  |  " counter(page); font-size: 8pt; color: #777; }}
}}
html {{ font-family: "Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC", sans-serif; color:#111; }}
body {{ font-size: 9.6pt; line-height: 1.55; }}
h1 {{ font-size: 20pt; line-height:1.3; margin: 0 0 8mm; }}
.meta {{ border-top: 1px solid #999; border-bottom:1px solid #999; padding: 4mm 0; margin-bottom:5mm; font-size:9pt; }}
.notice {{ background:#f3f3f3; border-left:3px solid #777; padding:3mm 4mm; margin:0 0 7mm; font-size:8.6pt; color:#444; }}
p.body {{ margin: 0 0 3.2mm; text-align: justify; word-break: break-all; }}
p.section {{ font-weight:700; font-size:12pt; margin:6mm 0 3mm; break-after:avoid; }}
</style></head><body>
<h1>{html_lib.escape(report['title'])}</h1>
<div class="meta">机构：{html_lib.escape(report['broker'])}<br>日期：{report['date']}<br>分析师：{html_lib.escape(report['analysts'])}<br>类型：{html_lib.escape(report['report_type'])}</div>
<div class="notice">说明：原始券商PDF未提供无需登录的公开直链。以下内容取自报告平台向访客公开展示的完整正文，按原文顺序重排为可检索PDF；文字内容保留，原始图表、分页、字体及版式可能与券商原版不同。</div>
{body}
</body></html>'''


def create_pdf(report: dict, text: str) -> Path:
    destination = REPORTS_DIR / report['filename']
    HTML(string=html_document(report, text), base_url='.').write_pdf(destination)
    return destination


def validate_pdf(pdf_path: Path, report: dict, source_text: str) -> dict:
    with pdf_path.open('rb') as handle:
        if handle.read(5) != b'%PDF-':
            raise RuntimeError(f'Invalid PDF signature: {pdf_path.name}')
    subprocess.run(['qpdf', '--check', str(pdf_path)], check=True, capture_output=True, text=True)
    reader = PdfReader(str(pdf_path), strict=False)
    pages = len(reader.pages)
    if pages < report['minimum_pdf_pages']:
        raise RuntimeError(f'Reflow PDF unexpectedly short: {pdf_path.name}: {pages} pages')

    text_path = OUT / f'{report["id"]}_pdftotext.txt'
    subprocess.run(['pdftotext', '-layout', str(pdf_path), str(text_path)], check=True)
    extracted = text_path.read_text(encoding='utf-8', errors='ignore')
    compact_source = re.sub(r'\s+', '', source_text)
    compact_extracted = re.sub(r'\s+', '', extracted)
    if len(compact_extracted) < int(len(compact_source) * 0.80):
        raise RuntimeError(f'PDF text coverage too low for {report["id"]}: {len(compact_extracted)}/{len(compact_source)}')
    for term in report['required_terms']:
        if re.sub(r'\s+', '', term) not in compact_extracted:
            raise RuntimeError(f'PDF missing required term {term!r}: {pdf_path.name}')

    render_checks = []
    for page_number in sorted(set([1, max(1, pages // 2), pages])):
        prefix = RENDERS_DIR / f'{report["id"]}_p{page_number}'
        subprocess.run([
            'pdftoppm', '-f', str(page_number), '-l', str(page_number), '-png', '-singlefile', '-r', '110',
            str(pdf_path), str(prefix)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        image_path = Path(str(prefix) + '.png')
        if not image_path.exists() or image_path.stat().st_size < 12000:
            raise RuntimeError(f'Render validation failed: {pdf_path.name}, page {page_number}')
        with Image.open(image_path) as image:
            image.verify()
        render_checks.append({'page': page_number, 'bytes': image_path.stat().st_size})

    return {
        'pdf_pages': pages,
        'pdf_bytes': pdf_path.stat().st_size,
        'pdf_sha256': hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        'pdftotext_chars': len(extracted),
        'render_checks': render_checks,
    }


manifest = []
for report in REPORTS:
    print('START', report['id'], report['title'])
    page_html = fetch_html(report['source_url'])
    (OUT / f'{report["id"]}.html').write_text(page_html, encoding='utf-8')
    text, extraction_meta = extract_report_text(page_html, report)
    (OUT / f'{report["id"]}_source_text.txt').write_text(text, encoding='utf-8')
    text_meta = validate_source_text(text, report)
    print('TEXT_META', report['id'], json.dumps({**extraction_meta, **text_meta}, ensure_ascii=False))
    pdf_path = create_pdf(report, text)
    pdf_meta = validate_pdf(pdf_path, report, text)
    item = {
        'company': '广东华沿机器人股份有限公司',
        'stock_code': '01021.HK',
        'report_id': report['id'],
        'broker': report['broker'],
        'date': report['date'],
        'analysts': report['analysts'],
        'title': report['title'],
        'report_type': report['report_type'],
        'edition': '公开网页完整正文重排版（非券商原始版式PDF）',
        'filename': pdf_path.name,
        'source_url': report['source_url'],
        **extraction_meta,
        **text_meta,
        **pdf_meta,
    }
    manifest.append(item)
    print('READY', report['id'], pdf_meta['pdf_pages'], pdf_meta['pdf_bytes'])

readme = '''华沿机器人（01021.HK）券商研究报告合集

本包收录3份券商首次覆盖/公司研究报告：交银国际、兴证国际、国泰海通证券各1份。

重要说明：相关平台仅公开展示报告正文及少量预览页，原始券商PDF下载需要登录或未提供公开直链。为避免把两页预览版冒充完整报告，本包从公开详情页提取完整正文，按照原文顺序重排为可检索PDF。文字内容完整性已通过报告标题、核心章节、风险提示、分析师声明/免责声明及正文长度等标志校验；但原始图表、分页、字体和版式可能与券商原版不同。

校验项目：HTML正文长度与完整性标志、PDF文件签名、qpdf结构检查、可提取文本覆盖率、实际页数、首/中/末页渲染及ZIP完整性。

文件仅供个人研究使用，报告版权归相应证券研究机构所有。
'''
(REPORTS_DIR / 'README_文件说明.txt').write_text(readme, encoding='utf-8')
(REPORTS_DIR / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
columns = ['broker','date','analysts','title','report_type','edition','filename','pdf_pages','pdf_bytes','pdf_sha256','text_chars','pdftotext_chars','source_url']
with (REPORTS_DIR / 'manifest.csv').open('w', encoding='utf-8-sig', newline='') as handle:
    writer = csv.DictWriter(handle, fieldnames=columns)
    writer.writeheader()
    for item in manifest:
        writer.writerow({key:item.get(key,'') for key in columns})

with ZipFile(FINAL_ZIP, 'w', compression=ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(REPORTS_DIR.iterdir(), key=lambda p:p.name):
        archive.write(path, arcname=path.name)
with ZipFile(FINAL_ZIP) as archive:
    bad = archive.testzip()
    if bad is not None:
        raise RuntimeError(f'ZIP integrity failure: {bad}')
    pdfs = [name for name in archive.namelist() if name.lower().endswith('.pdf')]
    if len(pdfs) != 3:
        raise RuntimeError(f'ZIP PDF count mismatch: {len(pdfs)}')

print('PACKAGE_READY', FINAL_ZIP, FINAL_ZIP.stat().st_size)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
client.close()
