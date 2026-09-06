from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import quote, unquote, urljoin

import requests
from pypdf import PdfReader

OUT = Path('out_ascletis_open_index')
PDFS = OUT / 'pdfs'
OUT.mkdir(exist_ok=True)
PDFS.mkdir(exist_ok=True)
BASE = 'https://aigc.idigital.com.cn/djyanbao/'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
S = requests.Session()
S.headers.update({'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'})


def fetch_index() -> str:
    attempts = []
    urls = [BASE, BASE + '?C=N;O=A', BASE + '?C=M;O=D']
    headers_list = [
        {'Accept':'text/html,application/xhtml+xml,*/*'},
        {'Accept':'*/*','Referer':'https://aigc.idigital.com.cn/'},
        {'User-Agent':'curl/8.5.0','Accept':'*/*'},
    ]
    for url in urls:
        for headers in headers_list:
            try:
                r = S.get(url, headers=headers, timeout=180, verify=True)
                print('INDEX_GET', r.status_code, len(r.content), r.headers.get('content-type'), r.url)
                attempts.append({'url':url,'status':r.status_code,'bytes':len(r.content),'ct':r.headers.get('content-type')})
                if r.status_code == 200 and len(r.content) > 100000:
                    encoding = r.encoding or 'utf-8'
                    text = r.content.decode(encoding, errors='replace')
                    (OUT/'index.html').write_text(text, encoding='utf-8')
                    return text
            except Exception as exc:
                print('INDEX_ERR', url, repr(exc))
                attempts.append({'url':url,'error':repr(exc)})
    # curl fallback
    try:
        result = subprocess.run(['curl','-L','--retry','3','--max-time','240','-A',UA,BASE], capture_output=True, check=False)
        print('CURL_INDEX', result.returncode, len(result.stdout), result.stderr.decode(errors='ignore')[-500:])
        if result.returncode == 0 and len(result.stdout) > 100000:
            text = result.stdout.decode('utf-8', errors='replace')
            (OUT/'index.html').write_text(text, encoding='utf-8')
            return text
    except Exception as exc:
        print('CURL_ERR', repr(exc))
    (OUT/'attempts.json').write_text(json.dumps(attempts, ensure_ascii=False, indent=2), encoding='utf-8')
    raise RuntimeError('Unable to fetch open directory listing')


def decode_href(value: str) -> str:
    value = html.unescape(value.strip())
    try:
        return unquote(value)
    except Exception:
        return value


def is_relevant(name: str) -> bool:
    norm = name.lower().replace(' ', '')
    keys = [
        '歌礼制药', '歌禮製藥', '歌礼制药-b', 'ascletis',
        '全新glp-1减重不减肌', '口服小分子率先破局',
        '口服小分子glp-1激动剂展现bic潜力',
        'asc30完成iia期患者入组', '代谢管线全面推进',
    ]
    return any(key.lower().replace(' ', '') in norm for key in keys)


def download_pdf(url: str, path: Path) -> bool:
    methods = [
        ({'Accept':'application/pdf,*/*','Referer':BASE}, True),
        ({'Accept':'*/*','Referer':'https://aigc.idigital.com.cn/'}, True),
        ({'User-Agent':'curl/8.5.0','Accept':'*/*'}, True),
    ]
    for headers, verify in methods:
        try:
            r = S.get(url, headers=headers, timeout=240, verify=verify, allow_redirects=True)
            print('PDF_GET', r.status_code, r.headers.get('content-type'), len(r.content), r.url)
            if r.status_code == 200 and len(r.content) > 50000 and r.content.startswith(b'%PDF-'):
                path.write_bytes(r.content)
                return True
        except Exception as exc:
            print('PDF_ERR', url, repr(exc))
    return False


index = fetch_index()
links = []
for match in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', index, re.I|re.S):
    href = decode_href(match.group(1))
    anchor = re.sub(r'<[^>]+>', '', html.unescape(match.group(2))).strip()
    name = decode_href(anchor or href)
    if is_relevant(name) or is_relevant(href):
        links.append({'name':name,'href':href,'url':urljoin(BASE, match.group(1))})

# Search raw HTML too, to catch truncated display names while href contains encoded full filename.
for raw in re.findall(r'(?:href=["\'])([^"\']+\.pdf)(?:["\'])', index, re.I):
    decoded = decode_href(raw)
    if is_relevant(decoded):
        item = {'name':decoded.split('/')[-1], 'href':decoded, 'url':urljoin(BASE, raw)}
        if item not in links:
            links.append(item)

print('MATCHED_LINKS', len(links))
for item in links:
    print('MATCH', json.dumps(item, ensure_ascii=False))
(OUT/'matched_links.json').write_text(json.dumps(links, ensure_ascii=False, indent=2), encoding='utf-8')

valid = []
seen = set()
for idx, item in enumerate(links, 1):
    path = PDFS / f'{idx:02d}_candidate.pdf'
    if not download_pdf(item['url'], path):
        continue
    try:
        reader = PdfReader(str(path), strict=False)
        pages = len(reader.pages)
        sample = '\n'.join((reader.pages[i].extract_text() or '') for i in range(min(pages, 15)))
        norm = re.sub(r'\s+', '', sample).lower()
        identity_ok = any(k in norm for k in ['歌礼制药','歌禮製藥','ascletis','01672','1672.hk'])
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if sha in seen:
            path.unlink(missing_ok=True)
            continue
        seen.add(sha)
        final = PDFS / f'{idx:02d}_{sha[:12]}.pdf'
        path.rename(final)
        meta = {'path':str(final),'name':item['name'],'source_url':item['url'],'pages':pages,'bytes':final.stat().st_size,'sha256':sha,'identity_ok':identity_ok,'sample':sample[:6000]}
        valid.append(meta)
        print('VALID', json.dumps({k:v for k,v in meta.items() if k!='sample'}, ensure_ascii=False))
    except Exception as exc:
        print('VALIDATE_ERR', item['url'], repr(exc))
        path.unlink(missing_ok=True)

(OUT/'valid.json').write_text(json.dumps(valid, ensure_ascii=False, indent=2), encoding='utf-8')
print('DONE', len(valid))
