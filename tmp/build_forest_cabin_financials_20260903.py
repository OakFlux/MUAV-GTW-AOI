from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
from pypdf import PdfReader

STOCK_ID = "1000285893"
STOCK_CODE = "02657"
COMPANY_ZH = "上海林清轩化妆品集团股份有限公司"
COMPANY_EN = "SHANGHAI FOREST CABIN COSMETICS GROUP CO., LTD."
CUTOFF = "2026-09-03"

OUT = Path("out_forest_cabin_20260903")
REPORTS = OUT / "reports"
RENDERS = OUT / "renders"
FINAL_ZIP = OUT / "Forest_Cabin_02657_All_Annual_Reports_Prospectus_Latest_Interim_2026-09-03.zip"
shutil.rmtree(OUT, ignore_errors=True)
REPORTS.mkdir(parents=True, exist_ok=True)
RENDERS.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
client = httpx.Client(
    http2=True,
    follow_redirects=True,
    timeout=httpx.Timeout(180.0, connect=30.0),
    headers={
        "User-Agent": UA,
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://www1.hkexnews.hk/search/titlesearch.xhtml",
    },
)


def hkex_search(t2code: str, lang: str = "zh") -> list[dict]:
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
        "t1code": "40000",
        "t2Gcode": "-2",
        "t2code": t2code,
        "rowRange": "2000",
        "lang": lang,
    }
    url = "https://www1.hkexnews.hk/search/titleSearchServlet.do"
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = client.get(url, params=params)
            response.raise_for_status()
            outer = response.json()
            inner = json.loads(outer["result"]) if isinstance(outer, dict) and isinstance(outer.get("result"), str) else outer
            if isinstance(inner, dict):
                for key in ("records", "data", "result", "items"):
                    if isinstance(inner.get(key), list):
                        inner = inner[key]
                        break
            if not isinstance(inner, list):
                raise RuntimeError(f"Unexpected HKEX response type for {t2code}/{lang}: {type(inner)}")
            records = []
            for item in inner:
                if not isinstance(item, dict):
                    continue
                item = dict(item)
                item["_query_lang"] = lang
                records.append(item)
            print(f"HKEX search t2code={t2code} lang={lang}: {len(records)} records")
            return records
        except Exception as exc:
            last_error = exc
            print(f"HKEX search attempt {attempt} failed: {exc}")
            time.sleep(attempt * 2)
    raise RuntimeError(f"HKEX search failed for {t2code}/{lang}: {last_error}")


def title_of(item: dict) -> str:
    return re.sub(r"\s+", " ", str(item.get("TITLE") or item.get("title") or "")).strip()


def date_of(item: dict) -> str:
    return str(item.get("DATE_TIME") or item.get("dateTime") or item.get("DATE") or "")


def info_of(item: dict) -> str:
    return str(item.get("FILE_INFO") or item.get("fileInfo") or "")


def url_of(item: dict) -> str:
    raw = str(item.get("FILE_LINK") or item.get("fileLink") or "").strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return "https://www1.hkexnews.hk/" + raw.lstrip("/")


def is_pdf_record(item: dict) -> bool:
    url = url_of(item)
    info = info_of(item)
    return url.lower().split("?", 1)[0].endswith(".pdf") and "多" not in info.lower() and "multi" not in info.lower()


def download_pdf(url: str, destination: Path) -> None:
    headers = {
        "User-Agent": UA,
        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.5",
        "Referer": "https://www1.hkexnews.hk/search/titlesearch.xhtml",
    }
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            with client.stream("GET", url, headers=headers) as response:
                response.raise_for_status()
                with destination.open("wb") as handle:
                    for chunk in response.iter_bytes(1024 * 1024):
                        handle.write(chunk)
            if destination.stat().st_size < 80_000:
                raise RuntimeError(f"Downloaded file too small: {destination.stat().st_size}")
            if destination.read_bytes()[:5] != b"%PDF-":
                raise RuntimeError("Downloaded content is not a PDF")
            return
        except Exception as exc:
            last_error = exc
            destination.unlink(missing_ok=True)
            print(f"Download attempt {attempt} failed for {url}: {exc}")
            time.sleep(attempt * 2)
    raise RuntimeError(f"Unable to download {url}: {last_error}")


