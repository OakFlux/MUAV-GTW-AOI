from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urljoin

import requests
from pypdf import PdfReader

OUT = Path('out_ascletis_open_index')
PDFS = OUT / 'pdfs'
OUT.mkdir(exist_ok=True)
PDFS.mkdir(exist_ok=True)
BASE = 'https://aigc.idigital.com.cn/djyanbao/'
HOST = 'aigc.idigital.com.cn'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'


def doh_lookup(name: str) -> dict:
    endpoint = 'https://dns.google/resolve'
    r = requests.get(
        endpoint,
        params={'name': name, 'type': 'A'},
        headers={'User-Agent': UA, 'Accept': 'application/dns-json'},
        timeout=30,
    )
    print('DOH', name, r.status_code, len(r.content), r.text[:1000])
    r.raise_for_status()
    return r.json()


def doh_ips() -> list[str]:
    queue = [HOST]
    visited = set()
    ips: list[str] = []
    traces = []
    while queue and len(visited) < 12:
        name = queue.pop(0).rstrip('.')
        if not name or name in visited:
            continue
        visited.add(name)
        try:
            obj = doh_lookup(name)
            traces.append({'name': name, 'response': obj})
            for ans in obj.get('Answer') or []:
                data = str(ans.get('data') or '').rstrip('.')
                rtype = int(ans.get('type') or 0)
                if rtype == 1 and re.fullmatch(r'\d{1,3}(?:\.\d{1,3}){3}', data):
                    ips.append(data)
                elif rtype == 5 and data and data not in visited:
                    queue.append(data)
        except Exception as exc:
            print('DOH_ERR', name, repr(exc))
    (OUT/'dns_trace.json').write_text(json.dumps(traces, ensure_ascii=False, indent=2), encoding='utf-8')
    return list(dict.fromkeys(ips))


def curl_get(url: str, output: Path, ip: str, max_time: int=240) -> bool:
    output.unlink(missing_ok=True)
    cmd = [
        'curl', '-L', '--fail', '--silent', '--show-error', '--retry', '2',
        '--connect-timeout', '20', '--max-time', str(max_time),
        '--resolve', f'{HOST}:443:{ip}', '-A', UA,
        '-H', f'Referer: {BASE}', '-o', str(output), url,
    ]
    result = subprocess.run(cmd, capture_output=True)
    print('CURL', ip, url, result.returncode, output.stat().st_size if output.exists() else 0, result.stderr.decode(errors='ignore')[-500:])
    return result.returncode == 0 and output.exists() and output.stat().st_size > 0


ips = doh_ips()
print('IPS', ips)
if not ips:
    raise RuntimeError('No A records after resolving public CNAME chain')
index_path = OUT / 'index.html'
for ip in ips:
    if curl_get(BASE, index_path, ip, 300) and index_path.stat().st_size > 100000:
        break
if not index_path.exists() or index_path.stat().st_size < 100000:
    raise RuntimeError('Could not fetch directory index with --resolve')
raw = index_path.read_bytes()
index = ''
for encoding in ['utf-8', 'gb18030', 'latin1']:
    try:
        index = raw.decode(encoding)
        if 'Index of' in index or '<a ' in index:
            break
    except Exception:
        pass
print('INDEX_BYTES', len(raw), 'CHARS', len(index))

keys = [
    '歌礼制药', '歌禮製藥', 'ascletis', '全新GLP-1减重不减肌', '口服小分子率先破局',
    '口服小分子GLP-1激动剂展现BIC潜力', 'ASC30完成IIa期患者入组', '代谢管线全面推进',
]


def decoded(value: str) -> str:
    value = html.unescape(value.strip())
    for _ in range(3):
        new = unquote(value)
        if new == value:
            break
        value = new
    return value


def relevant(value: str) -> bool:
    compact = value.lower().replace(' ', '')
    return any(k.lower().replace(' ', '') in compact for k in keys)


links = []
for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', index, re.I | re.S):
    raw_href = html.unescape(m.group(1))
    href_dec = decoded(raw_href)
    anchor = decoded(re.sub(r'<[^>]+>', '', m.group(2)))
    if relevant(href_dec) or relevant(anchor):
        links.append({'name': anchor or href_dec.split('/')[-1], 'raw_href': raw_href, 'decoded_href': href_dec, 'url': urljoin(BASE, raw_href)})

for key in keys:
    for m in re.finditer(re.escape(key), index, re.I):
        context = index[max(0, m.start() - 1000):m.end() + 1000]
        for href in re.findall(r'href=["\']([^"\']+\.pdf)["\']', context, re.I):
            raw_href = html.unescape(href)
            href_dec = decoded(raw_href)
            item = {'name': href_dec.split('/')[-1], 'raw_href': raw_href, 'decoded_href': href_dec, 'url': urljoin(BASE, raw_href)}
            if item not in links:
                links.append(item)

uniq = {item['url']: item for item in links}
links = list(uniq.values())
print('MATCHES', len(links))
for item in links:
    print('MATCH', json.dumps(item, ensure_ascii=False))
(OUT/'matched_links.json').write_text(json.dumps(links, ensure_ascii=False, indent=2), encoding='utf-8')

valid = []
seen = set()
for idx, item in enumerate(links, 1):
    out = PDFS / f'{idx:02d}_candidate.pdf'
    ok = False
    for ip in ips:
        if curl_get(item['url'], out, ip, 300) and out.stat().st_size > 50000 and out.read_bytes()[:5] == b'%PDF-':
            ok = True
            break
    if not ok:
        out.unlink(missing_ok=True)
        continue
    try:
        reader = PdfReader(str(out), strict=False)
        pages = len(reader.pages)
        sample = '\n'.join((reader.pages[i].extract_text() or '') for i in range(min(pages, 15)))
        norm = re.sub(r'\s+', '', sample).lower()
        identity_ok = any(x in norm for x in ['歌礼制药', '歌禮製藥', 'ascletis', '01672', '1672.hk'])
        sha = hashlib.sha256(out.read_bytes()).hexdigest()
        if sha in seen:
            out.unlink()
            continue
        seen.add(sha)
        final = PDFS / f'{idx:02d}_{sha[:12]}.pdf'
        out.rename(final)
        meta = {'path': str(final), 'name': item['name'], 'source_url': item['url'], 'pages': pages, 'bytes': final.stat().st_size, 'sha256': sha, 'identity_ok': identity_ok, 'sample': sample[:8000]}
        valid.append(meta)
        print('VALID', json.dumps({k: v for k, v in meta.items() if k != 'sample'}, ensure_ascii=False))
    except Exception as exc:
        print('VALIDATE_ERR', item['url'], repr(exc))
        out.unlink(missing_ok=True)

(OUT/'valid.json').write_text(json.dumps(valid, ensure_ascii=False, indent=2), encoding='utf-8')
print('DONE', len(valid))
