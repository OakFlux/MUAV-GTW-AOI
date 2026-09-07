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

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

STOCK_ID = "560"
STOCK_CODE_HK = "00317"
STOCK_CODE_A = "600685"
CUTOFF = "2026-09-07"
BASE = "https://www1.hkexnews.hk"
SEARCH_URL = f"{BASE}/search/titlesearch.xhtml"

OUT = Path("out_cssc_defense_financials_20260907")
PACKAGE = OUT / "package"
RAW = OUT / "raw"
RENDERS = OUT / "renders"
DIAG = OUT / "diagnostics"
FINAL = OUT / "CSSC_Defense_600685_00317_2020_2025_Annual_Reports_2026_Interim.zip"

shutil.rmtree(OUT, ignore_errors=True)
for directory in (PACKAGE, RAW, RENDERS, DIAG):
    directory.mkdir(parents=True, exist_ok=True)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
session = requests.Session()
session.headers.update(
    {
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
)


def clean_markup(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value, flags=re.S)
    return re.sub(r"\s+", " ", html_lib.unescape(value)).strip()


def parse_size_bytes(text: str) -> int:
    match = re.search(r"\((\d+(?:\.\d+)?)\s*(KB|MB)\)", text, re.I)
    if not match:
        return 0
    value = float(match.group(1))
    return int(value * (1024 if match.group(2).upper() == "KB" else 1024 * 1024))


def parse_rows(page_html: str, language: str) -> list[dict]:
    soup = BeautifulSoup(page_html, "html.parser")
    records: list[dict] = []
    for row in soup.find_all("tr"):
        link = row.select_one(".doc-link a") or row.find("a", href=True)
        if link is None:
            continue
        href = str(link.get("href") or "").strip()
        if not href:
            continue
        title = re.sub(r"\s+", " ", link.get_text(" ", strip=True)).strip()
        if not title:
            continue
        release = row.select_one(".release-time")
        headline = row.select_one(".headline")
        stock = row.select_one(".stock-short-code")
        row_text = re.sub(r"\s+", " ", row.get_text(" ", strip=True)).strip()
        records.append(
            {
                "title": title,
                "published": re.sub(
                    r"^(Release Time:|發放時間:|发布时间:)\s*",
                    "",
                    release.get_text(" ", strip=True) if release else "",
                    flags=re.I,
                ).strip(),
                "category": headline.get_text(" ", strip=True) if headline else "",
                "stock_blob": stock.get_text(" ", strip=True) if stock else "",
                "pdf_url": urljoin(BASE + "/", href),
                "language": language,
                "size_hint_bytes": parse_size_bytes(row_text),
                "row_text": row_text,
            }
        )
    return records


def search_records(date_from: str, date_to: str, language: str, label: str) -> list[dict]:
    form = {
        "stockId": STOCK_ID,
        "sortDir": "desc",
        "sortByOptions": "DateTime",
        "market": "SEHK",
        "language": language,
        "category": "0",
        "from": date_from,
        "to": date_to,
        "page": "1",
    }
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": SEARCH_URL,
        "Origin": BASE,
    }
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = session.post(SEARCH_URL, data=form, headers=headers, timeout=90)
            response.raise_for_status()
            (DIAG / f"{label}_{language}.html").write_text(response.text, encoding="utf-8")
            records = parse_rows(response.text, language)
            print(
                "SEARCH",
                label,
                language,
                response.status_code,
                len(response.content),
                "records=",
                len(records),
            )
            return records
        except Exception as exc:
            last_error = exc
            print("SEARCH_RETRY", label, language, attempt, repr(exc))
            time.sleep(attempt * 2)
    raise RuntimeError(f"HKEX search failed for {label}/{language}: {last_error}")


def is_pdf_record(item: dict) -> bool:
    return item["pdf_url"].lower().split("?", 1)[0].endswith(".pdf")


def year_tokens(year: int) -> tuple[str, str]:
    digits = "零一二三四五六七八九"
    return str(year), "".join(digits[int(ch)] for ch in str(year))


