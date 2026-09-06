from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

OUT = Path('out_ascletis_eastmoney_sina')
PDFS = OUT / 'pdfs'
OUT.mkdir(exist_ok=True)
PDFS.mkdir(exist_ok=True)

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
s = requests.Session()
s.headers.update({'User-Agent': UA})
needles = ['歌礼制药', '歌禮製藥', '全新GLP-1减重不减肌', '口服小分子率先破局', '01672', '1672.HK']

matches = []
valid = []
seen_urls = set()
seen_hash = set()

def relevant(x) -> bool:
    blob = json.dumps(x, ensure_ascii=False).lower()
    return any(k.lower() in blob for k in needles)


def save_pdf(url: str, label: str, meta=None):
    if not url or url in seen_urls:
        return
    seen_urls.add(url)
    try:
        r = s.get(url, timeout=90, headers={'Referer':'https://data.eastmoney.com/report/','Accept':'application/pdf,*/*'})
        print('PDF', r.status_code, r.headers.get('content-type'), len(r.content), url)
        if r.status_code != 200 or len(r.content) < 50000 or not r.content.startswith(b'%PDF-'):
            return
        sha = hashlib.sha256(r.content).hexdigest()
        if sha in seen_hash:
            return
        seen_hash.add(sha)
        p = PDFS / f'{label}_{sha[:12]}.pdf'
        p.write_bytes(r.content)
        reader = PdfReader(str(p), strict=False)
        pages = len(reader.pages)
        text = '\n'.join((pg.extract_text() or '') for pg in reader.pages[:min(12,pages)])
        norm = re.sub(r'\s+', '', text).lower()
        ok = any(x in norm for x in ['歌礼制药','歌禮製藥','ascletis','01672','1672hk','1672.hk'])
        item = {'file':str(p),'url':url,'pages':pages,'bytes':len(r.content),'sha256':sha,'identity_ok':ok,'meta':meta or {},'sample':text[:5000]}
        valid.append(item)
        print('VALID', json.dumps({k:v for k,v in item.items() if k not in ['meta','sample']}, ensure_ascii=False))
    except Exception as exc:
        print('PDF_ERR', url, repr(exc))

# Eastmoney legacy API: exact windows around both reports, all pages/qTypes.
windows = [
    ('2025-03-29','2025-04-05'),
    ('2025-09-05','2025-09-12'),
    ('2025-12-24','2026-01-03'),
]
for begin,end in windows:
    for qtype in ['0','1','2']:
        for page in range(1,80):
            params={
                'industryCode':'*','pageSize':'100','industry':'*','rating':'*','ratingChange':'*',
                'beginTime':begin,'endTime':end,'pageNo':str(page),'fields':'','qType':qtype,
                'orgCode':'','code':'','rcode':'','p':str(page),'pageNum':str(page),'pageNumber':str(page),
            }
            try:
                r=s.get('https://reportapi.eastmoney.com/report/list',params=params,timeout=60,headers={'Referer':'https://data.eastmoney.com/report/'})
                obj=r.json(); data=obj.get('data') or []
                if page==1: print('EM_META',begin,end,qtype,r.status_code,len(data),{k:obj.get(k) for k in ['TotalPage','TotalCount','hits']})
                for row in data:
                    if relevant(row):
                        print('EM_MATCH',json.dumps(row,ensure_ascii=False));matches.append({'source':'eastmoney','row':row})
                total=int(obj.get('TotalPage') or 1)
                if page>=total or not data: break
            except Exception as exc:
                print('EM_ERR',begin,end,qtype,page,repr(exc));break
            time.sleep(.15)

