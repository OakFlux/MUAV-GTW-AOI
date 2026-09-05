from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path
from urllib.parse import quote, urljoin

import httpx
from pypdf import PdfReader

OUT = Path('out_huayan_sina_report')
PDF_DIR = OUT / 'pdfs'
OUT.mkdir(exist_ok=True)
PDF_DIR.mkdir(exist_ok=True)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
client = httpx.Client(http2=True, follow_redirects=True, timeout=httpx.Timeout(90, connect=25), headers={
    'User-Agent': UA,
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
})

TITLES = [
    '华沿机器人(1021.HK)人形机器人行业系列(4)：“卖铲人”型平台公司，运动控制底层价值有望重估',
    '头部协作机器人公司，七轴人形手臂放量可期',
    '协作机器人头部企业，具身智能空间广阔',
    '协作机器人与人形机器人核心部件龙头',
]
KNOWN = [
    'https://stock.finance.sina.com.cn/hkstock/view/hk_report.php?reportid=839511181107',
    'https://finance.sina.com.cn/stock/hkstock/marketalerts/2026-06-06/doc-iniamtiv0919967.shtml',
    'https://finance.sina.com.cn/stock/hkstock/hkgg/2026-05-26/doc-inhzffsp2260795.shtml',
    'https://finance.sina.com.cn/stock/hkstock/hkgg/2026-05-25/doc-inhzawmn3606327.shtml',
    'https://stock.finance.sina.com.cn/hkstock/news/01021.html',
]

results: dict = {'pages': [], 'candidate_links': [], 'pdfs': []}
seen_pages: set[str] = set()
seen_links: set[str] = set()


def decode_body(response: httpx.Response) -> str:
    raw = response.content
    head = raw[:5000].lower()
    candidates = []
    m = re.search(br'charset\s*=\s*["\']?([a-zA-Z0-9_-]+)', head)
    if m:
        candidates.append(m.group(1).decode('ascii', errors='ignore'))
    candidates += [response.encoding or '', 'utf-8', 'gb18030', 'gbk']
    for enc in candidates:
        if not enc:
            continue
        try:
            text = raw.decode(enc)
            if '�' not in text[:1000] or enc.lower().startswith('gb'):
                return text
        except Exception:
            pass
    return raw.decode('utf-8', errors='ignore')


def normalize_escaped(text: str) -> str:
    text = html.unescape(text)
    text = text.replace('\\/','/')
    try:
        text = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), text)
    except Exception:
        pass
    return text


def extract_links(text: str, base: str) -> set[str]:
    text2 = normalize_escaped(text)
    links: set[str] = set()
    patterns = [
        r'https?://[^\s"\'<>\\]+',
        r'(?:href|src|data-src|data-url|data-file|url|file|pdfUrl|downloadUrl)\s*[=:]\s*["\']([^"\']+)["\']',
    ]
    for pidx, pat in enumerate(patterns):
        for match in re.finditer(pat, text2, re.I):
            val = match.group(0 if pidx == 0 else 1).strip().rstrip(');,]')
            if val.startswith('//'):
                val = 'https:' + val
            if not val.startswith('http'):
                val = urljoin(base, val)
            if val.startswith('http'):
                links.add(val)
    return links


def validate_pdf(data: bytes, url: str, label: str) -> dict | None:
    if len(data) < 60_000 or not data.startswith(b'%PDF-'):
        return None
    sha = hashlib.sha256(data).hexdigest()
    path = PDF_DIR / f'{label}_{sha[:12]}.pdf'
    path.write_bytes(data)
    try:
        reader = PdfReader(str(path), strict=False)
        pages = len(reader.pages)
        sample = '\n'.join((reader.pages[i].extract_text() or '') for i in range(min(pages, 20)))
    except Exception as exc:
        print('PDF_PARSE_ERR', url, repr(exc))
        path.unlink(missing_ok=True)
        return None
    norm = re.sub(r'\s+', '', sample).lower()
    identity = any(token in norm for token in ['华沿机器人','華沿機器人','huayanrobotics','1021hk','01021'])
    meta = {'url': url, 'path': str(path), 'bytes': len(data), 'sha256': sha, 'pages': pages, 'identity_ok': identity, 'sample': sample[:4000]}
    print('VALID_PDF', json.dumps({k:v for k,v in meta.items() if k != 'sample'}, ensure_ascii=False))
    results['pdfs'].append(meta)
    return meta


