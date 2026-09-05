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

OUT = Path("out_sinofert_broker_reports_20260905")
REPORTS = OUT / "reports"
RENDERS = OUT / "renders"
FINAL_ZIP = OUT / "Sinofert_00297_Broker_Research_Reports_3.pdfs.zip"
shutil.rmtree(OUT, ignore_errors=True)
REPORTS.mkdir(parents=True, exist_ok=True)
RENDERS.mkdir(parents=True, exist_ok=True)

BASE = "https://www.sdicsi.com.hk/backend/storage/app/media/ResearchReports/CorporateReports/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"
client = httpx.Client(
    http2=True,
    follow_redirects=True,
    timeout=httpx.Timeout(180.0, connect=30.0),
    headers={
        "User-Agent": UA,
        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.5",
        "Referer": "https://www.sdicsi.com.hk/cn/research-report/tag/297hk",
    },
)

# Official filename conventions observed on SDIC Securities International's
# public Sinofert research-report tag page. Older publication dates are probed
# in both same-day and prior-business-day variants because the file date can
# precede the displayed publication date by one day.
CANDIDATES = [
    ("2024-08-12", "297-20240812.pdf"),
    ("2024-08-12", "297-20240811.pdf"),
    ("2024-08-27", "297-20240827.pdf"),
    ("2024-08-27", "297-20240826.pdf"),
    ("2025-03-27", "297-20250327.pdf"),
    ("2025-03-27", "297-20250326.pdf"),
    ("2025-08-28", "297-20250828.pdf"),
    ("2025-08-28", "297-20250827.pdf"),
    ("2026-03-31", "297-20260330.pdf"),
    ("2026-03-31", "297-20260331.pdf"),
    ("2026-08-28", "297-20260826.pdf"),
    ("2026-08-28", "297-20260827.pdf"),
    ("2026-08-28", "297-20260828.pdf"),
]


def download(url: str, destination: Path) -> bool:
    for attempt in range(1, 4):
        try:
            response = client.get(url)
            print("PROBE", response.status_code, response.headers.get("content-type"), len(response.content), url)
            if response.status_code != 200:
                return False
            if len(response.content) < 30_000 or not response.content.startswith(b"%PDF-"):
                return False
            destination.write_bytes(response.content)
            return True
        except Exception as exc:
            print("RETRY", attempt, repr(exc), url)
            time.sleep(attempt * 2)
    return False


