from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import httpx

OUT = Path('out_huayan_source_probe')
OUT.mkdir(exist_ok=True)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
client = httpx.Client(http2=True, follow_redirects=True, timeout=httpx.Timeout(60, connect=20), headers={
    'User-Agent': UA,
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
})


def dump_page(label: str, url: str) -> str:
    try:
        r = client.get(url, headers={'Referer': url})
        print('PAGE', label, r.status_code, len(r.content), r.headers.get('content-type'), r.url)
        OUT.joinpath(label + '.html').write_bytes(r.content)
        text = r.text
        urls = set()
        for pattern in [
            r'https?://[^\"\'<>\\\s]+',
            r'(?:href|src|data-url|data-src|content)=[\"\']([^\"\']+)[\"\']',
        ]:
            for match in re.findall(pattern, text, re.I):
                value = match if isinstance(match, str) else match[0]
                value = html.unescape(value.strip())
                if value:
                    urls.add(urljoin(str(r.url), value))
        interesting = sorted(u for u in urls if any(k in u.lower() for k in ['pdf','download','file','storage','media','report','oss','cdn','attachment','api']))
        print('INTERESTING', label, json.dumps(interesting[:300], ensure_ascii=False))
        for term in ['1021', '华沿', '華沿', '.pdf', 'download', 'attachment', 'reportId', 'fileUrl', 'pdfUrl', 'storage/app/media']:
            for m in list(re.finditer(re.escape(term), text, re.I))[:20]:
                print('CTX', label, term, text[max(0,m.start()-500):m.end()+1000].replace('\n',' ')[:1800])
        return text
    except Exception as e:
        print('PAGE_ERROR', label, url, repr(e))
        return ''

pages = {
    'sdicsi_tag_en': 'https://www.sdicsi.com.hk/en/research-report/tag/1021hk',
    'sdicsi_tag_cn': 'https://www.sdicsi.com.hk/cn/research-report/tag/1021hk',
    'vzkoo_bocom': 'https://www.vzkoo.com/read/1136817497660001144e2b0d6510.html',
    'fx_bocom': 'https://www.fxbaogao.com/detail/5587624',
    'fx_xingye': 'https://www.fxbaogao.com/detail/5435007',
    'fx_sdicsi': 'https://www.fxbaogao.com/detail/5316158',
    'hangyan_sdicsi': 'https://www.hangyan.co/reports/3859886390573533068',
}
page_texts = {label: dump_page(label, url) for label, url in pages.items()}

# Fetch JS bundles discovered in report pages and inspect endpoint/file patterns.
script_urls = set()
for label, text in page_texts.items():
    base = pages[label]
    for src in re.findall(r'<script[^>]+src=[\"\']([^\"\']+)[\"\']', text, re.I):
        script_urls.add(urljoin(base, html.unescape(src)))
for idx, url in enumerate(sorted(script_urls)):
    try:
        r = client.get(url, headers={'Referer': pages['fx_bocom']})
        if r.status_code != 200 or len(r.content) > 3_000_000:
            continue
        text = r.text
        if not any(k in text.lower() for k in ['report', 'pdf', 'download', 'fileurl', 'attachment']):
            continue
        OUT.joinpath(f'script_{idx}.js').write_text(text, encoding='utf-8', errors='ignore')
        print('SCRIPT', idx, r.status_code, len(r.content), r.url)
        for term in ['getReportPreviewImages','getReport','download','pdfUrl','fileUrl','attachment','report-image','mofoun/report']:
            for m in list(re.finditer(term, text, re.I))[:20]:
                print('SCRIPT_CTX', idx, term, text[max(0,m.start()-500):m.end()+1200].replace('\n',' ')[:2000])
    except Exception as e:
        print('SCRIPT_ERROR', idx, url, repr(e))

# Probe SDIC Securities International public attachment filename conventions.
base = 'https://www.sdicsi.com.hk/backend/storage/app/media/ResearchReports'
dirs = ['CorporateReports','IPOReports','IPOComments','IPO','CompanyReports','IPORating','']
dates = ['20260319','20260320','20260321','20260322','20260323','20260324','20260325']
names = []
for code in ['1021','01021','1021HK','1021-HK']:
    for date in dates:
        names.extend([f'{code}-{date}.pdf', f'{date}-{code}.pdf', f'{code}_{date}.pdf'])