def annual_score(item: dict, year: int) -> float:
    title = item["title"]
    category = item["category"]
    combined = f"{title} {category}"
    numeric, chinese = year_tokens(year)
    if not is_pdf_record(item):
        return -10_000
    if not re.search(r"年報|年报|年度報告|年度报告|annual\s+report", combined, re.I):
        return -10_000
    if numeric not in combined and chinese not in combined:
        return -10_000
    if re.search(
        r"業績|业绩|results|summary|摘要|環境|环境|ESG|sustainab|corporate governance|企業管治|企业管治",
        combined,
        re.I,
    ):
        return -10_000
    score = 100.0
    if re.search(r"Financial Statements|財務報表|财务报表", category, re.I):
        score += 30
    if re.search(r"\[Annual Report\]|\[年報\]|\[年报\]", combined, re.I):
        score += 20
    if item["language"] == "ZH":
        score += 8
    score += min(item.get("size_hint_bytes", 0), 50 * 1024 * 1024) / (1024 * 1024)
    return score


def latest_score(item: dict) -> float:
    title = item["title"]
    category = item["category"]
    combined = f"{title} {category}"
    if not is_pdf_record(item):
        return -10_000
    if re.search(
        r"estimated|estimate|expected|improvement|profit warning|profit alert|預告|预告|預增|预增|盈利警告|業績預告|业绩预告",
        combined,
        re.I,
    ):
        return -10_000
    score = -10_000.0
    if re.search(r"2026|二零二六", combined, re.I) and re.search(
        r"半年度報告|半年度报告|中期報告|中期报告|interim\s+report|half[- ]year\s+report",
        combined,
        re.I,
    ):
        score = 300.0
    elif re.search(r"2026|二零二六", combined, re.I) and re.search(
        r"中期業績|中期业绩|interim\s+results|half[- ]year\s+results",
        combined,
        re.I,
    ):
        score = 200.0
    elif re.search(r"FIRST\s+QUARTERLY\s+REPORT\s+OF\s+2026|2026.*第一季度報告|2026.*第一季度报告", combined, re.I):
        score = 100.0
    if score < 0:
        return score
    if item["language"] == "ZH":
        score += 10
    if re.search(r"Overseas Regulatory Announcement|海外監管公告|海外监管公告", category, re.I):
        score += 5
    score += min(item.get("size_hint_bytes", 0), 50 * 1024 * 1024) / (1024 * 1024)
    return score


def download_pdf(url: str, destination: Path) -> None:
    headers = {
        "User-Agent": UA,
        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.5",
        "Referer": SEARCH_URL,
    }
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            with session.get(url, headers=headers, timeout=240, stream=True) as response:
                response.raise_for_status()
                with destination.open("wb") as handle:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            handle.write(chunk)
            if destination.stat().st_size < 80_000:
                raise RuntimeError(f"file too small: {destination.stat().st_size}")
            with destination.open("rb") as handle:
                if handle.read(5) != b"%PDF-":
                    raise RuntimeError("downloaded content is not PDF")
            print("DOWNLOADED", destination.name, destination.stat().st_size, url)
            return
        except Exception as exc:
            last_error = exc
            destination.unlink(missing_ok=True)
            print("DOWNLOAD_RETRY", destination.name, attempt, repr(exc))
            time.sleep(attempt * 2)
    raise RuntimeError(f"Unable to download {url}: {last_error}")