def inspect_pdf(path: Path) -> dict:
    reader = PdfReader(str(path), strict=False)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise RuntimeError(f"Encrypted PDF: {path.name}: {exc}")
    pages = len(reader.pages)
    if pages < 4:
        raise RuntimeError(f"Too few pages: {path.name}: {pages}")

    sample_parts: list[str] = []
    sample_indices = list(range(min(8, pages)))
    if pages > 12:
        sample_indices.extend([pages // 2, pages - 1])
    for index in sorted(set(sample_indices)):
        try:
            sample_parts.append(reader.pages[index].extract_text() or "")
        except Exception:
            pass
    sample = "\n".join(sample_parts)
    normalized = re.sub(r"\s+", "", sample).lower()
    if not any(token in normalized for token in ["中化化肥", "sinofert", "00297", "297.hk", "297hk"]):
        raise RuntimeError(f"Sinofert identity not found: {path.name}")

    pdfinfo = subprocess.run(
        ["pdfinfo", str(path)], capture_output=True, text=True, check=True
    ).stdout
    pdftotext_path = OUT / f"{path.stem}.txt"
    subprocess.run(["pdftotext", "-layout", str(path), str(pdftotext_path)], check=True)
    extracted = pdftotext_path.read_text(encoding="utf-8", errors="ignore")
    if len(extracted.strip()) < 2_000:
        raise RuntimeError(f"Insufficient searchable text: {path.name}")

    # Derive a compact title from the first pages, falling back to the filename.
    lines = [re.sub(r"\s+", " ", line).strip() for line in sample.splitlines()]
    lines = [line for line in lines if line]
    likely_title = ""
    title_hints = [
        "化肥行业", "化肥行業", "业绩", "業績", "生物肥料", "生物+", "中报", "中報",
        "稳健增长", "穩健增長", "新质生产力", "新質生產力",
    ]
    for line in lines[:120]:
        if 6 <= len(line) <= 100 and any(hint in line for hint in title_hints):
            likely_title = line
            break

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": digest,
        "pdfinfo": pdfinfo,
        "text_chars": len(extracted),
        "title_from_pdf": likely_title,
        "sample_text": sample[:6000],
    }


def render_pages(path: Path, pages: int) -> list[str]:
    targets = sorted(set([1, max(1, (pages + 1) // 2), pages]))
    outputs: list[str] = []
    for page_number in targets:
        prefix = RENDERS / f"{path.stem}_p{page_number}"
        subprocess.run(
            [
                "pdftoppm", "-f", str(page_number), "-l", str(page_number),
                "-png", "-singlefile", "-r", "90", str(path), str(prefix),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        image = Path(str(prefix) + ".png")
        if not image.exists() or image.stat().st_size < 8_000:
            raise RuntimeError(f"Render failed: {path.name} page {page_number}")
        outputs.append(image.name)
    return outputs


valid: list[dict] = []
seen_hashes: set[str] = set()
for displayed_date, filename in CANDIDATES:
    url = BASE + filename
    temp = OUT / filename
    if not download(url, temp):
        continue
    try:
        meta = inspect_pdf(temp)
        if meta["sha256"] in seen_hashes:
            temp.unlink(missing_ok=True)
            continue
        seen_hashes.add(meta["sha256"])
        meta.update({
            "displayed_date_hint": displayed_date,
            "official_filename": filename,
            "source_url": url,
            "temp_path": str(temp),
        })
        meta["rendered_pages"] = render_pages(temp, meta["pages"])
        valid.append(meta)
        print("VALID", json.dumps({k: v for k, v in meta.items() if k not in {"sample_text", "pdfinfo"}}, ensure_ascii=False))
        print("TEXT_SAMPLE", filename, meta["sample_text"].replace("\n", " ")[:2500])
    except Exception as exc:
        print("REJECT", filename, repr(exc))
        temp.unlink(missing_ok=True)

if len(valid) < 2:
    raise RuntimeError(f"Only {len(valid)} valid official reports were found")

# Selection: the 2024 initial-coverage/deep report plus the two newest complete
# company reports. When the older report is unavailable, take the three longest
# and newest reports instead.
def sort_date(item: dict) -> str:
    return item["displayed_date_hint"]

initial = [item for item in valid if item["displayed_date_hint"].startswith("2024-08")]
selected: list[dict] = []
if initial:
    selected.append(max(initial, key=lambda item: (item["pages"], sort_date(item))))
for item in sorted(valid, key=lambda item: (sort_date(item), item["pages"]), reverse=True):
    if item["sha256"] not in {x["sha256"] for x in selected}:
        selected.append(item)
    if len(selected) == 3:
        break
if len(selected) < 2:
    selected = sorted(valid, key=lambda item: (item["pages"], sort_date(item)), reverse=True)[:3]

# Known official titles for the selected publication dates. PDF-derived title is
# retained in the manifest as an independent cross-check.
KNOWN = {
    "2024-08-12": {
        "broker": "安信国际证券（香港）有限公司",
        "title": "中化化肥（297.HK）：化肥行业“国家队”，大力发展农业新质生产力",
        "report_type": "首次覆盖 / 公司深度",
    },
    "2024-08-27": {
        "broker": "安信国际证券（香港）有限公司",
        "title": "中化化肥（297.HK）：业绩超预期，生物+战略推进显成效",
        "report_type": "公司跟踪",
    },
    "2025-03-27": {
        "broker": "国投证券国际",
        "title": "中化化肥（297.HK）：业绩符合预期，生物+战略初见成效",
        "report_type": "公司跟踪",
    },
    "2025-08-28": {
        "broker": "国投证券国际",
        "title": "中化化肥（297.HK）：业绩向好，生物肥料快速增长",
        "report_type": "公司跟踪",
    },
    "2026-03-31": {
        "broker": "国投证券国际",
        "title": "中化化肥（297.HK）：25年业绩稳健增长",
        "report_type": "公司跟踪",
    },
    "2026-08-28": {
        "broker": "国投证券国际",
        "title": "中化化肥（297.HK）：中报业绩稳健增长",
        "report_type": "公司跟踪",
    },
}

manifest: list[dict] = []
for index, item in enumerate(selected, start=1):
    known = KNOWN.get(item["displayed_date_hint"], {})
    safe_date = item["displayed_date_hint"]
    if safe_date == "2024-08-12":
        out_name = f"{index:02d}_安信国际_2024-08-12_中化化肥首次覆盖公司深度.pdf"
    elif safe_date == "2026-08-28":
        out_name = f"{index:02d}_国投证券国际_2026-08-28_中化化肥中报业绩跟踪.pdf"
    elif safe_date == "2026-03-31":
        out_name = f"{index:02d}_国投证券国际_2026-03-31_中化化肥年度业绩跟踪.pdf"
    else:
        out_name = f"{index:02d}_国投证券国际_{safe_date}_中化化肥公司研究.pdf"
    source_path = Path(item["temp_path"])
    destination = REPORTS / out_name
    shutil.copy2(source_path, destination)
    manifest.append({
        "index": index,
        "broker": known.get("broker", "国投证券国际/安信国际"),
        "date": safe_date,
        "title": known.get("title", item.get("title_from_pdf") or source_path.name),
        "report_type": known.get("report_type", "公司研究"),
        "filename": out_name,
        "pages": item["pages"],
        "bytes": item["bytes"],
        "sha256": item["sha256"],
        "source_url": item["source_url"],
        "official_filename": item["official_filename"],
        "pdf_title_cross_check": item.get("title_from_pdf", ""),
        "searchable_text_chars": item["text_chars"],
    })

readme_lines = [
    "中化化肥（00297.HK）券商研究报告合集",
    "",
    "本包收录公开可获取的完整券商PDF，包含一份首次覆盖公司深度报告及两份较新的完整公司跟踪报告。",
    "全部文件来自国投证券国际（原安信国际）官网公开文件路径，仅供个人研究使用。",
    "",
    "文件清单：",
]
for item in manifest:
    readme_lines.append(
        f"{item['index']}. {item['broker']}｜{item['date']}｜{item['pages']}页｜{item['report_type']}｜{item['title']}"
    )
readme_lines.extend([
    "",
    "校验项目：PDF文件签名、可解析页数、公司名称/股票代码、全文文本可提取、首/中/末页渲染、SHA-256及ZIP完整性。",
])
(REPORTS / "README_报告说明.txt").write_text("\n".join(readme_lines), encoding="utf-8")
(REPORTS / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
with (REPORTS / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(manifest[0].keys()))
    writer.writeheader()
    writer.writerows(manifest)

with ZipFile(FINAL_ZIP, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(REPORTS.iterdir(), key=lambda p: p.name):
        archive.write(path, arcname=path.name)
with ZipFile(FINAL_ZIP) as archive:
    bad = archive.testzip()
    if bad is not None:
        raise RuntimeError(f"ZIP integrity failure: {bad}")
    pdf_names = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
    if len(pdf_names) != len(manifest):
        raise RuntimeError("PDF count mismatch in ZIP")

print("PACKAGE_READY", FINAL_ZIP, FINAL_ZIP.stat().st_size)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
client.close()
