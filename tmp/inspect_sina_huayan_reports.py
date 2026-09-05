from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import quote, urljoin

import httpx

OUT = Path('out_sina_huayan_reports')
OUT.mkdir(exist_ok=True)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
client = httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60, connect=20), headers={'User-Agent': UA})

queries = [
    ('华沿机器人', '5'),
    ('头部协作机器人公司，七轴人形手臂放量可期', '5'),
    ('协作机器人头部企业，具身智能空间广阔', '5'),
    ('人形机器人行业系列（4）：“卖铲人”型平台公司，运动控制底层价值有望重估', '5'),
    ('余小丽', '4'),
    ('肖群稀', '4'),
    ('陈庆', '4'),
]

def decode_response(r: httpx.Response) -> str:
    raw = r.content
    head = raw[:5000].lower()
    if b'gb2312' in head or b'gbk' in head:
        return raw.decode('gb18030', errors='ignore')
    return raw.decode('utf-8', errors='ignore')

show_urls = set()
for idx, (term, t1) in enumerate(queries):
    param = 'title' if t1 == '5' else 'analysts'
    url = f'http://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?t1={t1}&{param}={quote(term)}'
    r = client.get(url)
    text = decode_response(r)
    (OUT / f'list_{idx}.html').write_text(text, encoding='utf-8')
    print('LIST', idx, term, r.status_code, len(text), r.url)
    print('HAS_TERM', term in text, 'NO_RESULT', '没有找到相关内容' in text)
    links = set(re.findall(r'https?://[^"\'<>\s]*vReport_Show[^"\'<>\s]*', text, re.I))
    links.update(urljoin(str(r.url), html.unescape(x)) for x in re.findall(r'href=["\']([^"\']*vReport_Show[^"\']*)["\']', text, re.I))
    for link in sorted(links):
        print('SHOW_URL', link)
        show_urls.add(link)

results = []
for idx, url in enumerate(sorted(show_urls)):
    try:
        r = client.get(url)
        text = decode_response(r)
        (OUT / f'show_{idx}.html').write_text(text, encoding='utf-8')
        title_match = re.search(r'<h1[^>]*>(.*?)</h1>', text, re.I | re.S) or re.search(r'<title>(.*?)</title>', text, re.I | re.S)
        title = re.sub(r'<[^>]+>', ' ', html.unescape(title_match.group(1))) if title_match else ''
        title = re.sub(r'\s+', ' ', title).strip()
        print('SHOW', idx, r.status_code, len(text), title, r.url)
        values = set()
        for pat in [r'https?://[^"\'<>\s]+', r'(?:href|src|data-url|data-file)=["\']([^"\']+)["\']']:
            for value in re.findall(pat, text, re.I):
                values.add(urljoin(str(r.url), html.unescape(value).replace('\\/', '/')))
        interesting = sorted(v for v in values if any(k in v.lower() for k in ['.pdf', 'download', 'attach', 'dfcfw', 'file']))
        for value in interesting:
            print('INTERESTING', value)
        contexts = []
        for key in ['.pdf', 'download', 'attach', 'encodeUrl', 'infoCode', 'rptid', 'fileurl', 'pdfurl']:
            for m in list(re.finditer(re.escape(key), text, re.I))[:20]:
                contexts.append({'key': key, 'context': re.sub(r'\s+', ' ', text[max(0,m.start()-700):m.end()+1400])})
        results.append({'url': str(r.url), 'title': title, 'interesting': interesting, 'contexts': contexts})
    except Exception as exc:
        print('SHOW_ERR', url, repr(exc))

(OUT / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
client.close()
