from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import requests
from pypdf import PdfReader

OUT = Path("out_huayan_eastmoney_list2")
PDFS = OUT / "pdfs"
OUT.mkdir(exist_ok=True)
PDFS.mkdir(exist_ok=True)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
    "Referer": "https://data.eastmoney.com/report/stock.jshtml",
    "Accept": "application/json,text/plain,*/*",
})

LIST = "https://reportapi.eastmoney.com/report/list"
LIST2 = "https://reportapi.eastmoney.com/report/list2"
KEYWORDS = [
    "华沿机器人", "華沿機器人", "Huayan Robotics", "1021.HK", "01021",
    "七轴人形手臂", "协作机器人头部企业", "运动控制底层价值", "卖铲人",
]

def is_match(row: dict) -> bool:
    blob = json.dumps(row, ensure_ascii=False).lower()
    return any(k.lower() in blob for k in KEYWORDS)

rows: list[dict] = []
raw_index: list[dict] = []

# New stock-report endpoint: POST JSON. Probe code variants and optional market hints.
code_variants = ["01021", "1021", "HK01021", "01021.HK", "1021.HK", "116.01021", "HK|01021", "*"]
for code in code_variants:
    for market in [None, "HK", "116"]:
        body = {
            "pageSize": 5000,
            "pageNo": 1,
            "p": 1,
            "pageNum": 1,
            "pageNumber": 1,
            "beginTime": "2026-03-01",
            "endTime": "2026-09-06",
            "code": code,
            "industryCode": "*",
            "rating": None,
            "ratingChange": None,
            "orgCode": None,
            "rcode": "",
        }
        if market is not None:
            body["market"] = market
        label = re.sub(r"[^A-Za-z0-9]+", "_", f"{code}_{market or 'none'}")
        try:
            response = session.post(LIST2, json=body, timeout=60)
            print("LIST2", label, response.status_code, len(response.content))
            obj = response.json()
            data = obj.get("data") or [] if isinstance(obj, dict) else []
            print("LIST2_META", label, {k: obj.get(k) for k in ["TotalPage", "hits", "TotalCount", "currentYear"] if isinstance(obj, dict)}, "rows", len(data))
            raw_index.append({"source": "list2", "label": label, "meta": {k: obj.get(k) for k in ["TotalPage", "hits", "TotalCount", "currentYear"] if isinstance(obj, dict)}, "rows": len(data)})
            for row in data:
                if is_match(row):
                    print("MATCH_LIST2", json.dumps(row, ensure_ascii=False))
                    rows.append(row)
        except Exception as exc:
            print("LIST2_ERR", label, repr(exc))
        time.sleep(0.3)

# Legacy endpoint: walk every page in the date range because code filtering omits HK names.
base_params = {
    "industryCode": "*", "pageSize": 100, "industry": "*", "rating": "*", "ratingChange": "*",
    "beginTime": "2026-03-01", "endTime": "2026-09-06", "fields": "", "qType": "0",
    "orgCode": "", "code": "", "rcode": "",
}
try:
    p1 = dict(base_params, pageNo=1, p=1, pageNum=1, pageNumber=1)
    first = session.get(LIST, params=p1, timeout=60).json()
    total_pages = int(first.get("TotalPage") or 1)
except Exception as exc:
    print("LIST_INIT_ERR", repr(exc))
    total_pages = 100

print("LIST_TOTAL_PAGES", total_pages)
for page in range(1, total_pages + 1):
    params = dict(base_params, pageNo=page, p=page, pageNum=page, pageNumber=page)
    try:
        response = session.get(LIST, params=params, timeout=60)
        obj = response.json()
        data = obj.get("data") or []
        print("LIST_PAGE", page, response.status_code, len(data))
        for row in data:
            if is_match(row):
                print("MATCH_LIST", json.dumps(row, ensure_ascii=False))
                rows.append(row)
    except Exception as exc:
        print("LIST_PAGE_ERR", page, repr(exc))
    time.sleep(0.25)

# De-duplicate and fetch direct PDF binaries from returned infoCode.
unique: dict[str, dict] = {}
for row in rows:
    key = str(row.get("infoCode") or row.get("encodeUrl") or json.dumps(row, sort_keys=True, ensure_ascii=False))
    unique[key] = row

valid: list[dict] = []
for idx, (key, row) in enumerate(unique.items()):
    info = row.get("infoCode")
    if not info:
        continue
    for suffix in ["_1.pdf", ".pdf"]:
        url = f"https://pdf.dfcfw.com/pdf/H3_{info}{suffix}"
        try:
            response = session.get(url, timeout=90, headers={"Accept": "application/pdf,*/*"})
            print("PDF_PROBE", idx, response.status_code, response.headers.get("content-type"), len(response.content), url)
            if response.status_code != 200 or not response.content.startswith(b"%PDF-") or len(response.content) < 50000:
                continue
            sha = hashlib.sha256(response.content).hexdigest()
            path = PDFS / f"{idx:02d}_{info}_{sha[:12]}.pdf"
            path.write_bytes(response.content)
            try:
                reader = PdfReader(str(path), strict=False)
                pages = len(reader.pages)
                sample = "\n".join((pg.extract_text() or "") for pg in reader.pages[:min(12, pages)])
            except Exception as exc:
                print("PARSE_ERR", repr(exc))
                pages, sample = -1, ""
            normalized = re.sub(r"\s+", "", sample).lower()
            identity_ok = any(k in normalized for k in ["华沿机器人", "華沿機器人", "huayanrobotics", "1021hk", "01021"])
            item = {
                "path": str(path), "url": url, "pages": pages, "bytes": len(response.content),
                "sha256": sha, "identity_ok": identity_ok, "row": row, "sample": sample[:5000],
            }
            valid.append(item)
            print("PDF_VALID", json.dumps({k: v for k, v in item.items() if k not in ["row", "sample"]}, ensure_ascii=False))
            break
        except Exception as exc:
            print("PDF_ERR", url, repr(exc))

(OUT / "raw_index.json").write_text(json.dumps(raw_index, ensure_ascii=False, indent=2), encoding="utf-8")
(OUT / "matches.json").write_text(json.dumps(list(unique.values()), ensure_ascii=False, indent=2), encoding="utf-8")
(OUT / "valid.json").write_text(json.dumps(valid, ensure_ascii=False, indent=2), encoding="utf-8")
print("DONE", "matches", len(unique), "valid", len(valid))
