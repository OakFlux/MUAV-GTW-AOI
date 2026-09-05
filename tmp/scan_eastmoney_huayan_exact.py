from __future__ import annotations
import json, re, hashlib
from pathlib import Path
import httpx
from pypdf import PdfReader

OUT=Path('out_huayan_em_exact'); OUT.mkdir(exist_ok=True); PDFS=OUT/'pdfs'; PDFS.mkdir(exist_ok=True)
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
client=httpx.Client(http2=True,follow_redirects=True,timeout=httpx.Timeout(60,connect=20),headers={'User-Agent':UA,'Referer':'https://data.eastmoney.com/report/'})
windows=[('2026-03-20','2026-04-05'),('2026-05-20','2026-05-30'),('2026-06-20','2026-07-02'),('2026-08-01','2026-08-14'),('2026-08-24','2026-09-02')]
exact_terms=['华沿机器人','華沿機器人','头部协作机器人公司','七轴人形手臂放量可期','协作机器人头部企业','具身智能空间广阔','运动控制底层价值','订单恢复与新品放量','1021.HK','01021']
all_matches=[]
for begin,end in windows:
 for qtype in ['0','1','2','3','4']:
  page=1
  while page<=20:
   params={'pageSize':'100','pageNo':str(page),'beginTime':begin,'endTime':end,'qType':qtype,'fields':'','industryCode':'*','industry':'*','rating':'*','ratingChange':'*','orgCode':'','rcode':'','p':str(page),'pageNum':str(page),'pageNumber':str(page)}
   try:
    r=client.get('https://reportapi.eastmoney.com/report/list',params=params)
    obj=r.json(); data=obj.get('data') or []
    print('PAGE',begin,end,qtype,page,r.status_code,len(data),obj.get('total') or obj.get('hits') or obj.get('TotalCount') or '')
    if not data: break
    for item in data:
     blob=json.dumps(item,ensure_ascii=False)
     if any(t.lower() in blob.lower() for t in exact_terms):
      print('MATCH',json.dumps(item,ensure_ascii=False)); all_matches.append(item)
    if len(data)<100: break
    page+=1
   except Exception as e:
    print('ERR',begin,end,qtype,page,repr(e)); break

# Deduplicate and download only exact identity/title matches.
seen=set(); valid=[]
for idx,item in enumerate(all_matches):
 info=str(item.get('infoCode') or item.get('INFO_CODE') or '')
 title=str(item.get('title') or item.get('TITLE') or '')
 stock=str(item.get('stockName') or item.get('SECURITY_NAME_ABBR') or '')
 blob=(title+' '+stock).lower()
 if not any(t.lower() in blob for t in exact_terms[:9]):
  continue
 if not info or info in seen: continue
 seen.add(info)
 for suffix in ['_1.pdf','.pdf']:
  url=f'https://pdf.dfcfw.com/pdf/H3_{info}{suffix}'
  try:
   r=client.get(url,headers={'Accept':'application/pdf,*/*'})
   print('PDF',info,r.status_code,r.headers.get('content-type'),len(r.content),url)
   if r.status_code==200 and len(r.content)>80000 and r.content.startswith(b'%PDF-'):
    h=hashlib.sha256(r.content).hexdigest(); p=PDFS/f'{info}_{h[:12]}.pdf'; p.write_bytes(r.content)
    rd=PdfReader(str(p),strict=False); pages=len(rd.pages); text='\n'.join((pg.extract_text() or '') for pg in rd.pages[:min(15,pages)])
    ident=any(x in re.sub(r'\s+','',text).lower() for x in ['华沿机器人','華沿機器人','huayanrobotics','01021','1021hk'])
    row={'item':item,'url':url,'path':str(p),'pages':pages,'sha256':h,'identity_ok':ident,'sample':text[:3000]}
    print('VALID',json.dumps({k:v for k,v in row.items() if k not in ['item','sample']},ensure_ascii=False)); valid.append(row); break
  except Exception as e: print('PDFERR',info,repr(e))

(OUT/'results.json').write_text(json.dumps({'matches':all_matches,'valid':valid},ensure_ascii=False,indent=2),encoding='utf-8')
print('DONE',len(all_matches),len(valid))
client.close()
