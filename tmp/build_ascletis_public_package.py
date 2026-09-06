from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import shutil
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import requests
from PIL import Image
from pypdf import PdfReader

OUT = Path('out_ascletis_public_package')
REPORTS = OUT / 'reports'
RENDERS = OUT / 'renders'
ZIP = OUT / 'ascletis_01672_reports.zip'
shutil.rmtree(OUT, ignore_errors=True)
REPORTS.mkdir(parents=True)
RENDERS.mkdir(parents=True)

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
s = requests.Session()
s.headers.update({'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'})

manifest = []


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_cover(path: Path) -> int:
    prefix = RENDERS / path.stem
    subprocess.run(['pdftoppm','-f','1','-l','1','-png','-singlefile','-r','110',str(path),str(prefix)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    png = Path(str(prefix) + '.png')
    if not png.exists() or png.stat().st_size < 10_000:
        raise RuntimeError(f'Render failed: {path.name}')
    return png.stat().st_size

# 1. Original public PDF from Hangyan CDN.
original_url = 'https://cdn.hangyan.co/documents/98/980839aeb3b9cde04c6b7c34aef205de26696bc36ac08713989fde10cddb7889.pdf'
r = s.get(original_url, timeout=90, headers={'Referer':'https://www.hangyan.co/reports/3448696034581022433','Accept':'application/pdf,*/*'})
print('ORIGINAL', r.status_code, r.headers.get('content-type'), len(r.content), r.url)
r.raise_for_status()
if not r.content.startswith(b'%PDF-') or len(r.content) < 100_000:
    raise RuntimeError('Guoyuan 2024 source is not a valid PDF')
p1 = REPORTS / '01_Guoyuan_International_2024-09-02_Ascletis_Company_Research_ORIGINAL_2p.pdf'
p1.write_bytes(r.content)
reader = PdfReader(str(p1), strict=False)
pages = len(reader.pages)
if pages != 2:
    raise RuntimeError(f'Unexpected Guoyuan 2024 page count: {pages}')
text = '\n'.join((page.extract_text() or '') for page in reader.pages)
norm = re.sub(r'\s+','',text).lower()
if not any(token in norm for token in ['歌礼制药','歌禮製藥','ascletis','1672hk','01672']):
    raise RuntimeError('Ascletis identity not found in Guoyuan 2024 PDF')
manifest.append({
    'broker':'国元国际控股','date':'2024-09-02','title':'歌礼制药-B：创新药研发推进顺利，BD合作空间广阔',
    'status':'公开原始PDF','filename':p1.name,'pages':pages,'bytes':p1.stat().st_size,'sha256':sha(p1),
    'source_page':'https://www.hangyan.co/reports/3448696034581022433','source_file':original_url,
    'cover_render_bytes':render_cover(p1),
})

# 2. The public FxBaogao viewer exposes both pages of this two-page report.
api = 'https://api.fxbaogao.com/mofoun/report/report/getReportPreviewImages?reportId=4984590'
r = s.get(api, timeout=60, headers={'Referer':'https://www.fxbaogao.com/view?id=4984590','Accept':'application/json,*/*'})
print('API', r.status_code, len(r.content), r.text[:500])
r.raise_for_status()
obj = r.json()
paths = obj.get('data') or []
if len(paths) != 2:
    raise RuntimeError(f'Expected exactly two public pages, got {len(paths)}')
images = []
image_meta = []
for idx, rel in enumerate(paths, start=1):
    url = 'https://public.fxbaogao.com/' + str(rel).lstrip('/')
    rr = s.get(url, timeout=90, headers={'Referer':'https://www.fxbaogao.com/view?id=4984590','Accept':'image/png,image/*,*/*'})
    print('IMAGE', idx, rr.status_code, rr.headers.get('content-type'), len(rr.content), rr.url)
    rr.raise_for_status()
    im = Image.open(io.BytesIO(rr.content))
    im.load()
    if im.width < 800 or im.height < 1000:
        raise RuntimeError(f'Public page image is too small: {im.size}')
    rgb = im.convert('RGB')
    images.append(rgb)
    image_meta.append({'page':idx,'url':url,'width':im.width,'height':im.height,'bytes':len(rr.content),'sha256':hashlib.sha256(rr.content).hexdigest()})

p2 = REPORTS / '02_Guoyuan_International_2025-08-06_ASC30_Phase_IIa_PUBLIC_PAGES_MERGED_2p.pdf'
images[0].save(p2, 'PDF', resolution=150.0, save_all=True, append_images=images[1:])
reader = PdfReader(str(p2), strict=False)
pages = len(reader.pages)
if pages != 2:
    raise RuntimeError(f'Unexpected merged PDF page count: {pages}')
manifest.append({
    'broker':'国元国际控股','date':'2025-08-06','title':'ASC30美国IIa期完成患者入组，将于Q4读出数据',
    'status':'公开阅读页逐页合并版（完整2页，非券商原始二进制）','filename':p2.name,'pages':pages,'bytes':p2.stat().st_size,'sha256':sha(p2),
    'source_page':'https://www.fxbaogao.com/detail/4984590','source_file':api,
    'public_page_images':json.dumps(image_meta, ensure_ascii=False),'cover_render_bytes':render_cover(p2),
})

readme = '''歌礼制药-B（01672.HK）券商公司研究报告包

本包包含两项不同日期、完整可阅读的券商公司研究内容：
1. 国元国际控股，2024-09-02，2页，公开原始PDF：
   《歌礼制药-B：创新药研发推进顺利，BD合作空间广阔》。
2. 国元国际控股，2025-08-06，2页：
   《ASC30美国IIa期完成患者入组，将于Q4读出数据》。
   该报告的公开阅读接口完整提供两页，本包按原页面逐页合并为PDF；
   它不是券商服务器的原始二进制文件，文件名和清单已明确标注。

重要范围说明：
- 东吴证券2025-04-01的19页首次覆盖深度报告，以及东方证券2025-12-28的首次覆盖报告，
  公开检索页面可以核验标题、页数与主要内容，但完整附件当前处于登录或会员入口。
- 本包没有绕过访问控制，也没有用两页预览冒充上述长篇报告全文。
- 因此本包更准确地说是两份完整券商“公司研究/即时点评”，而不是两份20页以上长篇深度报告。

校验项目：PDF文件签名、页数、公司身份（原始PDF）、公开页数量、首页渲染、SHA-256和ZIP完整性。
仅供个人研究使用，版权归原券商及发布机构所有。
'''
(REPORTS/'README.txt').write_text(readme, encoding='utf-8')
(REPORTS/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
with (REPORTS/'manifest.csv').open('w', encoding='utf-8-sig', newline='') as f:
    columns=sorted({k for row in manifest for k in row})
    w=csv.DictWriter(f, fieldnames=columns); w.writeheader(); w.writerows(manifest)

with ZipFile(ZIP,'w',ZIP_DEFLATED,compresslevel=9) as zf:
    for p in sorted(REPORTS.iterdir(), key=lambda x:x.name): zf.write(p,p.name)
with ZipFile(ZIP) as zf:
    bad=zf.testzip()
    if bad is not None: raise RuntimeError(f'ZIP integrity failure: {bad}')
    if len([n for n in zf.namelist() if n.lower().endswith('.pdf')]) != 2: raise RuntimeError('PDF count mismatch')
print('PACKAGE_READY', ZIP, ZIP.stat().st_size)
print(json.dumps(manifest,ensure_ascii=False,indent=2))
