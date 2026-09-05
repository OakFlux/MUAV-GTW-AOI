from __future__ import annotations

import calendar
import csv
import hashlib
import json
import re
import shutil
import subprocess
import time
from datetime import date
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import requests
from pypdf import PdfReader

OUT = Path("out_china_tower_broker_reports_20260905")
RAW = OUT / "raw_pdfs"
REPORTS = OUT / "reports"
RENDERS = OUT / "renders"
FINAL_ZIP = OUT / "China_Tower_00788_Broker_Deep_Research_Reports.zip"

shutil.rmtree(OUT, ignore_errors=True)
RAW.mkdir(parents=True, exist_ok=True)
REPORTS.mkdir(parents=True, exist_ok=True)
RENDERS.mkdir(parents=True, exist_ok=True)

LIST_URL = "https://reportapi.eastmoney.com/report/list"
LIST2_URL = "https://reportapi.eastmoney.com/report/list2"
PDF_BASE = "https://pdf.dfcfw.com/pdf/H3_{info}_1.pdf"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"
S = requests.Session()
S.headers.update({
    "User-Agent": UA,
    "Referer": "https://data.eastmoney.com/report/stock.jshtml",
    "Accept": "application/json,text/plain,*/*",
})

COMPANY_TOKENS = [
    "中国铁塔", "中國鐵塔", "china tower", "00788", "0788.hk", "0788hk",
]
TITLE_EXCLUDE = ["东方铁塔", "中國鐵建", "中国铁建", "中国中铁", "铁塔制造"]
DEEP_HINTS = ["深度", "首次覆盖", "首次覆蓋", "initiation", "公司研究", "公司深度", "专题"]


def month_windows(start_year: int, start_month: int, end_year: int, end_month: int):
    y, m = start_year, start_month
    while (y, m) <= (end_year, end_month):
        last = calendar.monthrange(y, m)[1]
        yield date(y, m, 1).isoformat(), date(y, m, last).isoformat()
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1


def relevant_row(row: dict) -> bool:
    blob = json.dumps(row, ensure_ascii=False).lower()
    if any(term.lower() in blob for term in TITLE_EXCLUDE):
        return False
    return any(term.lower() in blob for term in COMPANY_TOKENS)


def fetch_legacy_window(begin: str, end: str) -> list[dict]:
    base = {
        "industryCode": "*",
        "pageSize": "100",
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "beginTime": begin,
        "endTime": end,
        "fields": "",
        "qType": "0",
        "orgCode": "",
        "code": "",
        "rcode": "",
    }
    rows: list[dict] = []
    first = None
    for attempt in range(1, 4):
        try:
            params = dict(base, pageNo="1", p="1", pageNum="1", pageNumber="1")
            response = S.get(LIST_URL, params=params, timeout=60)
            response.raise_for_status()
            first = response.json()
            break
        except Exception as exc:
            print("WINDOW_FIRST_RETRY", begin, end, attempt, repr(exc))
            time.sleep(attempt * 1.5)
    if not isinstance(first, dict):
        return rows
    total_pages = int(first.get("TotalPage") or 0)
    print("WINDOW", begin, end, "pages", total_pages, "hits", first.get("hits"))
    for page in range(1, total_pages + 1):
        obj = first if page == 1 else None
        if obj is None:
            for attempt in range(1, 4):
                try:
                    params = dict(base, pageNo=str(page), p=str(page), pageNum=str(page), pageNumber=str(page))
                    response = S.get(LIST_URL, params=params, timeout=60)
                    response.raise_for_status()
                    obj = response.json()
                    break
                except Exception as exc:
                    print("WINDOW_PAGE_RETRY", begin, page, attempt, repr(exc))
                    time.sleep(attempt * 1.5)
        data = (obj or {}).get("data") or []
        for row in data:
            if isinstance(row, dict) and relevant_row(row):
                print("MATCH", json.dumps(row, ensure_ascii=False))
                rows.append(row)
        time.sleep(0.08)
    return rows


