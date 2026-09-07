from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import requests
from pypdf import PdfReader

OUT = Path('out_cgnne_eastmoney_20260907')
PDFS = OUT / 'pdfs'
PACKAGE = OUT / 'package'
RENDERS = OUT / 'renders'
for d in (PDFS, PACKAGE, RENDERS):
    d.mkdir(parents=True, exist_ok=True)

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36',
    'Referer': 'https://data.eastmoney.com/report/stock.jshtml',
    'Accept': 'application/json,text/plain,*/*',
})

list_url = 'https://reportapi.eastmoney.com/report/list'
list2_url = 'https://reportapi.eastmoney.com/report/list2'
keywords = ['中广核新能源', '中廣核新能源', 'CGN New Energy', '01811', '1811.HK', '1811 HK']
matched: dict[str, dict] = {}
logs = []


def add_rows(source: str, rows: list[dict]) -> None:
    for row in rows:
        blob = json.dumps(row, ensure_ascii=False).lower()
        if any(k.lower() in blob for k in keywords):
            key = str(row.get('infoCode') or row.get('encodeUrl') or row.get('id') or hashlib.sha256(blob.encode()).hexdigest())
            matched[key] = row
            print('MATCH', source, json.dumps(row, ensure_ascii=False))


# Targeted GET endpoint, including common HK code forms.
for code in ['01811', '1811', 'HK01811', '01811.HK', '1811.HK', '116.01811', '116.1811']:
    params = {
        'code': code,
        'pageSize': 5000,
        'pageNo': 1,
        'beginTime': '2018-01-01',
        'endTime': '2026-09-07',
        'qType': 0,
        'fields': '',
        'industryCode': '*',
        'industry': '*',
        'rating': '*',
        'ratingChange': '*',
        'orgCode': '',
        'rcode': '',
        'p': 1,
        'pageNum': 1,
        'pageNumber': 1,
    }
    try:
        r = session.get(list_url, params=params, timeout=90)
        obj = r.json()
        rows = obj.get('data') or [] if isinstance(obj, dict) else []
        print('GET_CODE', code, r.status_code, len(rows), {k: obj.get(k) for k in ('TotalPage','TotalCount','hits') if isinstance(obj,dict)})
        logs.append({'source':'get_code','code':code,'status':r.status_code,'rows':len(rows),'meta':{k: obj.get(k) for k in ('TotalPage','TotalCount','hits') if isinstance(obj,dict)}})
        add_rows(f'get:{code}', rows)
    except Exception as exc:
        print('GET_CODE_ERROR', code, repr(exc))

# Targeted POST endpoint.
for code in ['01811', '1811', 'HK01811', '01811.HK', '1811.HK', '116.01811', '*']:
    body = {
        'pageSize': 5000,
        'pageNo': 1,
        'p': 1,
        'pageNum': 1,
        'pageNumber': 1,
        'beginTime': '2018-01-01',
        'endTime': '2026-09-07',
        'code': code,
        'industryCode': '*',
        'rating': None,
        'ratingChange': None,
        'orgCode': None,
        'rcode': '',
    }
    try:
        r = session.post(list2_url, json=body, timeout=90)
        obj = r.json()
        rows = obj.get('data') or [] if isinstance(obj, dict) else []
        print('POST_CODE', code, r.status_code, len(rows), {k: obj.get(k) for k in ('TotalPage','TotalCount','hits') if isinstance(obj,dict)})
        logs.append({'source':'post_code','code':code,'status':r.status_code,'rows':len(rows),'meta':{k: obj.get(k) for k in ('TotalPage','TotalCount','hits') if isinstance(obj,dict)}})
        add_rows(f'post:{code}', rows)
    except Exception as exc:
        print('POST_CODE_ERROR', code, repr(exc))

# Search recent pages globally. This catches HK reports when code filters are ignored.
base = {
    'pageSize': 100,
    'beginTime': '2020-01-01',
    'endTime': '2026-09-07',
    'qType': 0,
    'fields': '',
    'industryCode': '*',
    'industry': '*',
    'rating': '*',
    'ratingChange': '*',
    'orgCode': '',
    'code': '',
    'rcode': '',
}
try:
    p = dict(base, pageNo=1, p=1, pageNum=1, pageNumber=1)
    first = session.get(list_url, params=p, timeout=90).json()
    total_pages = int(first.get('TotalPage') or 1)
except Exception:
    total_pages = 1
print('GLOBAL_TOTAL_PAGES', total_pages)
# Avoid excessive runtime: the API sorts newest-first; traverse all only if manageable, else first 250 pages.
for page in range(1, min(total_pages, 250) + 1):
    params = dict(base, pageNo=page, p=page, pageNum=page, pageNumber=page)
    try:
        r = session.get(list_url, params=params, timeout=60)
        obj = r.json()
        rows = obj.get('data') or []
        if page == 1 or page % 25 == 0:
            print('GLOBAL_PAGE', page, len(rows))
        add_rows(f'global:{page}', rows)
    except Exception as exc:
        print('GLOBAL_ERROR', page, repr(exc))

(OUT / 'api_probe_log.json').write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding='utf-8')
(OUT / 'matches.json').write_text(json.dumps(list(matched.values()), ensure_ascii=False, indent=2), encoding='utf-8')

