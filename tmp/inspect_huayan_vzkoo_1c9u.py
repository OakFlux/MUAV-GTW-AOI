from __future__ import annotations
import html, json, re, hashlib
from pathlib import Path
from urllib.parse import urljoin, unquote
import httpx
from pypdf import PdfReader

OUT=Path('out_huayan_vzkoo_1c9u'); OUT.mkdir(exist_ok=True); PDFS=OUT/'pdfs'; PDFS.mkdir(exist_ok=True)
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
client=httpx.Client(http2=True,follow_redirects=True,timeout=httpx.Timeout(60,connect=20),headers={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9,en;q=0.8'})
pages=[
 ('vzkoo','https://www.vzkoo.com/read/1136817497660001144e2b0d6510.html'),
 ('1c9u','https://www.1c9u.com/zhishiku/%E4%BA%BA%E5%BD%A2%E6%9C%BA%E5%99%A8%E4%BA%BA%E7%9F%A5%E8%AF%86%E5%BA%93'),
 ('1c9u2','https://1c9u.com/zhishiku/%E4%BA%BA%E5%BD%A2%E6%9C%BA%E5%99%A8%E4%BA%BA%E7%9F%A5%E8%AF%86%E5%BA%93'),
]

def save_pdf(url,label):
 try:
  r=client.get(url,headers={'Referer':'https://www.vzkoo.com/','Accept':'application/pdf,application/octet-stream,*/*'})
  print('PDF_PROBE',r.status_code,r.headers.get('content-type'),len(r.content),r.url)
  if r.status_code==200 and len(r.content)>80000 and r.content.startswith(b'%PDF-'):
   h=hashlib.sha256(r.content).hexdigest(); p=PDFS/f'{label}_{h[:12]}.pdf'; p.write_bytes(r.content)
   rd=PdfReader(str(p),strict=False); pages=len(rd.pages); text='\n'.join((pg.extract_text() or '') for pg in rd.pages[:min(15,pages)])
   identity=any(x in re.sub(r'\s+','',text).lower() for x in ['华沿机器人','華沿機器人','huayanrobotics','01021','1021hk'])
   print('VALID_PDF',p,pages,identity,text[:1000].replace('\n',' '))
   return {'url':url,'path':str(p),'pages':pages,'identity_ok':identity,'sha256':h}
 except Exception as e: print('PDF_ERR',url,repr(e))
 return None

allout=[]; seen=set()
for label,url in pages:
 try:
  r=client.get(url); text=r.text; (OUT/f'{label}.html').write_text(text,encoding='utf-8',errors='ignore')
  print('PAGE',label,r.status_code,r.headers.get('content-type'),len(r.content),r.url)
  scripts=[urljoin(str(r.url),html.unescape(x)) for x in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']',text,re.I)]
  links=set(re.findall(r'https?://[^"\'<>\s]+',text))
  links.update(urljoin(str(r.url),html.unescape(x)) for x in re.findall(r'(?:href|src|data-url|data-file|data-src|content)=["\']([^"\']+)["\']',text,re.I))
  interesting=[]
  for x in sorted(links):
   x=html.unescape(x).replace('\\/','/').rstrip(');,')
   if any(k in x.lower() for k in ['.pdf','download','file','attach','oss','cos','storage','1136817497660001144e2b0d6510','20260807','1021']):
    interesting.append(x); print('LINK',label,x)
    if x not in seen and '.pdf' in x.lower():
     seen.add(x); save_pdf(x,label)
  contexts=[]
  pats=['20260807','华沿机器人','卖铲人','pdf','download','fileUrl','file_url','attachment','oss','cos','docId','documentId','knowledge','douyinbao']
  for pat in pats:
   for m in list(re.finditer(pat,text,re.I))[:20]:
    c=text[max(0,m.start()-500):m.end()+1200]
    contexts.append({'pattern':pat,'context':c}); print('CTX',label,pat,c.replace('\n',' ')[:1800])
  allout.append({'label':label,'url':str(r.url),'scripts':scripts,'interesting':interesting,'contexts':contexts})
  for si,surl in enumerate(scripts[:30]):
   try:
    sr=client.get(surl); st=sr.text
    if any(p.lower() in st.lower() for p in ['download','pdf','fileurl','attachment','docid']):
     (OUT/f'{label}_script_{si}.js').write_text(st,encoding='utf-8',errors='ignore')
     print('SCRIPT',label,si,sr.status_code,len(st),surl)
     for pat in ['download','pdf','fileUrl','file_url','attachment','oss','cos','docId','documentId']:
      for m in list(re.finditer(pat,st,re.I))[:20]: print('SCRIPT_CTX',label,pat,st[max(0,m.start()-350):m.end()+700].replace('\n',' ')[:1200])
   except Exception as e: print('SCRIPT_ERR',surl,repr(e))
 except Exception as e: print('PAGE_ERR',label,url,repr(e))
(OUT/'results.json').write_text(json.dumps(allout,ensure_ascii=False,indent=2),encoding='utf-8')
client.close()
