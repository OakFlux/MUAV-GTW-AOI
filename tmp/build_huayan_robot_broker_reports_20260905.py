from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
import img2pdf
from PIL import Image
from pypdf import PdfReader

OUT = Path("out_huayan_robot_broker_reports_20260905")
REPORTS_DIR = OUT / "reports"
IMAGES_DIR = OUT / "images"
RENDERS_DIR = OUT / "renders"
FINAL_ZIP = OUT / "Huayan_Robotics_01021_Broker_Research_Reports_3.zip"

shutil.rmtree(OUT, ignore_errors=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
RENDERS_DIR.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
client = httpx.Client(
    http2=True,
    follow_redirects=True,
    timeout=httpx.Timeout(90.0, connect=30.0),
    headers={
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    },
)

REPORTS: list[dict[str, Any]] = [
    {
        "id": "5587624",
        "date_path": "2026/08/07",
        "date": "2026-08-07",
        "broker": "交银国际",
        "analysts": "陈庆、李柳晓",
        "title": "人形机器人行业系列（4）：‘卖铲人’型平台公司，运动控制底层价值有望重估",
        "type": "首次覆盖 / 公司深度",
        "minimum_pages": 30,
        "output_name": "01_交银国际_2026-08-07_华沿机器人_卖铲人型平台公司_首次覆盖深度.pdf",
    },
    {
        "id": "5435007",
        "date_path": "2026/05/24",
        "date": "2026-05-24",
        "broker": "兴证国际",
        "analysts": "余小丽、张忠业",
        "title": "头部协作机器人公司，七轴人形手臂放量可期",
        "type": "首次覆盖 / 公司深度",
        "minimum_pages": 12,
        "output_name": "02_兴证国际_2026-05-24_华沿机器人_七轴人形手臂放量可期_首次覆盖深度.pdf",
    },
    {
        "id": "5316158",
        "date_path": "2026/03/23",
        "date": "2026-03-23",
        "broker": "国投证券（香港）",
        "analysts": "王强",
        "title": "华沿机器人IPO点评",
        "type": "IPO研究 / 公司研究",
        "minimum_pages": 3,
        "output_name": "03_国投证券香港_2026-03-23_华沿机器人IPO点评.pdf",
    },
]


def clean_text(raw: str) -> str:
    raw = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<style\b[^>]*>.*?</style>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(raw)).strip()


def get_with_retries(url: str, *, referer: str, attempts: int = 5) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = client.get(
                url,
                headers={
                    "User-Agent": UA,
                    "Referer": referer,
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                },
            )
            return response
        except Exception as exc:
            last_error = exc
            print(f"RETRY {attempt}/{attempts} {url}: {exc}")
            time.sleep(min(8, attempt * 2))
    raise RuntimeError(f"Request failed after {attempts} attempts: {url}: {last_error}")


