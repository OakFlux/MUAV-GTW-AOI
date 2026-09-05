import json, httpx
from pathlib import Path

OUT=Path('out_gtht_huayan_fast'); OUT.mkdir(exist_ok=True)
base='https://irs.gtht.com/irs/api/fesServer'
headers={'User-Agent':'Mozilla/5.0','Referer':'https://irs.gtht.com/irs/reports/public','Accept':'application/json,text/plain,*/*'}
client=httpx.Client(follow_redirects=True,timeout=httpx.Timeout(12,connect=5),headers=headers)
endpoints=['onrept/qryCompName','onrept/qryHomePage','onrept/qryNewest','onrept/qryRecommend','onrept/qryReptType']
payloads=[
 {'compName':'华沿机器人'}, {'companyName':'华沿机器人'}, {'keyWord':'华沿机器人'}, {'keyword':'华沿机器人'},
 {'stockCode':'01021'}, {'pageNum':1,'pageSize':50,'compName':'华沿机器人'}, {'pageNo':1,'pageSize':50,'keyWord':'华沿机器人'}, {}
]
rows=[]
for ep in endpoints:
 for method in ['get','post-json','post-form']:
  for payload in payloads:
   try:
    url=f'{base}/{ep}'
    if method=='get': r=client.get(url,params=payload)
    elif method=='post-json': r=client.post(url,json=payload,headers={**headers,'Content-Type':'application/json'})
    else: r=client.post(url,data=payload)
    row={'ep':ep,'method':method,'payload':payload,'status':r.status_code,'ct':r.headers.get('content-type',''),'len':len(r.content),'url':str(r.url),'text':r.text[:20000]}
    rows.append(row)
    print('ROW',json.dumps(row,ensure_ascii=False)[:22000])
   except Exception as e: print('ERR',ep,method,payload,repr(e))
(OUT/'rows.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
client.close()
