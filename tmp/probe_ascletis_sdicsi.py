from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

OUT = Path('out_ascletis_sdicsi')
PDFS = OUT / 'pdfs'
OUT.mkdir(exist_ok=True)
PDFS.mkdir(exist_ok=True)
BASE = 'https://www.sdicsi.com.hk'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36'
S = requests.Session()
S.headers.update({'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'})

KEYS = ['歌礼制药', '歌禮製藥', 'Ascletis', '01672', '1672.HK', '1672HK', '口服小分子GLP-1', 'BIC潜力']


def relevant(text: str) -> bool:
    compact = re.sub(r'\s+', '', html.unescape(text or '')).lower()
    return any(re.sub(r'\s+', '', k).lower() in compact for k in KEYS)


def get(url: str, label: str, accept='text/html,*/*') -> requests.Response | None:
    for attempt in range(1, 5):
        try:
            r = S.get(url, timeout=90, headers={'Accept': accept, 'Referer': BASE + '/cn/research-report'})
            print('GET', label, attempt, r.status_code, r.headers.get('content-type'), len(r.content), r.url)
            OUT.joinpath(f'{label}.body').write_bytes(r.content)
            return r
        except Exception as exc:
            print('GET_ERR', label, attempt, repr(exc))
            time.sleep(attempt * 2)
    return None


