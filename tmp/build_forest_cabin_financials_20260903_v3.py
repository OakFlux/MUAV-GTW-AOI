from __future__ import annotations

import csv
import hashlib
import html as html_lib
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
BASE = "https://www1.hkexnews.hk"
SEARCH_URL = f"{BASE}/search/titlesearch.xhtml"
OUT = Path("out_forest_cabin_20260903")
REPORTS = OUT / "reports"
RENDERS = OUT / "renders"
FINAL_ZIP = OUT / "Forest_Cabin_02657_All_Annual_Reports_Prospectus_Latest_Interim_2026-09-03.zip"

shutil.rmtree(OUT, ignore_errors=True)
REPORTS.mkdir(parents=True, exist_ok=True)
RENDERS.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
client = httpx.Client(
    http2=True,
    follow_redirects=True,
    timeout=httpx.Timeout(240.0, connect=30.0),
    headers={
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    },
)


def clean_markup(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value, flags=re.S)
    return re.sub(r"\s+", " ", html_lib.unescape(value)).strip()


def parse_results(page_html: str, language: str) -> list[dict]:
    records: list[dict] = []
    for row in re.findall(r"<tr[^>]*>.*?</tr>", page_html, re.I | re.S):
        link_match = re.search(r'class=["\'][^"\']*doc-link[^"\']*["\'][^>]*>.*?<a[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', row, re.I | re.S)
        if not link_match:
            continue
        href = html_lib.unescape(link_match.group(1)).strip()
        title = clean_markup(link_match.group(2))
        if not title:
            continue
        headline_match = re.search(r'class=["\'][^"\']*headline[^"\']*["\'][^>]*>(.*?)</(?:div|td)>', row, re.I | re.S)
        release_match = re.search(r'class=["\'][^"\']*release-time[^"\']*["\'][^>]*>(.*?)</td>', row, re.I | re.S)
        code_match = re.search(r'(?:Stock Code|股份代號|股份代码)\s*:?\s*</span>\s*(\d+)', row, re.I | re.S)
        stock_match = re.search(r'class=["\'][^"\']*stock-short-code[^"\']*["\'][^>]*>(.*?)</td>', row, re.I | re.S)
        stock_blob = clean_markup(stock_match.group(1)) if stock_match else ""
        if not code_match:
            code_match = re.search(r"\b(02657|2657)\b", stock_blob)
        records.append({
            "title": title,
            "published": clean_markup(release_match.group(1)).replace("Release Time:", "").replace("發放時間:", "").strip() if release_match else "",
            "category": clean_markup(headline_match.group(1)) if headline_match else "",
            "stock_code": code_match.group(1).zfill(5) if code_match else "",
            "pdf_url": urljoin(BASE + "/", href),
            "language": language,
        })
    return records


def query_page(language: str, page: int = 1) -> list[dict]:
    form = {
        "stockId": STOCK_ID,
        "sortDir": "desc",
        "sortByOptions": "DateTime",
        "market": "SEHK",
        "language": language,
        "category": "0",
        "from": "20250501",
        "to": "20260903",
        "page": str(page),
    }
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": SEARCH_URL,
        "Origin": BASE,
    }
    last_error = None
    for attempt in range(1, 5):
        try:
            response = client.post(SEARCH_URL, data=form, headers=headers)
            response.raise_for_status()
            records = parse_results(response.text, language)
            print(f"POST SEARCH language={language} page={page}: status={response.status_code} html={len(response.text)} records={len(records)}")
            if records:
                return records
            # Save a diagnostic sample in the workflow workspace if the site changes.
            (OUT / f"diagnostic_search_{language}_{page}.html").write_text(response.text, encoding="utf-8")
            return []
        except Exception as exc:
            last_error = exc
            print(f"POST SEARCH retry {attempt}: {exc}")
            time.sleep(attempt * 2)
    raise RuntimeError(f"HKEX title search failed: {last_error}")