def fetch_list2_codes() -> list[dict]:
    rows: list[dict] = []
    for code in ["00788", "0788", "HK00788", "00788.HK", "0788.HK", "116.00788"]:
        body = {
            "pageSize": 5000,
            "pageNo": 1,
            "p": 1,
            "pageNum": 1,
            "pageNumber": 1,
            "beginTime": "2020-01-01",
            "endTime": "2026-09-05",
            "code": code,
            "industryCode": "*",
            "rating": None,
            "ratingChange": None,
            "orgCode": None,
            "rcode": "",
        }
        try:
            response = S.post(LIST2_URL, json=body, timeout=60)
            print("LIST2", code, response.status_code, len(response.content))
            response.raise_for_status()
            obj = response.json()
            data = obj.get("data") or [] if isinstance(obj, dict) else []
            for row in data:
                if isinstance(row, dict) and relevant_row(row):
                    print("MATCH_LIST2", json.dumps(row, ensure_ascii=False))
                    rows.append(row)
        except Exception as exc:
            print("LIST2_ERROR", code, repr(exc))
    return rows


def download_pdf(info: str, dest: Path) -> str | None:
    urls = [
        f"https://pdf.dfcfw.com/pdf/H3_{info}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H3_{info}.pdf",
    ]
    for url in urls:
        for attempt in range(1, 4):
            try:
                response = S.get(url, timeout=120, headers={
                    "User-Agent": UA,
                    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.5",
                    "Referer": "https://data.eastmoney.com/report/stock.jshtml",
                })
                print("PDF_PROBE", response.status_code, response.headers.get("content-type"), len(response.content), url)
                if response.status_code == 200 and response.content.startswith(b"%PDF-") and len(response.content) > 50_000:
                    dest.write_bytes(response.content)
                    return url
                break
            except Exception as exc:
                print("PDF_RETRY", attempt, url, repr(exc))
                time.sleep(attempt * 1.5)
    return None


