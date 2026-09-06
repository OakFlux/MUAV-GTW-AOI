from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests

OUT = Path('out_qunabox_hibor_public')
PDFS = OUT / 'pdfs'
OUT.mkdir(exist_ok=True)
PDFS.mkdir(exist_ok=True)

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
})

pages = [
    'https://wap.hibor.com.cn/repinfodetail_3863473.html',
    'https://www.hibor.com.cn/repinfodetail_3863473.html',
    'https://www.hibor.com.cn/docdetail_3863473.html',
]

results = []
seen = set()

for index, url in enumerate(pages):
    try:
        response = session.get(url, timeout=60, allow_redirects=True)
        print('PAGE', index, response.status_code, response.headers.get('content-type'), len(response.content), response.url)
        text = response.text
        (OUT / f'page_{index}.html').write_text(text, encoding='utf-8', errors='ignore')

        links = []
        for match in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', text, re.I | re.S):
            href = urljoin(response.url, html.unescape(match.group(1)))
            label = re.sub(r'<[^>]+>', ' ', match.group(2))
            label = re.sub(r'\s+', ' ', html.unescape(label)).strip()
            links.append({'text': label, 'href': href})
        scripts = [urljoin(response.url, html.unescape(src)) for src in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', text, re.I)]
        (OUT / f'page_{index}_links.json').write_text(json.dumps(links, ensure_ascii=False, indent=2), encoding='utf-8')

        candidates = set()
        for item in links:
            blob = f"{item['text']} {item['href']}"
            if re.search(r'报告原文|報告原文|下载报告|下載報告|download|original|pdf|report', blob, re.I):
                print('LINK', index, json.dumps(item, ensure_ascii=False))
                candidates.add(item['href'])
        for pattern in [
            r'https?://[^"\'<>\s]+\.pdf(?:\?[^"\'<>\s]*)?',
            r'(?:pdfUrl|pdf_url|fileUrl|file_url|downloadUrl|download_url|originalUrl|original_url)["\'\s:=]+["\']([^"\']+)["\']',
        ]:
            for match in re.finditer(pattern, text, re.I):
                raw = match.group(1) if match.lastindex else match.group(0)
                candidates.add(urljoin(response.url, html.unescape(raw).replace('\\/', '/')))

        for script_index, script_url in enumerate(scripts):
            try:
                script_response = session.get(script_url, timeout=45, headers={'Referer': response.url})
                script_text = script_response.text
                (OUT / f'page_{index}_script_{script_index}.js').write_text(script_text, encoding='utf-8', errors='ignore')
                if re.search(r'3863473|报告原文|下載報告|下载报告|pdfUrl|fileUrl|downloadUrl', script_text, re.I):
                    for match in re.finditer(r'https?://[^"\'<>\s]+\.pdf(?:\?[^"\'<>\s]*)?', script_text, re.I):
                        candidates.add(html.unescape(match.group(0)).replace('\\/', '/'))
            except Exception as exc:
                print('SCRIPT_ERROR', script_url, repr(exc))

        for candidate in sorted(candidates):
            if candidate in seen or not candidate.startswith(('http://', 'https://')):
                continue
            seen.add(candidate)
            try:
                file_response = session.get(candidate, timeout=90, headers={'Referer': response.url}, allow_redirects=True)
                content_type = file_response.headers.get('content-type', '')
                body = file_response.content
                print('CANDIDATE', file_response.status_code, content_type, len(body), candidate, 'FINAL', file_response.url)
                if file_response.status_code == 200 and len(body) > 50000 and body.startswith(b'%PDF-'):
                    digest = hashlib.sha256(body).hexdigest()
                    file_name = f'hibor_{digest[:12]}.pdf'
                    (PDFS / file_name).write_bytes(body)
                    results.append({'source_page': response.url, 'url': candidate, 'final_url': file_response.url, 'file_name': file_name, 'bytes': len(body), 'sha256': digest})
            except Exception as exc:
                print('CANDIDATE_ERROR', candidate, repr(exc))
    except Exception as exc:
        print('PAGE_ERROR', url, repr(exc))

(OUT / 'manifest.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print('DONE', len(results))