valid = []
seen_hashes = set()
for idx, (key, row) in enumerate(matched.items(), 1):
    info = row.get('infoCode') or row.get('INFO_CODE')
    direct_urls = []
    if info:
        direct_urls += [
            f'https://pdf.dfcfw.com/pdf/H3_{info}_1.pdf',
            f'https://pdf.dfcfw.com/pdf/H3_{info}.pdf',
        ]
    for value in row.values():
        if isinstance(value, str) and value.startswith('http') and ('.pdf' in value.lower() or 'download' in value.lower()):
            direct_urls.append(value)
    for url in dict.fromkeys(direct_urls):
        try:
            r = session.get(url, timeout=120, headers={'Accept':'application/pdf,*/*','Referer':'https://data.eastmoney.com/'})
            print('PDF_PROBE', r.status_code, r.headers.get('content-type'), len(r.content), url)
            if r.status_code != 200 or len(r.content) < 30000 or not r.content.startswith(b'%PDF-'):
                continue
            digest = hashlib.sha256(r.content).hexdigest()
            if digest in seen_hashes:
                break
            path = PDFS / f'{idx:02d}_{info or key}_{digest[:12]}.pdf'
            path.write_bytes(r.content)
            reader = PdfReader(str(path), strict=False)
            pages = len(reader.pages)
            indices = list(range(min(15, pages)))
            if pages > 20:
                indices.extend([pages // 2, pages - 1])
            text = '\n'.join((reader.pages[i].extract_text() or '') for i in sorted(set(indices)))
            normalized = re.sub(r'\s+', '', text).lower()
            identity = any(x in normalized for x in ['中广核新能源','中廣核新能源','cgnnewenergy','01811','1811.hk'])
            if not identity or pages < 2:
                path.unlink(missing_ok=True)
                continue
            seen_hashes.add(digest)
            item = {'path':str(path),'pages':pages,'bytes':len(r.content),'sha256':digest,'url':url,'row':row,'text':text[:5000]}
            valid.append(item)
            print('VALID_PDF', pages, row.get('orgSName'), row.get('publishDate'), row.get('title'))
            break
        except Exception as exc:
            print('PDF_ERROR', url, repr(exc))

(OUT / 'valid.json').write_text(json.dumps(valid, ensure_ascii=False, indent=2), encoding='utf-8')

# Select up to three longest reports, favoring title indications of first coverage/deep research.
def score(item: dict) -> tuple:
    row = item['row']
    title = str(row.get('title') or '')
    deep = 1 if re.search(r'首次|深度|initi', title, re.I) else 0
    date = str(row.get('publishDate') or '')
    return (deep, item['pages'], date)

selected = sorted(valid, key=score, reverse=True)[:3]
if len(selected) < 2:
    raise RuntimeError(f'Only {len(selected)} usable Eastmoney PDFs found')

manifest = []
for index, item in enumerate(selected, 1):
    row = item['row']
    broker = str(row.get('orgSName') or row.get('orgName') or '券商')
    date = str(row.get('publishDate') or '')[:10]
    title = str(row.get('title') or '中广核新能源公司研究')
    safe = re.sub(r'[^A-Za-z0-9_-]+', '_', broker)[:40]
    destination = PACKAGE / f'{index:02d}_{date}_{safe}_CGN_New_Energy_{item["pages"]}p.pdf'
    shutil.copy2(item['path'], destination)
    for page_number in sorted({1, max(1,(item['pages']+1)//2), item['pages']}):
        prefix = RENDERS / f'r{index}_p{page_number}'
        subprocess.run(['pdftoppm','-f',str(page_number),'-l',str(page_number),'-png','-singlefile','-r','90',str(destination),str(prefix)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        png = Path(str(prefix)+'.png')
        if not png.exists() or png.stat().st_size < 8000:
            raise RuntimeError(f'Render failed: {destination.name} p{page_number}')
    manifest.append({'序号':index,'券商':broker,'发布日期':date,'报告标题':title,'实际页数':item['pages'],'文件名':destination.name,'SHA256':item['sha256'],'原始PDF地址':item['url']})

readme = ['中广核新能源（01811.HK）券商研究报告合集','',f'本包收录{len(manifest)}份实际PDF，不含网页快捷方式或预览图片。','', '文件清单：']
for row in manifest:
    readme.append(f"{row['序号']}. {row['券商']}｜{row['发布日期']}｜{row['实际页数']}页｜{row['报告标题']}")
readme += ['', '已检查PDF签名、公司身份、页数、SHA-256、首中末页渲染及ZIP完整性。']
(PACKAGE/'README.txt').write_text('\n'.join(readme),encoding='utf-8')
(PACKAGE/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
with (PACKAGE/'manifest.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(manifest[0].keys())); w.writeheader(); w.writerows(manifest)

final = OUT/'CGN_New_Energy_01811_Eastmoney_Reports.zip'
with ZipFile(final,'w',ZIP_DEFLATED,compresslevel=9) as zf:
    for p in sorted(PACKAGE.iterdir()): zf.write(p,p.name)
with ZipFile(final) as zf:
    bad=zf.testzip()
    if bad: raise RuntimeError(bad)
print('PACKAGE_READY', final, final.stat().st_size)
print(json.dumps(manifest,ensure_ascii=False,indent=2))