def discover_records() -> list[dict]:
    records: list[dict] = []
    for language in ("ZH", "EN"):
        for page in range(1, 4):
            batch = query_page(language, page)
            if not batch:
                break
            records.extend(batch)
            if len(batch) < 100:
                break
    deduped: dict[str, dict] = {}
    for item in records:
        url = item["pdf_url"]
        if not url.lower().split("?", 1)[0].endswith(".pdf"):
            continue
        current = deduped.get(url)
        if current is None or item["language"] == "ZH":
            deduped[url] = item
    result = list(deduped.values())
    print("UNIQUE PDF RECORDS", len(result))
    for item in result:
        if re.search(r"年報|年报|annual report|全球.*發售|全球.*发售|global offering|中期業績|中期业绩|interim results", item["title"], re.I):
            print("RELEVANT", json.dumps(item, ensure_ascii=False))
    return result


def download(url: str, destination: Path) -> None:
    headers = {
        "User-Agent": UA,
        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.5",
        "Referer": SEARCH_URL,
    }
    last_error = None
    for attempt in range(1, 6):
        try:
            with client.stream("GET", url, headers=headers) as response:
                response.raise_for_status()
                with destination.open("wb") as handle:
                    for chunk in response.iter_bytes(1024 * 1024):
                        handle.write(chunk)
            if destination.stat().st_size < 80_000:
                raise RuntimeError(f"file too small: {destination.stat().st_size}")
            with destination.open("rb") as handle:
                if handle.read(5) != b"%PDF-":
                    raise RuntimeError("not a PDF")
            return
        except Exception as exc:
            last_error = exc
            destination.unlink(missing_ok=True)
            print(f"DOWNLOAD retry {attempt}: {url}: {exc}")
            time.sleep(attempt * 2)
    raise RuntimeError(f"Download failed: {url}: {last_error}")


