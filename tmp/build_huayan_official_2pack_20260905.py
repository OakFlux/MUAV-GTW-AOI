from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
from pypdf import PdfReader

OUT = Path("out_huayan_official_2pack")
REPORTS = OUT / "reports"
RENDERS = OUT / "renders"
FINAL_ZIP = OUT / "Huayan_Robotics_01021_Broker_Research_Reports_2.zip"

shutil.rmtree(OUT, ignore_errors=True)
REPORTS.mkdir(parents=True, exist_ok=True)
RENDERS.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"
REFERER = "https://www.sdicsi.com.hk/cn/research-report/tag/1021hk"
client = httpx.Client(
    http2=True,
    follow_redirects=True,
    timeout=httpx.Timeout(180.0, connect=30.0),
    headers={
        "User-Agent": UA,
        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.5",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": REFERER,
    },
)

DOCS = [
    {
        "kind": "standalone_company_report",
        "broker": "国投证券（香港）有限公司",
        "date": "2026-03-23",
        "title": "华沿机器人IPO点评",
        "description": "独立公司IPO研究报告",
        "url": "https://www.sdicsi.com.hk/backend/storage/app/media/ResearchReports/IPOReports/1021-20260323.pdf",
        "filename": "01_国投证券香港_2026-03-23_华沿机器人IPO点评_原始PDF.pdf",
        "minimum_pages": 3,
    },
    {
        "kind": "broker_morning_report_with_company_section",
        "broker": "国投证券（香港）有限公司",
        "date": "2026-03-25",
        "title": "港股晨报（含华沿机器人IPO研究栏目）",
        "description": "券商官方港股晨报；内含华沿机器人IPO研究栏目，作为第二份公开原始券商研究资料收录",
        "url": "https://www.sdicsi.com.hk/backend/storage/app/media/ResearchReports/MorningPosts/Daily_Note_20260325.pdf",
        "filename": "02_国投证券香港_2026-03-25_港股晨报_含华沿机器人IPO研究_原始PDF.pdf",
        "minimum_pages": 3,
    },
]


def download(url: str, destination: Path) -> None:
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                content_type = (response.headers.get("content-type") or "").lower()
                with destination.open("wb") as handle:
                    for chunk in response.iter_bytes(1024 * 1024):
                        handle.write(chunk)
            size = destination.stat().st_size
            with destination.open("rb") as handle:
                signature = handle.read(5)
            print("DOWNLOAD", attempt, response.status_code, content_type, size, url)
            if size < 50_000:
                raise RuntimeError(f"Downloaded file too small: {size}")
            if signature != b"%PDF-":
                raise RuntimeError(f"Not a PDF: signature={signature!r}")
            return
        except Exception as exc:
            last_error = exc
            destination.unlink(missing_ok=True)
            print("DOWNLOAD_RETRY", attempt, url, repr(exc))
            time.sleep(attempt * 2)
    raise RuntimeError(f"Unable to download {url}: {last_error}")


def inspect_pdf(path: Path, minimum_pages: int) -> dict:
    subprocess.run(["qpdf", "--check", str(path)], check=True, capture_output=True, text=True)
    reader = PdfReader(str(path), strict=False)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise RuntimeError(f"Encrypted PDF cannot be read: {path.name}: {exc}")
    pages = len(reader.pages)
    if pages < minimum_pages:
        raise RuntimeError(f"Too few pages in {path.name}: {pages} < {minimum_pages}")

    page_texts: list[str] = []
    for page in reader.pages:
        try:
            page_texts.append(page.extract_text() or "")
        except Exception:
            page_texts.append("")
    full_text = "\n".join(page_texts)
    normalized = "".join(full_text.lower().split())
    identity_terms = ["华沿机器人", "華沿機器人", "1021.hk", "01021", "1021"]
    if not any("".join(term.lower().split()) in normalized for term in identity_terms):
        raise RuntimeError(f"Huayan Robotics identity not found in {path.name}")

    relevant_pages: list[int] = []
    for index, text in enumerate(page_texts, start=1):
        compact = "".join(text.lower().split())
        if any("".join(term.lower().split()) in compact for term in identity_terms):
            relevant_pages.append(index)

    text_file = OUT / f"{path.stem}.txt"
    subprocess.run(["pdftotext", "-layout", str(path), str(text_file)], check=True)
    extracted_text = text_file.read_text(encoding="utf-8", errors="ignore")
    if len(extracted_text.strip()) < 1_500:
        raise RuntimeError(f"Insufficient searchable text in {path.name}")

    pdfinfo = subprocess.run(
        ["pdfinfo", str(path)], check=True, capture_output=True, text=True
    ).stdout

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "relevant_pages": relevant_pages,
        "searchable_text_chars": len(extracted_text),
        "pdfinfo": pdfinfo,
    }