def fetch_page(url: str, label: str) -> tuple[str, str] | None:
    if url in seen_pages:
        return None
    seen_pages.add(url)
    try:
        r = client.get(url, headers={'Referer': 'https://stock.finance.sina.com.cn/hkstock/news/01021.html'})
        ct = r.headers.get('content-type','')
        print('GET', label, r.status_code, ct, len(r.content), str(r.url))
        if validate_pdf(r.content, str(r.url), label):
            return '', str(r.url)
        text = decode_body(r)
        (OUT / f'{label}.html').write_text(text, encoding='utf-8', errors='ignore')
        row = {'label': label, 'requested': url, 'final': str(r.url), 'status': r.status_code, 'content_type': ct, 'bytes': len(r.content), 'title': ''}
        tm = re.search(r'<title[^>]*>(.*?)</title>', text, re.I|re.S)
        if tm:
            row['title'] = re.sub(r'<[^>]+>',' ',html.unescape(tm.group(1))).strip()
        results['pages'].append(row)
        for term in ['.pdf','download','报告原文','reportid','attachment','fileUrl','pdfUrl','mp.weixin.qq.com','附下载','href=', 'data-src']:
            positions = [m.start() for m in re.finditer(re.escape(term), text, re.I)][:8]
            for pos in positions:
                print('CTX', label, term, normalize_escaped(text[max(0,pos-500):pos+1400]).replace('\n',' ')[:1900])
        return text, str(r.url)
    except Exception as exc:
        print('GET_ERR', label, url, repr(exc))
        return None

# Direct pages and title-specific Sina search pages.
queue: list[tuple[str,str]] = [(u, f'known_{i}') for i,u in enumerate(KNOWN)]
for i,title in enumerate(TITLES):
    queue.append((f'http://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?symbol=&orgname=&industry=&title={quote(title)}&t1=all', f'list_{i}'))
    queue.append((f'https://search.sina.com.cn/?q={quote(title)}&c=news&from=channel', f'search_{i}'))

all_links: set[str] = set()
for url,label in queue:
    got = fetch_page(url,label)
    if not got:
        continue
    text,base = got
    links = extract_links(text,base)
    print('LINK_COUNT', label, len(links))
    for link in sorted(links):
        if any(key in link.lower() for key in ['hk_report.php','vreport_show','mp.weixin.qq.com','weixin.qq.com','.pdf','download','attachment','doc-iniamtiv0919967']):
            print('CANDIDATE_LINK', label, link)
            all_links.add(link)

# Follow public report/article/WeChat links. Do not submit forms or authenticate.
for idx,link in enumerate(sorted(all_links)):
    if link in seen_pages:
        continue
    got = fetch_page(link, f'follow_{idx}')
    if not got:
        continue
    text,base = got
    links = extract_links(text,base)
    for inner in sorted(links):
        if any(key in inner.lower() for key in ['.pdf','download','attachment','file','media','mmbiz','res.wx.qq.com']):
            if inner not in seen_links:
                seen_links.add(inner)
                results['candidate_links'].append(inner)
                print('INNER_LINK', inner)

# Probe likely direct public PDF/attachment URLs found in page source. Do not probe auth/login endpoints.
for idx,link in enumerate(results['candidate_links']):
    low = link.lower()
    if any(bad in low for bad in ['login','passport','account','oauth','register']):
        continue
    if not any(good in low for good in ['.pdf','attachment','download','file','mmbiz']):
        continue
    try:
        r = client.get(link, headers={'Referer':'https://finance.sina.com.cn/'})
        print('PROBE', idx, r.status_code, r.headers.get('content-type'), len(r.content), str(r.url))
        validate_pdf(r.content, str(r.url), f'probe_{idx}')
    except Exception as exc:
        print('PROBE_ERR', idx, link, repr(exc))

(OUT/'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print('DONE', len(results['pdfs']))
client.close()
