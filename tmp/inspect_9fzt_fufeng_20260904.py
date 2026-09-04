from __future__ import annotations
import json,re
from pathlib import Path
from urllib.parse import urljoin
import httpx

OUT=Path('out_9fzt_fufeng_inspect'); OUT.mkdir(exist_ok=True)
URLS=[
 'https://gmg.9fzt.com/report/HKSE/00546/740072245787.html',
 'https://gmg.9fzt.com/report/HKSE/00546/index.html',
]
client=httpx.Client(follow_redirects=True,timeout=60,headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36','Accept':'text/html,application/xhtml+xml,*/*'})
result=[]
for u in URLS:
    try:
        r=client.get(u); print('GET',u,r.status_code,len(r.content),r.headers.get('content-type'),r.url)
        rec={'url':u,'status':r.status_code,'final_url':str(r.url),'headers':dict(r.headers),'length':len(r.content)}
        text=r.text
        (OUT/(re.sub(r'\W+','_',u)[-100:]+'.html')).write_text(text,encoding='utf-8')
        urls=sorted(set(re.findall(r'https?://[^"\'<>\s]+',text)))
        rels=sorted(set(re.findall(r'(?:src|href)=["\']([^"\']+)["\']',text,re.I)))
        all_urls=sorted(set(urls+[urljoin(str(r.url),x) for x in rels]))
        interesting=[x for x in all_urls if re.search(r'pdf|report|download|file|api|740072245787|00546',x,re.I)]
        scripts=[x for x in all_urls if re.search(r'\.js(?:\?|$)',x,re.I)]
        rec.update({'interesting':interesting,'scripts':scripts,'title':(re.search(r'<title[^>]*>(.*?)</title>',text,re.I|re.S).group(1) if re.search(r'<title[^>]*>(.*?)</title>',text,re.I|re.S) else '')})
        print('INTERESTING',json.dumps(interesting,ensure_ascii=False,indent=2))
        print('SCRIPTS',len(scripts))
        result.append(rec)
        for i,s in enumerate(scripts[:30]):
            try:
                sr=client.get(s); print('SCRIPT',i,s,sr.status_code,len(sr.content),sr.headers.get('content-type'))
                if sr.status_code==200 and len(sr.content)<5_000_000:
                    st=sr.text
                    fn=OUT/f'script_{i}.js'; fn.write_text(st,encoding='utf-8')
                    for pat in ['pdf','download','reportDetail','report/detail','740072245787']:
                        if pat.lower() in st.lower():
                            idx=st.lower().find(pat.lower()); print('SCRIPT_CONTEXT',s,pat,st[max(0,idx-800):idx+1600])
            except Exception as e: print('SCRIPT_ERR',s,e)
    except Exception as e:
        print('ERR',u,e); result.append({'url':u,'error':str(e)})

# Probe common static-file/API forms.
probes=[]
bases=[
 'https://gmg.9fzt.com/report/HKSE/00546/740072245787.pdf',
 'https://gmg.9fzt.com/report/HKSE/00546/740072245787.PDF',
 'https://gmg.9fzt.com/report/download/HKSE/00546/740072245787',
 'https://gmg.9fzt.com/api/report/HKSE/00546/740072245787',
 'https://gmg.9fzt.com/api/report/740072245787',
 'https://gmg.9fzt.com/report/HKSE/00546/740072245787.json',
]
for u in bases:
    try:
        r=client.get(u); ct=r.headers.get('content-type',''); sig=r.content[:10].hex(); print('PROBE',u,r.status_code,len(r.content),ct,str(r.url),sig)
        probes.append({'url':u,'status':r.status_code,'bytes':len(r.content),'content_type':ct,'final_url':str(r.url),'signature_hex':sig,'text':r.text[:1000] if len(r.content)<100000 else ''})
    except Exception as e: probes.append({'url':u,'error':str(e)})
(OUT/'summary.json').write_text(json.dumps({'pages':result,'probes':probes},ensure_ascii=False,indent=2),encoding='utf-8')
client.close()
