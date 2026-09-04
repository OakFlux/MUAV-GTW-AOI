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
import img2pdf
from PIL import Image
from pypdf import PdfReader

OUT = Path("out_fufeng_broker_final_20260904")
REPORTS_DIR = OUT / "reports"
PAGES_DIR = OUT / "page_images"
RENDERS_DIR = OUT / "cover_renders"
FINAL_ZIP = OUT / "Fufeng_Group_00546_Broker_Research_Reports_3_Complete.zip"

shutil.rmtree(OUT, ignore_errors=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
PAGES_DIR.mkdir(parents=True, exist_ok=True)
RENDERS_DIR.mkdir(parents=True, exist_ok=True)

# Publicly displayed complete page-image sequences. The first report is mandatory;
# the remaining candidates are tried in order until three complete reports are obtained.
CANDIDATES = [
    {
        "priority": 1,
        "mandatory": True,
        "id": 817436,
        "institution": "西南证券",
        "report_date": "2024-09-02",
        "display_date": "2024-09-10",
        "title": "阜丰集团(0546.HK)2024年中报点评：生物发酵龙头，多品类蓄势待发",
        "kind": "首次覆盖／公司研究",
        "pages": 12,
        "page_base": "https://oss.sdyanbao.com/page/2024/9/10/1082137",
        "detail_url": "https://www.sdyanbao.com/detail/817436",
        "filename": "01_西南证券_阜丰集团_生物发酵龙头多品类蓄势待发_2024-09-02_12页.pdf",
    },
    {
        "priority": 2,
        "mandatory": False,
        "id": 729569,
        "institution": "兴业证券",
        "report_date": "2024-04-03",
        "display_date": "2024-04-03",
        "title": "阜丰集团(00546.HK)：营收增速回落，高档氨基酸表现亮眼",
        "kind": "公司研究",
        "pages": 5,
        "page_base": "https://oss.sdyanbao.com/page/2024/4/3/964646",
        "detail_url": "https://www.sdyanbao.com/detail/729569",
        "filename": "02_兴业证券_阜丰集团_营收增速回落高档氨基酸表现亮眼_2024-04-03_5页.pdf",
    },
    {
        "priority": 3,
        "mandatory": False,
        "id": 459914,
        "institution": "海通国际",
        "report_date": "2023-09-02",
        "display_date": "2023-09-02",
        "title": "阜丰集团(0546.HK)：2023H1股东应占溢利同比下降24.10%，积极实施国际化战略",
        "kind": "公司研究",
        "pages": 12,
        "page_base": "https://oss.sdyanbao.com/page/2023/9/2/609533",
        "detail_url": "https://www.sdyanbao.com/detail/459914",
        "filename": "03_海通国际_阜丰集团_2023H1业绩及国际化战略_2023-09-02_12页.pdf",
    },
    {
        "priority": 4,
        "mandatory": False,
        "id": 377562,
        "institution": "兴业证券",
        "report_date": "2023-04-03",
        "display_date": "2023-04-03",
        "title": "阜丰集团(00546.HK)：量价齐升，收入利润高增长",
        "kind": "公司研究",
        "pages": 5,
        "page_base": "https://oss.sdyanbao.com/page/2023/4/3/472066",
        "detail_url": "https://www.sdyanbao.com/detail/377562",
        "filename": "03_兴业证券_阜丰集团_量价齐升收入利润高增长_2023-04-03_5页.pdf",
    },
    {
        "priority": 5,
        "mandatory": False,
        "id": 283248,
        "institution": "海通国际",
        "report_date": "2022-09-01",
        "display_date": "2022-09-01",
        "title": "阜丰集团(0546.HK)：2022H1股东应占期内溢利同比增长242.8%，有望受益黄原胶高景气延续",
        "kind": "公司研究",
        "pages": 12,
        "page_base": "https://oss.sdyanbao.com/page/2022/9/1/351108",
        "detail_url": "https://www.sdyanbao.com/detail/283248",
        "filename": "03_海通国际_阜丰集团_2022H1业绩及黄原胶景气_2022-09-01_12页.pdf",
    },
    {
        "priority": 6,
        "mandatory": False,
        "id": 253994,
        "institution": "海通国际",
        "report_date": "2022-07-04",
        "display_date": "2022-07-04",
        "title": "阜丰集团(0546.HK)：2022H1净利润同比增幅超过100%，看好公司长期业绩增长",
        "kind": "公司研究",
        "pages": 11,
        "page_base": "https://oss.sdyanbao.com/page/2022/7/4/316581",
        "detail_url": "https://www.sdyanbao.com/detail/253994",
        "filename": "03_海通国际_阜丰集团_2022H1净利润高增长_2022-07-04_11页.pdf",
    },
]

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
client = httpx.Client(
    http2=True,
    follow_redirects=True,
    timeout=httpx.Timeout(90.0, connect=20.0),
    headers={
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    },
)


def download_page(url: str, destination: Path, referer: str) -> dict:
    headers = {
        "User-Agent": UA,
        "Referer": referer,
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }
    last_error: Exception | None = None
    for attempt in range(1, 5):
        try:
            response = client.get(url, headers=headers)
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}")
            content_type = response.headers.get("content-type", "")
            if not content_type.lower().startswith("image/"):
                raise RuntimeError(f"unexpected content type {content_type!r}")
            if len(response.content) < 10_000:
                raise RuntimeError(f"image too small: {len(response.content)} bytes")
            destination.write_bytes(response.content)
            with Image.open(destination) as image:
                image.verify()
            with Image.open(destination) as image:
                width, height = image.size
                image_format = image.format
            if width < 700 or height < 900:
                raise RuntimeError(f"resolution too low: {width}x{height}")
            return {
                "url": url,
                "filename": destination.name,
                "bytes": destination.stat().st_size,
                "width": width,
                "height": height,
                "format": image_format,
                "sha256": hashlib.sha256(response.content).hexdigest(),
            }
        except Exception as exc:
            last_error = exc
            destination.unlink(missing_ok=True)
            if attempt < 4:
                time.sleep(attempt)
    raise RuntimeError(f"unable to obtain public page image {url}: {last_error}")


