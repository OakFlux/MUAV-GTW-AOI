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

SRC = Path('out_ascletis_resolved')
OUT = Path('out_ascletis_final')
REPORTS = OUT / 'reports'
RENDERS = OUT / 'renders'
ZIP = OUT / 'ascletis_01672_reports_new.zip'
shutil.rmtree(OUT, ignore_errors=True)
REPORTS.mkdir(parents=True)
RENDERS.mkdir(parents=True)

items = json.loads((SRC/'saved.json').read_text(encoding='utf-8'))
valid=[]
seen=set()
for item in items:
    path=Path(item['file'])
    if not path.exists():
        continue
    data=path.read_bytes()
    if not data.startswith(b'%PDF-') or len(data)<50000:
        continue
    sha=hashlib.sha256(data).hexdigest()
    if sha in seen:
        continue
    seen.add(sha)
    reader=PdfReader(str(path),strict=False)
    pages=len(reader.pages)
    if pages<2:
        continue
    idxs=sorted(set(list(range(min(12,pages)))+[pages//2,pages-1]))
    text='\n'.join((reader.pages[i].extract_text() or '') for i in idxs)
    norm=re.sub(r'\s+','',text).lower()
    if not any(x in norm for x in ['歌礼制药','歌禮製藥','ascletis','01672','1672.hk','1672hk']):
        continue
    for pageno in sorted({1,max(1,(pages+1)//2),pages}):
        prefix=RENDERS/f'{sha[:12]}_p{pageno}'
        subprocess.run(['pdftoppm','-f',str(pageno),'-l',str(pageno),'-png','-singlefile','-r','80',str(path),str(prefix)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        image=Path(str(prefix)+'.png')
        if not image.exists() or image.stat().st_size<4000:
            raise RuntimeError(f'render failed {path} p{pageno}')
    blob=' '.join([item.get('filenameHint',''),item.get('pageTitle',''),text[:8000]])
    broker='券商研究'
    for n in ['东方证券','東方證券','东吴证券','東吳證券','国元国际控股','國元國際控股','国元国际','國元國際']:
        if n in blob:
            broker=n;break
    date=''
    for pat in [r'(20\d{2})[-年./](\d{1,2})[-月./](\d{1,2})',r'(20\d{2})(\d{2})(\d{2})']:
        m=re.search(pat,blob)
        if m:
            y,mo,d=map(int,m.groups())
            if 1<=mo<=12 and 1<=d<=31:
                date=f'{y:04d}-{mo:02d}-{d:02d}';break
    title=(item.get('filenameHint') or item.get('pageTitle') or '').removesuffix('.pdf')
    deep=pages>=15 or any(x in blob.lower() for x in ['首次覆盖','首次覆蓋','全新glp-1减重不减肌','口服小分子率先破局','best-in-class'])
    valid.append({**item,'path':str(path),'pages':pages,'sha256':sha,'bytes':len(data),'broker':broker,'date':date,'title':title,'deep':deep})

valid.sort(key=lambda x:(int(x['deep']),x['pages'],x['date']),reverse=True)
selected=valid[:3]
if len(selected)<2:
    raise RuntimeError(f'only {len(selected)} distinct valid PDFs')

mapping={'东方证券':'Orient','東方證券':'Orient','东吴证券':'Soochow','東吳證券':'Soochow','国元国际控股':'Guoyuan','國元國際控股':'Guoyuan','国元国际':'Guoyuan','國元國際':'Guoyuan'}
manifest=[]
for i,x in enumerate(selected,1):
    filename=f"{i:02d}_{mapping.get(x['broker'],'Broker')}_{x['date'] or 'undated'}_Ascletis_01672_{x['pages']}p.pdf"
    shutil.copy2(x['path'],REPORTS/filename)
    manifest.append({'index':i,'broker':x['broker'],'date':x['date'],'title':x['title'],'type':'深度/首次覆盖' if x['deep'] else '完整公司研究','filename':filename,'pages':x['pages'],'bytes':x['bytes'],'sha256':x['sha256'],'report_page':x.get('reportUrl',''),'source_pdf':x.get('pdfUrl','')})

readme=['歌礼制药（01672.HK）券商研究报告重新下载包','',f'包含{len(manifest)}份不同的实际PDF，不含网页快捷方式、自制摘要或图片预览。','']
for x in manifest:
    readme.append(f"{x['index']}. {x['broker']}｜{x['date']}｜{x['pages']}页｜{x['type']}｜{x['title']}")
readme+=['','已检查PDF文件签名、公司名称/证券代码、实际页数、首中末页渲染、SHA-256与ZIP完整性。']
(REPORTS/'README.txt').write_text('\n'.join(readme),encoding='utf-8')
(REPORTS/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
with (REPORTS/'manifest.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(manifest[0].keys()));w.writeheader();w.writerows(manifest)
with ZipFile(ZIP,'w',ZIP_DEFLATED,compresslevel=9) as zf:
    for p in sorted(REPORTS.iterdir(),key=lambda x:x.name): zf.write(p,p.name)
with ZipFile(ZIP) as zf:
    if zf.testzip() is not None: raise RuntimeError('bad zip')
    if len([n for n in zf.namelist() if n.lower().endswith('.pdf')])!=len(manifest): raise RuntimeError('count mismatch')
print('PACKAGE_READY',ZIP,ZIP.stat().st_size)
print(json.dumps(manifest,ensure_ascii=False,indent=2))
