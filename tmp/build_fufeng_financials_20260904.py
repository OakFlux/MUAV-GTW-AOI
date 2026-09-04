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

COMPANY_ZH = "阜丰集团有限公司"
COMPANY_EN = "FUFENG GROUP LIMITED"
STOCK_CODE = "00546"
HKEX_STOCK_ID = "13457"
CUTOFF = "2026-09-04"
BASE = "https://www1.hkexnews.hk"
SEARCH_URL = f"{BASE}/search/titlesearch.xhtml"

OUT = Path("out_fufeng_20260904")
REPORTS = OUT / "reports"
RENDERS = OUT / "renders"
FINAL_ZIP = OUT / "Fufeng_Group_00546_2020_2025_Annual_Reports_2026_Interim_Results.zip"

shutil.rmtree(OUT, ignore_errors=True)
REPORTS.mkdir(parents=True, exist_ok=True)
RENDERS.mkdir(parents=True, exist_ok=True)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
client = httpx.Client(
    http2=True,
    follow_redirects=True,
    timeout=httpx.Timeout(300.0, connect=30.0),
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
    rows = re.findall(r"<tr[^>]*>.*?</tr>", page_html, re.I | re.S)
    for row in rows:
        link_match = re.search(
            r'class=["\'][^"\']*doc-link[^"\']*["\'][^>]*>.*?'
            r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            row,
            re.I | re.S,
        )
        if not link_match:
            continue
        href = html_lib.unescape(link_match.group(1)).strip()
        doc_title = clean_markup(link_match.group(2))
        if not doc_title:
            continue
        headline_match = re.search(
            r'class=["\'][^"\']*headline[^"\']*["\'][^>]*>(.*?)</(?:div|td)>',
            row,
            re.I | re.S,
        )
        release_match = re.search(
            r'class=["\'][^"\']*release-time[^"\']*["\'][^>]*>(.*?)</td>',
            row,
            re.I | re.S,
        )
        code_match = re.search(
            r'(?:Stock Code|股份代號|股份代码)\s*:?\s*</span>\s*(\d+)',
            row,
            re.I | re.S,
        )
        records.append(
            {
                "title": doc_title,
                "published": (
                    clean_markup(release_match.group(1))
                    .replace("Release Time:", "")
                    .replace("發放時間:", "")
                    .replace("发布时间:", "")
                    .strip()
                    if release_match
                    else ""
                ),
                "category": clean_markup(headline_match.group(1)) if headline_match else "",
                "stock_code": code_match.group(1).zfill(5) if code_match else "",
                "pdf_url": urljoin(BASE + "/", href),
                "language": language,
            }
        )
    return records


def query_window(language: str, date_from: str, date_to: str, max_pages: int = 8) -> list[dict]:
    all_records: list[dict] = []
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": SEARCH_URL,
        "Origin": BASE,
    }
    for page in range(1, max_pages + 1):
        form = {
            "stockId": HKEX_STOCK_ID,
            "sortDir": "desc",
            "sortByOptions": "DateTime",
            "market": "SEHK",
            "language": language,
            "category": "0",
            "from": date_from,
            "to": date_to,
            "page": str(page),
        }
        last_error: Exception | None = None
        batch: list[dict] = []
        for attempt in range(1, 5):
            try:
                response = client.post(SEARCH_URL, data=form, headers=headers)
                response.raise_for_status()
                batch = parse_results(response.text, language)
                print(
                    f"HKEX window={date_from}-{date_to} language={language} "
                    f"page={page} status={response.status_code} records={len(batch)}"
                )
                if not batch:
                    diagnostic = OUT / f"diagnostic_{date_from}_{date_to}_{language}_{page}.html"
                    diagnostic.write_text(response.text, encoding="utf-8")
                break
            except Exception as exc:
                last_error = exc
                print(f"HKEX search retry {attempt}: {exc}")
                time.sleep(attempt * 2)
        else:
            raise RuntimeError(f"HKEX search failed: {last_error}")

        if not batch:
            break
        all_records.extend(batch)
        if len(batch) < 100:
            break
    return all_records


def deduplicate(records: list[dict]) -> list[dict]:
    by_url: dict[str, dict] = {}
    for item in records:
        url = item.get("pdf_url", "")
        if not url.lower().split("?", 1)[0].endswith(".pdf"):
            continue
        current = by_url.get(url)
        if current is None:
            by_url[url] = item
        elif item.get("language") == "ZH" and current.get("language") != "ZH":
            by_url[url] = item
    return list(by_url.values())


