from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

OUT = Path('out_sdicsi_sinofert_inspect')
OUT.mkdir(exist_ok=True)
BASE = 'https://www.sdicsi.com.hk'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
client = httpx.Client(http2=True, follow_redirects=True, timeout=45, headers={'User-Agent': UA, 'Accept-Language':'zh-CN,zh;q=0.9,en;q=0.8'})


def clean(s: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html.unescape(s))).strip()


def inspect_html(label: str, url: str):
    r = client.get(url)
    print('GET', label, r.status_code, len(r.content), r.headers.get('content-type'), r.url)
    OUT.joinpath(label + '.html').write_bytes(r.content)
    text = r.text
    links=[]
    for m in re.finditer(r'<a\b([^>]*)href=["\']([^"\']+)["\']([^>]*)>(.*?)</a>', text, re.I|re.S):
        href = urljoin(str(r.url), html.unescape(m.group(2)))
        txt = clean(m.group(4))
        attrs = m.group(1)+m.group(3)
        if txt or href:
            links.append({'text':txt,'href':href,'attrs':attrs[:500]})
    pdfs = sorted(set(re.findall(r'https?://[^"\'<>\s]+\.pdf(?:\?[^"\'<>\s]*)?', text, re.I)))
    relative_pdfs = sorted(set(urljoin(str(r.url), x) for x in re.findall(r'(?:href|src)=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', text, re.I)))
    print('PDFS', label, json.dumps(sorted(set(pdfs+relative_pdfs)), ensure_ascii=False))
    for item in links:
        hay = (item['text']+' '+item['href']).lower()
        if any(x in hay for x in ['中化化肥','297.hk','297hk','00297','research-report','report','pdf']):
            print('LINK', label, json.dumps(item, ensure_ascii=False)[:1800])
    OUT.joinpath(label+'_links.json').write_text(json.dumps(links, ensure_ascii=False, indent=2), encoding='utf-8')
    return r, links

# Tag pages in all languages.
all_links=[]
for i, url in enumerate([
    BASE+'/zh/research-report/tag/297hk',
    BASE+'/cn/research-report/tag/297hk',
    BASE+'/en/research-report/tag/297hk',
    BASE+'/zh/research-report/tag/00297hk',
    BASE+'/cn/research-report/tag/00297hk',
]):
    try:
        _, links = inspect_html(f'tag_{i}', url)
        all_links.extend(links)
    except Exception as exc:
        print('TAG ERROR', url, repr(exc))

# Probe common CMS / WP APIs.
api_urls = [
    BASE+'/wp-json/',
    BASE+'/wp-json/wp/v2/search?search=%E4%B8%AD%E5%8C%96%E5%8C%96%E8%82%A5&per_page=100',
    BASE+'/wp-json/wp/v2/posts?search=%E4%B8%AD%E5%8C%96%E5%8C%96%E8%82%A5&per_page=100&_embed=1',
    BASE+'/wp-json/wp/v2/research-report?search=%E4%B8%AD%E5%8C%96%E5%8C%96%E8%82%A5&per_page=100&_embed=1',
    BASE+'/api/search?keyword=%E4%B8%AD%E5%8C%96%E5%8C%96%E8%82%A5',
    BASE+'/api/research-report?tag=297hk',
]
for i,url in enumerate(api_urls):
    try:
        r=client.get(url, headers={'Accept':'application/json,text/plain,*/*'})
        print('API', i, r.status_code, len(r.content), r.headers.get('content-type'), r.url, r.text[:1000].replace('\n',' '))
        OUT.joinpath(f'api_{i}.txt').write_bytes(r.content)
    except Exception as exc:
        print('API ERROR', url, repr(exc))

# Fetch all unique official candidate links under research-report, excluding generic category/tag pages.
candidates=[]
for item in all_links:
    href=item['href']
    p=urlparse(href)
    if p.netloc.endswith('sdicsi.com.hk') and '/research-report/' in p.path:
        if any(x in p.path for x in ['/tag/','/category/']) or p.path.rstrip('/').endswith('/research-report'):
            continue
        candidates.append(href)
for idx,url in enumerate(sorted(set(candidates))):
    try:
        inspect_html(f'article_{idx}', url)
    except Exception as exc:
        print('ARTICLE ERROR', url, repr(exc))

# Search site XML sitemaps for Sinofert article URLs.
for i,url in enumerate([BASE+'/sitemap.xml',BASE+'/sitemap_index.xml',BASE+'/wp-sitemap.xml',BASE+'/robots.txt']):
    try:
        r=client.get(url)
        print('SITEMAP', i, r.status_code, len(r.content), r.url)
        OUT.joinpath(f'sitemap_{i}.txt').write_bytes(r.content)
        if 'xml' in (r.headers.get('content-type') or '').lower() or '<loc>' in r.text:
            locs=re.findall(r'<loc>(.*?)</loc>',r.text,re.I|re.S)
            for loc in locs:
                if 'research' in loc.lower() or 'post' in loc.lower(): print('LOC',html.unescape(loc))
    except Exception as exc:
        print('SITEMAP ERROR',url,repr(exc))

client.close()