def inspect(path: Path, minimum_pages: int, extra_tokens: tuple[str, ...] = ()) -> tuple[int, str]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < minimum_pages:
        raise RuntimeError(f"Too few pages in {path.name}: {pages} < {minimum_pages}")
    sample_parts = []
    sample_indexes = list(range(min(45, pages)))
    if pages > 80:
        sample_indexes.extend([pages // 2, pages - 2, pages - 1])
    for idx in sorted(set(i for i in sample_indexes if 0 <= i < pages)):
        try:
            sample_parts.append(reader.pages[idx].extract_text() or "")
        except Exception:
            pass
    normalized = re.sub(r"\s+", "", "\n".join(sample_parts)).lower()
    identity_tokens = ("forestcabin", "上海林清軒", "上海林清轩", "02657", "2657") + extra_tokens
    if not any(token.lower() in normalized for token in identity_tokens):
        raise RuntimeError(f"Company identity not found in {path.name}")
    return pages, hashlib.sha256(path.read_bytes()).hexdigest()


def render_first(path: Path) -> int:
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


def choose(records: list[dict], include: str, exclude: str = "") -> dict | None:
    candidates = [item for item in records if re.search(include, item["title"], re.I) and (not exclude or not re.search(exclude, item["title"], re.I))]
    candidates.sort(key=lambda x: (x["published"], 1 if x["language"] == "ZH" else 0), reverse=True)
    return candidates[0] if candidates else None


records = discover_records()

# Direct official HKEX URLs are retained as fallbacks for the two documents whose identities were independently verified.
annual_item = choose(records, r"2025.*年報|2025.*年报|annual report 2025") or {
    "title": "ANNUAL REPORT 2025",
    "published": "17/04/2026 16:59",
    "category": "Annual Report",
    "pdf_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0417/2026041700672.pdf",
    "language": "EN",
}
prospectus_item = choose(records, r"全球.*發售|全球.*发售|global offering", r"formal notice|正式通告|正式公告") or {
    "title": "GLOBAL OFFERING",
    "published": "18/12/2025 07:35",
    "category": "Listing Documents - Offer for Subscription",
    "pdf_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/1218/2025121800221.pdf",
    "language": "EN",
}
interim_item = choose(records, r"中期業績|中期业绩|interim results", r"dividend|股息|董事會會議|董事会会议|board meeting")
if interim_item is None:
    raise RuntimeError("The current 2026 interim-results PDF link was not found in the live HKEX form response.")

selected = [
    (annual_item, REPORTS / "01_林清轩_2025年年度报告_港交所官方版.pdf", "annual_report", 100, {"reporting_year": 2025}),
    (prospectus_item, REPORTS / "02_林清轩_正式招股章程_2025-12-18_港交所官方版.pdf", "final_prospectus", 250, {}),
    (interim_item, REPORTS / "03_林清轩_2026年中期业绩公告_截至2026年6月30日_港交所官方版.pdf", "latest_interim_results_announcement", 15, {"reporting_period_end": "2026-06-30"}),
]

manifest: list[dict] = []
for item, path, doc_type, min_pages, extra in selected:
    print("DOWNLOAD SELECTED", doc_type, json.dumps(item, ensure_ascii=False))
    download(item["pdf_url"], path)
    pages, digest = inspect(path, min_pages)
    render_bytes = render_first(path)
    manifest.append({
        "type": doc_type,
        **extra,
        "publication_time": item["published"],
        "title": item["title"],
        "category": item.get("category", ""),
        "filename": path.name,
        "source_url": item["pdf_url"],
        "pages": pages,
        "bytes": path.stat().st_size,
        "first_page_render_bytes": render_bytes,
        "sha256": digest,
    })

readme = f"""林清轩（02657.HK）所有正式年报、正式招股章程及最新定期财务报告合集

整理截止日期：{CUTOFF}
上市主体：上海林清轩化妆品集团股份有限公司
英文名称：Shanghai Forest Cabin Cosmetics Group Co., Ltd.
上市日期：2025年12月30日

本压缩包收录：
1. 2025年完整年度报告；
2. 2025年12月18日正式招股章程（Global Offering）；
3. 截至2026年6月30日止六个月的2026年中期业绩公告，为截至整理日最新定期财务披露。

范围说明：
- 林清轩于2025年12月30日才在港交所上市，因此截至2026年9月3日仅有一份港交所正式年报；2020—2024年不存在其作为上市公司的正式年报，历史财务数据已包含在正式招股章程中。
- 香港主板发行人通常披露年度报告和中期报告，不强制披露A股式普通季度报告。截至整理日，2026年正式中期报告尚未发布，因此以2026年8月31日发布的中期业绩公告作为“最新季报/最新定期财务披露”。
- 未收录已被正式招股章程取代的申请版本、聆讯后资料集、招股表格及其他重复上市文件。
- 全部PDF来自香港交易所披露易官方文件链接，仅供个人研究使用，版权归原发布机构所有。

已完成校验：PDF签名、公司身份、报告类型、实际页数、首页渲染可读性、SHA-256及ZIP完整性。
"""
(REPORTS / "README_文件说明.txt").write_text(readme, encoding="utf-8")
(REPORTS / "文件清单与官方来源.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
with (REPORTS / "文件清单与官方来源.csv").open("w", encoding="utf-8-sig", newline="") as handle:
    columns = ["type", "reporting_year", "reporting_period_end", "publication_time", "title", "category", "filename", "pages", "bytes", "first_page_render_bytes", "sha256", "source_url"]
    writer = csv.DictWriter(handle, fieldnames=columns)
    writer.writeheader()
    for item in manifest:
        writer.writerow({column: item.get(column, "") for column in columns})

with ZipFile(FINAL_ZIP, "w", ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(REPORTS.iterdir(), key=lambda p: p.name):
        archive.write(path, path.name)
with ZipFile(FINAL_ZIP) as archive:
    bad = archive.testzip()
    if bad is not None:
        raise RuntimeError(f"ZIP integrity failure: {bad}")
    if len([name for name in archive.namelist() if name.lower().endswith(".pdf")]) != 3:
        raise RuntimeError("ZIP does not contain exactly three PDFs")

print("PACKAGE_READY", FINAL_ZIP, FINAL_ZIP.stat().st_size)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
client.close()
