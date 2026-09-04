from __future__ import annotations
import json, time
from pathlib import Path
import httpx

OUT=Path('out_fufeng_image_probe')
OUT.mkdir(exist_ok=True)
client=httpx.Client(follow_redirects=True,timeout=45,headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.fxbaogao.com/'})

for rid in ['4490043','3755592','94798']:
    u=f'https://api.fxbaogao.com/mofoun/report/report/getReportPreviewImages?reportId={rid}'
    r=client.get(u)
    print('API',rid,r.status_code,r.headers.get('content-type'),r.text[:1000])
    (OUT/f'{rid}_preview.json').write_text(r.text,encoding='utf-8')

sets=[
 ('fx_4490043','https://public.fxbaogao.com/report-image/2024/09/05/4490043-{}.png',1,80),
 ('fx_3755592','https://public.fxbaogao.com/report-image/2023/06/14/3755592-{}.png',1,100),
 ('fx_94798','https://public.fxbaogao.com/report-image/2017/03/15/94798-{}.png',1,100),
 ('sdy_817436','https://oss.sdyanbao.com/page/2024/9/10/1082137/{}.png',0,30),
]
results={}
for name,tmpl,start,stop in sets:
    rows=[]; misses=0
    for i in range(start,stop+1):
        u=tmpl.format(i)
        try:
            r=client.get(u,headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.sdyanbao.com/' if name.startswith('sdy') else 'https://www.fxbaogao.com/'})
            ct=r.headers.get('content-type','')
            valid=r.status_code==200 and len(r.content)>5000 and ct.startswith('image/')
            rows.append({'i':i,'status':r.status_code,'bytes':len(r.content),'content_type':ct,'valid':valid,'url':u})
            print('IMG',name,i,r.status_code,len(r.content),ct,valid)
            if valid:
                misses=0
            else:
                misses+=1
                if misses>=3: break
        except Exception as e:
            rows.append({'i':i,'error':str(e),'valid':False,'url':u})
            print('ERR',name,i,e)
            misses+=1
            if misses>=3: break
        time.sleep(.05)
    results[name]=rows
(OUT/'probe.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
client.close()
