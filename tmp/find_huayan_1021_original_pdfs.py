from __future__ import annotations

import json, re, html, hashlib, sys
from pathlib import Path
from urllib.parse import urljoin, unquote
import httpx
from pypdf import PdfReader

OUT = Path('out_huayan_1021_original_search')
OUT.mkdir(exist_ok=True)
PDFS = OUT / 'pdfs'; PDFS.mkdir(exist_ok=True)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
client = httpx.Client(http2=True, follow_redirects=True, timeout=httpx.Timeout(60, connect=20), headers={'User-Agent': UA})
TERMS = ['华沿机器人','華沿機器人','huayan robotics','01021','1021 hk','七轴人形手臂','协作机器人头部企业','卖铲人','运动控制底层价值']

def parse_json_response(r):
    try: return r.json()
    except Exception:
        t=r.text.strip(); m=re.search(r'^[^(]*\((.*)\)\s*;?$',t,re.S)
        return json.loads(m.group(1)) if m else {'raw':t[:2000]}

def blob_text(x):
    return json.dumps(x,ensure_ascii=False).lower()

def relevant(x):
    s=blob_text(x)
    return any(t.lower() in s for t in TERMS)

def save_pdf(url, label):
    try:
        r=client.get(url,headers={'Accept':'application/pdf,application/octet-stream,*/*','Referer':'https://data.eastmoney.com/'})
        print('PDF_PROBE',r.status_code,r.headers.get('content-type'),len(r.content),url)
        if r.status_code==200 and len(r.content)>80000 and r.content[:5]==b'%PDF-':
            h=hashlib.sha256(r.content).hexdigest()
            p=PDFS/f'{label}_{h[:12]}.pdf'; p.write_bytes(r.content)
            try:
                rd=PdfReader(str(p),strict=False); pages=len(rd.pages)
                sample='\n'.join((pg.extract_text() or '') for pg in rd.pages[:min(12,pages)])
            except Exception as e:
                pages=-1; sample=''; print('PDF_PARSE_ERR',repr(e))
            ok=any(t in re.sub(r'\s+','',sample).lower() for t in ['华沿机器人','華沿機器人','huayanrobotics','01021','1021hk'])
            meta={'url':url,'path':str(p),'bytes':len(r.content),'sha256':h,'pages':pages,'identity_ok':ok,'sample':sample[:2500]}
            print('PDF_VALID',json.dumps({k:v for k,v in meta.items() if k!='sample'},ensure_ascii=False))
            return meta
    except Exception as e: print('PDF_ERR',url,repr(e))
    return None

results={'eastmoney_matches':[],'sina_matches':[],'page_links':[],'valid_pdfs':[]}

# Eastmoney broad research report API. Query several common parameter layouts.
for qtype in ['0','1','2']:
  for page in range(1,8):
    params={'pageSize':'100','pageNo':str(page),'beginTime':'2026-03-01','endTime':'2026-09-05','qType':qtype,
            'fields':'','industryCode':'*','industry':'*','rating':'*','ratingChange':'*','orgCode':'','rcode':'',
            'p':str(page),'pageNum':str(page),'pageNumber':str(page)}
    try:
      r=client.get('https://reportapi.eastmoney.com/report/list',params=params,headers={'Referer':'https://data.eastmoney.com/report/'})
      obj=parse_json_response(r); data=obj.get('data') or [] if isinstance(obj,dict) else []
      print('EM_PAGE',qtype,page,r.status_code,len(data),len(r.content))
      if not isinstance(data,list) or not data: break
      for item in data:
        if relevant(item):
          print('EM_MATCH',json.dumps(item,ensure_ascii=False)[:10000]); results['eastmoney_matches'].append(item)
      if len(data)<100: break
    except Exception as e: print('EM_ERR',qtype,page,repr(e)); break

# Also try direct stock code queries.
for code in ['01021','1021','HK01021']:
  params={'code':code,'pageSize':'200','pageNo':'1','beginTime':'2026-03-01','endTime':'2026-09-05','qType':'0'}
  try:
    r=client.get('https://reportapi.eastmoney.com/report/list',params=params,headers={'Referer':'https://data.eastmoney.com/report/'})
    obj=parse_json_response(r); data=obj.get('data') or [] if isinstance(obj,dict) else []
    print('EM_CODE',code,r.status_code,len(data),len(r.content))
    for item in data:
      print('EM_CODE_ITEM',json.dumps(item,ensure_ascii=False)[:6000])
      if relevant(item): results['eastmoney_matches'].append(item)
  except Exception as e: print('EM_CODE_ERR',code,repr(e))