def render_check(path: Path, pages: int, relevant_pages: list[int]) -> list[dict]:
    targets = [1, pages]
    if relevant_pages:
        targets.extend([relevant_pages[0], relevant_pages[-1]])
    targets = sorted(set(page for page in targets if 1 <= page <= pages))
    results: list[dict] = []
    for page_number in targets:
        prefix = RENDERS / f"{path.stem}_p{page_number}"
        subprocess.run(
            [
                "pdftoppm",
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                "-png",
                "-singlefile",
                "-r",
                "110",
                str(path),
                str(prefix),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        image = Path(str(prefix) + ".png")
        if not image.exists() or image.stat().st_size < 10_000:
            raise RuntimeError(f"Render check failed for {path.name}, page {page_number}")
        results.append({"page": page_number, "bytes": image.stat().st_size})
    return results


manifest: list[dict] = []
for doc in DOCS:
    path = REPORTS / doc["filename"]
    download(doc["url"], path)
    meta = inspect_pdf(path, doc["minimum_pages"])
    render_checks = render_check(path, meta["pages"], meta["relevant_pages"])
    manifest.append(
        {
            "kind": doc["kind"],
            "broker": doc["broker"],
            "date": doc["date"],
            "title": doc["title"],
            "description": doc["description"],
            "filename": doc["filename"],
            "source_url": doc["url"],
            "pages": meta["pages"],
            "huayan_section_pages": meta["relevant_pages"],
            "bytes": meta["bytes"],
            "sha256": meta["sha256"],
            "searchable_text_chars": meta["searchable_text_chars"],
            "render_checks": render_checks,
        }
    )
    print("VALID", json.dumps(manifest[-1], ensure_ascii=False))

# Require that the standalone report is exactly a short complete IPO report and
# that the morning report contains at least one distinct Huayan page.
if not manifest[0]["huayan_section_pages"]:
    raise RuntimeError("Standalone IPO report lacks a Huayan Robotics section")
if not manifest[1]["huayan_section_pages"]:
    raise RuntimeError("Morning report lacks a Huayan Robotics section")

readme_lines = [
    "华沿机器人（01021.HK）公开券商研究资料合集",
    "",
    "本包只收录无需登录即可从券商官网公开下载的原始PDF，不包含网页跳转、封面文件或两页预览版。",
    "",
    "收录文件：",
]
for index, item in enumerate(manifest, start=1):
    section = ",".join(str(x) for x in item["huayan_section_pages"])
    readme_lines.append(
        f"{index}. {item['broker']}｜{item['date']}｜{item['pages']}页｜{item['title']}｜华沿机器人内容所在页：{section}"
    )
readme_lines.extend(
    [
        "",
        "范围说明：目前公开可核实的交银国际、兴证国际、国泰海通、中信证券及德意志银行公司首次覆盖报告，原始PDF均未提供无需登录的公开直链，部分网站只展示摘要或前两页预览，因此没有将这些预览冒充完整报告。",
        "本包第一份为独立的华沿机器人IPO公司研究报告；第二份为券商官方港股晨报，其中含华沿机器人IPO研究栏目。后者不是另一份独立公司深度报告，收录目的是满足两份公开原始券商研究资料的需求，并在文件名及清单中明确标注。",
        "",
        "校验项目：PDF签名、qpdf结构检查、实际页数、公司名称/证券代码、全文可提取性、华沿机器人栏目页定位、相关页面渲染和ZIP完整性。",
        "文件仅供个人研究使用，版权归原发布机构所有。",
    ]
)
(REPORTS / "README_文件说明.txt").write_text("\n".join(readme_lines), encoding="utf-8")
(REPORTS / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

columns = [
    "kind",
    "broker",
    "date",
    "title",
    "description",
    "filename",
    "pages",
    "huayan_section_pages",
    "bytes",
    "sha256",
    "searchable_text_chars",
    "source_url",
]
with (REPORTS / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=columns)
    writer.writeheader()
    for item in manifest:
        row = {key: item.get(key, "") for key in columns}
        row["huayan_section_pages"] = ",".join(str(x) for x in item["huayan_section_pages"])
        writer.writerow(row)

with ZipFile(FINAL_ZIP, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(REPORTS.iterdir(), key=lambda p: p.name):
        archive.write(path, arcname=path.name)

with ZipFile(FINAL_ZIP) as archive:
    bad = archive.testzip()
    if bad is not None:
        raise RuntimeError(f"ZIP integrity failure at {bad}")
    pdfs = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
    if len(pdfs) != 2:
        raise RuntimeError(f"Expected 2 PDFs in ZIP, got {len(pdfs)}")

print("PACKAGE_READY", FINAL_ZIP, FINAL_ZIP.stat().st_size)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
client.close()
