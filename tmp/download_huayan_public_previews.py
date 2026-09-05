from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image

OUT = Path('out_huayan_public_previews')
OUT.mkdir(exist_ok=True)
s = requests.Session()
s.headers.update({'User-Agent':'Mozilla/5.0','Referer':'https://www.fxbaogao.com/'})

urls = {
    'fx_5435007_p1.png':'https://public.fxbaogao.com/report-image/2026/05/24/5435007-1.png',
    'fx_5435007_p2.png':'https://public.fxbaogao.com/report-image/2026/05/24/5435007-2.png',
    'fx_5497229_p1.png':'https://public.fxbaogao.com/report-image/2026/06/26/5497229-1.png',
    'fx_5497229_p2.png':'https://public.fxbaogao.com/report-image/2026/06/26/5497229-2.png',
    'fx_5587624_p1.png':'https://public.fxbaogao.com/report-image/2026/08/07/5587624-1.png',
    'fx_5587624_p2.png':'https://public.fxbaogao.com/report-image/2026/08/07/5587624-2.png',
    'sg_1272177_preview_1.gif':'https://file.sgpjbg.com/fileroot3/2026-6/29/62c1854b-5e9d-4d4f-a2d0-495b6e0df5bb/62c1854b-5e9d-4d4f-a2d0-495b6e0df5bb1.gif',
    'sg_1272177_preview_2.gif':'https://file.sgpjbg.com/fileroot3/2026-6/29/62c1854b-5e9d-4d4f-a2d0-495b6e0df5bb/62c1854b-5e9d-4d4f-a2d0-495b6e0df5bb2.gif',
}

meta=[]
for name,url in urls.items():
    try:
        r=s.get(url,timeout=90)
        print('GET',name,r.status_code,r.headers.get('content-type'),len(r.content),r.url)
        if r.status_code!=200 or len(r.content)<1000:
            continue
        p=OUT/name
        p.write_bytes(r.content)
        row={'name':name,'url':url,'bytes':len(r.content),'sha256':hashlib.sha256(r.content).hexdigest(),'content_type':r.headers.get('content-type','')}
        try:
            with Image.open(p) as im:
                row.update({'format':im.format,'size':im.size,'frames':getattr(im,'n_frames',1),'mode':im.mode})
                # Export the first frame to PNG for easier inspection.
                im.seek(0)
                im.convert('RGB').save(OUT/(p.stem+'_frame0.png'))
        except Exception as e:
            row['image_error']=repr(e)
        meta.append(row)
    except Exception as e:
        print('ERR',name,repr(e))

# Save the public preview-list API responses that authorize the two Fx images.
for rid in ['5435007','5497229','5587624']:
    u=f'https://api.fxbaogao.com/mofoun/report/report/getReportPreviewImages?reportId={rid}'
    try:
        r=s.get(u,timeout=60)
        print('API',rid,r.status_code,len(r.content),r.text[:500])
        (OUT/f'fx_{rid}_preview_api.json').write_bytes(r.content)
    except Exception as e:
        print('API_ERR',rid,repr(e))

# Save public viewer helper endpoints for inspection.
helpers={
 'sg_bookread_token.html':'https://www.sgpjbg.com/BookRead.aspx?id=K%7cbxLYA%7cnKY%3d',
 'sg_view_1272177.html':'https://www.sgpjbg.com/sgpjbg/View.aspx?id=1272177',
}
for name,u in helpers.items():
    try:
        r=s.get(u,timeout=60,headers={'Referer':'https://www.sgpjbg.com/baogao/1272177.html','User-Agent':'Mozilla/5.0'})
        print('HELPER',name,r.status_code,r.headers.get('content-type'),len(r.content),r.url)
        (OUT/name).write_bytes(r.content)
    except Exception as e:
        print('HELPER_ERR',name,repr(e))

(OUT/'metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
