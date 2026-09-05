from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

OUT = Path('out_huayan_eastmoney_narrow')
OUT.mkdir(exist_ok=True)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
client = httpx.Client(http2=True, follow_redirects=True, timeout=45, headers={'User-Agent': UA, 'Referer': 'https://data.eastmoney.com/report/'})

windows = [
    ('2026-03-20','2026-03-27'),
    ('2026-05-20','2026-05-29'),
    ('2026-06-23','2026-07-01'),
    ('2026-08-04','2026-08-11'),
    ('2026-08-25','2026-09-01'),
]
terms = ['华沿机器人','華沿機器人','头部协作机器人','協作機器人頭部','七轴人形手臂','七軸人形手臂','卖铲人','賣鏟人','运动控制底层价值','運動控制底層價值','1021.hk','01021']
authors = ['余小丽','张忠业','肖群稀','刘麒硕','陈庆','李柳晓','王强']

all_matches=[]
summary=[]
for begin,end in windows:
  for qtype in ['0','1','2','3','4','5']:
    for page in range(1,10):
      params={
        'pageSize':'100','pageNo':str(page),'beginTime':begin,'endTime':end,'qType':qtype,
        'fields':'','industryCode':'*','industry':'*','rating':'*','ratingChange':'*','orgCode':'','rcode':'',
        'p':str(page),'pageNum':str(page),'pageNumber':str(page),
      }
      try:
        r=client.get('https://reportapi.eastmoney.com/report/list',params=params)
        try: obj=r.json()
        except Exception:
          m=re.search(r'^[^(]*\((.*)\)\s*;?$',r.text,re.S); obj=json.loads(m.group(1)) if m else {}
        data=(obj.get('data') or []) if isinstance(obj,dict) else []
        total=obj.get('TotalCount') or obj.get('total') or obj.get('count') if isinstance(obj,dict) else None
        print('PAGE',begin,end,qtype,page,r.status_code,len(data),total,len(r.content))
        if not isinstance(data,list) or not data: break
        for item in data:
          title=str(item.get('title') or '')
          stock=str(item.get('stockName') or '')
          stockcode=str(item.get('stockCode') or '')
          researchers=str(item.get('researcher') or '')
          hay=' '.join([title,stock,stockcode,researchers,json.dumps(item.get('author') or [],ensure_ascii=False)]).lower()
          hit_terms=[t for t in terms if t.lower() in hay]
          hit_authors=[a for a in authors if a in hay]
          if hit_terms or (hit_authors and any(k in title for k in ['机器人','機器人','协作','協作','人形'])):
            rec={'window':[begin,end],'qType':qtype,'page':page,'hit_terms':hit_terms,'hit_authors':hit_authors,'item':item}
            all_matches.append(rec)
            print('MATCH',json.dumps(rec,ensure_ascii=False)[:20000])
        if len(data)<100: break
      except Exception as exc:
        print('ERR',begin,end,qtype,page,repr(exc)); break

# Direct title searches using likely accepted query parameters.
for title in ['华沿机器人','头部协作机器人公司，七轴人形手臂放量可期','协作机器人头部企业，具身智能空间广阔','运动控制底层价值有望重估']:
 for key in ['title','keyword','searchTitle','searchKeyword']:
  params={'pageSize':'200','pageNo':'1','beginTime':'2026-03-01','endTime':'2026-09-05','qType':'0',key:title}
  try:
   r=client.get('https://reportapi.eastmoney.com/report/list',params=params)
   try: obj=r.json()
   except: obj={}
   data=(obj.get('data') or []) if isinstance(obj,dict) else []
   print('DIRECT',key,title,r.status_code,len(data),len(r.content))
   for item in data:
    hay=json.dumps(item,ensure_ascii=False)
    if any(t in hay for t in terms) or any(a in hay for a in authors):
     rec={'direct_key':key,'direct_title':title,'item':item}; all_matches.append(rec); print('DIRECT_MATCH',json.dumps(rec,ensure_ascii=False)[:20000])
  except Exception as exc: print('DIRECT_ERR',key,title,repr(exc))

(OUT/'matches.json').write_text(json.dumps(all_matches,ensure_ascii=False,indent=2),encoding='utf-8')
print('MATCH_COUNT',len(all_matches))
client.close()
