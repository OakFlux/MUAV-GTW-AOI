from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from pypdf import PdfReader

OUT = Path('out_qunabox_full_reports_v2')
RAW = OUT / 'raw_pdfs'
PACKAGE = OUT / 'package'
RENDERS = OUT / 'renders'
FINAL = OUT / 'Qunabox_00917_Broker_Deep_Research_Reports.zip'
PACKAGE.mkdir(parents=True, exist_ok=True)
RENDERS.mkdir(parents=True, exist_ok=True)

fetch_manifest_path = OUT / 'fetch_manifest.json'
fetch_manifest = json.loads(fetch_manifest_path.read_text(encoding='utf-8')) if fetch_manifest_path.exists() else []
meta_by_name = {x.get('fileName'): x for x in fetch_manifest if isinstance(x, dict)}


def norm(text: str) -> str:
    return re.sub(r'[^a-z0-9\u4e00-\u9fff]+', '', unicodedata.normalize('NFKC', text).lower())


def extract_text(reader: PdfReader) -> str:
    pages = len(reader.pages)
    indices = list(range(min(pages, 12)))
    if pages > 15:
        indices += [pages // 2, pages - 2, pages - 1]
    parts = []
    for i in sorted(set(x for x in indices if 0 <= x < pages)):
        try:
            parts.append(reader.pages[i].extract_text() or '')
        except Exception:
            pass
    return '\n'.join(parts)


def identify(text: str, hint: dict) -> tuple[str, str, str, str]:
    compact = norm(text)
    broker = hint.get('brokerHint') or ''
    date = hint.get('dateHint') or ''
    title = hint.get('titleHint') or ''
    language = '中文'

    if 'westbull' in compact or '西牛证券' in text or '西牛證券' in text:
        broker = '西牛证券'
    elif '中银国际证券' in text or '中銀國際證券' in text or '中银证券' in text or '中銀證券' in text:
        broker = '中银证券'
    elif '华源证券' in text or '華源證券' in text:
        broker = '华源证券'
    elif '申万宏源' in text or '申萬宏源' in text:
        broker = '申万宏源'

    # Dates from the cover pages.
    for pat in [
        r'(20\d{2})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})\s*日?',
        r'(\d{1,2})\s+(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z, ]*(20\d{2})',
    ]:
        m = re.search(pat, text[:12000], re.I)
        if m:
            if len(m.groups()) == 3 and m.group(2).isalpha():
                months = {'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}
                date = f"{int(m.group(3)):04d}-{months[m.group(2).upper()]:02d}-{int(m.group(1)):02d}"
            else:
                date = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            break

    title_map = [
        ('存量终端迈入ai变现周期高毛利业务有望获得重估', '存量终端迈入AI变现周期，高毛利业务有望获得重估'),
        ('legacyterminalbaseentersaimonetisationcycle', 'Legacy Terminal Base Enters AI Monetisation Cycle; High-Margin Segment Poised for Re-Rating'),
        ('ai互动营销领导者公司业绩高速增长', 'AI互动营销领导者，公司业绩高速增长'),
        ('深耕ka客户加速出海中东', '深耕KA客户，加速出海中东'),
        ('物理ai构建营销闭环', '物理AI构建营销闭环'),
        ('ai营销加速放量物理ai有望打开第二增长曲线', 'AI营销加速放量，物理AI有望打开第二增长曲线'),
    ]
    for token, canonical in title_map:
        if token in compact:
            title = canonical
            break

    if re.search(r'\bQunabox\b|RESEARCH|INITIATION', text[:10000], re.I) and not re.search(r'[趣致集團]', text[:10000]):
        language = '英文'
    return broker, date, title, language


def report_key(broker: str, title: str, text: str) -> str:
    t = norm(title)
    # Treat West Bull Chinese and English editions as the same report.
    if '存量终端迈入ai变现周期' in t or 'legacyterminalbaseentersaimonetisationcycle' in t:
        return 'westbull_2026_08_24_initiation'
    if 'ai互动营销领导者公司业绩高速增长' in t:
        return 'boci_2025_01_15_initiation'
    if '深耕ka客户加速出海中东' in t:
        return 'shenwan_2026_03_12_initiation'
    if '物理ai构建营销闭环' in t:
        return 'huayuan_2026_07_29_initiation'
    if 'ai营销加速放量物理ai有望打开第二增长曲线' in t:
        return 'huayuan_2026_08_26_update'
    # Stable fallback uses broker, date and the first substantial cover line.
    cover_lines = [re.sub(r'\s+', ' ', line).strip() for line in text[:15000].splitlines()]
    cover_lines = [line for line in cover_lines if 8 <= len(line) <= 120]
    return norm(f'{broker}|{title}|{cover_lines[0] if cover_lines else "unknown"}')[:180]


valid = []
for pdf in sorted(RAW.glob('*.pdf')):
    try:
        if pdf.read_bytes()[:5] != b'%PDF-':
            continue
        reader = PdfReader(str(pdf), strict=False)
        pages = len(reader.pages)
        if pages < 3:
            continue
        text = extract_text(reader)
        compact = norm(text)
        if not any(x in compact for x in ['趣致集团','趣致集團','qunabox','00917','0917hk']):
            continue
        hint = meta_by_name.get(pdf.name, {})
        broker, date, title, language = identify(text, hint)
        key = report_key(broker, title, text)
        sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
        # Rendering provides a final structural/readability check.
        rendered = []
        for page_no in sorted(set([1, max(1, (pages + 1)//2), pages])):
            prefix = RENDERS / f'{pdf.stem}_p{page_no}'
            subprocess.run(['pdftoppm','-f',str(page_no),'-l',str(page_no),'-png','-singlefile','-r','80',str(pdf),str(prefix)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            png = Path(str(prefix)+'.png')
            if not png.exists() or png.stat().st_size < 5000:
                raise RuntimeError(f'render failed {pdf.name} page {page_no}')
            rendered.append(png.name)
        valid.append({
            'source_path': str(pdf), 'source_name': pdf.name, 'pages': pages, 'bytes': pdf.stat().st_size,
            'sha256': sha, 'broker': broker or '未知券商', 'date': date or '日期待核验',
            'title': title or '趣致集团公司研究报告', 'language': language, 'report_key': key,
            'source_url': hint.get('url',''), 'rendered_pages': rendered,
        })
        print('VALID', json.dumps(valid[-1], ensure_ascii=False))
    except Exception as exc:
        print('REJECT', pdf.name, repr(exc))

# Keep one best file per distinct research report. Prefer Chinese and more pages.
by_report = {}
for item in valid:
    current = by_report.get(item['report_key'])
    score = (1 if item['language']=='中文' else 0, item['pages'], item['bytes'])
    current_score = (-1,-1,-1) if current is None else (1 if current['language']=='中文' else 0, current['pages'], current['bytes'])
    if current is None or score > current_score:
        by_report[item['report_key']] = item

distinct = list(by_report.values())
# Prefer full initiation/deep reports, then recent complete updates.
def priority(item):
    t = norm(item['title'])
    deep = 200 if item['pages'] >= 15 else 0
    initiation = 200 if any(x in t for x in ['首次覆盖','互动营销领导者','存量终端迈入ai','物理ai构建营销闭环','深耕ka客户']) else 0
    return (deep + initiation, item['date'], item['pages'])

distinct.sort(key=priority, reverse=True)
selected = distinct[:3]
if len(selected) < 2:
    raise RuntimeError(f'Only {len(selected)} distinct complete Qunabox broker report(s) were found; refusing to package duplicate-language editions as separate reports.')

manifest = []
for i, item in enumerate(selected, 1):
    broker_en = {'西牛证券':'WestBull','中银证券':'BOCI','华源证券':'Huayuan','申万宏源':'Shenwan'}.get(item['broker'],'Broker')
    date_safe = re.sub(r'[^0-9-]+','',item['date']) or 'undated'
    filename = f'{i:02d}_{broker_en}_{date_safe}_Qunabox_00917_{item["pages"]}p.pdf'
    dest = PACKAGE / filename
    shutil.copy2(item['source_path'], dest)
    manifest.append({
        'index': i, 'broker': item['broker'], 'date': item['date'], 'title': item['title'],
        'pages': item['pages'], 'language': item['language'], 'filename': filename,
        'bytes': dest.stat().st_size, 'sha256': item['sha256'], 'source_url': item['source_url'],
    })

readme = ['趣致集团（00917.HK）券商深度/公司研究报告合集','',f'本包收录{len(manifest)}份不同报告的完整PDF，不以中英文重复版本凑数。','']
for x in manifest:
    readme.append(f"{x['index']}. {x['broker']}｜{x['date']}｜{x['pages']}页｜{x['title']}")
readme += ['','校验项目：PDF文件签名、趣致集团/00917公司身份、实际页数、首/中/末页渲染、SHA-256及ZIP完整性。','所有文件均从无需登录即可访问的公开页面或券商官网取得；未绕过登录、会员或付费限制。']
(PACKAGE/'README_文件说明.txt').write_text('\n'.join(readme),encoding='utf-8')
(PACKAGE/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
with (PACKAGE/'manifest.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(manifest[0].keys()));w.writeheader();w.writerows(manifest)

with ZipFile(FINAL,'w',ZIP_DEFLATED,compresslevel=9) as z:
    for p in sorted(PACKAGE.iterdir(),key=lambda x:x.name): z.write(p,p.name)
with ZipFile(FINAL) as z:
    if z.testzip() is not None: raise RuntimeError('ZIP integrity failure')
    if len([n for n in z.namelist() if n.lower().endswith('.pdf')]) != len(manifest): raise RuntimeError('PDF count mismatch')

(OUT/'all_validated.json').write_text(json.dumps(valid,ensure_ascii=False,indent=2),encoding='utf-8')
print('PACKAGE_READY', FINAL, FINAL.stat().st_size)
print(json.dumps(manifest,ensure_ascii=False,indent=2))