def inspect_pdf(path: Path, minimum_pages: int) -> tuple[int, str, str]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < minimum_pages:
        raise RuntimeError(f"Too few pages in {path.name}: {pages} < {minimum_pages}")
    sample_parts = []
    for page in reader.pages[: min(35, pages)]:
        try:
            sample_parts.append(page.extract_text() or "")
        except Exception:
            pass
    sample = "\n".join(sample_parts)
    normalized = re.sub(r"\s+", "", sample).lower()
    identity_tokens = [
        "forestcabin",
        "shanghaiforestcabincosmetics",
        "上海林清軒",
        "上海林清轩",
        "02657",
        "2657",
    ]
    if not any(token.lower() in normalized for token in identity_tokens):
        raise RuntimeError(f"Company identity could not be verified in {path.name}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return pages, digest, sample


def render_cover(path: Path) -> Path:
    prefix = RENDERS / path.stem
    subprocess.run(
        ["pdftoppm", "-f", "1", "-l", "1", "-png", "-singlefile", "-r", "100", str(path), str(prefix)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    png = Path(str(prefix) + ".png")
    if not png.exists() or png.stat().st_size < 10_000:
        raise RuntimeError(f"Cover rendering failed for {path.name}")
    return png


def parse_year(text: str) -> int | None:
    match = re.search(r"(20\d{2})", text)
    return int(match.group(1)) if match else None


annual_records = hkex_search("40200", "zh")
if not annual_records:
    annual_records = hkex_search("40200", "EN")
annual_candidates = [
    item for item in annual_records
    if is_pdf_record(item) and re.search(r"年報|年报|annual\s+report", title_of(item), re.I)
]
if not annual_candidates:
    raise RuntimeError("No complete annual report record was found.")

# Keep one complete annual report per reporting year, preferring the Chinese record and the later publication.
annual_by_year: dict[int, dict] = {}
for item in annual_candidates:
    year = parse_year(title_of(item)) or (parse_year(date_of(item)) - 1 if parse_year(date_of(item)) else None)
    if year is None:
        continue
    current = annual_by_year.get(year)
    score = (100 if item.get("_query_lang") == "zh" else 0, date_of(item))
    current_score = (-1, "") if current is None else (100 if current.get("_query_lang") == "zh" else 0, date_of(current))
    if current is None or score > current_score:
        annual_by_year[year] = item

manifest: list[dict] = []
for index, year in enumerate(sorted(annual_by_year), start=1):
    item = annual_by_year[year]
    filename = f"{index:02d}_林清轩_{year}年年度报告_港交所官方版.pdf"
    destination = REPORTS / filename
    source_url = url_of(item)
    print(f"Downloading annual report {year}: {source_url}")
    download_pdf(source_url, destination)
    pages, digest, _ = inspect_pdf(destination, 100)
    render_cover(destination)
    manifest.append({
        "type": "annual_report",
        "reporting_year": year,
        "publication_time": date_of(item),
        "title": title_of(item),
        "filename": filename,
        "source_url": source_url,
        "pages": pages,
        "bytes": destination.stat().st_size,
        "sha256": digest,
    })

# Final prospectus: select from the prospectus category and validate candidate PDFs by page count.
prospectus_records = hkex_search("40500", "zh")
if not prospectus_records:
    prospectus_records = hkex_search("40500", "EN")
prospectus_candidates = [item for item in prospectus_records if is_pdf_record(item)]
prospectus_candidates.sort(
    key=lambda item: (
        1 if "2025/12/18" in date_of(item) or "18/12/2025" in date_of(item) else 0,
        1 if re.search(r"全球.*發售|全球.*发售|global\s+offering|prospectus|招股", title_of(item), re.I) else 0,
        date_of(item),
    ),
    reverse=True,
)
selected_prospectus: tuple[dict, Path, int, str] | None = None
for candidate_index, item in enumerate(prospectus_candidates[:10], start=1):
    temp = OUT / f"prospectus_candidate_{candidate_index}.pdf"
    try:
        print(f"Testing prospectus candidate: {title_of(item)} {date_of(item)} {url_of(item)}")
        download_pdf(url_of(item), temp)
        pages, digest, sample = inspect_pdf(temp, 250)
        # Prefer the final offer document dated 18 December 2025 over application proofs/PHIPs.
        title = title_of(item)
        if re.search(r"application proof|申請版本|申请版本|phip|聆訊後|聆讯后", title, re.I):
            temp.unlink(missing_ok=True)
            continue
        selected_prospectus = (item, temp, pages, digest)
        break
    except Exception as exc:
        print(f"Prospectus candidate rejected: {exc}")
        temp.unlink(missing_ok=True)
if selected_prospectus is None:
    raise RuntimeError("No valid final prospectus PDF was found.")
prospectus_item, prospectus_temp, prospectus_pages, prospectus_digest = selected_prospectus
prospectus_filename = f"{len(manifest)+1:02d}_林清轩_正式招股章程_2025-12-18_港交所官方版.pdf"
prospectus_destination = REPORTS / prospectus_filename
prospectus_temp.replace(prospectus_destination)
render_cover(prospectus_destination)
manifest.append({
    "type": "final_prospectus",
    "reporting_year": None,
    "publication_time": date_of(prospectus_item),
    "title": title_of(prospectus_item),
    "filename": prospectus_filename,
    "source_url": url_of(prospectus_item),
    "pages": prospectus_pages,
    "bytes": prospectus_destination.stat().st_size,
    "sha256": prospectus_digest,
})

# Prefer a formal interim report; when none exists yet, use the latest interim-results announcement.
interim_report_records = hkex_search("40300", "zh")
interim_candidates = [item for item in interim_report_records if is_pdf_record(item)]
latest_item: dict | None = None
latest_type = "interim_report"
minimum_pages = 20
if interim_candidates:
    latest_item = sorted(interim_candidates, key=date_of, reverse=True)[0]
else:
    announcement_records = hkex_search("40100", "zh")
    announcement_candidates = [
        item for item in announcement_records
        if is_pdf_record(item)
        and re.search(r"中期業績|中期业绩|interim\s+results", title_of(item), re.I)
        and not re.search(r"股息|dividend.*form|董事會會議|董事会会议|board meeting", title_of(item), re.I)
    ]
    announcement_candidates.sort(key=date_of, reverse=True)
    if not announcement_candidates:
        raise RuntimeError("No interim report or interim-results announcement was found.")
    latest_item = announcement_candidates[0]
    latest_type = "interim_results_announcement"
    minimum_pages = 15

latest_filename = f"{len(manifest)+1:02d}_林清轩_2026年中期业绩公告_截至2026年6月30日_港交所官方版.pdf"
latest_destination = REPORTS / latest_filename
print(f"Downloading latest interim disclosure: {url_of(latest_item)}")
download_pdf(url_of(latest_item), latest_destination)
latest_pages, latest_digest, latest_sample = inspect_pdf(latest_destination, minimum_pages)
render_cover(latest_destination)
manifest.append({
    "type": latest_type,
    "reporting_period_end": "2026-06-30",
    "publication_time": date_of(latest_item),
    "title": title_of(latest_item),
    "filename": latest_filename,
    "source_url": url_of(latest_item),
    "pages": latest_pages,
    "bytes": latest_destination.stat().st_size,
    "sha256": latest_digest,
})

# Confirm scope: Forest Cabin listed on 30 Dec 2025, so only one post-listing annual report exists by the cutoff.
annual_count = sum(1 for item in manifest if item["type"] == "annual_report")
if annual_count != 1 or 2025 not in annual_by_year:
    raise RuntimeError(f"Unexpected annual-report scope: {sorted(annual_by_year)}")

readme = f"""林清轩（02657.HK）公开财务与上市文件合集

整理截止日期：{CUTOFF}
上市主体：{COMPANY_ZH}
英文名称：{COMPANY_EN}
上市日期：2025年12月30日

本压缩包收录：
1. 2025年完整年度报告（林清轩上市后截至整理日唯一一份正式年报）；
2. 2025年12月18日正式招股章程；
3. 截至2026年6月30日止六个月的2026年中期业绩公告，为截至整理日最新定期财务披露。

说明：
- 林清轩于2025年12月30日才在港交所上市，因此不存在2020—2024年港交所正式年报；相关历史财务数据已包含在正式招股章程中。
- 香港主板公司通常披露年度报告和中期报告，不强制披露A股式普通季度报告。截至2026年9月3日，2026年正式中期报告尚未刊发，因此以2026年8月31日发布的中期业绩公告作为“最新季报/最新定期财务披露”。
- 未收录已被正式招股章程取代的申请版本、聆讯后资料集及招股表格，以避免重复。
- 所有PDF均来自香港交易所披露易官方文件链接，仅供个人研究使用，版权归原发布机构所有。

校验：
- 已检查PDF文件签名、文件体积、公司名称/股票代码及页数；
- 已将每份PDF首页渲染为图片以验证可读性；
- 已生成SHA-256校验值；
- 已执行ZIP完整性测试。
"""
(REPORTS / "README_文件说明.txt").write_text(readme, encoding="utf-8")
(REPORTS / "文件清单与官方来源.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

with (REPORTS / "文件清单与官方来源.csv").open("w", encoding="utf-8-sig", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=[
        "type", "reporting_year", "reporting_period_end", "publication_time", "title",
        "filename", "pages", "bytes", "sha256", "source_url",
    ])
    writer.writeheader()
    for item in manifest:
        writer.writerow({key: item.get(key, "") for key in writer.fieldnames})

members = sorted(REPORTS.iterdir(), key=lambda p: p.name)
with ZipFile(FINAL_ZIP, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
    for member in members:
        archive.write(member, arcname=member.name)
with ZipFile(FINAL_ZIP) as archive:
    bad = archive.testzip()
    if bad is not None:
        raise RuntimeError(f"ZIP integrity failure at {bad}")
    pdf_names = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
    if len(pdf_names) != len(manifest):
        raise RuntimeError(f"ZIP PDF count mismatch: {len(pdf_names)} != {len(manifest)}")

print("PACKAGE_READY", FINAL_ZIP, FINAL_ZIP.stat().st_size)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
client.close()
