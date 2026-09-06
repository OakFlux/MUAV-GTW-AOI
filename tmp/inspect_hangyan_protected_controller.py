from __future__ import annotations
import json,re
from pathlib import Path
import requests

OUT=Path('out_hangyan_controller');OUT.mkdir(exist_ok=True)
urls=[
 'https://cdn.hangyan.co/assets/application-ec845e69.js',
 'https://www.hangyan.co/charts/3601111842144912396',
]
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0','Referer':'https://www.hangyan.co/'})
for i,u in enumerate(urls):
 r=s.get(u,timeout=60);print('GET',i,r.status_code,r.headers.get('content-type'),len(r.content),r.url)
 p=OUT/f'file_{i}.txt';p.write_bytes(r.content)
 text=r.text
 for pat in ['protected-link','protected_link','token-value','turbo-value','google_vignette','/protected','decrypt','atob','AES','fetch(']:
  hits=list(re.finditer(re.escape(pat),text,re.I))
  print('PAT',pat,'COUNT',len(hits))
  for m in hits[:20]: print('CTX',pat,text[max(0,m.start()-1200):m.end()+2500].replace('\n',' ')[:5000])
 # URL/path candidates
 cands=sorted(set(re.findall(r'["\']([^"\']{0,300}(?:protected|link|token|redirect)[^"\']{0,300})["\']',text,re.I)))
 print('CANDS',json.dumps(cands[:500],ensure_ascii=False))
(OUT/'done.txt').write_text('ok',encoding='utf-8')
