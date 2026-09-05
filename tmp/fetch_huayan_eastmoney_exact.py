from __future__ import annotations
import json, re, hashlib
from pathlib import Path
import requests
from pypdf import PdfReader

OUT=Path('out_huayan_eastmoney_exact'); OUT.mkdir(exist_ok=True)
PDFS=OUT/'pdfs'; PDFS.mkdir(exist_ok=True)
s=requests.Session(); s.headers.update({'User-Agent':'Mozilla/5.0','Referer':'https://data.eastmoney.com/report/stock.jshtml'})
base='https://reportapi.eastmoney.com/report/list'
common={
 'industryCode':'*','pageSize':'5000','industry':'*','rating':'*','ratingChange':'*',
 'beginTime':'2026-03-01','endTime':'2026-09-06','pageNo':'1','fields':'','qType':'0',
 'orgCode':'','rcode':'','p':'1','pageNum':'1','pageNumber':'1'
}
queries=[('code_01021',dict(common,code='01021')),('code_1021',dict(common,code='1021')),('code_HK01021',dict(common,code='HK01021')),('all_2026',dict(common,code=''))]
all_rows=[]
for name,params in queries:
    try:
        r=s.get(base,params=params,timeout=90)
        print('QUERY',name,r.status_code,len(r.content),r.url)
        (OUT/f'{name}.json').write_bytes(r.content)
        obj=r.json()
        print('META',name,{k:obj.get(k) for k in ['TotalPage','TotalCount','currentYear','hits'] if isinstance(obj,dict)})
        data=obj.get('data') or []
        print('ROWS',name,len(data))
        for x in data:
            blob=json.dumps(x,ensure_ascii=False).lower()
            if any(k in blob for k in ['华沿机器人','華沿機器人','01021','1021.hk','1021 hk','huayan robotics']):
                print('MATCH',name,json.dumps(x,ensure_ascii=False))
                all_rows.append(x)
    except Exception as e: print('ERR',name,repr(e))

# De-duplicate and fetch original Eastmoney PDFs.
uniq={}
for row in all_rows:
    key=str(row.get('infoCode') or json.dumps(row,sort_keys=True,ensure_ascii=False))
    uniq[key]=row
valid=[]
for i,(key,row) in enumerate(uniq.items()):
    info=row.get('infoCode')
    if not info: continue
    candidates=[f'https://pdf.dfcfw.com/pdf/H3_{info}_1.pdf',f'https://pdf.dfcfw.com/pdf/H3_{info}.pdf']
    for j,u in enumerate(candidates):
        try:
            rr=s.get(u,timeout=90)
            print('PDF_PROBE',i,j,rr.status_code,rr.headers.get('content-type'),len(rr.content),u)
            if rr.status_code==200 and rr.content.startswith(b'%PDF-') and len(rr.content)>50000:
                h=hashlib.sha256(rr.content).hexdigest(); p=PDFS/f'{i}_{info}_{h[:12]}.pdf';p.write_bytes(rr.content)
                try:
                    rd=PdfReader(str(p),strict=False); pages=len(rd.pages); sample='\n'.join((pg.extract_text() or '') for pg in rd.pages[:min(10,pages)])
                except Exception as e: pages=-1; sample=''; print('PARSE_ERR',repr(e))
                norm=re.sub(r'\s+','',sample).lower(); ok=any(k in norm for k in ['华沿机器人','華沿機器人','huayanrobotics','1021hk','01021'])
                meta={'path':str(p),'url':u,'pages':pages,'bytes':len(rr.content),'sha256':h,'identity_ok':ok,'row':row,'sample':sample[:2500]}
                valid.append(meta); print('PDF_VALID',json.dumps({k:v for k,v in meta.items() if k not in ['sample','row']},ensure_ascii=False));break
        except Exception as e: print('PDF_ERR',u,repr(e))
(OUT/'matches.json').write_text(json.dumps(list(uniq.values()),ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'valid.json').write_text(json.dumps(valid,ensure_ascii=False,indent=2),encoding='utf-8')
print('DONE',len(uniq),len(valid))
