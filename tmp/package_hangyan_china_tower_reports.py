from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from pypdf import PdfReader

OUT = Path("out_hangyan_china_tower_resolve")
PDFDIR = OUT / "pdfs"
REPORTS = OUT / "package"
RENDERS = OUT / "renders"
FINAL = OUT / "China_Tower_00788_Broker_Research_Reports.zip"
REPORTS.mkdir(exist_ok=True)
RENDERS.mkdir(exist_ok=True)

raw_path = OUT / "downloaded_raw.json"
if not raw_path.exists():
    raise FileNotFoundError("downloaded_raw.json was not produced")
raw_items = json.loads(raw_path.read_text(encoding="utf-8"))


def parse_field(text: str, label: str) -> str:
    match = re.search(rf"{re.escape(label)}\s*[:：]\s*([^\n\r]+)", text)
    return match.group(1).strip() if match else ""


def inspect_pdf(path: Path) -> tuple[int, str, str]:
    reader = PdfReader(str(path), strict=False)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            pass
    pages = len(reader.pages)
    parts: list[str] = []
    indexes = list(range(min(12, pages)))
    if pages > 16:
        indexes.extend([pages // 2, pages - 1])
    for index in sorted(set(indexes)):
        try:
            parts.append(reader.pages[index].extract_text() or "")
        except Exception:
            pass
    text = "\n".join(parts)
    norm = re.sub(r"\s+", "", text).lower()
    if not any(token in norm for token in ["中国铁塔", "中國鐵塔", "chinatower", "00788.hk", "0788.hk", "00788", "0788"]):
        raise RuntimeError(f"China Tower identity missing in {path.name}")
    if any(token in norm for token in ["东方铁塔", "中信出版", "300788"]):
        raise RuntimeError(f"False-positive company detected in {path.name}")
    return pages, hashlib.sha256(path.read_bytes()).hexdigest(), text


def render_cover(path: Path, stem: str) -> int:
    prefix = RENDERS / stem
    subprocess.run(
        ["pdftoppm", "-f", "1", "-l", "1", "-png", "-singlefile", "-r", "100", str(path), str(prefix)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    image = Path(str(prefix) + ".png")
    if not image.exists() or image.stat().st_size < 8_000:
        raise RuntimeError(f"Cover render failed: {path.name}")
    return image.stat().st_size


valid = []
seen_hashes = set()
for item in raw_items:
    path = Path(item["outPath"])
    if not path.exists() or path.stat().st_size < 50_000:
        continue
    try:
        pages, digest, sample = inspect_pdf(path)
    except Exception as exc:
        print("REJECT", path, repr(exc))
        continue
    if digest in seen_hashes:
        continue
    seen_hashes.add(digest)
    body = item.get("bodyText", "")
    h1 = re.sub(r"^【[^】]+】", "", item.get("h1", "")).strip()
    title = h1
    if title.startswith("中国铁塔-"):
        title = title[len("中国铁塔-"):].strip()
    broker = parse_field(body, "机构")
    report_type = parse_field(body, "类型")
    published = parse_field(body, "发表时间")[:10]
    if not published:
        date_match = re.search(r"20\d{2}[-/]\d{2}[-/]\d{2}", body)
        published = date_match.group(0).replace("/", "-") if date_match else ""
    score = pages
    combined = f"{title} {report_type}".lower()
    if any(x in combined for x in ["深度", "首次覆盖", "首次覆蓋", "initiation"]):
        score += 300
    if pages >= 20:
        score += 120
    elif pages >= 10:
        score += 60
    elif pages >= 5:
        score += 20
    valid.append({
        "source_path": str(path),
        "title": title or path.stem,
        "broker": broker or "券商",
        "report_type": report_type or "公司研究",
        "date": published,
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": digest,
        "source_page": item.get("reportUrl", ""),
        "source_pdf": item.get("pdfUrl", ""),
        "score": score,
    })

if len(valid) < 2:
    raise RuntimeError(f"Only {len(valid)} valid original China Tower PDFs were downloaded")

valid.sort(key=lambda x: (x["score"], x["pages"], x["date"]), reverse=True)
selected = valid[:3]
manifest = []
for index, item in enumerate(selected, start=1):
    safe_broker = re.sub(r'[\\/:*?"<>|]', "_", item["broker"])
    safe_title = re.sub(r'[\\/:*?"<>|]', "_", item["title"])[:95]
    filename = f"{index:02d}_{safe_broker}_{item['date']}_{safe_title}.pdf"
    destination = REPORTS / filename
    shutil.copy2(item["source_path"], destination)
    render_bytes = render_cover(destination, f"cover_{index}")
    manifest.append({
        "index": index,
        "broker": item["broker"],
        "date": item["date"],
        "title": item["title"],
        "report_type": item["report_type"],
        "pages": item["pages"],
        "filename": filename,
        "bytes": item["bytes"],
        "sha256": item["sha256"],
        "source_page": item["source_page"],
        "source_pdf": item["source_pdf"],
        "cover_render_bytes": render_bytes,
    })

readme = [
    "中国铁塔（00788.HK）券商公司研究报告合集",
    "",
    "本包仅收录公开页面直接提供的完整原始PDF，不含网页跳转、摘要截图、年度报告或其他同名公司资料。",
    "筛选时优先保留深度/首次覆盖和页数较完整的报告；公开可直接取得的文件不足三份时，收录两份完整公司研究报告。",
    "",
    "文件清单：",
]
for row in manifest:
    readme.append(f"{row['index']}. {row['broker']}｜{row['date']}｜{row['pages']}页｜{row['report_type']}｜{row['title']}")
readme.extend([
    "",
    "校验项目：PDF文件签名、公司名称/证券代码、实际页数、首页渲染、SHA-256和ZIP完整性。",
    "资料仅供个人研究使用，版权归原发布机构所有。",
])
(REPORTS / "README_报告说明.txt").write_text("\n".join(readme), encoding="utf-8")
(REPORTS / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
with (REPORTS / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(manifest[0].keys()))
    writer.writeheader()
    writer.writerows(manifest)

with ZipFile(FINAL, "w", ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(REPORTS.iterdir(), key=lambda p: p.name):
        archive.write(path, path.name)
with ZipFile(FINAL) as archive:
    bad = archive.testzip()
    if bad is not None:
        raise RuntimeError(f"ZIP integrity failure: {bad}")
    pdf_names = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
    if len(pdf_names) != len(manifest):
        raise RuntimeError("ZIP PDF count mismatch")

print("PACKAGE_READY", FINAL, FINAL.stat().st_size)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