for directory in dirs:
    for name in names:
        url = f"{base}/{directory + '/' if directory else ''}{name}"
        try:
            r = client.get(url, headers={'Referer': pages['sdicsi_tag_en'], 'Accept':'application/pdf,*/*;q=0.8'})
            ct = (r.headers.get('content-type') or '').lower()
            if r.status_code == 200 and (r.content.startswith(b'%PDF-') or 'pdf' in ct):
                print('SDIC_PDF_FOUND', len(r.content), ct, r.url)
                OUT.joinpath('found_' + re.sub(r'[^A-Za-z0-9_.-]+','_',directory+'_'+name)).write_bytes(r.content)
            elif r.status_code not in (200,404) or (r.status_code == 200 and len(r.content) < 100000):
                print('SDIC_PROBE', r.status_code, len(r.content), ct, r.url)
        except Exception as e:
            print('SDIC_ERROR', url, repr(e))

# FxBaogao public API endpoint discovery/probes.
report_ids = ['5587624','5435007','5316158']
methods = ['getReportPreviewImages','getReportDetail','getReportInfo','getReportById','getReport','detail','info','getReportImages','getReportFile','getReportDownloadUrl','getDownloadUrl','download']
for rid in report_ids:
    for method in methods:
        for param in ['reportId','id']:
            url=f'https://api.fxbaogao.com/mofoun/report/report/{method}?{param}={rid}'
            try:
                r=client.get(url,headers={'Referer':f'https://www.fxbaogao.com/detail/{rid}','Accept':'application/json,text/plain,*/*'})
                preview=r.text[:1200].replace('\n',' ')
                if r.status_code != 404 or len(r.content) > 200:
                    print('FX_API',rid,method,param,r.status_code,len(r.content),r.headers.get('content-type'),r.url,preview)
            except Exception as e:
                print('FX_API_ERROR',rid,method,param,repr(e))

# Eastmoney report APIs for HK code variants.
for code in ['01021','1021','HK01021','116.01021']:
    params={
        'code':code,'pageSize':'200','pageNo':'1','beginTime':'2026-01-01','endTime':'2026-09-05','qType':'0','fields':'',
        'industryCode':'*','industry':'*','rating':'*','ratingChange':'*','orgCode':'','rcode':'','p':'1','pageNum':'1','pageNumber':'1'
    }
    try:
        r=client.get('https://reportapi.eastmoney.com/report/list',params=params,headers={'Referer':'https://data.eastmoney.com/report/'})
        print('EM_API',code,r.status_code,len(r.content),r.text[:3000])
    except Exception as e:
        print('EM_ERROR',code,repr(e))

# Probe likely BOCOM public report/static hosts based on common URL patterns.
bocom_urls = [
    'https://research.bocomgroup.com/report/pdf/20260807/1021HK.pdf',
    'https://research.bocomgroup.com/report/pdf/20260807/01021HK.pdf',
    'https://research.bocomgroup.com/report/20260807/1021HK.pdf',
    'https://research.bocomgroup.com/Research/DownloadReport?reportId=5587624',
    'https://research.bocomgroup.com/Research/DownloadReport?stockCode=1021&date=20260807',
]
for url in bocom_urls:
    try:
        r=client.get(url,headers={'Referer':'https://research.bocomgroup.com/','Accept':'application/pdf,*/*;q=0.8'})
        print('BOCOM_PROBE',r.status_code,len(r.content),r.headers.get('content-type'),r.url,r.content[:10].hex())
        if r.status_code==200 and r.content.startswith(b'%PDF-'):
            OUT.joinpath('bocom_found_'+str(len(list(OUT.glob('bocom_found_*'))))+'.pdf').write_bytes(r.content)
    except Exception as e:
        print('BOCOM_ERROR',url,repr(e))

client.close()
print('DONE', OUT)
