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
import img2pdf
from PIL import Image
from pypdf import PdfReader

OUT = Path("out_fufeng_broker_reports_20260904")
REPORTS_DIR = OUT / "reports"
IMAGES_DIR = OUT / "page_images"
RENDERS_DIR = OUT / "cover_renders"
FINAL_ZIP = OUT / "Fufeng_Group_00546_Broker_Research_Reports_3.zip"

shutil.rmtree(OUT, ignore_errors=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
RENDERS_DIR.mkdir(parents=True, exist_ok=True)

REPORTS = [
    {
        "order": 1,
        "detail_id": 898168,
        "organization": "长江证券",
        "report_date": "2025-06-22",
        "title": "阜丰集团(0546.HK)：味精行业龙头，不断拓展发酵平台",
        "expected_pages": 30,
        "report_type": "公司深度／首次覆盖",
        "rating": "买入",
        "filename": "01_长江证券_阜丰集团_味精行业龙头不断拓展发酵平台_2025-06-22_30页.pdf",
    },
    {
        "order": 2,
        "detail_id": 848366,
        "organization": "华泰证券",
        "report_date": "2024-12-25",
        "title": "阜丰集团(0546.HK)：味精底部有望回升，氨基酸景气持续",
        "expected_pages": 25,
        "report_type": "首次覆盖",
        "rating": "增持",
        "filename": "02_华泰证券_阜丰集团_味精底部有望回升氨基酸景气持续_2024-12-25_25页.pdf",
    },
    {
        "order": 3,
        "detail_id": 817436,
        "organization": "西南证券",
        "report_date": "2024-09-02",
        "title": "阜丰集团(0546.HK)2024年中报点评：生物发酵龙头，多品类蓄势待发",
        "expected_pages": 12,
        "report_type": "首次覆盖／中报点评",
        "rating": "买入",
        "filename": "03_西南证券_阜丰集团_生物发酵龙头多品类蓄势待发_2024-09-02_12页.pdf",
    },
]

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
client = httpx.Client(
    http2=True,
    follow_redirects=True,
    timeout=httpx.Timeout(120.0, connect=30.0),
    headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
)


def fetch_with_retry(url: str, *, referer: str, binary: bool = False) -> bytes | str:
    last_error: Exception | None = None
    headers = {
        "User-Agent": UA,
        "Referer": referer,
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8" if binary else "text/html,application/xhtml+xml,*/*;q=0.8",
    }
    for attempt in range(1, 6):
        try:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            if binary:
                if len(response.content) < 10_000:
                    raise RuntimeError(f"binary response unexpectedly small: {len(response.content)} bytes")
                return response.content
            if len(response.text) < 10_000:
                raise RuntimeError(f"HTML response unexpectedly small: {len(response.text)} characters")
            return response.text
        except Exception as exc:
            last_error = exc
            print(f"FETCH RETRY {attempt}: {url}: {exc}")
            time.sleep(attempt * 1.5)
    raise RuntimeError(f"Unable to fetch {url}: {last_error}")


def decode_js_ascii(value: str) -> str:
    # The Nuxt payload represents slashes as \u002F. The matched URL is ASCII-only.
    return bytes(value, "utf-8").decode("unicode_escape")


def parse_detail_page(detail_id: int) -> dict:
    detail_url = f"https://www.sdyanbao.com/detail/{detail_id}"
    html = fetch_with_retry(detail_url, referer="https://www.sdyanbao.com/report")
    assert isinstance(html, str)

    page_url_match = re.search(r'page_url:"([^"]+)"', html)
    page_count_match = re.search(r"page_count:(\d+)", html)
    file_size_match = re.search(r"file_size:(\d+)", html)
    time_text_match = re.search(r'time_text:"([^"]+)"', html)
    name_match = re.search(rf'detail:\{{id:{detail_id},name:"([^"]+)"', html)
    organization_match = re.search(r'organization:\{id:[^,]+,name:"([^"]+)"\}', html)
    original_id_match = re.search(r"original_id:(\d+)", html)

    missing = [
        label
        for label, match in (
            ("page_url", page_url_match),
            ("page_count", page_count_match),
            ("name", name_match),
            ("organization", organization_match),
            ("original_id", original_id_match),
        )
        if match is None
    ]
    if missing:
        raise RuntimeError(f"Could not parse {detail_url}; missing {missing}")

    return {
        "detail_url": detail_url,
        "page_url": decode_js_ascii(page_url_match.group(1)).rstrip("/"),
        "page_count": int(page_count_match.group(1)),
        "file_size_bytes_reported": int(file_size_match.group(1)) if file_size_match else None,
        "upload_date": time_text_match.group(1) if time_text_match else None,
        "page_title": name_match.group(1),
        "organization_page": organization_match.group(1),
        "original_id": int(original_id_match.group(1)),
    }


def download_and_validate_image(url: str, destination: Path, referer: str) -> dict:
    content = fetch_with_retry(url, referer=referer, binary=True)
    assert isinstance(content, bytes)
    destination.write_bytes(content)
    try:
        with Image.open(destination) as image:
            image.verify()
        with Image.open(destination) as image:
            width, height = image.size
            mode = image.mode
            image_format = image.format
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"Invalid page image {url}: {exc}") from exc
    if width < 700 or height < 900:
        raise RuntimeError(f"Page image resolution too low: {url}: {width}x{height}")
    return {
        "url": url,
        "filename": destination.name,
        "bytes": destination.stat().st_size,
        "width": width,
        "height": height,
        "mode": mode,
        "format": image_format,
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def create_pdf(image_paths: list[Path], output_path: Path) -> None:
    # img2pdf embeds the PNG/JPEG pages without OCR or semantic modification.
    pdf_bytes = img2pdf.convert([str(path) for path in image_paths])
    output_path.write_bytes(pdf_bytes)
    if output_path.read_bytes()[:5] != b"%PDF-":
        raise RuntimeError(f"Invalid PDF signature after conversion: {output_path.name}")


def render_cover(pdf_path: Path) -> dict:
    prefix = RENDERS_DIR / pdf_path.stem
    subprocess.run(
        [
            "pdftoppm",
            "-f", "1",
            "-l", "1",
            "-png",
            "-singlefile",
            "-r", "100",
            str(pdf_path),
            str(prefix),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    png = Path(str(prefix) + ".png")
    if not png.exists() or png.stat().st_size < 10_000:
        raise RuntimeError(f"Cover rendering failed: {pdf_path.name}")
    with Image.open(png) as image:
        width, height = image.size
    return {"filename": png.name, "bytes": png.stat().st_size, "width": width, "height": height}


manifest: list[dict] = []
for report in REPORTS:
    parsed = parse_detail_page(report["detail_id"])
    print("PARSED", json.dumps(parsed, ensure_ascii=False))

    if parsed["page_count"] != report["expected_pages"]:
        raise RuntimeError(
            f"Page-count mismatch for {report['detail_id']}: "
            f"page says {parsed['page_count']}, expected {report['expected_pages']}"
        )
    if parsed["organization_page"] != report["organization"]:
        raise RuntimeError(
            f"Institution mismatch for {report['detail_id']}: "
            f"{parsed['organization_page']} != {report['organization']}"
        )
    normalized_page_title = re.sub(r"\s+", "", parsed["page_title"])
    normalized_expected_title = re.sub(r"\s+", "", report["title"])
    if normalized_page_title != normalized_expected_title:
        raise RuntimeError(
            f"Title mismatch for {report['detail_id']}: "
            f"{parsed['page_title']} != {report['title']}"
        )

    report_images_dir = IMAGES_DIR / f"{report['order']:02d}_{report['detail_id']}"
    report_images_dir.mkdir(parents=True, exist_ok=True)
    image_paths: list[Path] = []
    image_manifest: list[dict] = []
    for page_index in range(parsed["page_count"]):
        image_url = f"{parsed['page_url']}/{page_index}.png"
        image_path = report_images_dir / f"page_{page_index + 1:03d}.png"
        meta = download_and_validate_image(image_url, image_path, parsed["detail_url"])
        meta["page_number"] = page_index + 1
        image_manifest.append(meta)
        image_paths.append(image_path)
        print(
            f"PAGE {report['detail_id']} {page_index + 1}/{parsed['page_count']} "
            f"{meta['width']}x{meta['height']} {meta['bytes']}"
        )

    output_pdf = REPORTS_DIR / report["filename"]
    create_pdf(image_paths, output_pdf)
    reader = PdfReader(str(output_pdf), strict=False)
    actual_pages = len(reader.pages)
    if actual_pages != report["expected_pages"]:
        raise RuntimeError(
            f"Generated PDF page-count mismatch for {output_pdf.name}: "
            f"{actual_pages} != {report['expected_pages']}"
        )
    cover_meta = render_cover(output_pdf)
    pdf_digest = hashlib.sha256(output_pdf.read_bytes()).hexdigest()

    manifest.append(
        {
            "order": report["order"],
            "detail_id": report["detail_id"],
            "organization": report["organization"],
            "report_date": report["report_date"],
            "upload_date": parsed["upload_date"],
            "title": report["title"],
            "report_type": report["report_type"],
            "rating": report["rating"],
            "filename": output_pdf.name,
            "pages": actual_pages,
            "bytes": output_pdf.stat().st_size,
            "sha256": pdf_digest,
            "source_detail_page": parsed["detail_url"],
            "source_page_image_base": parsed["page_url"],
            "source_original_id": parsed["original_id"],
            "reported_original_file_size_bytes": parsed["file_size_bytes_reported"],
            "cover_render": cover_meta,
            "page_images": image_manifest,
            "conversion_note": "由报告聚合页公开展示的逐页高清图片按原顺序无损嵌入PDF；未进行OCR、删页或内容改写。",
        }
    )

readme = """阜丰集团（00546.HK）券商研究报告合集

整理日期：2026年9月4日

收录文件：
1. 长江证券，2025年6月22日，《味精行业龙头，不断拓展发酵平台》，30页，公司深度、首次覆盖、买入；
2. 华泰证券，2024年12月25日，《味精底部有望回升，氨基酸景气持续》，25页，首次覆盖、增持；
3. 西南证券，2024年9月2日，《生物发酵龙头，多品类蓄势待发》，12页，首次覆盖、中报点评、买入。

文件说明：
- 公开页面没有提供无需登录即可取得的券商原始PDF直链，但公开展示了报告的逐页高清页面图片；
- 本合集将公开页面图片按原始页码顺序嵌入PDF，未进行OCR、删页、裁切、文字改写或图表重绘；
- 因此报告正文、图表、页码和免责声明均保留，但PDF主要为图片页，不能像原生文本PDF一样直接全文检索；
- 文件仅供个人研究和学习使用，版权归报告发布机构及原作者所有，请勿用于商业传播。

完整性校验：
- 页面总数分别与公开页面标注的30页、25页、12页一致；
- 每一页均检查图片格式、分辨率、文件大小和SHA-256；
- 合成PDF后再次检查PDF签名和实际页数；
- 每份PDF均渲染首页验证可正常打开；
- ZIP已执行完整性测试。
"""
(REPORTS_DIR / "README_文件说明.txt").write_text(readme, encoding="utf-8")
(REPORTS_DIR / "报告清单与来源.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
)
with (REPORTS_DIR / "报告清单与来源.csv").open("w", encoding="utf-8-sig", newline="") as handle:
    columns = [
        "order",
        "organization",
        "report_date",
        "upload_date",
        "title",
        "report_type",
        "rating",
        "filename",
        "pages",
        "bytes",
        "sha256",
        "source_detail_page",
        "source_page_image_base",
    ]
    writer = csv.DictWriter(handle, fieldnames=columns)
    writer.writeheader()
    for item in manifest:
        writer.writerow({column: item.get(column, "") for column in columns})

with ZipFile(FINAL_ZIP, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(REPORTS_DIR.iterdir(), key=lambda p: p.name):
        archive.write(path, arcname=path.name)

with ZipFile(FINAL_ZIP) as archive:
    bad_member = archive.testzip()
    if bad_member is not None:
        raise RuntimeError(f"ZIP integrity test failed at {bad_member}")
    pdf_names = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
    if len(pdf_names) != 3:
        raise RuntimeError(f"ZIP PDF count mismatch: {len(pdf_names)} != 3")

print("PACKAGE_READY", FINAL_ZIP, FINAL_ZIP.stat().st_size)
print(json.dumps([{k: v for k, v in item.items() if k != "page_images"} for item in manifest], ensure_ascii=False, indent=2))
client.close()