def pdf_metadata(path: Path) -> dict:
    reader = PdfReader(str(path), strict=False)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            pass
    pages = len(reader.pages)
    sample_parts = []
    indices = list(range(min(12, pages)))
    if pages > 20:
        indices.extend([pages // 2, pages - 1])
    for idx in sorted(set(indices)):
        try:
            sample_parts.append(reader.pages[idx].extract_text() or "")
        except Exception:
            pass
    sample = "\n".join(sample_parts)
    normalized = re.sub(r"\s+", "", sample).lower()
    identity_ok = any(token.lower().replace(" ", "") in normalized for token in COMPANY_TOKENS)
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "identity_ok": identity_ok,
        "sample_text": sample[:5000],
    }


def render_first(path: Path) -> int:
    prefix = RENDERS / path.stem
    subprocess.run(
        ["pdftoppm", "-f", "1", "-l", "1", "-png", "-singlefile", "-r", "100", str(path), str(prefix)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    image = Path(str(prefix) + ".png")
    if not image.exists() or image.stat().st_size < 8_000:
        raise RuntimeError(f"Render failed for {path.name}")
    return image.stat().st_size


matches: list[dict] = []
matches.extend(fetch_list2_codes())
# Scan every monthly report page from 2023 onward. Monthly windows keep page counts modest.
for begin, end in month_windows(2023, 1, 2026, 9):
    matches.extend(fetch_legacy_window(begin, end))

# De-duplicate by infoCode, retaining the most complete row.
unique: dict[str, dict] = {}
for row in matches:
    info = str(row.get("infoCode") or "").strip()
    if not info:
        continue
    current = unique.get(info)
    if current is None or len(json.dumps(row, ensure_ascii=False)) > len(json.dumps(current, ensure_ascii=False)):
        unique[info] = row
print("UNIQUE_MATCHES", len(unique))
(OUT / "all_matching_rows.json").write_text(json.dumps(list(unique.values()), ensure_ascii=False, indent=2), encoding="utf-8")

valid: list[dict] = []
for idx, (info, row) in enumerate(unique.items(), start=1):
    temp = RAW / f"{idx:03d}_{info}.pdf"
    url = download_pdf(info, temp)
    if not url:
        continue
    try:
        meta = pdf_metadata(temp)
        if meta["pages"] < 3 or not meta["identity_ok"]:
            print("REJECT_PDF", info, meta["pages"], meta["identity_ok"])
            temp.unlink(missing_ok=True)
            continue
        render_bytes = render_first(temp)
        title = str(row.get("title") or row.get("TITLE") or "").strip()
        publish = str(row.get("publishDate") or row.get("publish_date") or row.get("date") or "")[:10]
        org = str(row.get("orgSName") or row.get("orgName") or row.get("org_name") or "").strip()
        attach_pages = row.get("attachPages")
        deep_score = 0
        if any(hint.lower() in title.lower() for hint in DEEP_HINTS):
            deep_score += 100
        if "首次" in title or "深度" in title:
            deep_score += 80
        deep_score += min(meta["pages"], 60)
        item = {
            "infoCode": info,
            "title": title,
            "broker": org,
            "publish_date": publish,
            "pages": meta["pages"],
            "bytes": meta["bytes"],
            "sha256": meta["sha256"],
            "source_url": url,
            "eastmoney_attach_pages": attach_pages,
            "deep_score": deep_score,
            "render_bytes": render_bytes,
            "raw_path": str(temp),
            "row": row,
        }
        valid.append(item)
        print("VALID", json.dumps({k: v for k, v in item.items() if k not in {"row", "raw_path"}}, ensure_ascii=False))
    except Exception as exc:
        print("PDF_INSPECT_ERROR", info, repr(exc))
        temp.unlink(missing_ok=True)

if not valid:
    raise RuntimeError("No valid China Tower broker-report PDFs were found")

# Prefer genuine deep/initial-coverage reports; supplement with the longest recent company reports.
valid.sort(key=lambda x: (x["deep_score"], x["pages"], x["publish_date"]), reverse=True)
selected: list[dict] = []
seen_titles: set[str] = set()
for item in valid:
    normalized_title = re.sub(r"\W+", "", item["title"].lower())
    if normalized_title in seen_titles:
        continue
    if item["pages"] >= 8 or any(hint.lower() in item["title"].lower() for hint in DEEP_HINTS):
        selected.append(item)
        seen_titles.add(normalized_title)
    if len(selected) == 3:
        break
if len(selected) < 2:
    for item in sorted(valid, key=lambda x: (x["pages"], x["publish_date"]), reverse=True):
        normalized_title = re.sub(r"\W+", "", item["title"].lower())
        if normalized_title in seen_titles:
            continue
        selected.append(item)
        seen_titles.add(normalized_title)
        if len(selected) == min(3, len(valid)):
            break
if len(selected) < 2:
    raise RuntimeError(f"Only {len(selected)} suitable complete reports were found")

manifest = []
for index, item in enumerate(selected, start=1):
    broker = item["broker"] or "券商"
    safe_broker = re.sub(r"[\\/:*?\"<>|]", "_", broker)
    safe_title = re.sub(r"[\\/:*?\"<>|]", "_", item["title"])[:90]
    filename = f"{index:02d}_{safe_broker}_{item['publish_date']}_{safe_title}.pdf"
    destination = REPORTS / filename
    shutil.copy2(Path(item["raw_path"]), destination)
    manifest.append({
        "index": index,
        "broker": broker,
        "date": item["publish_date"],
        "title": item["title"],
        "pages": item["pages"],
        "filename": filename,
        "bytes": item["bytes"],
        "sha256": item["sha256"],
        "source_url": item["source_url"],
        "infoCode": item["infoCode"],
    })

readme = [
    "中国铁塔（00788.HK）券商深度/公司研究报告合集",
    "",
    "筛选规则：优先首次覆盖、公司深度及页数较完整的报告；排除年度报告、公告、行业周报和其他同名公司。",
    "全部PDF来自公开研报附件链接，仅供个人研究使用，版权归原发布机构所有。",
    "",
    "文件清单：",
]
for item in manifest:
    readme.append(f"{item['index']}. {item['broker']}｜{item['date']}｜{item['pages']}页｜{item['title']}")
readme.extend([
    "",
    "校验：PDF文件签名、公司名称/证券代码、实际页数、首页渲染、SHA-256及ZIP完整性。",
])
(REPORTS / "README_报告说明.txt").write_text("\n".join(readme), encoding="utf-8")
(REPORTS / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
with (REPORTS / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(manifest[0].keys()))
    writer.writeheader()
    writer.writerows(manifest)

with ZipFile(FINAL_ZIP, "w", ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(REPORTS.iterdir(), key=lambda p: p.name):
        archive.write(path, path.name)
with ZipFile(FINAL_ZIP) as archive:
    bad = archive.testzip()
    if bad is not None:
        raise RuntimeError(f"ZIP integrity failure: {bad}")
    pdf_names = [n for n in archive.namelist() if n.lower().endswith(".pdf")]
    if len(pdf_names) != len(manifest):
        raise RuntimeError("ZIP PDF count mismatch")

print("PACKAGE_READY", FINAL_ZIP, FINAL_ZIP.stat().st_size)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
