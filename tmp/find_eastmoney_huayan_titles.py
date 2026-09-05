from pathlib import Path
import hashlib, json, re
import httpx
from pypdf import PdfReader

out = Path('out_huayan_eastmoney_title')
out.mkdir(exist_ok=True)
pdfs = out / 'pdfs'
pdfs.mkdir(exist_ok=True)
client = httpx.Client(follow_redirects=True, timeout=60, headers={'User-Agent':'Mozilla/5.0','Referer':'https://data.eastmoney.com/report/'})

targets = [
    ('2026-05-20','2026-05-29','头部协作机器人公司，七轴人形手臂放量可期'),
    ('2026-06-20','2026-07-02','协作机器人头部企业，具身智能空间广阔'),
    ('2026-08-01','2026-08-14','人形机器人行业系列（4）：“卖铲人”型平台公司，运动控制底层价值有望重估'),
    ('2026-08-25','2026-09-02','1H26增长偏弱，订单恢复与新品放量支撑2H26提速'),
]

def norm(s):
    return re.sub(r'[^0-9A-Za-z一-龥]+','',str(s)).lower()

def parse(r):
    try:
        return r.json()
    except Exception:
        return {}

matches = []
seen = set()
for begin, end, title in targets:
    for qtype in ['0','1','2','3','4']:
        for page in range(1, 4):
            params = {
                'beginTime':begin, 'endTime':end, 'pageSize':'100', 'pageNo':str(page),
                'qType':qtype, 'title':title, 'p':str(page), 'pageNum':str(page),
                'pageNumber':str(page), 'industryCode':'*', 'industry':'*', 'rating':'*',
                'ratingChange':'*', 'orgCode':'', 'rcode':'', 'fields':''
            }
            r = client.get('https://reportapi.eastmoney.com/report/list', params=params)
            obj = parse(r)
            data = obj.get('data') or [] if isinstance(obj, dict) else []
            print('QUERY', begin, end, qtype, page, r.status_code, len(data), r.url)
            for item in data:
                blob = norm(json.dumps(item, ensure_ascii=False))
                if norm(title) in blob or norm('华沿机器人') in blob or norm('華沿機器人') in blob:
                    key = item.get('infoCode') or json.dumps(item, sort_keys=True, ensure_ascii=False)
                    if key not in seen:
                        seen.add(key)
                        matches.append(item)
                        print('MATCH', json.dumps(item, ensure_ascii=False))
            if len(data) < 100:
                break

found = []
for i, item in enumerate(matches):
    code = item.get('infoCode') or item.get('INFO_CODE')
    if not code:
        continue
    for suffix in ['_1.pdf','.pdf']:
        url = f'https://pdf.dfcfw.com/pdf/H3_{code}{suffix}'
        r = client.get(url, headers={'Accept':'application/pdf,*/*'})
        print('PDF', r.status_code, r.headers.get('content-type'), len(r.content), url)
        if r.status_code == 200 and r.content.startswith(b'%PDF-') and len(r.content) > 60000:
            sha = hashlib.sha256(r.content).hexdigest()
            path = pdfs / f'{i}_{sha[:12]}.pdf'
            path.write_bytes(r.content)
            reader = PdfReader(str(path), strict=False)
            pages = len(reader.pages)
            text = '\n'.join((p.extract_text() or '') for p in reader.pages[:min(pages,20)])
            ok = any(x in norm(text) for x in [norm('华沿机器人'), norm('華沿機器人'), norm('Huayan Robotics'), norm('1021 HK')])
            meta = {'url':url,'path':str(path),'pages':pages,'bytes':len(r.content),'sha256':sha,'identity_ok':ok,'sample':text[:3000]}
            found.append(meta)
            print('FOUND', json.dumps({k:v for k,v in meta.items() if k!='sample'}, ensure_ascii=False))

(out/'results.json').write_text(json.dumps({'matches':matches,'pdfs':found},ensure_ascii=False,indent=2),encoding='utf-8')
client.close()