def collect_image_urls(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for item in value.values():
            found.extend(collect_image_urls(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(collect_image_urls(item))
    elif isinstance(value, str):
        if value.startswith("http") and re.search(r"\.(?:png|jpe?g|webp)(?:\?|$)", value, re.I):
            found.append(value)
    return found


def probe_public_api(report: dict[str, Any]) -> list[str]:
    url = f"https://api.fxbaogao.com/mofoun/report/report/getReportPreviewImages?reportId={report['id']}"
    try:
        response = client.get(
            url,
            headers={
                "User-Agent": UA,
                "Referer": f"https://www.fxbaogao.com/detail/{report['id']}",
                "Accept": "application/json,text/plain,*/*",
            },
        )
        print("PREVIEW_API", report["id"], response.status_code, response.headers.get("content-type"), len(response.content))
        if response.status_code != 200:
            return []
        payload = response.json()
        urls = collect_image_urls(payload)
        print("PREVIEW_API_URLS", report["id"], len(urls), json.dumps(urls[:8], ensure_ascii=False))
        return urls
    except Exception as exc:
        print("PREVIEW_API_ERROR", report["id"], repr(exc))
        return []


def validate_detail_page(report: dict[str, Any]) -> dict[str, Any]:
    detail_url = f"https://www.fxbaogao.com/detail/{report['id']}"
    response = client.get(detail_url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    response.raise_for_status()
    text = clean_text(response.text)
    if "华沿机器人" not in text and "華沿機器人" not in text:
        raise RuntimeError(f"Company name not found on detail page {report['id']}")
    if report["title"].split("，", 1)[0].replace("‘", "").replace("’", "")[:8] not in text.replace("‘", "").replace("’", ""):
        print("DETAIL_TITLE_WARNING", report["id"], report["title"])
    page_denominators = [int(x) for x in re.findall(r"\b\d+\s*/\s*(\d{1,3})\b", text)]
    html_page_hints = [
        int(x)
        for x in re.findall(
            r"(?:pageCount|page_count|totalPage|total_page|totalPages|pages)\s*[:=]\s*[\"']?(\d{1,3})",
            response.text,
            flags=re.I,
        )
    ]
    return {
        "detail_url": detail_url,
        "detail_bytes": len(response.content),
        "detail_text_chars": len(text),
        "page_count_hints": sorted(set(page_denominators + html_page_hints)),
    }


def save_valid_image(content: bytes, destination: Path) -> tuple[int, int, str]:
    destination.write_bytes(content)
    try:
        with Image.open(destination) as image:
            image.load()
            width, height = image.size
            image_format = image.format or ""
            if width < 700 or height < 900:
                raise RuntimeError(f"Image dimensions too small: {width}x{height}")
            # Normalize to RGB PNG only when the source is not directly usable by img2pdf.
            if image.mode not in ("RGB", "L", "1") or image_format.upper() not in ("PNG", "JPEG", "JPG"):
                normalized = image.convert("RGB")
                normalized.save(destination, format="PNG", optimize=True)
                image_format = "PNG"
                width, height = normalized.size
            return width, height, image_format
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def discover_and_download_pages(report: dict[str, Any]) -> tuple[list[Path], list[dict[str, Any]]]:
    report_dir = IMAGES_DIR / report["id"]
    report_dir.mkdir(parents=True, exist_ok=True)
    referer = f"https://www.fxbaogao.com/detail/{report['id']}"

    api_urls = probe_public_api(report)
    api_url_by_page: dict[int, str] = {}
    for url in api_urls:
        match = re.search(r"-(\d+)\.(?:png|jpe?g|webp)(?:\?|$)", url, re.I)
        if match:
            api_url_by_page[int(match.group(1))] = url

    pages: list[Path] = []
    metadata: list[dict[str, Any]] = []
    consecutive_misses = 0
    max_pages = 120

    for page_number in range(1, max_pages + 1):
        candidate_urls = []
        if page_number in api_url_by_page:
            candidate_urls.append(api_url_by_page[page_number])
        candidate_urls.extend(
            [
                f"https://public.fxbaogao.com/report-image/{report['date_path']}/{report['id']}-{page_number}.png",
                f"https://public.fxbaogao.com/report-image/{report['date_path']}/{report['id']}-{page_number}.jpg",
            ]
        )

        downloaded = False
        for url in dict.fromkeys(candidate_urls):
            try:
                response = get_with_retries(url, referer=referer, attempts=3)
                content_type = (response.headers.get("content-type") or "").lower()
                valid_status = response.status_code == 200
                valid_type = content_type.startswith("image/")
                valid_size = len(response.content) > 15_000
                print(
                    "PAGE_PROBE",
                    report["id"],
                    page_number,
                    response.status_code,
                    content_type,
                    len(response.content),
                    url,
                )
                if not (valid_status and valid_type and valid_size):
                    continue
                destination = report_dir / f"page_{page_number:03d}.png"
                width, height, image_format = save_valid_image(response.content, destination)
                digest = hashlib.sha256(destination.read_bytes()).hexdigest()
                pages.append(destination)
                metadata.append(
                    {
                        "page": page_number,
                        "url": str(response.url),
                        "bytes": destination.stat().st_size,
                        "width": width,
                        "height": height,
                        "format": image_format,
                        "sha256": digest,
                    }
                )
                consecutive_misses = 0
                downloaded = True
                break
            except Exception as exc:
                print("PAGE_ERROR", report["id"], page_number, url, repr(exc))

        if not downloaded:
            consecutive_misses += 1
            if page_number == 1:
                raise RuntimeError(f"First page unavailable for report {report['id']}")
            if consecutive_misses >= 3:
                break

    # Reject gaps and duplicate pages.
    expected = list(range(1, len(pages) + 1))
    actual = [item["page"] for item in metadata]
    if actual != expected:
        raise RuntimeError(f"Non-contiguous pages for report {report['id']}: {actual[:10]} ... {actual[-10:]}")
    hashes = [item["sha256"] for item in metadata]
    if len(set(hashes)) != len(hashes):
        raise RuntimeError(f"Duplicate page images detected for report {report['id']}")
    if len(pages) < report["minimum_pages"]:
        raise RuntimeError(
            f"Incomplete report {report['id']}: found {len(pages)} pages, expected at least {report['minimum_pages']}"
        )
    return pages, metadata


def build_pdf(report: dict[str, Any], page_images: list[Path]) -> Path:
    output = REPORTS_DIR / report["output_name"]
    try:
        pdf_bytes = img2pdf.convert([str(path) for path in page_images])
    except Exception as exc:
        print("IMG2PDF_DIRECT_FAILED", report["id"], repr(exc))
        normalized_paths: list[Path] = []
        normalized_dir = page_images[0].parent / "normalized"
        normalized_dir.mkdir(exist_ok=True)
        for path in page_images:
            normalized = normalized_dir / path.name
            with Image.open(path) as image:
                image.convert("RGB").save(normalized, "JPEG", quality=96, optimize=True)
            normalized_paths.append(normalized)
        pdf_bytes = img2pdf.convert([str(path) for path in normalized_paths])
    output.write_bytes(pdf_bytes)
    return output


def validate_pdf(pdf_path: Path, expected_pages: int, report: dict[str, Any]) -> dict[str, Any]:
    if pdf_path.read_bytes()[:5] != b"%PDF-":
        raise RuntimeError(f"Invalid PDF signature: {pdf_path.name}")
    reader = PdfReader(str(pdf_path), strict=False)
    pages = len(reader.pages)
    if pages != expected_pages:
        raise RuntimeError(f"PDF page mismatch: {pdf_path.name}: {pages} != {expected_pages}")
    subprocess.run(["qpdf", "--check", str(pdf_path)], check=True, capture_output=True, text=True)

    render_pages = sorted(set([1, max(1, pages // 2), pages]))
    rendered: list[dict[str, Any]] = []
    for page_number in render_pages:
        prefix = RENDERS_DIR / f"{report['id']}_p{page_number}"
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
                "90",
                str(pdf_path),
                str(prefix),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        image_path = Path(str(prefix) + ".png")
        if not image_path.exists() or image_path.stat().st_size < 10_000:
            raise RuntimeError(f"PDF render verification failed: {pdf_path.name}, page {page_number}")
        with Image.open(image_path) as image:
            image.verify()
        rendered.append({"page": page_number, "bytes": image_path.stat().st_size})

    return {
        "pdf_pages": pages,
        "pdf_bytes": pdf_path.stat().st_size,
        "pdf_sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        "render_checks": rendered,
    }


manifest: list[dict[str, Any]] = []
errors: list[dict[str, str]] = []

for report in REPORTS:
    try:
        print("START_REPORT", json.dumps(report, ensure_ascii=False))
        detail_meta = validate_detail_page(report)
        page_images, image_meta = discover_and_download_pages(report)
        pdf_path = build_pdf(report, page_images)
        pdf_meta = validate_pdf(pdf_path, len(page_images), report)
        manifest.append(
            {
                "company": "广东华沿机器人股份有限公司",
                "stock_code": "01021.HK",
                "report_id": report["id"],
                "broker": report["broker"],
                "analysts": report["analysts"],
                "date": report["date"],
                "title": report["title"],
                "report_type": report["type"],
                "filename": pdf_path.name,
                "source_detail_url": detail_meta["detail_url"],
                "source_page_image_pattern": f"https://public.fxbaogao.com/report-image/{report['date_path']}/{report['id']}-PAGE.png",
                "detail_page_bytes": detail_meta["detail_bytes"],
                "detail_text_chars": detail_meta["detail_text_chars"],
                "page_count_hints": detail_meta["page_count_hints"],
                "image_pages": len(page_images),
                "image_metadata": image_meta,
                **pdf_meta,
            }
        )
        print("REPORT_READY", report["id"], len(page_images), pdf_path, pdf_path.stat().st_size)
    except Exception as exc:
        errors.append({"report_id": report["id"], "error": repr(exc)})
        print("REPORT_FAILED", report["id"], repr(exc))

# The two long initiation reports are mandatory. The IPO report is optional.
completed_ids = {item["report_id"] for item in manifest}
mandatory_ids = {"5587624", "5435007"}
if not mandatory_ids.issubset(completed_ids):
    raise RuntimeError(f"One or both mandatory deep reports failed: completed={sorted(completed_ids)}, errors={errors}")
if len(manifest) < 2:
    raise RuntimeError(f"Only {len(manifest)} valid reports were produced")

readme_lines = [
    "华沿机器人（01021.HK）券商研究报告合集",
    "",
    "本包优先收录两份完整首次覆盖公司深度报告；如公开页面完整可用，同时收录一份IPO研究作为补充。",
    "报告页面图像均来自发现报告面向访客公开展示的逐页文件，本包仅将公开逐页图像按原顺序无删减合成为PDF，未绕过登录、付费或其他访问控制。",
    "",
    "文件清单：",
]
for index, item in enumerate(manifest, start=1):
    readme_lines.append(
        f"{index}. {item['broker']}｜{item['date']}｜{item['pdf_pages']}页｜{item['report_type']}｜{item['title']}"
    )
readme_lines.extend(
    [
        "",
        "校验项目：逐页连续性、图片尺寸、重复页检测、PDF文件签名、PDF页数、qpdf结构检查、首/中/末页渲染、SHA-256及ZIP完整性。",
        "说明：PDF为公开逐页图像重建版，版面与公开报告页面一致，但不保证具备原始PDF的文本搜索、书签或矢量图层。",
        "仅供个人研究使用，报告版权归相应证券研究机构所有。",
    ]
)
(REPORTS_DIR / "README_文件说明.txt").write_text("\n".join(readme_lines), encoding="utf-8")
(REPORTS_DIR / "manifest.json").write_text(
    json.dumps({"reports": manifest, "errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8"
)

summary_rows: list[dict[str, Any]] = []
for item in manifest:
    summary_rows.append(
        {
            "broker": item["broker"],
            "date": item["date"],
            "title": item["title"],
            "report_type": item["report_type"],
            "filename": item["filename"],
            "pages": item["pdf_pages"],
            "bytes": item["pdf_bytes"],
            "sha256": item["pdf_sha256"],
            "source_detail_url": item["source_detail_url"],
        }
    )
with (REPORTS_DIR / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0].keys()))
    writer.writeheader()
    writer.writerows(summary_rows)

with ZipFile(FINAL_ZIP, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
    for path in sorted(REPORTS_DIR.iterdir(), key=lambda p: p.name):
        archive.write(path, arcname=path.name)

with ZipFile(FINAL_ZIP) as archive:
    bad_member = archive.testzip()
    if bad_member is not None:
        raise RuntimeError(f"ZIP integrity failure at {bad_member}")
    pdf_members = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
    if len(pdf_members) != len(manifest):
        raise RuntimeError(f"ZIP PDF count mismatch: {len(pdf_members)} != {len(manifest)}")

print("PACKAGE_READY", FINAL_ZIP, FINAL_ZIP.stat().st_size)
print(json.dumps({"reports": summary_rows, "errors": errors}, ensure_ascii=False, indent=2))
client.close()