def save_pdf(data: bytes, label: str, url: str, metadata: dict) -> dict | None:
    if len(data) < 50000 or not data.startswith(b'%PDF-'):
        return None
    sha = hashlib.sha256(data).hexdigest()
    path = PDFS / f'{label}_{sha[:12]}.pdf'
    path.write_bytes(data)
    try:
        reader = PdfReader(str(path), strict=False)
        pages = len(reader.pages)
        indices = list(range(min(pages, 15)))
        if pages > 20:
            indices.extend([pages // 2, pages - 1])
        text = '\n'.join((reader.pages[i].extract_text() or '') for i in sorted(set(indices)))
        norm = re.sub(r'\s+', '', text).lower()
        identity_ok = any(token in norm for token in ['歌礼制药', '歌禮製藥', 'ascletis', '01672', '1672.hk'])
    except Exception as exc:
        print('PDF_PARSE_ERR', label, repr(exc))
        pages, text, identity_ok = -1, '', False
    item = {
        'path': str(path), 'source_url': url, 'pages': pages, 'bytes': len(data),
        'sha256': sha, 'identity_ok': identity_ok, 'sample': text[:10000], **metadata,
    }
    print('VALID_PDF', json.dumps({k:v for k,v in item.items() if k != 'sample'}, ensure_ascii=False))
    return item


pages_to_fetch = []
for lang in ['cn', 'zh', 'en']:
    pages_to_fetch.extend([
        (f'{lang}_tag_1672hk', f'{BASE}/{lang}/research-report/tag/1672hk'),
        (f'{lang}_tag_01672hk', f'{BASE}/{lang}/research-report/tag/01672hk'),
        (f'{lang}_tag_1672', f'{BASE}/{lang}/research-report/tag/1672'),
        (f'{lang}_research', f'{BASE}/{lang}/research-report'),
    ])

article_urls = set()
all_links = []
for label, url in pages_to_fetch:
    r = get(url, label)
    if not r or r.status_code != 200:
        continue
    text = r.text
    soup = BeautifulSoup(text, 'html.parser')
    page_title = soup.title.get_text(' ', strip=True) if soup.title else ''
    body_text = soup.get_text(' ', strip=True)
    print('PAGE_META', label, page_title, 'RELEVANT', relevant(page_title + ' ' + body_text))
    for tag in soup.find_all(['a','iframe','embed','object','img','source']):
        for attr in ['href','src','data','data-src','data-url','data-file']:
            raw = tag.get(attr)
            if not raw:
                continue
            absolute = urljoin(str(r.url), html.unescape(raw))
            anchor = tag.get_text(' ', strip=True)
            item = {'from': str(r.url), 'text': anchor, 'url': absolute}
            if relevant(anchor + ' ' + absolute) or '/research-report/' in absolute or '.pdf' in absolute.lower():
                all_links.append(item)
                print('LINK', json.dumps(item, ensure_ascii=False)[:1500])
            if '/research-report/' in absolute and '/tag/' not in absolute and absolute.rstrip('/') != f'{BASE}/{label.split("_")[0]}/research-report':
                article_urls.add(absolute)

# Public site search endpoints and search-engine style query pages.
search_urls = [
    f'{BASE}/cn/search?keyword={quote("歌礼制药")}',
    f'{BASE}/cn/research-report?keyword={quote("歌礼制药")}',
    f'{BASE}/cn/research-report?search={quote("1672.HK")}',
    f'{BASE}/cn/research-report/tag/1672hk?page=1',
]
for idx, url in enumerate(search_urls):
    r = get(url, f'search_{idx}')
    if not r or r.status_code != 200:
        continue
    soup = BeautifulSoup(r.text, 'html.parser')
    for a in soup.find_all('a', href=True):
        absolute = urljoin(str(r.url), html.unescape(a['href']))
        txt = a.get_text(' ', strip=True)
        if relevant(txt + ' ' + absolute):
            article_urls.add(absolute)
            all_links.append({'from':str(r.url),'text':txt,'url':absolute})
            print('SEARCH_LINK', txt, absolute)

# Crawl relevant article pages found from tags/research page.
article_data = []
for idx, url in enumerate(sorted(article_urls)):
    r = get(url, f'article_{idx}')
    if not r or r.status_code != 200:
        continue
    soup = BeautifulSoup(r.text, 'html.parser')
    title = soup.title.get_text(' ', strip=True) if soup.title else ''
    text = soup.get_text(' ', strip=True)
    is_rel = relevant(title + ' ' + text + ' ' + url)
    if not is_rel:
        continue
    item = {'url':str(r.url),'title':title,'text':text[:12000],'links':[]}
    print('RELEVANT_ARTICLE', title, r.url)
    for tag in soup.find_all(['a','iframe','embed','object','img','source']):
        for attr in ['href','src','data','data-src','data-url','data-file']:
            raw = tag.get(attr)
            if not raw:
                continue
            absolute = urljoin(str(r.url), html.unescape(raw))
            if '.pdf' in absolute.lower() or 'researchreports' in absolute.lower() or 'download' in absolute.lower():
                item['links'].append(absolute)
                print('ARTICLE_ASSET', absolute)
    # Raw HTML URL extraction catches links embedded in JS/JSON.
    raw_urls = re.findall(r'https?://[^"\'\\\s<>]+', r.text)
    for raw in raw_urls:
        absolute = html.unescape(raw).replace('\\/','/')
        if '.pdf' in absolute.lower() or 'researchreports' in absolute.lower():
            item['links'].append(absolute)
            print('RAW_ASSET', absolute)
    item['links'] = list(dict.fromkeys(item['links']))
    article_data.append(item)

(OUT/'all_links.json').write_text(json.dumps(all_links, ensure_ascii=False, indent=2), encoding='utf-8')
(OUT/'articles.json').write_text(json.dumps(article_data, ensure_ascii=False, indent=2), encoding='utf-8')

# Probe all PDF URLs discovered from article pages.
valid = []
seen_sha = set()
asset_urls = []
for article in article_data:
    asset_urls.extend(article['links'])
for link in all_links:
    if '.pdf' in link['url'].lower():
        asset_urls.append(link['url'])

# Probe official filename conventions around known publication dates.
root = BASE + '/backend/storage/app/media/ResearchReports/CorporateReports/'
dates = []
# SDIC report surfaced in public indexes on 2025-08-23; include surrounding business days.
for ymd in ['20250818','20250819','20250820','20250821','20250822','20250823','20250824','20250825','20250826',
            '20260330','20260331','20260401','20260402','20260403','20260406',
            '20260810','20260811','20260812','20260813','20260814']:
    dates.append(ymd)
for code in ['1672','01672','1672HK','01672HK']:
    for ymd in dates:
        for suffix in ['.pdf','_c.pdf','_C.pdf','-cn.pdf']:
            asset_urls.append(f'{root}{code}-{ymd}{suffix}')
# Other plausible folders.
for code in ['1672','01672']:
    for ymd in dates:
        asset_urls.extend([
            f'{BASE}/backend/storage/app/media/ResearchReports/CompanyReports/{code}-{ymd}.pdf',
            f'{BASE}/backend/storage/app/media/ResearchReports/CorporateReport/{code}-{ymd}.pdf',
            f'{BASE}/backend/storage/app/media/ResearchReports/CorporateReports/{ymd}-{code}.pdf',
        ])

for idx, url in enumerate(dict.fromkeys(asset_urls)):
    try:
        r = S.get(url, timeout=60, headers={'Accept':'application/pdf,*/*','Referer':BASE+'/cn/research-report'})
        if idx % 100 == 0 or r.status_code == 200:
            print('PROBE', idx, r.status_code, r.headers.get('content-type'), len(r.content), url)
        item = save_pdf(r.content, f'sdicsi_{idx:04d}', str(r.url), {'requested_url':url})
        if item and item['sha256'] not in seen_sha:
            seen_sha.add(item['sha256'])
            valid.append(item)
    except Exception as exc:
        if idx % 100 == 0:
            print('PROBE_ERR', idx, url, repr(exc))

(OUT/'valid.json').write_text(json.dumps(valid, ensure_ascii=False, indent=2), encoding='utf-8')
print('DONE', len(valid))
