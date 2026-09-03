from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urljoin
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
from pypdf import PdfReader

STOCK_ID = "1000285893"
CUTOFF = "2026-09-03"
OUT = Path("out_forest_cabin_20260903")
REPORTS = OUT / "reports"
RENDERS = OUT / "renders"
FINAL_ZIP = OUT / "Forest_Cabin_02657_All_Annual_Reports_Prospectus_Latest_Interim_2026-09-03.zip"

shutil.rmtree(OUT, ignore_errors=True)
REPORTS.mkdir(parents=True, exist_ok=True)
RENDERS.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"
client = httpx.Client(
    http2=True,
    follow_redirects=True,
    timeout=httpx.Timeout(240.0, connect=30.0),
    headers={"User-Agent": UA, "Referer": "https://www1.hkexnews.hk/search/titlesearch.xhtml"},
)


def unpack_records(payload):
    if isinstance(payload, dict) and isinstance(payload.get("result"), str):
        payload = json.loads(payload["result"])
    if isinstance(payload, dict):
        for key in ("records", "data", "items", "result"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    return payload if isinstance(payload, list) else []


def search_all(lang: str) -> list[dict]:
    endpoint = "https://www1.hkexnews.hk/search/titleSearchServlet.do"
    combinations = [
        ("40000", "-2", "-2"),
        ("-2", "-2", "-2"),
        ("", "", ""),
    ]
    for t1code, t2gcode, t2code in combinations:
        params = {
            "sortDir": "0",
            "sortByOptions": "DateTime",
            "category": "0",
            "market": "SEHK",
            "stockId": STOCK_ID,
            "documentType": "-1",
            "fromDate": "20250501",
            "toDate": "20260903",
            "title": "",
            "searchType": "1",
            "t1code": t1code,
            "t2Gcode": t2gcode,
            "t2code": t2code,
            "rowRange": "2000",
            "lang": lang,
        }
        for attempt in range(1, 4):
            try:
                response = client.get(endpoint, params=params, headers={"Accept": "application/json,*/*"})
                response.raise_for_status()
                records = unpack_records(response.json())
                records = [dict(item, _lang=lang) for item in records if isinstance(item, dict)]
                print(f"SEARCH lang={lang} t1={t1code!r} t2={t2code!r}: {len(records)}")
                if records:
                    return records
                break
            except Exception as exc:
                print(f"SEARCH retry {attempt} lang={lang}: {exc}")
                time.sleep(attempt * 2)
    return []


def field(item: dict, *names: str) -> str:
    for name in names:
        value = item.get(name)
        if value not in (None, ""):
            return str(value)
    return ""


def title(item: dict) -> str:
    return re.sub(r"\s+", " ", field(item, "TITLE", "title")).strip()


def date(item: dict) -> str:
    return field(item, "DATE_TIME", "dateTime", "DATE", "date")


def file_info(item: dict) -> str:
    return field(item, "FILE_INFO", "fileInfo")


def file_url(item: dict) -> str:
    raw = field(item, "FILE_LINK", "fileLink", "url").strip()
    return urljoin("https://www1.hkexnews.hk/", raw)


def is_pdf(item: dict) -> bool:
    u = file_url(item).lower().split("?", 1)[0]
    info = file_info(item).lower()
    return u.endswith(".pdf") and "multi" not in info and "多檔" not in info and "多档" not in info


def chinese_priority(item: dict) -> int:
    u = file_url(item).lower()
    return (2 if item.get("_lang") == "zh" else 0) + (2 if u.endswith("_c.pdf") else 0)


def download(url: str, destination: Path) -> None:
    last_error = None
    headers = {
        "User-Agent": UA,
        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.5",
        "Referer": "https://www1.hkexnews.hk/search/titlesearch.xhtml",
    }
    for attempt in range(1, 6):
        try:
            with client.stream("GET", url, headers=headers) as response:
                response.raise_for_status()
                with destination.open("wb") as f:
                    for chunk in response.iter_bytes(1024 * 1024):
                        f.write(chunk)
            if destination.stat().st_size < 80_000:
                raise RuntimeError(f"file too small: {destination.stat().st_size}")
            with destination.open("rb") as f:
                if f.read(5) != b"%PDF-":
                    raise RuntimeError("not a PDF")
            return
        except Exception as exc:
            last_error = exc
            destination.unlink(missing_ok=True)
            print(f"DOWNLOAD retry {attempt}: {url}: {exc}")
            time.sleep(attempt * 2)
    raise RuntimeError(f"Download failed: {url}: {last_error}")


def inspect(path: Path, minimum_pages: int) -> tuple[int, str]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < minimum_pages:
        raise RuntimeError(f"Too few pages in {path.name}: {pages} < {minimum_pages}")
    text = "\n".join((page.extract_text() or "") for page in reader.pages[: min(40, pages)])
    normalized = re.sub(r"\s+", "", text).lower()
    tokens = ("forestcabin", "上海林清軒", "上海林清轩", "02657", "2657")
    if not any(token.lower() in normalized for token in tokens):
        raise RuntimeError(f"Company identity not found in {path.name}")
    return pages, hashlib.sha256(path.read_bytes()).hexdigest()


def render_first_page(path: Path) -> int:
    prefix = RENDERS / path.stem
    subprocess.run(
        ["pdftoppm", "-f", "1", "-l", "1", "-png", "-singlefile", "-r", "100", str(path), str(prefix)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    png = Path(str(prefix) + ".png")
    if not png.exists() or png.stat().st_size < 10_000:
        raise RuntimeError(f"First-page render failed: {path.name}")
    return png.stat().st_size


records = search_all("zh") + search_all("EN")
if not records:
    raise RuntimeError("HKEX returned no filings for Forest Cabin.")

# Deduplicate exact file URLs while preserving the Chinese-language record when available.
by_url: dict[str, dict] = {}
for item in records:
    u = file_url(item)
    if not u:
        continue
    current = by_url.get(u)
    if current is None or chinese_priority(item) > chinese_priority(current):
        by_url[u] = item
records = list(by_url.values())
print("TOTAL UNIQUE RECORDS", len(records))
for item in records:
    if re.search(r"年報|年报|annual report|全球.*發售|全球.*发售|global offering|中期業績|中期业绩|interim results", title(item), re.I):
        print("RELEVANT", date(item), title(item), file_info(item), file_url(item))

manifest: list[dict] = []

# All complete annual reports. Forest Cabin listed on 30 Dec 2025, so only FY2025 should exist by the cutoff.
annual_candidates = [
    item for item in records
    if is_pdf(item)
    and re.search(r"年報|年报|annual\s+report", title(item), re.I)
    and not re.search(r"環境|环境|esg|摘要|summary|補充|补充", title(item), re.I)
]
annual_candidates.sort(key=lambda item: (chinese_priority(item), date(item)), reverse=True)
if not annual_candidates:
    raise RuntimeError("Complete annual report not found.")
annual_item = annual_candidates[0]
annual_path = REPORTS / "01_林清轩_2025年年度报告_港交所官方版.pdf"
download(file_url(annual_item), annual_path)
annual_pages, annual_sha = inspect(annual_path, 100)
annual_render = render_first_page(annual_path)
manifest.append({
    "type": "annual_report",
    "reporting_year": 2025,
    "publication_time": date(annual_item),
    "title": title(annual_item),
    "filename": annual_path.name,
    "source_url": file_url(annual_item),
    "pages": annual_pages,
    "bytes": annual_path.stat().st_size,
    "first_page_render_bytes": annual_render,
    "sha256": annual_sha,
})

# Final prospectus / global offering document dated 18 Dec 2025. Formal notice is rejected by page-count validation.
prospectus_candidates = [
    item for item in records
    if is_pdf(item)
    and ("2025/12/18" in date(item) or "18/12/2025" in date(item) or "2025-12-18" in date(item))
    and re.search(r"全球.*發售|全球.*发售|global\s+offering|prospectus|招股", title(item), re.I)
    and not re.search(r"application proof|申請版本|申请版本|phip|聆訊後|聆讯后", title(item), re.I)
]
prospectus_candidates.sort(key=lambda item: (chinese_priority(item), len(file_info(item)), file_info(item)), reverse=True)
selected = None
for idx, item in enumerate(prospectus_candidates, 1):
    temp = OUT / f"prospectus_candidate_{idx}.pdf"
    try:
        print("TRY PROSPECTUS", date(item), title(item), file_info(item), file_url(item))
        download(file_url(item), temp)
        pages, sha = inspect(temp, 250)
        selected = (item, temp, pages, sha)
        break
    except Exception as exc:
        print("REJECT PROSPECTUS", exc)
        temp.unlink(missing_ok=True)
if selected is None:
    raise RuntimeError("Final prospectus could not be identified and validated.")
prospectus_item, temp, prospectus_pages, prospectus_sha = selected
prospectus_path = REPORTS / "02_林清轩_正式招股章程_2025-12-18_港交所官方版.pdf"
temp.replace(prospectus_path)
prospectus_render = render_first_page(prospectus_path)
manifest.append({
    "type": "final_prospectus",
    "publication_time": date(prospectus_item),
    "title": title(prospectus_item),
    "filename": prospectus_path.name,
    "source_url": file_url(prospectus_item),
    "pages": prospectus_pages,
    "bytes": prospectus_path.stat().st_size,
    "first_page_render_bytes": prospectus_render,
    "sha256": prospectus_sha,
})

# Latest formal periodic financial disclosure as at the cutoff: 2026 interim-results announcement.
interim_candidates = [
    item for item in records
    if is_pdf(item)
    and re.search(r"中期業績|中期业绩|interim\s+results", title(item), re.I)
    and not re.search(r"股息|dividend.*form|董事會會議|董事会会议|board meeting", title(item), re.I)
]
interim_candidates.sort(key=lambda item: (date(item), chinese_priority(item)), reverse=True)
if not interim_candidates:
    raise RuntimeError("Latest interim results announcement not found.")
interim_item = interim_candidates[0]
interim_path = REPORTS / "03_林清轩_2026年中期业绩公告_截至2026年6月30日_港交所官方版.pdf"
download(file_url(interim_item), interim_path)
interim_pages, interim_sha = inspect(interim_path, 15)
interim_render = render_first_page(interim_path)
manifest.append({
    "type": "latest_interim_results_announcement",
    "reporting_period_end": "2026-06-30",
    "publication_time": date(interim_item),
    "title": title(interim_item),
    "filename": interim_path.name,
    "source_url": file_url(interim_item),
    "pages": interim_pages,
    "bytes": interim_path.stat().st_size,
    "first_page_render_bytes": interim_render,
    "sha256": interim_sha,
})

readme = f"""林清轩（02657.HK）年报、招股章程及最新定期财务报告合集

整理截止日期：{CUTOFF}
上市主体：上海林清轩化妆品集团股份有限公司
英文名称：Shanghai Forest Cabin Cosmetics Group Co., Ltd.
上市日期：2025年12月30日

收录范围：
1. 2025年完整年度报告。林清轩于2025年12月30日上市，因此截至整理日仅有这一份港交所正式年报；
2. 2025年12月18日正式招股章程；
3. 截至2026年6月30日止六个月的2026年中期业绩公告，为截至整理日最新定期财务披露。

重要说明：
- 2020—2024年不存在林清轩作为港股上市公司的港交所正式年报；历史财务数据已包含在正式招股章程中。
- 香港主板发行人通常披露年度报告和中期报告，不强制披露A股式普通季度报告。截至2026年9月3日，2026年正式中期报告尚未发布，因此本包以2026年8月31日的中期业绩公告作为“最新季报/最新定期财务披露”。
- 未收录已被正式招股章程取代的申请版本、聆讯后资料集、招股表格及其他重复上市文件。
- 全部PDF来自香港交易所披露易官方链接，仅供个人研究使用，版权归原发布机构所有。

已完成的校验：PDF签名、公司名称/股票代码、报告类型、页数、首页渲染可读性、SHA-256及ZIP完整性。
"""
(REPORTS / "README_文件说明.txt").write_text(readme, encoding="utf-8")
(REPORTS / "文件清单与官方来源.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
with (REPORTS / "文件清单与官方来源.csv").open("w", encoding="utf-8-sig", newline="") as f:
    columns = ["type", "reporting_year", "reporting_period_end", "publication_time", "title", "filename", "pages", "bytes", "first_page_render_bytes", "sha256", "source_url"]
    writer = csv.DictWriter(f, fieldnames=columns)
    writer.writeheader()
    for item in manifest:
        writer.writerow({column: item.get(column, "") for column in columns})

with ZipFile(FINAL_ZIP, "w", ZIP_DEFLATED, compresslevel=9) as zf:
    for path in sorted(REPORTS.iterdir(), key=lambda p: p.name):
        zf.write(path, path.name)
with ZipFile(FINAL_ZIP) as zf:
    assert zf.testzip() is None
    assert len([name for name in zf.namelist() if name.lower().endswith(".pdf")]) == 3

print("PACKAGE_READY", FINAL_ZIP, FINAL_ZIP.stat().st_size)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
client.close()
