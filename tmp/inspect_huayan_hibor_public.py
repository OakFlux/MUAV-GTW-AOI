from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import httpx

OUT=Path('out_huayan_hibor_public')
OUT.mkdir(exist_ok=True)
UA='Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 Chrome/131 Mobile Safari/537.36'
client=httpx.Client(http2=True,follow_redirects=True,timeout=httpx.Timeout(60,connect=20),headers={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'})

pages=[
 ('guotai','https://m.hibor.com.cn/wap_detail.aspx?id=5136789'),
 ('bocom_morning','https://wap.hibor.com.cn/repinfodetail_5315187.html'),
 ('guotai_alt','https://wap.hibor.com.cn/repinfodetail_5136789.html'),
]
patterns=['pdf','download','下载报告','打开报告原文','file','attach','oss','storage','url','reportid','repinfo','preview','image','login','会员','id=5136789']
results=[]
for label,url in pages:
    try:
        r=client.get(url)
        print('PAGE',label,r.status_code,r.headers.get('content-type'),len(r.content),r.url)
        raw=r.content
        enc='gb18030' if b'charset=gb' in raw[:5000].lower() else (r.encoding or 'utf-8')
        try: text=raw.decode(enc,errors='ignore')
        except: text=r.text
        (OUT/f'{label}.html').write_text(text,encoding='utf-8')
        links=set(re.findall(r'https?://[^"\'<>\s]+',text))
        links.update(urljoin(str(r.url),html.unescape(x)) for x in re.findall(r'(?:href|src|data-url|data-file|data-src|action|content)=["\']([^"\']+)["\']',text,re.I))
        interesting=[]
        for x in sorted(links):
            x=html.unescape(x).replace('\\/','/').rstrip(');,')
            if any(k in x.lower() for k in ['.pdf','download','file','attach','oss','storage','repinfo','report','preview','open']):
                interesting.append(x)
                print('LINK',label,x)
        ctx=[]
        for pat in patterns:
            for m in list(re.finditer(pat,text,re.I))[:100]:
                c=text[max(0,m.start()-600):m.end()+1400]
                ctx.append({'pattern':pat,'context':c})
                print('CTX',label,pat,c.replace('\n',' ')[:2000])
        scripts=[urljoin(str(r.url),html.unescape(x)) for x in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']',text,re.I)]
        script_rows=[]
        for i,surl in enumerate(scripts):
            try:
                sr=client.get(surl)
                st=sr.text
                (OUT/f'{label}_script_{i}.js').write_text(st,encoding='utf-8',errors='ignore')
                sctx=[]
                for pat in patterns:
                    for m in list(re.finditer(pat,st,re.I))[:100]:
                        c=st[max(0,m.start()-500):m.end()+1200]
                        sctx.append({'pattern':pat,'context':c})
                        if pat.lower() in ['pdf','download','file','attach','reportid','repinfo']:
                            print('SCRIPT_CTX',label,i,pat,c.replace('\n',' ')[:1800])
                endpoints=sorted(set(re.findall(r'https?://[^"\'`\\\s<>]+',st)))
                paths=sorted(set(re.findall(r'["\'](\/[^"\']*(?:download|file|pdf|report|repinfo|preview)[^"\']*)["\']',st,re.I)))
                for e in endpoints:
                    if any(k in e.lower() for k in ['download','file','pdf','report','repinfo','preview']): print('SCRIPT_ENDPOINT',label,i,e)
                for p in paths[:300]: print('SCRIPT_PATH',label,i,p)
                script_rows.append({'url':surl,'status':sr.status_code,'bytes':len(sr.content),'contexts':sctx,'endpoints':endpoints,'paths':paths})
            except Exception as exc: print('SCRIPT_ERR',label,i,surl,repr(exc))
        results.append({'label':label,'url':url,'final_url':str(r.url),'status':r.status_code,'interesting_links':interesting,'contexts':ctx,'scripts':script_rows})
    except Exception as exc:
        print('PAGE_ERR',label,url,repr(exc))
        results.append({'label':label,'url':url,'error':repr(exc)})

# Probe only direct PDF URLs explicitly found in public HTML. Do not use credentials or call member-only download endpoints.
probes=[]
seen=set()
for row in results:
    for u in row.get('interesting_links',[]):
        if u in seen or not u.lower().split('?',1)[0].endswith('.pdf'): continue
        seen.add(u)
        try:
            pr=client.get(u,headers={'Accept':'application/pdf,*/*','Referer':row.get('final_url',row['url'])})
            p={'url':u,'status':pr.status_code,'content_type':pr.headers.get('content-type',''),'bytes':len(pr.content),'final_url':str(pr.url),'pdf_signature':pr.content[:5]==b'%PDF-'}
            print('PDF_PROBE',json.dumps(p,ensure_ascii=False)); probes.append(p)
        except Exception as exc: print('PDF_PROBE_ERR',u,repr(exc))
(OUT/'results.json').write_text(json.dumps({'pages':results,'pdf_probes':probes},ensure_ascii=False,indent=2),encoding='utf-8')
client.close()