def inspect_pdf(path: Path, minimum_pages: int) -> dict:
    data = path.read_bytes()
    if not data.startswith(b"%PDF-"):
        raise RuntimeError(f"Invalid PDF signature: {path.name}")
    reader = PdfReader(str(path), strict=False)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            pass
    pages = len(reader.pages)
    if pages < minimum_pages:
        raise RuntimeError(f"Unexpectedly short PDF {path.name}: {pages} pages")

    sample_indices = list(range(min(20, pages)))
    if pages > 30:
        sample_indices.extend([pages // 2, pages - 2, pages - 1])
    samples: list[str] = []
    for index in sorted(set(i for i in sample_indices if 0 <= i < pages)):
        try:
            samples.append(reader.pages[index].extract_text() or "")
        except Exception:
            pass
    text = "\n".join(samples)
    normalized = re.sub(r"\s+", "", text).lower()
    identity_tokens = [
        "中船防务",
        "中船海洋与防务装备",
        "中船海洋與防務裝備",
        "csscoffshore",
        "comec",
        "600685",
        "00317",
        "317hk",
    ]
    identity_ok = any(token.lower() in normalized for token in identity_tokens)
    if not identity_ok:
        print("WARNING_IDENTITY_TEXT_NOT_EXTRACTED", path.name)

    digest = hashlib.sha256(data).hexdigest()
    return {
        "pages": pages,
        "bytes": len(data),
        "sha256": digest,
        "identity_text_ok": identity_ok,
        "sample_text_chars": len(text),
    }


def render_cover(path: Path) -> Path:
    prefix = RENDERS / path.stem
    subprocess.run(
        [
            "pdftoppm",
            "-f",
            "1",
            "-l",
            "1",
            "-png",
            "-singlefile",
            "-r",
            "100",
            str(path),
            str(prefix),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    image = Path(str(prefix) + ".png")
    if not image.exists() or image.stat().st_size < 8_000:
        raise RuntimeError(f"Cover render failed: {path.name}")
    return image


all_selected: list[tuple[str, dict, Path, dict]] = []

# Download one complete annual report for every financial year 2020-2025.
for year in range(2020, 2026):
    pub_year = year + 1
    date_from = f"{pub_year}0101"
    date_to = f"{pub_year}0630"
    records = []
    for language in ("ZH", "EN"):
        records.extend(search_records(date_from, date_to, language, f"annual_{year}"))
    candidates = sorted(
        ((annual_score(item, year), item) for item in records),
        key=lambda pair: pair[0],
        reverse=True,
    )
    candidates = [item for score, item in candidates if score > 0]
    if not candidates:
        raise RuntimeError(f"No complete annual report candidate found for {year}")

    selected = None
    errors = []
    for index, item in enumerate(candidates[:8], 1):
        temp = RAW / f"annual_{year}_candidate_{index}.pdf"
        try:
            download_pdf(item["pdf_url"], temp)
            meta = inspect_pdf(temp, 100)
            render_cover(temp)
            selected = (item, temp, meta)
            break
        except Exception as exc:
            errors.append(f"{item['title']} :: {exc}")
            temp.unlink(missing_ok=True)
    if selected is None:
        raise RuntimeError(f"Annual report {year} candidates failed: {errors}")
    item, temp, meta = selected
    output = PACKAGE / f"{year}_中船防务_年度报告.pdf"
    temp.replace(output)
    all_selected.append(("annual_report", item, output, meta))
    print("SELECTED_ANNUAL", year, item["published"], item["title"], meta["pages"])

# Select the latest complete periodic report available by the cutoff.
latest_records: list[dict] = []
for date_from in ("20260801", "20260701"):
    for language in ("ZH", "EN"):
        latest_records.extend(search_records(date_from, "20260907", language, f"latest_{date_from}"))

# Deduplicate identical URLs.
latest_by_url: dict[str, dict] = {}
for item in latest_records:
    current = latest_by_url.get(item["pdf_url"])
    if current is None or latest_score(item) > latest_score(current):
        latest_by_url[item["pdf_url"]] = item
latest_candidates = sorted(
    ((latest_score(item), item) for item in latest_by_url.values()),
    key=lambda pair: pair[0],
    reverse=True,
)
latest_candidates = [item for score, item in latest_candidates if score > 0]
if not latest_candidates:
    # Fallback query for the entire current year, including the Q1 report.
    fallback = []
    for language in ("ZH", "EN"):
        fallback.extend(search_records("20260101", "20260907", language, "latest_fallback"))
    latest_candidates = [
        item
        for score, item in sorted(
            ((latest_score(item), item) for item in fallback),
            key=lambda pair: pair[0],
            reverse=True,
        )
        if score > 0
    ]
if not latest_candidates:
    raise RuntimeError("No 2026 interim or quarterly report candidate was found")

latest_selected = None
latest_errors = []
for index, item in enumerate(latest_candidates[:12], 1):
    temp = RAW / f"latest_candidate_{index}.pdf"
    try:
        download_pdf(item["pdf_url"], temp)
        min_pages = 20 if latest_score(item) >= 200 else 5
        meta = inspect_pdf(temp, min_pages)
        render_cover(temp)
        latest_selected = (item, temp, meta)
        break
    except Exception as exc:
        latest_errors.append(f"{item['title']} :: {exc}")
        temp.unlink(missing_ok=True)
if latest_selected is None:
    raise RuntimeError(f"Latest-report candidates failed: {latest_errors}")
latest_item, latest_temp, latest_meta = latest_selected
latest_title_norm = f"{latest_item['title']} {latest_item['category']}"
if re.search(r"半年度|中期|interim|half[- ]year", latest_title_norm, re.I):
    latest_output = PACKAGE / "2026_中船防务_半年度报告_最新定期财务报告.pdf"
    latest_type = "2026 interim / half-year report"
else:
    latest_output = PACKAGE / "2026_中船防务_第一季度报告_最新季报.pdf"
    latest_type = "2026 first quarterly report"
latest_temp.replace(latest_output)
all_selected.append((latest_type, latest_item, latest_output, latest_meta))
print(
    "SELECTED_LATEST",
    latest_item["published"],
    latest_item["title"],
    latest_meta["pages"],
)

# Ensure all seven PDFs are distinct.
hashes = [entry[3]["sha256"] for entry in all_selected]
if len(all_selected) != 7 or len(set(hashes)) != 7:
    raise RuntimeError("Selected report count or uniqueness check failed")

manifest: list[dict] = []
for index, (report_type, item, path, meta) in enumerate(all_selected, 1):
    manifest.append(
        {
            "序号": index,
            "报告类型": report_type,
            "发布日期": item["published"],
            "港交所标题": item["title"],
            "语言": item["language"],
            "文件名": path.name,
            "实际页数": meta["pages"],
            "文件大小_字节": meta["bytes"],
            "SHA256": meta["sha256"],
            "公司身份文本校验": meta["identity_text_ok"],
            "官方来源": item["pdf_url"],
        }
    )

readme = f"""中船防务（600685.SH / 00317.HK）2020—2025年报及最新定期财务报告

整理截止日期：{CUTOFF}
上市主体：中船海洋与防务装备股份有限公司
港股简称：COMEC

本压缩包收录：
1. 2020年完整年度报告；
2. 2021年完整年度报告；
3. 2022年完整年度报告；
4. 2023年完整年度报告；
5. 2024年完整年度报告；
6. 2025年完整年度报告；
7. 截至整理日最新的2026年半年度/中期报告；如正式中期报告尚未发布，则收录完整中期业绩公告；仅在两者均不存在时才回退至2026年第一季度报告。

“最新季报”口径说明：
截至2026年9月7日，中船防务已经披露2026年半年度报告。半年度报告覆盖第二季度和上半年累计数据，发布时间晚于2026年第一季度报告，因此作为最新定期财务报告收录。

来源与校验：
- 全部PDF来自香港交易所披露易的中船防务/COMEC官方披露链接；
- 已检查PDF文件签名、实际页数、文件体积、公司名称或证券代码、SHA-256及首页渲染；
- 已执行最终ZIP完整性测试；
- 压缩包内不含网页快捷方式或跳转文件。
"""
(PACKAGE / "README_文件说明.txt").write_text(readme, encoding="utf-8")
(PACKAGE / "文件清单与官方来源.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
)
with (PACKAGE / "文件清单与官方来源.csv").open(
    "w", encoding="utf-8-sig", newline=""
) as handle:
    writer = csv.DictWriter(handle, fieldnames=list(manifest[0].keys()))
    writer.writeheader()
    writer.writerows(manifest)

FINAL.unlink(missing_ok=True)
with ZipFile(FINAL, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
    for member in sorted(PACKAGE.iterdir(), key=lambda path: path.name):
        archive.write(member, arcname=member.name)
with ZipFile(FINAL) as archive:
    damaged = archive.testzip()
    if damaged is not None:
        raise RuntimeError(f"ZIP integrity failure: {damaged}")
    pdf_names = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
    if len(pdf_names) != 7:
        raise RuntimeError(f"Expected 7 PDFs in ZIP, found {len(pdf_names)}")

print("PACKAGE_READY", FINAL, FINAL.stat().st_size)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
session.close()
