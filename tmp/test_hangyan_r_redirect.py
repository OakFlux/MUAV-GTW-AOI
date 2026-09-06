from __future__ import annotations
import json,re,html
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

OUT=Path('out_hangyan_redirect_test');OUT.mkdir(exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36','Accept-Language':'zh-CN,zh;q=0.9'})
url='https://www.hangyan.co/charts/3601111842144912396'
r=s.get(url,timeout=60);print('GET',r.status_code,len(r.content),r.url,r.history)
r.raise_for_status();(OUT/'chart.html').write_bytes(r.content)
soup=BeautifulSoup(r.text,'html.parser')
csrf_param=(soup.find('meta',attrs={'name':'csrf-param'}) or {}).get('content','authenticity_token')
csrf_token=(soup.find('meta',attrs={'name':'csrf-token'}) or {}).get('content','')
print('CSRF',csrf_param,csrf_token[:20],len(csrf_token))
anchors=[]
for a in soup.select('a[data-controller="protected-link"]'):
 anchors.append({'text':' '.join(a.get_text(' ',strip=True).split()),'token':a.get('data-protected-link-token-value',''),'turbo':a.get('data-protected-link-turbo-value','')})
print('ANCHORS',json.dumps(anchors,ensure_ascii=False,indent=2))
results=[]
for idx,a in enumerate(anchors):
 data={'token':a['token']}
 if csrf_token:data[csrf_param]=csrf_token
 headers={'Referer':url,'Origin':'https://www.hangyan.co','Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'}
 rr=s.post('https://www.hangyan.co/r',data=data,headers=headers,timeout=60,allow_redirects=False)
 print('POST',idx,rr.status_code,rr.headers.get('location'),rr.headers.get('content-type'),len(rr.content),rr.text[:500].replace('\n',' '))
 row={'anchor':a,'status':rr.status_code,'location':rr.headers.get('location'),'headers':dict(rr.headers),'body':rr.text[:10000]}
 if rr.is_redirect or rr.is_permanent_redirect:
  loc=urljoin(str(rr.url),rr.headers['location'])
  follow=s.get(loc,headers={'Referer':url},timeout=60,allow_redirects=True)
  print('FOLLOW',idx,follow.status_code,follow.url,len(follow.content),follow.history)
  row['follow_url']=follow.url;row['follow_status']=follow.status_code;row['follow_body']=follow.text[:30000]
  (OUT/f'follow_{idx}.html').write_bytes(follow.content)
 results.append(row)
(OUT/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
