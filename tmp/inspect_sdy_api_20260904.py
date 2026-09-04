from __future__ import annotations
import re, json
from pathlib import Path
import httpx

OUT=Path('out_sdy_api_inspect')
OUT.mkdir(exist_ok=True)
client=httpx.Client(follow_redirects=True,timeout=60,headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.sdyanbao.com/report'})
chunks=['86c5b4f.js','0bec462.js','7ff3a18.js','359ac1f.js','a94fdf1.js']
all_text=''
for name in chunks:
    url='https://www.sdyanbao.com/_nuxt/'+name
    r=client.get(url); print('CHUNK',name,r.status_code,len(r.content),r.headers.get('content-type'))
    r.raise_for_status(); text=r.text; (OUT/name).write_text(text,encoding='utf-8'); all_text+='\n'+text

endpoints=sorted(set(re.findall(r'["\'](/api/[A-Za-z0-9_./?=&${}-]+)',all_text)))
print('ENDPOINTS',json.dumps(endpoints,ensure_ascii=False,indent=2))
(OUT/'endpoints.json').write_text(json.dumps(endpoints,ensure_ascii=False,indent=2),encoding='utf-8')
for ep in endpoints:
    if any(k in ep.lower() for k in ['file','search','report']):
        idx=all_text.find(ep)
        print('CONTEXT',ep,all_text[max(0,idx-500):idx+1000])

# Probe likely public search endpoints using the exact title/keywords.
queries=['阜丰集团','多品类布局全球领先的生物发酵企业','生物发酵企业']
likely=['/api/file/list','/api/file/search','/api/file/searchlist','/api/file/reportlist','/api/file/homelist']
results=[]
for ep in sorted(set(endpoints+likely)):
    if not any(k in ep.lower() for k in ['file','search','report']): continue
    if any(ch in ep for ch in ['${','{']): continue
    url='https://api.sdyanbao.com'+ep.split('?',1)[0]
    for q in queries:
        payload={'page':1,'pageSize':20,'keyword':q,'keywords':q,'name':q,'search':q,'opFrom':1}
        try:
            r=client.post(url,json=payload)
            text=r.text
            match='阜丰' in text or '多品类布局全球领先' in text
            print('PROBE',ep,q,r.status_code,len(text),match,text[:300] if match else '')
            results.append({'endpoint':ep,'query':q,'status':r.status_code,'length':len(text),'match':match,'body':text[:20000] if match else text[:1000]})
        except Exception as e:
            results.append({'endpoint':ep,'query':q,'error':str(e)})
(OUT/'probe_results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
client.close()