def download_pdf(url: str, destination: Path) -> None:
    headers = {
        "User-Agent": UA,
        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.5",
        "Referer": SEARCH_URL,
    }
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            with client.stream("GET", url, headers=headers) as response:
                response.raise_for_status()
                with destination.open("wb") as handle:
                    for chunk in response.iter_bytes(1024 * 1024):
                        handle.write(chunk)
            if destination.stat().st_size < 150_000:
                raise RuntimeError(f"Downloaded file is unexpectedly small: {destination.stat().st_size}")
            with destination.open("rb") as handle:
                if handle.read(5) != b"%PDF-":
                    raise RuntimeError("Downloaded content is not a PDF")
            return
        except Exception as exc:
            last_error = exc
            destination.unlink(missing_ok=True)
            print(f"Download retry {attempt} for {url}: {exc}")
            time.sleep(attempt * 2)
    raise RuntimeError(f"Unable to download {url}: {last_error}")


def extract_validation_text(path: Path, reader: PdfReader, pages: int) -> str:
    sample_parts: list[str] = []
    indexes = list(range(min(35, pages)))
    if pages > 70:
        indexes.extend([pages // 2, pages - 3, pages - 2, pages - 1])
    for index in sorted(set(i for i in indexes if 0 <= i < pages)):
        try:
            sample_parts.append(reader.pages[index].extract_text() or "")
        except Exception:
            pass
    sample = "\n".join(sample_parts)
    if len(sample.strip()) >= 500:
        return sample

    text_path = OUT / f"{path.stem}_pdftotext.txt"
    subprocess.run(
        ["pdftotext", "-f", "1", "-l", str(min(35, pages)), str(path), str(text_path)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    return text_path.read_text(encoding="utf-8", errors="ignore")


def validate_pdf(path: Path, expected_year: int | None, minimum_pages: int) -> tuple[int, str]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < minimum_pages:
        raise RuntimeError(f"Too few pages in {path.name}: {pages} < {minimum_pages}")
    sample = extract_validation_text(path, reader, pages)
    normalized = re.sub(r"\s+", "", sample).lower()
    identity_tokens = ("fufenggroup", "阜豐集團", "阜丰集团", "stockcode546", "股份代號546")
    if not any(token.lower() in normalized for token in identity_tokens):
        raise RuntimeError(f"Fufeng identity could not be verified in {path.name}")
    if expected_year is not None and str(expected_year) not in normalized:
        raise RuntimeError(f"Expected reporting year {expected_year} not found in {path.name}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return pages, digest


def render_first_page(path: Path) -> int:
    prefix = RENDERS / path.stem
    subprocess.run(
        ["pdftoppm", "-f", "1", "-l", "1", "-png", "-singlefile", "-r", "110", str(path), str(prefix)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    png = Path(str(prefix) + ".png")
    if not png.exists() or png.stat().st_size < 10_000:
        raise RuntimeError(f"First-page rendering failed for {path.name}")
    return png.stat().st_size


def annual_candidate_score(item: dict, year: int) -> tuple[int, str]:
    blob = f"{item.get('title', '')} {item.get('category', '')}".lower()
    score = 0
    if str(year) in blob:
        score += 100
    if "annual report" in blob or "年報" in blob or "年报" in blob:
        score += 100
    if "financial statements/esg information" in blob:
        score += 20
    if "environmental" in blob or "esg report" in blob or "中期" in blob or "interim" in blob:
        score -= 300
    if item.get("language") == "ZH":
        score += 10
    return score, item.get("published", "")


def select_annual(year: int) -> dict:
    publication_year = year + 1
    date_from = f"{publication_year}0101"
    date_to = f"{publication_year}0630"
    records = deduplicate(
        query_window("ZH", date_from, date_to) + query_window("EN", date_from, date_to)
    )
    candidates = [
        item
        for item in records
        if annual_candidate_score(item, year)[0] >= 180
    ]
    candidates.sort(key=lambda item: annual_candidate_score(item, year), reverse=True)
    if not candidates:
        relevant = [
            f"{item.get('published')} | {item.get('category')} | {item.get('title')} | {item.get('pdf_url')}"
            for item in records
            if str(year) in f"{item.get('title')} {item.get('category')}"
        ]
        raise RuntimeError(f"No annual report found for {year}. Relevant records: {relevant[:20]}")
    return candidates[0]


def select_latest_interim() -> dict:
    records = deduplicate(
        query_window("ZH", "20260801", "20260904")
        + query_window("EN", "20260801", "20260904")
    )
    candidates: list[tuple[int, str, dict]] = []
    for item in records:
        blob = f"{item.get('title', '')} {item.get('category', '')}".lower()
        score = 0
        if "interim results" in blob or "中期業績" in blob or "中期业绩" in blob:
            score += 200
        if "30 june 2026" in blob or "二零二六年六月三十日" in blob or "2026年6月30日" in blob:
            score += 150
        if "announcement" in blob or "公布" in blob:
            score += 20
        if "dividend" in blob and "interim results" not in blob:
            score -= 250
        if "notification letter" in blob or "通知" in blob:
            score -= 250
        if item.get("language") == "ZH":
            score += 10
        if score >= 250:
            candidates.append((score, item.get("published", ""), item))
    candidates.sort(key=lambda row: (row[0], row[1]), reverse=True)
    if not candidates:
        raise RuntimeError("No valid 2026 interim-results announcement found.")
    return candidates[0][2]


manifest: list[dict] = []
for index, year in enumerate(range(2020, 2026), start=1):
    selected = select_annual(year)
    filename = f"{index:02d}_阜丰集团_{year}年年度报告_港交所官方版.pdf"
    destination = REPORTS / filename
    print(f"SELECTED ANNUAL {year}: {json.dumps(selected, ensure_ascii=False)}")
    download_pdf(selected["pdf_url"], destination)
    pages, digest = validate_pdf(destination, year, 120)
    render_size = render_first_page(destination)
    manifest.append(
        {
            "type": "annual_report",
            "reporting_year": year,
            "publication_time": selected.get("published", ""),
            "title": selected.get("title", ""),
            "category": selected.get("category", ""),
            "filename": filename,
            "source_url": selected["pdf_url"],
            "pages": pages,
            "bytes": destination.stat().st_size,
            "first_page_render_bytes": render_size,
            "sha256": digest,
        }
    )

latest = select_latest_interim()
latest_filename = "07_阜丰集团_2026年中期业绩公告_截至2026年6月30日_港交所官方版.pdf"
latest_destination = REPORTS / latest_filename
print(f"SELECTED LATEST INTERIM: {json.dumps(latest, ensure_ascii=False)}")
download_pdf(latest["pdf_url"], latest_destination)
latest_pages, latest_digest = validate_pdf(latest_destination, 2026, 20)
latest_render_size = render_first_page(latest_destination)
manifest.append(
    {
        "type": "latest_interim_results_announcement",
        "reporting_period_end": "2026-06-30",
        "publication_time": latest.get("published", ""),
        "title": latest.get("title", ""),
        "category": latest.get("category", ""),
        "filename": latest_filename,
        "source_url": latest["pdf_url"],
        "pages": latest_pages,
        "bytes": latest_destination.stat().st_size,
        "first_page_render_bytes": latest_render_size,
        "sha256": latest_digest,
    }
)

if [item.get("reporting_year") for item in manifest if item["type"] == "annual_report"] != list(range(2020, 2026)):
    raise RuntimeError("Annual-report year coverage is incomplete.")

readme = f"""阜丰集团（00546.HK）2020-2025年报及最新财务披露合集

整理截止日期：{CUTOFF}
上市主体：{COMPANY_ZH}
英文名称：{COMPANY_EN}
证券代码：{STOCK_CODE}.HK

收录文件：
- 2020、2021、2022、2023、2024、2025年度完整年度报告，共6份；
- 截至2026年6月30日止六个月的2026年中期业绩公告，共1份。

“最新季报”说明：
阜丰集团为香港上市公司，通常披露年度报告和中期报告，不按A股模式强制发布普通季度报告。截至2026年9月4日，2026年正式中期报告尚未刊发；最新完整定期财务披露为2026年8月28日发布的中期业绩公告，因此本包将其作为“最新季报/最新财务披露”收录。

来源与校验：
- 全部PDF来自香港交易所披露易官方文件链接；
- 已逐份检查PDF签名、报告年份、公司名称/证券代码和实际页数；
- 已逐份渲染首页检查可读性；
- 已生成SHA-256校验值，并执行ZIP完整性测试。

文件仅供个人研究使用，版权归阜丰集团及原发布机构所有。
"""
(REPORTS / "README_文件说明.txt").write_text(readme, encoding="utf-8")
(REPORTS / "文件清单与官方来源.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
)
with (REPORTS / "文件清单与官方来源.csv").open("w", encoding="utf-8-sig", newline="") as handle:
    columns = [
        "type",
        "reporting_year",
        "reporting_period_end",
        "publication_time",
        "title",
        "category",
        "filename",
        "pages",
        "bytes",
        "first_page_render_bytes",
        "sha256",
        "source_url",
    ]
    writer = csv.DictWriter(handle, fieldnames=columns)
    writer.writeheader()
    for item in manifest:
        writer.writerow({column: item.get(column, "") for column in columns})

(REPORTS / "SHA256SUMS.txt").write_text(
    "\n".join(f"{item['sha256']}  {item['filename']}" for item in manifest) + "\n",
    encoding="utf-8",
)
(REPORTS / "页数校验结果.json").write_text(
    json.dumps({item["filename"]: item["pages"] for item in manifest}, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

with ZipFile(FINAL_ZIP, "w", ZIP_DEFLATED, compresslevel=9) as archive:
    for member in sorted(REPORTS.iterdir(), key=lambda path: path.name):
        archive.write(member, arcname=member.name)
with ZipFile(FINAL_ZIP) as archive:
    bad = archive.testzip()
    if bad is not None:
        raise RuntimeError(f"ZIP integrity failure at {bad}")
    pdf_names = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
    if len(pdf_names) != 7:
        raise RuntimeError(f"Expected 7 PDFs in ZIP, found {len(pdf_names)}")

print("PACKAGE_READY", FINAL_ZIP, FINAL_ZIP.stat().st_size)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
client.close()
