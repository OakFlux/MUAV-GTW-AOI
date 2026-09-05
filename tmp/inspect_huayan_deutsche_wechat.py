from __future__ import annotations
import html,json,re
from pathlib import Path
from urllib.parse import urljoin
import httpx

OUT=Path('out_huayan_deutsche_wechat'); OUT.mkdir(exist_ok=True)
UA='Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 MicroMessenger/8.0.50 NetType/WIFI Language/zh_CN'
url='https://mp.weixin.qq.com/s/ykbXicJzYXyYVs6M0GIYYg'
c=httpx.Client(http2=True,follow_redirects=True,timeout=httpx.Timeout(90,connect=30),headers={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9','Referer':'https://mp.weixin.qq.com/'})
r=c.get(url)
print('PAGE',r.status_code,len(r.content),r.headers.get('content-type'),r.url)
OUT.joinpath('article.html').write_bytes(r.content)
t=r.text
print('TITLE',re.findall(r'<title[^>]*>(.*?)</title>',t,re.I|re.S)[:3])
# Save visible text.
text=re.sub(r'<script\b[^>]*>.*?</script>',' ',t,flags=re.I|re.S)
text=re.sub(r'<style\b[^>]*>.*?</style>',' ',text,flags=re.I|re.S)
text=re.sub(r'<[^>]+>','\n',text)
text=html.unescape(text)
text='\n'.join(line.strip() for line in text.splitlines() if line.strip())
OUT.joinpath('article.txt').write_text(text,encoding='utf-8')
print('TEXT',text[:6000])
# Extract every URL and special app link.
vals=set()
patterns=[r'https?://[^"\'<>\\\s]+',r'(?:href|src|data-src|data-original|data-link|data-url|data-file)=["\']([^"\']+)["\']',r'["\']([^"\']*(?:pan\.baidu|aliyundrive|quark|weiyun|lanzou|123pan|pdf|download|file|附件|下载)[^"\']*)["\']']
for pat in patterns:
 for x in re.findall(pat,t,re.I):
  x=html.unescape(x if isinstance(x,str) else x[0]).strip()
  if x: vals.add(urljoin(str(r.url),x))
interesting=sorted(vals)
OUT.joinpath('urls.json').write_text(json.dumps(interesting,ensure_ascii=False,indent=2),encoding='utf-8')
print('URLS',json.dumps([x for x in interesting if any(k in x.lower() for k in ['pdf','download','file','pan.baidu','aliyundrive','quark','weiyun','lanzou','123pan','mp.weixin.qq.com/s','res.wx.qq.com'])],ensure_ascii=False,indent=2))
# Extract all article images with sequence and context.
imgs=[]
for m in re.finditer(r'<img\b[^>]*>',t,re.I):
 tag=m.group(0)
 attrs={}
 for k,v in re.findall(r'([\w:-]+)=["\']([^"\']*)["\']',tag): attrs[k]=html.unescape(v)
 src=attrs.get('data-src') or attrs.get('src') or attrs.get('data-original')
 if not src: continue
 before=re.sub(r'<[^>]+>',' ',t[max(0,m.start()-1000):m.start()])
 after=re.sub(r'<[^>]+>',' ',t[m.end():m.end()+1000])
 item={'index':len(imgs)+1,'src':urljoin(str(r.url),src),'attrs':attrs,'before':html.unescape(re.sub(r'\s+',' ',before)).strip(),'after':html.unescape(re.sub(r'\s+',' ',after)).strip()}
 imgs.append(item)
OUT.joinpath('images.json').write_text(json.dumps(imgs,ensure_ascii=False,indent=2),encoding='utf-8')
print('IMAGES',len(imgs))
for item in imgs: print('IMG_META',json.dumps(item,ensure_ascii=False)[:2500])
# Download images; retain actual bytes for visual inspection.
for item in imgs:
 try:
  rr=c.get(item['src'],headers={'Referer':str(r.url),'User-Agent':UA,'Accept':'image/avif,image/webp,image/apng,image/*,*/*;q=0.8'})
  ct=(rr.headers.get('content-type') or '').lower()
  ext='.jpg'
  if 'png' in ct: ext='.png'
  elif 'webp' in ct: ext='.webp'
  elif 'gif' in ct: ext='.gif'
  name=f"img_{item['index']:03d}{ext}"
  OUT.joinpath(name).write_bytes(rr.content)
  print('IMG',item['index'],rr.status_code,len(rr.content),ct,rr.url,name)
 except Exception as e: print('IMG_ERR',item['index'],repr(e))
# Print contexts around download-related terms.
for term in ['下载','附件','原文','报告','百度网盘','提取码','夸克','PDF','阅读原文','点击']:
 for m in list(re.finditer(term,t,re.I))[:30]: print('CTX',term,t[max(0,m.start()-800):m.end()+1400].replace('\n',' ')[:2600])
c.close()