# Generate and probe direct URLs from Eastmoney metadata.
seen_urls=set()
for i,item in enumerate(results['eastmoney_matches']):
  vals=[]
  def walk(x):
    if isinstance(x,dict):
      for k,v in x.items():
        if isinstance(v,(dict,list)): walk(v)
        else:
          s=str(v)
          if s.startswith('http'): vals.append(s)
          if k.lower() in ['infocode','info_code','reportid','report_id','id'] and re.fullmatch(r'[A-Za-z0-9_]+',s):
            vals.extend([f'https://pdf.dfcfw.com/pdf/H3_{s}_1.pdf',f'https://pdf.dfcfw.com/pdf/H3_{s}.pdf'])
    elif isinstance(x,list):
      for v in x: walk(v)
  walk(item)
  for j,u in enumerate(vals):
    u=html.unescape(u).replace('\\/','/')
    if u not in seen_urls:
      seen_urls.add(u); m=save_pdf(u,f'em_{i}_{j}')
      if m: results['valid_pdfs'].append(m)

# Sina research list/search pages, then inspect report-show pages and links.
list_urls=[
 'http://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?symbol=hk01021&orgname=&industry=&title=&t1=all',
 'http://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?symbol=&orgname=&industry=&title=%E5%8D%8E%E6%B2%BF%E6%9C%BA%E5%99%A8%E4%BA%BA&t1=all',
]
show_urls=set()
for idx,u in enumerate(list_urls):
  try:
    r=client.get(u); raw=r.content
    enc='gb18030' if b'charset=gb' in raw[:5000].lower() else (r.encoding or 'utf-8')
    txt=raw.decode(enc,errors='ignore'); (OUT/f'sina_list_{idx}.html').write_text(txt,encoding='utf-8')
    print('SINA_LIST',idx,r.status_code,len(txt),str(r.url))
    for x in re.findall(r'https?://stock\.finance\.sina\.com\.cn/stock/go\.php/vReport_Show/[^"\'<>\s]+',txt,re.I): show_urls.add(html.unescape(x))
    for x in re.findall(r'(?:href|url)=["\']([^"\']*vReport_Show[^"\']*)["\']',txt,re.I): show_urls.add(urljoin(str(r.url),html.unescape(x)))
  except Exception as e: print('SINA_LIST_ERR',repr(e))
print('SINA_SHOW_COUNT',len(show_urls))
for idx,u in enumerate(sorted(show_urls)):
  try:
    r=client.get(u); raw=r.content; enc='gb18030' if b'charset=gb' in raw[:5000].lower() else (r.encoding or 'utf-8'); txt=raw.decode(enc,errors='ignore')
    if not any(t.lower() in txt.lower() for t in TERMS): continue
    print('SINA_MATCH',u,txt[:1500].replace('\n',' ')); results['sina_matches'].append({'url':u,'html':txt[:50000]})
    links=set(re.findall(r'https?://[^"\'<>\s]+',txt))
    links.update(urljoin(str(r.url),html.unescape(x)) for x in re.findall(r'(?:href|src)=["\']([^"\']+)["\']',txt,re.I))
    for j,x in enumerate(sorted(links)):
      if any(k in x.lower() for k in ['.pdf','download','attachment','dfcfw']):
        print('SINA_LINK',x); results['page_links'].append(x)
        if x not in seen_urls:
          seen_urls.add(x); m=save_pdf(x,f'sina_{idx}_{j}')
          if m: results['valid_pdfs'].append(m)
  except Exception as e: print('SINA_SHOW_ERR',u,repr(e))

# Inspect known public detail/download pages for embedded file links.
pages=[
 'https://www.sgpjbg.com/bgdown/1272177.html',
 'https://www.fxbaogao.com/detail/5435007',
 'https://www.fxbaogao.com/detail/5497229',
 'https://www.fxbaogao.com/detail/5587624',
 'https://www.hstong.com/news/detail/26060611082313115',
 'https://wap.hibor.com.cn/repinfodetail_5315187.html',
]
for idx,u in enumerate(pages):
  try:
    r=client.get(u); txt=r.text; (OUT/f'page_{idx}.html').write_text(txt,encoding='utf-8',errors='ignore')
    print('PAGE',idx,r.status_code,r.headers.get('content-type'),len(r.content),str(r.url))
    links=set(re.findall(r'https?://[^"\'<>\s]+',txt))
    links.update(urljoin(str(r.url),html.unescape(x)) for x in re.findall(r'(?:href|src|data-file|data-url|data-src)=["\']([^"\']+)["\']',txt,re.I))
    for j,x in enumerate(sorted(links)):
      x=x.replace('\\/','/').rstrip(');,')
      if any(k in x.lower() for k in ['.pdf','download','attachment','oss','fileurl','bgdown']):
        print('PAGE_LINK',idx,x); results['page_links'].append(x)
        if x not in seen_urls:
          seen_urls.add(x); m=save_pdf(x,f'page_{idx}_{j}')
          if m: results['valid_pdfs'].append(m)
  except Exception as e: print('PAGE_ERR',idx,u,repr(e))

# One known official public report from SDIC Securities International (IPO research) as a legal fallback.
u='https://www.sdicsi.com.hk/backend/storage/app/media/ResearchReports/IPOReports/1021-20260323.pdf'
m=save_pdf(u,'sdicsi_ipo');
if m: results['valid_pdfs'].append(m)

(OUT/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print('DONE_VALID',len(results['valid_pdfs']))
client.close()