def build_pdf(image_paths: list[Path], output_path: Path) -> None:
    output_path.write_bytes(img2pdf.convert([str(path) for path in image_paths]))
    with output_path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise RuntimeError(f"invalid PDF signature: {output_path.name}")


def render_first_page(pdf_path: Path) -> dict:
    prefix = RENDERS_DIR / pdf_path.stem
    subprocess.run(
        [
            "pdftoppm", "-f", "1", "-l", "1", "-png", "-singlefile", "-r", "100",
            str(pdf_path), str(prefix),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    image_path = Path(str(prefix) + ".png")
    if not image_path.exists() or image_path.stat().st_size < 10_000:
        raise RuntimeError(f"first-page render failed: {pdf_path.name}")
    with Image.open(image_path) as image:
        width, height = image.size
    return {
        "filename": image_path.name,
        "bytes": image_path.stat().st_size,
        "width": width,
        "height": height,
    }


def try_candidate(report: dict) -> dict | None:
    candidate_dir = PAGES_DIR / f"{report['priority']:02d}_{report['id']}"
    shutil.rmtree(candidate_dir, ignore_errors=True)
    candidate_dir.mkdir(parents=True, exist_ok=True)
    image_paths: list[Path] = []
    page_manifest: list[dict] = []

    try:
        for zero_index in range(report["pages"]):
            url = f"{report['page_base']}/{zero_index}.png"
            destination = candidate_dir / f"page_{zero_index + 1:03d}.png"
            metadata = download_page(url, destination, report["detail_url"])
            metadata["page_number"] = zero_index + 1
            image_paths.append(destination)
            page_manifest.append(metadata)
            print(
                f"PAGE_OK id={report['id']} page={zero_index + 1}/{report['pages']} "
                f"{metadata['width']}x{metadata['height']} bytes={metadata['bytes']}"
            )

        pdf_path = REPORTS_DIR / report["filename"]
        build_pdf(image_paths, pdf_path)
        reader = PdfReader(str(pdf_path), strict=False)
        actual_pages = len(reader.pages)
        if actual_pages != report["pages"]:
            raise RuntimeError(
                f"generated page count {actual_pages} != expected {report['pages']}"
            )
        if pdf_path.stat().st_size < 200_000:
            raise RuntimeError(f"generated PDF unexpectedly small: {pdf_path.stat().st_size}")
        cover = render_first_page(pdf_path)
        result = {
            **report,
            "filename": pdf_path.name,
            "actual_pages": actual_pages,
            "pdf_bytes": pdf_path.stat().st_size,
            "pdf_sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
            "cover_render": cover,
            "page_images": page_manifest,
            "conversion_note": (
                "由公开展示的逐页高清图片按原页码顺序嵌入PDF；"
                "未进行OCR、删页、裁切、文字改写或图表重绘。"
            ),
        }
        print("CANDIDATE_COMPLETE", json.dumps({k: v for k, v in result.items() if k != "page_images"}, ensure_ascii=False))
        return result
    except Exception as exc:
        print(f"CANDIDATE_INCOMPLETE id={report['id']} reason={exc}")
        (REPORTS_DIR / report["filename"]).unlink(missing_ok=True)
        shutil.rmtree(candidate_dir, ignore_errors=True)
        return None


selected: list[dict] = []
for candidate in CANDIDATES:
    result = try_candidate(candidate)
    if result is not None:
        selected.append(result)
        if len(selected) == 3:
            break
    elif candidate["mandatory"]:
        raise RuntimeError(
            "The mandatory 12-page Southwest Securities report was not fully obtainable."
        )

if len(selected) != 3:
    raise RuntimeError(f"Only {len(selected)} complete reports were available; expected 3.")

# Normalize file order regardless of which fallback candidates were selected.
for index, item in enumerate(selected, start=1):
    old_path = REPORTS_DIR / item["filename"]
    stem_without_prefix = old_path.name.split("_", 1)[1] if "_" in old_path.name else old_path.name
    new_path = REPORTS_DIR / f"{index:02d}_{stem_without_prefix}"
    if old_path != new_path:
        old_path.replace(new_path)
    item["filename"] = new_path.name
    item["package_order"] = index

readme_lines = [
    "阜丰集团（00546.HK）券商研究报告合集",
    "",
    "整理日期：2026年9月4日",
    "",
    "收录文件：",
]
for item in selected:
    readme_lines.append(
        f"{item['package_order']}. {item['institution']}，{item['report_date']}，"
        f"《{item['title']}》，{item['actual_pages']}页，{item['kind']}。"
    )
readme_lines.extend(
    [
        "",
        "范围与版本说明：",
        "- 第一份为完整的首次覆盖／深度型公司报告；其余为完整券商公司研究报告。",
        "- 另检索到长江证券30页和华泰证券25页的深度／首次覆盖报告，但公开页面只展示部分页码，故未将残缺版本装入本压缩包。",
        "- 本包所收录的三份文件均已取得公开展示的全部页面，页数与来源页面标注一致。",
        "- 公开来源没有提供无需账户即可直接取得的原始PDF，因此本包将公开展示的逐页高清图片按原顺序嵌入PDF；未进行OCR、删页、裁切、文字改写或图表重绘。",
        "- 由于是图片型PDF，正文通常不能直接全文检索或复制。",
        "- 文件仅供个人研究和学习使用，版权归报告发布机构及原作者所有，请勿用于商业传播。",
        "",
        "完整性校验：",
        "- 每一页均检查HTTP状态、图片格式、分辨率、文件大小和SHA-256；",
        "- 每份PDF均检查文件签名、实际页数和首页渲染可读性；",
        "- ZIP已执行完整性测试。",
    ]
)
(REPORTS_DIR / "README_文件说明.txt").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")
(REPORTS_DIR / "报告清单与来源.json").write_text(
    json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8"
)
with (REPORTS_DIR / "报告清单与来源.csv").open("w", encoding="utf-8-sig", newline="") as handle:
    columns = [
        "package_order", "institution", "report_date", "display_date", "title", "kind",
        "filename", "actual_pages", "pdf_bytes", "pdf_sha256", "detail_url", "page_base",
    ]
    writer = csv.DictWriter(handle, fieldnames=columns)
    writer.writeheader()
    for item in selected:
        writer.writerow({column: item.get(column, "") for column in columns})

with ZipFile(FINAL_ZIP, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(REPORTS_DIR.iterdir(), key=lambda p: p.name):
        archive.write(path, arcname=path.name)

with ZipFile(FINAL_ZIP) as archive:
    bad = archive.testzip()
    if bad is not None:
        raise RuntimeError(f"ZIP integrity failure at {bad}")
    pdf_names = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
    if len(pdf_names) != 3:
        raise RuntimeError(f"ZIP contains {len(pdf_names)} PDFs, expected 3")

print("FINAL_PACKAGE_READY", FINAL_ZIP, FINAL_ZIP.stat().st_size)
print(
    json.dumps(
        [
            {
                "institution": item["institution"],
                "report_date": item["report_date"],
                "title": item["title"],
                "filename": item["filename"],
                "pages": item["actual_pages"],
                "bytes": item["pdf_bytes"],
                "sha256": item["pdf_sha256"],
            }
            for item in selected
        ],
        ensure_ascii=False,
        indent=2,
    )
)
client.close()
