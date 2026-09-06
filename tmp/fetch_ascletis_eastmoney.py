from __future__ import annotations
import hashlib, json, re, time
from pathlib import Path
import requests
from pypdf import PdfReader

OUT=Path('out_ascletis_eastmoney'); PDFS=OUT/'pdfs'; PDFS.mkdir(parents=True,exist_ok=True)
s=requests.Session(); s.headers.update({'User-Agent':'Mozilla/5.0','Referer':'https://data.eastmoney.com/report/stock.jshtml','Accept':'application/json,text/plain,*/*'})
MATCH=('歌礼制药','歌禮製藥','Ascletis','01672','1672.HK','ASC30')
rows=[]

def relevant(x):
 b=json.dumps(x,ensure_ascii=False).lower(); return any(k.lower() in b for k in MATCH)

# New endpoint with HK code variants and exact date windows.
for code in ['01672','1672','HK01672','01672.HK','1672.HK','116.01672','']:
 for begin,end in [('2025-03-25','2025-04-10'),('2025-08-01','2025-09-15'),('2025-12-20','2026-01-10'),('2026-03-25','2026-04-10'),('2026-08-01','2026-09-06')]:
  body={'pageSize':5000,'pageNo':1,'p':1,'pageNum':1,'pageNumber':1,'beginTime':begin,'endTime':end,'code':code,'industryCode':'*','rating':None,'ratingChange':None,'orgCode':None,'rcode':''}
  try:
   r=s.post('https://reportapi.eastmoney.com/report/list2',json=body,timeout=60); obj=r.json(); data=obj.get('data') or []
   print('LIST2',code,begin,end,r.status_code,len(data))
   for x in data:
    if relevant(x): print('MATCH2',json.dumps(x,ensure_ascii=False)); rows.append(x)
  except Exception as e: print('ERR2',code,begin,repr(e))

# Legacy endpoint; walk exact windows with broad no-code query.
for begin,end in [('2025-03-25','2025-04-10'),('2025-08-01','2025-09-15'),('2025-12-20','2026-01-10'),('2026-03-25','2026-04-10'),('2026-08-01','2026-09-06')]:
 base={'industryCode':'*','pageSize':100,'industry':'*','rating':'*','ratingChange':'*','beginTime':begin,'endTime':end,'fields':'','qType':'0','orgCode':'','code':'','rcode':''}
 try:
  first=s.get('https://reportapi.eastmoney.com/report/list',params={**base,'pageNo':1,'p':1,'pageNum':1,'pageNumber':1},timeout=60).json(); total=min(int(first.get('TotalPage') or 1),200)
 except Exception as e: print('LEGACY_INIT_ERR',begin,repr(e)); continue
 print('LEGACY_WINDOW',begin,end,'pages',total)
 for page in range(1,total+1):
  try:
   r=s.get('https://reportapi.eastmoney.com/report/list',params={**base,'pageNo':page,'p':page,'pageNum':page,'pageNumber':page},timeout=60); data=r.json().get('data') or []
   for x in data:
    if relevant(x): print('MATCH1',json.dumps(x,ensure_ascii=False)); rows.append(x)
  except Exception as e: print('LEGACY_ERR',begin,page,repr(e))
  time.sleep(.08)

unique={}
for x in rows:
 key=str(x.get('infoCode') or x.get('reportId') or x.get('encodeUrl') or json.dumps(x,sort_keys=True,ensure_ascii=False)); unique[key]=x
valid=[]
for i,(key,x) in enumerate(unique.items()):
 info=x.get('infoCode') or x.get('INFO_CODE')
 urls=[]
 if info: urls += [f'https://pdf.dfcfw.com/pdf/H3_{info}_1.pdf',f'https://pdf.dfcfw.com/pdf/H3_{info}.pdf']
 for v in x.values():
  if isinstance(v,str) and v.startswith('http') and ('.pdf' in v.lower() or 'download' in v.lower()): urls.append(v)
 for u in dict.fromkeys(urls):
  try:
   r=s.get(u,timeout=90,headers={'Accept':'application/pdf,*/*'}); print('PDF',r.status_code,len(r.content),u)
   if r.status_code!=200 or len(r.content)<50000 or not r.content.startswith(b'%PDF-'): continue
   h=hashlib.sha256(r.content).hexdigest(); p=PDFS/f'{i:02d}_{h[:12]}.pdf'; p.write_bytes(r.content)
   rd=PdfReader(str(p),strict=False); pages=len(rd.pages); text='\n'.join((pg.extract_text() or '') for pg in rd.pages[:min(12,pages)]); norm=re.sub(r'\s+','',text).lower(); ok=any(k.lower().replace('.','') in norm.replace('.','') for k in MATCH)
   item={'path':str(p),'url':u,'pages':pages,'bytes':len(r.content),'sha256':h,'identity_ok':ok,'row':x,'sample':text[:3000]}; valid.append(item); print('VALID',json.dumps({k:v for k,v in item.items() if k not in ('row','sample')},ensure_ascii=False)); break
  except Exception as e: print('PDF_ERR',u,repr(e))
(OUT/'matches.json').write_text(json.dumps(list(unique.values()),ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'valid.json').write_text(json.dumps(valid,ensure_ascii=False,indent=2),encoding='utf-8')
print('DONE',len(unique),len(valid))
