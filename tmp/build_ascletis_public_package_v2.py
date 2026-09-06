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

OUT = Path('out_ascletis_public_package_v2')
REPORTS = OUT / 'reports'
RENDERS = OUT / 'renders'
ZIP = OUT / 'ascletis_01672_reports_v2.zip'
shutil.rmtree(OUT, ignore_errors=True)
REPORTS.mkdir(parents=True)
RENDERS.mkdir(parents=True)

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
s = requests.Session()
s.headers.update({'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'})
manifest = []

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def render_all(path: Path) -> list[dict]:
    out = RENDERS / path.stem
    out.mkdir()
    subprocess.run(['pdftoppm','-png','-r','130',str(path),str(out/'page')], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    rows=[]
    for image in sorted(out.glob('page-*.png')):
        im=Image.open(image).convert('RGB')
        # A near-black rendered page indicates failed alpha compositing.
        thumb=im.resize((20,20))
        avg=sum(sum(pixel) for pixel in thumb.getdata())/(20*20*3)
        if avg < 80:
            raise RuntimeError(f'Rendered page is unexpectedly dark: {path.name} {image.name} avg={avg:.1f}')
        rows.append({'file':image.name,'bytes':image.stat().st_size,'average_rgb':round(avg,1)})
    if len(rows) != len(PdfReader(str(path), strict=False).pages):
        raise RuntimeError(f'Render count mismatch: {path.name}')
    return rows

def white_flatten(im: Image.Image) -> Image.Image:
    rgba = im.convert('RGBA')
    canvas = Image.new('RGBA', rgba.size, (255,255,255,255))
    canvas.alpha_composite(rgba)
    return canvas.convert('RGB')

# Report 1: original public PDF.
url1='https://cdn.hangyan.co/documents/98/980839aeb3b9cde04c6b7c34aef205de26696bc36ac08713989fde10cddb7889.pdf'
r=s.get(url1,timeout=90,headers={'Referer':'https://www.hangyan.co/reports/3448696034581022433','Accept':'application/pdf,*/*'}); r.raise_for_status()
if not r.content.startswith(b'%PDF-') or len(r.content)<100000: raise RuntimeError('Invalid original PDF')
p1=REPORTS/'01_Guoyuan_International_2024-09-02_Ascletis_ORIGINAL_2p.pdf'; p1.write_bytes(r.content)
rd=PdfReader(str(p1),strict=False); pages=len(rd.pages)
text='\n'.join((p.extract_text() or '') for p in rd.pages); norm=re.sub(r'\s+','',text).lower()
if pages!=2 or not any(x in norm for x in ['歌礼制药','歌禮製藥','ascletis','1672hk','01672']): raise RuntimeError('Original PDF validation failed')
manifest.append({'broker':'国元国际控股','date':'2024-09-02','title':'歌礼制药-B：创新药研发推进顺利，BD合作空间广阔','status':'公开原始PDF','filename':p1.name,'pages':pages,'bytes':p1.stat().st_size,'sha256':digest(p1),'source_page':'https://www.hangyan.co/reports/3448696034581022433','source_file':url1,'render_checks':render_all(p1)})

# Report 2: all public pages of a two-page report, flattened against white before PDF creation.
api='https://api.fxbaogao.com/mofoun/report/report/getReportPreviewImages?reportId=4984590'
r=s.get(api,timeout=60,headers={'Referer':'https://www.fxbaogao.com/view?id=4984590','Accept':'application/json,*/*'}); r.raise_for_status(); paths=(r.json().get('data') or [])
if len(paths)!=2: raise RuntimeError(f'Expected 2 pages, got {len(paths)}')
images=[]; image_meta=[]
for i,rel in enumerate(paths,1):
    url='https://public.fxbaogao.com/'+str(rel).lstrip('/')
    rr=s.get(url,timeout=90,headers={'Referer':'https://www.fxbaogao.com/view?id=4984590','Accept':'image/png,image/*,*/*'}); rr.raise_for_status()
    raw=Image.open(io.BytesIO(rr.content)); raw.load()
    if raw.width<800 or raw.height<1000: raise RuntimeError(f'Page image too small: {raw.size}')
    flat=white_flatten(raw)
    images.append(flat)
    image_meta.append({'page':i,'url':url,'mode':raw.mode,'width':raw.width,'height':raw.height,'bytes':len(rr.content),'sha256':hashlib.sha256(rr.content).hexdigest()})
p2=REPORTS/'02_Guoyuan_International_2025-08-06_ASC30_Phase_IIa_PUBLIC_PAGES_MERGED_2p.pdf'
images[0].save(p2,'PDF',resolution=150.0,save_all=True,append_images=images[1:])
pages=len(PdfReader(str(p2),strict=False).pages)
if pages!=2: raise RuntimeError('Merged PDF page count mismatch')
manifest.append({'broker':'国元国际控股','date':'2025-08-06','title':'ASC30美国IIa期完成患者入组，将于Q4读出数据','status':'公开阅读页逐页合并版（完整2页，非券商原始二进制）','filename':p2.name,'pages':pages,'bytes':p2.stat().st_size,'sha256':digest(p2),'source_page':'https://www.fxbaogao.com/detail/4984590','source_file':api,'public_page_images':image_meta,'render_checks':render_all(p2)})

readme='''歌礼制药-B（01672.HK）券商公司研究报告包\n\n本包仅含实际PDF，不含网页快捷方式：\n1. 国元国际控股，2024-09-02，2页，公开原始PDF；\n2. 国元国际控股，2025-08-06，2页，公开阅读接口完整展示的两页合并版。\n\n第二份不是券商服务器原始二进制，文件名与清单已明确标注。其两页公开页面先以白色背景进行透明度合成，再生成PDF，并逐页渲染检查。\n\n东吴证券2025-04-01的19页首次覆盖深度报告和东方证券2025-12-28的首次覆盖报告，目前完整附件处于登录或会员入口，因此未绕过权限，也未用两页预览冒充长篇全文。当前包更准确地属于两份完整公司研究/即时点评。\n\n已检查PDF签名、页数、公司身份（原始PDF）、页面完整性、渲染亮度、SHA-256及ZIP完整性。仅供个人研究，版权归原券商及发布机构。\n'''
(REPORTS/'README.txt').write_text(readme,encoding='utf-8')
(REPORTS/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
with (REPORTS/'manifest.csv').open('w',encoding='utf-8-sig',newline='') as f:
    rows=[]
    for x in manifest:
        y=dict(x); y['public_page_images']=json.dumps(y.get('public_page_images',''),ensure_ascii=False); y['render_checks']=json.dumps(y.get('render_checks',''),ensure_ascii=False); rows.append(y)
    cols=sorted({k for x in rows for k in x}); w=csv.DictWriter(f,fieldnames=cols); w.writeheader(); w.writerows(rows)
with ZipFile(ZIP,'w',ZIP_DEFLATED,compresslevel=9) as z:
    for p in sorted(REPORTS.iterdir(),key=lambda x:x.name): z.write(p,p.name)
with ZipFile(ZIP) as z:
    if z.testzip() is not None: raise RuntimeError('ZIP integrity failed')
    if len([n for n in z.namelist() if n.lower().endswith('.pdf')])!=2: raise RuntimeError('PDF count mismatch')
print('PACKAGE_READY',ZIP,ZIP.stat().st_size)
print(json.dumps(manifest,ensure_ascii=False,indent=2))
