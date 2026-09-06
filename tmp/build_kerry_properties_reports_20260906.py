from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse
from zipfile import ZIP_DEFLATED, ZipFile

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

BASE = "https://www.kerryprops.com"
MIRROR = "https://kerryprops.kerryplus.com"
STOCK_CODE = "00683"
CUTOFF_DATE = "2026-09-06"

OUT = Path("out_kerry_properties_20260906")
RAW = OUT / "raw"
PACKAGE = OUT / "package"
RENDERS = OUT / "renders"
DIAGNOSTICS = OUT / "diagnostics"
ZIP_PATH = OUT / "Kerry_Properties_00683_2020_2025_Annual_Reports_2026_Interim_Results.zip"

shutil.rmtree(OUT, ignore_errors=True)
for directory in (RAW, PACKAGE, RENDERS, DIAGNOSTICS):
    directory.mkdir(parents=True, exist_ok=True)

session = requests.Session()
session.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf;q=0.8,*/*;q=0.7",
        "Connection": "keep-alive",
    }
)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def alternate_urls(url: str) -> list[str]:
    """Generate official-host fallbacks without leaving the issuer's domains."""
    parsed = urlparse(url)
    variants: list[str] = [url]

    for host in ("www.kerryprops.com", "kerryprops.kerryplus.com"):
        for scheme in ("https", "http"):
            candidate = urlunparse((scheme, host, parsed.path, parsed.params, parsed.query, parsed.fragment))
            if candidate not in variants:
                variants.append(candidate)
    return variants


def get_html(url: str, label: str) -> tuple[str, str]:
    last_error: Exception | None = None
    for candidate in alternate_urls(url):
        for attempt in range(1, 4):
            try:
                response = session.get(candidate, timeout=45, allow_redirects=True)
                print("HTML", label, response.status_code, len(response.content), response.url)
                if response.status_code == 200 and len(response.content) > 1000:
                    text = response.text
                    (DIAGNOSTICS / f"{label}.html").write_text(text, encoding="utf-8", errors="ignore")
                    return text, str(response.url)
            except Exception as exc:
                last_error = exc
                print("HTML_RETRY", label, attempt, repr(exc), candidate)
                time.sleep(attempt)
    raise RuntimeError(f"Unable to fetch HTML for {label}: {last_error}")


def find_annual_detail_links() -> dict[int, str]:
    html, final_url = get_html(f"{BASE}/cn/report", "report_list_cn")
    soup = BeautifulSoup(html, "html.parser")
    found: dict[int, str] = {}
    for anchor in soup.find_all("a", href=True):
        text = clean_text(anchor.get_text(" ", strip=True))
        href = urljoin(final_url, anchor.get("href", ""))
        for year in range(2020, 2026):
            patterns = (
                f"{year} 年报",
                f"{year} 年報",
                f"{year} Annual Report",
            )
            if any(pattern.lower() in text.lower() for pattern in patterns):
                found[year] = href
    # Stable report-detail IDs are retained only as official fallback URLs.
    fallback_ids = {2020: 42, 2021: 44, 2022: 46, 2023: 49, 2024: 51, 2025: 54}
    for year, report_id in fallback_ids.items():
        found.setdefault(year, f"{BASE}/cn/report/view?id={report_id}")
    print("ANNUAL_DETAIL_LINKS", json.dumps(found, ensure_ascii=False, indent=2))
    return found


def find_pdf_link_on_detail(detail_url: str, year: int) -> str | None:
    try:
        html, final_url = get_html(detail_url, f"annual_{year}_detail")
    except Exception as exc:
        print("DETAIL_FETCH_FAILED", year, repr(exc))
        return None
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[tuple[int, str]] = []
    for anchor in soup.find_all("a", href=True):
        text = clean_text(anchor.get_text(" ", strip=True))
        href = urljoin(final_url, anchor.get("href", ""))
        low = href.lower()
        score = 0
        if "下载完整报告" in text or "下載完整報告" in text or "download full report" in text.lower():
            score += 100
        if low.endswith(".pdf"):
            score += 60
        if "/reports/annual/" in low:
            score += 40
        if str(year) in low:
            score += 10
        if score:
            candidates.append((score, href))
    candidates.sort(reverse=True)
    if candidates:
        print("ANNUAL_PDF_DISCOVERED", year, candidates[0][1])
        return candidates[0][1]
    return None


ANNUAL_FALLBACKS: dict[int, list[str]] = {
    2020: [
        f"{BASE}/files/reports/annual/cn/2020/ar2020_c1.pdf",
        f"{BASE}/files/reports/annual/hk/2020/ar2020_c1.pdf",
        f"{BASE}/files/reports/annual/en/2020/ar2020_e1.pdf",
    ],
    2021: [
        f"{BASE}/files/reports/annual/cn/2021/c_00683ar_20220427.pdf",
        f"{BASE}/files/reports/annual/cn/2021/c_00683ar_20220426.pdf",
        f"{BASE}/files/reports/annual/cn/2021/c_00683ar_20220428.pdf",
        f"{BASE}/files/reports/annual/cn/2021/ar2021_c1.pdf",
        f"{BASE}/files/reports/annual/hk/2021/c_00683ar_20220427.pdf",
        f"{BASE}/files/reports/annual/en/2021/e_00683ar_20220427.pdf",
    ],
    2022: [f"{BASE}/files/reports/annual/cn/2022/c_00683ar_20230427.pdf"],
    2023: [f"{BASE}/files/reports/annual/cn/2023/c_00683ar_20240424.pdf"],
    2024: [f"{BASE}/files/reports/annual/cn/2024/c_00683ar_20250428.pdf"],
    2025: [f"{BASE}/files/reports/annual/cn/2025/c_00683ar_20260427.pdf"],
}


def find_latest_interim_results_link() -> tuple[str | None, str]:
    page_urls = [
        f"{BASE}/cn/news/announcements/2026",
        f"{BASE}/hk/news/announcements/2026",
        f"{BASE}/en/news/announcements/2026",
        f"{BASE}/cn",
        f"{BASE}/",
    ]
    title_patterns = [
        "二零二六年中期业绩公告",
        "二零二六年中期業績公告",
        "2026年中期业绩公告",
        "Interim Results Announcement 2026",
    ]
    for index, page_url in enumerate(page_urls):
        try:
            html, final_url = get_html(page_url, f"interim_source_{index}")
        except Exception as exc:
            print("INTERIM_PAGE_FAILED", page_url, repr(exc))
            continue
        soup = BeautifulSoup(html, "html.parser")
        for row in soup.find_all(["tr", "li", "div"]):
            row_text = clean_text(row.get_text(" ", strip=True))
            if not any(pattern.lower() in row_text.lower() for pattern in title_patterns):
                continue
            anchors = row.find_all("a", href=True)
            for anchor in anchors:
                href = urljoin(final_url, anchor.get("href", ""))
                if href:
                    if href.lower().endswith(".pdf"):
                        print("INTERIM_PDF_DISCOVERED", href)
                        return href, row_text
                    # Detail-page fallback: inspect it for a PDF.
                    try:
                        detail_html, detail_final = get_html(href, "interim_detail")
                        detail_soup = BeautifulSoup(detail_html, "html.parser")
                        for link in detail_soup.find_all("a", href=True):
                            pdf_href = urljoin(detail_final, link.get("href", ""))
                            if pdf_href.lower().endswith(".pdf"):
                                print("INTERIM_PDF_DISCOVERED_FROM_DETAIL", pdf_href)
                                return pdf_href, row_text
                    except Exception:
                        pass
        # Also inspect anchors directly; some pages use no table rows.
        for anchor in soup.find_all("a", href=True):
            text = clean_text(anchor.get_text(" ", strip=True))
            if any(pattern.lower() in text.lower() for pattern in title_patterns):
                href = urljoin(final_url, anchor.get("href", ""))
                if href.lower().endswith(".pdf"):
                    return href, text
    return None, ""


INTERIM_FALLBACKS = [
    f"{BASE}/files/news/cn/c_00683ann_20260824.pdf",
    f"{BASE}/files/news/hk/c_00683ann_20260824.pdf",
    f"{BASE}/files/news/en/e_00683ann_20260824.pdf",
]


def download_pdf(candidates: list[str], destination: Path, referer: str) -> str:
    errors: list[str] = []
    tried: set[str] = set()
    expanded: list[str] = []
    for candidate in candidates:
        if not candidate:
            continue
        for variant in alternate_urls(candidate):
            if variant not in tried:
                tried.add(variant)
                expanded.append(variant)

    for url in expanded:
        for attempt in range(1, 4):
            try:
                response = session.get(
                    url,
                    timeout=180,
                    allow_redirects=True,
                    headers={
                        "Referer": referer,
                        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.5",
                    },
                )
                content_type = response.headers.get("content-type", "")
                data = response.content
                print("PDF_GET", response.status_code, content_type, len(data), response.url)
                if response.status_code == 200 and len(data) > 80_000 and data.startswith(b"%PDF-"):
                    destination.write_bytes(data)
                    return str(response.url)
                errors.append(f"{url}: HTTP {response.status_code}, {content_type}, {len(data)} bytes")
            except Exception as exc:
                errors.append(f"{url}: {exc!r}")
                print("PDF_RETRY", attempt, repr(exc), url)
                time.sleep(attempt * 2)
    raise RuntimeError("All PDF download candidates failed:\n" + "\n".join(errors[-20:]))


def validate_pdf(path: Path, document_type: str, report_year: int | None = None) -> dict:
    if path.read_bytes()[:5] != b"%PDF-":
        raise RuntimeError(f"Not a PDF: {path}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    minimum = 100 if document_type == "annual_report" else 20
    if pages < minimum:
        raise RuntimeError(f"Unexpectedly short PDF {path.name}: {pages} pages")

    sample_indices = list(range(min(18, pages)))
    if pages > 30:
        sample_indices.extend([pages // 2, pages - 2, pages - 1])
    text_parts: list[str] = []
    for index in sorted(set(sample_indices)):
        try:
            text_parts.append(reader.pages[index].extract_text() or "")
        except Exception:
            pass
    extracted = "\n".join(text_parts)
    normalized = re.sub(r"\s+", "", extracted).lower()
    tokens = ["kerryproperties", "嘉里建設", "嘉里建设", "00683", "683.hk"]
    if not any(token.lower() in normalized for token in tokens):
        raise RuntimeError(f"Company identity not detected in {path.name}")
    if report_year is not None and str(report_year) not in normalized:
        print("WARNING_YEAR_NOT_IN_SAMPLE", report_year, path.name)

    pdfinfo = subprocess.run(
        ["pdfinfo", str(path)], capture_output=True, text=True, check=True
    ).stdout
    render_prefix = RENDERS / path.stem
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
            str(render_prefix),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    render_path = Path(str(render_prefix) + ".png")
    if not render_path.exists() or render_path.stat().st_size < 10_000:
        raise RuntimeError(f"Cover render failed for {path.name}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "pdfinfo": pdfinfo,
        "render_file": render_path.name,
        "sample_text_chars": len(extracted),
    }


detail_links = find_annual_detail_links()
manifest: list[dict] = []

for index, year in enumerate(range(2020, 2026), start=1):
    detail_url = detail_links[year]
    discovered = find_pdf_link_on_detail(detail_url, year)
    raw_path = RAW / f"annual_{year}.pdf"
    source_url = download_pdf(
        [discovered or "", *ANNUAL_FALLBACKS[year]],
        raw_path,
        referer=detail_url,
    )
    meta = validate_pdf(raw_path, "annual_report", report_year=year)
    output_name = f"{index:02d}_Kerry_Properties_{year}_Annual_Report.pdf"
    destination = PACKAGE / output_name
    shutil.copy2(raw_path, destination)
    manifest.append(
        {
            "index": index,
            "type": "annual_report",
            "reporting_year": year,
            "filename": output_name,
            "source_page": detail_url,
            "source_pdf": source_url,
            **{k: v for k, v in meta.items() if k != "pdfinfo"},
        }
    )

interim_discovered, interim_title = find_latest_interim_results_link()
interim_raw = RAW / "interim_results_2026.pdf"
interim_source = download_pdf(
    [interim_discovered or "", *INTERIM_FALLBACKS],
    interim_raw,
    referer=f"{BASE}/cn/news/announcements/2026",
)
interim_meta = validate_pdf(interim_raw, "interim_results_announcement")
interim_name = "07_Kerry_Properties_2026_Interim_Results_Announcement.pdf"
shutil.copy2(interim_raw, PACKAGE / interim_name)
manifest.append(
    {
        "index": 7,
        "type": "latest_interim_results_announcement",
        "reporting_period_end": "2026-06-30",
        "publication_date": "2026-08-24",
        "title": interim_title or "二零二六年中期业绩公告",
        "filename": interim_name,
        "source_page": f"{BASE}/cn/news/announcements/2026",
        "source_pdf": interim_source,
        **{k: v for k, v in interim_meta.items() if k != "pdfinfo"},
    }
)

readme = f"""嘉里建设（00683.HK）2020-2025年报及最新财务披露

整理截止日期：{CUTOFF_DATE}
上市主体：嘉里建设有限公司（Kerry Properties Limited）
股票代码：00683.HK

压缩包内容：
- 2020、2021、2022、2023、2024、2025年完整年度报告；
- 2026年中期业绩公告，报告期截至2026年6月30日，发布日期为2026年8月24日。

关于“最新季报”的说明：
嘉里建设为香港上市公司，不按A股制度强制披露普通第一季度或第三季度财务报告。截至2026年9月6日，公司尚未发布2026年正式中期报告，最新定期财务披露为2026年8月24日发布的中期业绩公告，因此本包将其作为“最新季报/最新定期财务报告”收录。

文件来源：
全部PDF均来自嘉里建设官网的官方投资者关系页面或其官方文件服务器。

校验项目：
PDF文件签名、公司名称/证券代码、实际页数、首页渲染可读性、SHA-256及ZIP完整性。
"""
(PACKAGE / "README_文件说明.txt").write_text(readme, encoding="utf-8")
(PACKAGE / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
)
with (PACKAGE / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
    columns = [
        "index",
        "type",
        "reporting_year",
        "reporting_period_end",
        "publication_date",
        "title",
        "filename",
        "pages",
        "bytes",
        "sha256",
        "source_page",
        "source_pdf",
        "render_file",
        "sample_text_chars",
    ]
    writer = csv.DictWriter(handle, fieldnames=columns)
    writer.writeheader()
    for item in manifest:
        writer.writerow({column: item.get(column, "") for column in columns})

with ZipFile(ZIP_PATH, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
    for member in sorted(PACKAGE.iterdir(), key=lambda p: p.name):
        archive.write(member, arcname=member.name)

with ZipFile(ZIP_PATH) as archive:
    damaged = archive.testzip()
    if damaged is not None:
        raise RuntimeError(f"ZIP integrity failure at {damaged}")
    pdf_names = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
    if len(pdf_names) != 7:
        raise RuntimeError(f"Expected 7 PDFs, found {len(pdf_names)}")

print("PACKAGE_READY", ZIP_PATH, ZIP_PATH.stat().st_size)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