# New list2 endpoint: POST JSON, exact dates and common code variants.
for begin,end in windows:
  for code in ['','01672','1672','HK01672','01672.HK','1672.HK','116.01672']:
    body={'pageSize':5000,'pageNo':1,'p':1,'pageNum':1,'pageNumber':1,'beginTime':begin,'endTime':end,'code':code,'industryCode':'*','rating':None,'ratingChange':None,'orgCode':None,'rcode':''}
    try:
      r=s.post('https://reportapi.eastmoney.com/report/list2',json=body,timeout=60,headers={'Referer':'https://data.eastmoney.com/report/'})
      obj=r.json();data=obj.get('data') or []
      print('EM2',begin,end,code,r.status_code,len(data),{k:obj.get(k) for k in ['TotalPage','TotalCount','hits']})
      for row in data:
        if relevant(row):
          print('EM2_MATCH',json.dumps(row,ensure_ascii=False));matches.append({'source':'eastmoney2','row':row})
    except Exception as exc: print('EM2_ERR',begin,end,code,repr(exc))

# Download all direct PDF URL candidates from Eastmoney rows.
for i,m in enumerate(matches):
    row=m['row']; info=str(row.get('infoCode') or row.get('INFO_CODE') or '')
    urls=[]
    for k,v in row.items():
        if isinstance(v,str) and v.startswith('http'):
            urls.append(v.replace('\\/','/'))
    if info:
        urls += [
            f'https://pdf.dfcfw.com/pdf/H3_{info}_1.pdf',
            f'https://pdf.dfcfw.com/pdf/H3_{info}.pdf',
            f'https://pdf.dfcfw.com/pdf/H2_{info}_1.pdf',
            f'https://pdf.dfcfw.com/pdf/H2_{info}.pdf',
        ]
    for j,u in enumerate(urls):
        if '.pdf' in u.lower() or 'dfcfw.com/pdf' in u.lower(): save_pdf(u,f'em_{i}_{j}',row)

# Sina report search by company/title/date.
sina_urls=[
 'https://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?symbol=hk01672&orgname=&industry=&title=&t1=all',
 'https://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?symbol=&orgname=&industry=&title=%E6%AD%8C%E7%A4%BC%E5%88%B6%E8%8D%AF&t1=all',
 'https://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?symbol=&orgname=&industry=&title=GLP-1%E5%87%8F%E9%87%8D%E4%B8%8D%E5%87%8F%E8%82%8C&t1=all',
]
show=set()
for idx,u in enumerate(sina_urls):
    try:
        r=s.get(u,timeout=60); raw=r.content
        txt=raw.decode('gb18030',errors='ignore')
        (OUT/f'sina_list_{idx}.html').write_text(txt,encoding='utf-8')
        print('SINA_LIST',idx,r.status_code,len(txt),r.url)
        for x in re.findall(r'(?:href|url)=["\']([^"\']*vReport_Show[^"\']*)["\']',txt,re.I):
            show.add(urljoin(str(r.url),x.replace('&amp;','&')))
    except Exception as exc: print('SINA_LIST_ERR',idx,repr(exc))
for idx,u in enumerate(sorted(show)):
    try:
        r=s.get(u,timeout=60);txt=r.content.decode('gb18030',errors='ignore')
        if not any(k.lower() in txt.lower() for k in needles): continue
        print('SINA_MATCH',u,re.sub(r'\s+',' ',BeautifulSoup(txt,'html.parser').get_text(' ',strip=True))[:1000])
        (OUT/f'sina_show_{idx}.html').write_text(txt,encoding='utf-8')
        for j,x in enumerate(re.findall(r'https?://[^"\'<>\s]+',txt)):
            x=x.replace('&amp;','&').replace('\\/','/')
            if '.pdf' in x.lower() or 'dfcfw.com/pdf' in x.lower(): save_pdf(x,f'sina_{idx}_{j}',{'page':u})
    except Exception as exc: print('SINA_SHOW_ERR',u,repr(exc))

(OUT/'matches.json').write_text(json.dumps(matches,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'valid.json').write_text(json.dumps(valid,ensure_ascii=False,indent=2),encoding='utf-8')
print('DONE',len(matches),len(valid))
